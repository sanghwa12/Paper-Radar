"""Read curated reviews and search one metadata page; never collect or write data."""
import hashlib
import ipaddress
import json
import re
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from classification import classify_candidate
from collector import API_URL, AREAS, metadata, normalize_doi, now


DIRECTORY = Path(__file__).resolve().parent / "data" / "review-radar" / "reviews"
AREA_QUERIES = {area["name"]: area["query"].removesuffix(" AND (SRC:MED OR SRC:PMC OR SRC:PPR)")
                for area in AREAS}
PAGE_SIZE = 30
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
REQUEST_TIMEOUT = 20
REQUEST_DEADLINE = 30


class ReviewRadarError(RuntimeError):
    """A public, non-sensitive explanation of an upstream or curated-data error."""


def _today(value):
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("기준 날짜를 YYYY-MM-DD로 확인해 주세요.") from None


def _window(today):
    try:
        start = today.replace(year=today.year - 3)
    except ValueError:
        start = today.replace(year=today.year - 3, day=28)
    return start.isoformat(), today.isoformat()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _safe_url(value):
    if not _text(value) or re.search(r'[\s\\<>"\x00-\x1f]', value):
        return False
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443)):
            return False
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith(".localhost"):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host
    except ValueError:
        return False


def _timestamp(value):
    try:
        return isinstance(value, str) and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _doi_url_matches(doi, url):
    parsed = urlsplit(url)
    return parsed.hostname not in ("doi.org", "dx.doi.org", "www.doi.org") or normalize_doi(unquote(parsed.path[1:])) == doi


def _validate_briefing(briefing, reading_scope):
    """Validate links and declared review scope; claim accuracy needs human review."""
    if (not isinstance(briefing, dict) or type(briefing.get("version")) is not int
            or briefing["version"] != 1 or not _timestamp(briefing.get("updatedAt"))
            or not isinstance(briefing.get("sources"), list) or not briefing["sources"]):
        raise ValueError
    sources = {}
    for source in briefing["sources"]:
        if (not isinstance(source, dict) or not _text(source.get("id"))
                or not re.fullmatch(r"[a-z][a-z0-9_-]*", source["id"]) or source["id"] in sources
                or not all(_text(source.get(key)) for key in ("label", "location", "scope"))
                or not _safe_url(source.get("url")) or "kind" in source and not _text(source["kind"])):
            raise ValueError
        sources[source["id"]] = source

    def references(value, allow_empty=False):
        if (not isinstance(value, list) or not value and not allow_empty
                or any(not isinstance(key, str) or key not in sources for key in value)
                or len(set(value)) != len(value)):
            raise ValueError
        return set(value)

    expected = [("overview", "요약"), ("methods", "방법 비교"), ("evidence", "근거와 원저"),
                ("limits", "그림·한계"), ("application", "연구 적용")]
    sections = briefing.get("sections")
    if not isinstance(sections, list) or len(sections) != len(expected):
        raise ValueError
    figure_references = set()
    for section, (identity, title) in zip(sections, expected):
        if (not isinstance(section, dict) or section.get("id") != identity or section.get("title") != title
                or not _text(section.get("lead")) or not isinstance(section.get("blocks"), list) or not section["blocks"]):
            raise ValueError
        used = set()
        for block in section["blocks"]:
            if (not isinstance(block, dict) or not _text(block.get("heading"))
                    or block.get("kind") not in {"review_claim", "evidence", "interpretation", "background", "limitation"}
                    or not isinstance(block.get("paragraphs"), list) or not block["paragraphs"]
                    or not all(_text(paragraph) for paragraph in block["paragraphs"])):
                raise ValueError
            used.update(references(block.get("sourceIds"), allow_empty=block["kind"] == "interpretation"))
        if "table" in section:
            table = section["table"]
            if (not isinstance(table, dict) or not _text(table.get("caption"))
                    or not isinstance(table.get("columns"), list) or not table["columns"]
                    or not all(_text(column) for column in table["columns"])
                    or not isinstance(table.get("rows"), list) or not table["rows"]):
                raise ValueError
            for row in table["rows"]:
                if (not isinstance(row, dict) or not isinstance(row.get("cells"), list)
                        or len(row["cells"]) != len(table["columns"]) or not all(_text(cell) for cell in row["cells"])):
                    raise ValueError
                used.update(references(row.get("sourceIds")))
        if "flow" in section:
            if (not isinstance(section["flow"], list) or not section["flow"]
                    or any(not isinstance(step, dict) or not all(_text(step.get(key)) for key in ("title", "text"))
                           for step in section["flow"])):
                raise ValueError
        if "figure" in section:
            figure = section["figure"]
            if (not isinstance(figure, dict) or not all(_text(figure.get(key)) for key in ("src", "alt", "caption"))
                    or not re.fullmatch(r"/assets/review-radar/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.svg", figure["src"])):
                raise ValueError
            used.update(references(figure.get("sourceIds")))
        if identity in {"limits", "evidence"}:
            figure_references.update(used)
    if reading_scope["figures"] == "checked":
        figure_pattern = r"(?:Figure|Fig\.?|그림)\s*(\d+)"
        noted = set(re.findall(figure_pattern, reading_scope["note"], re.I))
        figures = [source for key, source in sources.items()
                   if key in figure_references and source.get("kind") == "review_figure"]
        if not figures or any(not (set(re.findall(figure_pattern, source["location"], re.I)) & noted) for source in figures):
            raise ValueError


def _validate_review(item, today):
    required = {"id", "title", "titleKo", "doi", "pmid", "pmcid", "date", "journal", "authors", "areas",
                "sourceUrl", "selectionReason", "summary", "readingScope", "originals", "citations",
                "journalMetric", "provenance", "summaryStatus"}
    if not isinstance(item, dict) or not required <= item.keys():
        raise ValueError
    for key in ("id", "title", "titleKo", "journal", "authors", "selectionReason"):
        if not _text(item[key]):
            raise ValueError
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", item["id"]):
        raise ValueError
    if (not isinstance(item["areas"], list) or not item["areas"]
            or any(not isinstance(a, str) or a not in AREA_QUERIES for a in item["areas"])
            or len(set(item["areas"])) != len(item["areas"])):
        raise ValueError
    published = date.fromisoformat(item["date"])
    if published.isoformat() != item["date"] or published > today:
        raise ValueError
    for key in ("doi", "pmid", "pmcid"):
        if not isinstance(item[key], str):
            raise ValueError
    doi = normalize_doi(item["doi"])
    if (item["doi"] and not doi or item["pmid"] and not re.fullmatch(r"\d+", item["pmid"])
            or item["pmcid"] and not re.fullmatch(r"PMC\d+", item["pmcid"])
            or not (doi or item["pmid"] or item["pmcid"])):
        raise ValueError
    if not _safe_url(item["sourceUrl"]) or not _doi_url_matches(doi, item["sourceUrl"]):
        raise ValueError
    summary = item["summary"]
    if not isinstance(summary, dict) or not _text(summary.get("scope")):
        raise ValueError
    for key in ("takeaways", "limitations"):
        if not isinstance(summary.get(key), list) or not summary[key] or not all(_text(v) for v in summary[key]):
            raise ValueError
    scope = item["readingScope"]
    if (not isinstance(scope, dict) or scope.get("abstract") != "checked"
            or scope.get("fullText") not in {"partial", "checked"} or scope.get("figures") not in {"unverified", "checked"}
            or scope.get("supplements") != "unverified" or scope.get("originalPapers") != "metadata_only"
            or not _text(scope.get("note")) or item["summaryStatus"] != "partial_review"):
        raise ValueError
    if "briefing" in item:
        _validate_briefing(item["briefing"], scope)
    elif scope["figures"] == "checked":
        raise ValueError
    if not isinstance(item["originals"], list):
        raise ValueError
    identities = set()
    for original in item["originals"]:
        keys = ("title", "doi", "sourceUrl", "role", "referenceLabel", "referenceLocation", "note")
        if not isinstance(original, dict) or not all(_text(original.get(key)) for key in keys):
            raise ValueError
        original_doi = normalize_doi(original["doi"])
        if (not original_doi or original_doi in identities or original_doi == doi
                or type(original.get("year")) is not int or not 1600 <= original["year"] <= today.year
                or original.get("verification") != "citation_metadata" or not _safe_url(original["sourceUrl"])
                or not _doi_url_matches(original_doi, original["sourceUrl"])):
            raise ValueError
        identities.add(original_doi)
    citations = item["citations"]
    if (not isinstance(citations, dict) or "count" not in citations
            or citations["count"] is not None and (type(citations["count"]) is not int or citations["count"] < 0)
            or not _safe_url(citations.get("sourceUrl"))
            or not (_timestamp(citations.get("observedAt")) or citations["count"] is None and citations.get("observedAt") == "")):
        raise ValueError
    metric = item["journalMetric"]
    if not isinstance(metric, dict) or metric != {"jif": None, "year": None, "status": "unverified"}:
        raise ValueError
    if not isinstance(item["provenance"], list) or not item["provenance"]:
        raise ValueError
    for entry in item["provenance"]:
        if (not isinstance(entry, dict) or not _text(entry.get("label")) or not _text(entry.get("scope"))
                or not _safe_url(entry.get("url")) or not _timestamp(entry.get("checkedAt"))):
            raise ValueError


def load_radar(today=None, directory=None):
    today = _today(today)
    start, end = _window(today)
    reviews, identities, dois = [], set(), set()
    directory = Path(directory) if directory is not None else DIRECTORY
    try:
        for path in sorted(directory.glob("*.json")):
            item = json.loads(path.read_text(encoding="utf-8-sig"))
            _validate_review(item, today)
            doi = normalize_doi(item["doi"])
            if item["id"] in identities or doi and doi in dois:
                raise ValueError
            identities.add(item["id"])
            if doi:
                dois.add(doi)
            reviews.append(item)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ReviewRadarError("저장된 리뷰의 필수 정보·출처·검토 범위를 확인하지 못했습니다.") from None
    return {"policy": {"windowYears": 3, "focus": "narrative_methods", "areas": list(AREA_QUERIES),
                       "from": start, "to": end, "oldWorkStatus": "paused", "scoringStatus": "not_defined"},
            "reviews": reviews}


def _epmc_url(url):
    parsed = urlsplit(url)
    if (not _safe_url(url) or parsed.hostname not in {"www.ebi.ac.uk", "ebi.ac.uk"}
            or parsed.path != "/europepmc/webservices/rest/search"):
        raise ReviewRadarError("Europe PMC 검색 주소를 확인하지 못했습니다.")
    return url


class _EPMCRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return super().redirect_request(request, fp, code, message, headers, _epmc_url(newurl))


def _fetch_page(url):
    request = Request(_epmc_url(url), headers={"User-Agent": "PaperRadar/1.0 (review metadata search)",
                                             "Accept": "application/json", "Accept-Encoding": "identity"})
    deadline = time.monotonic() + REQUEST_DEADLINE
    try:
        with build_opener(_EPMCRedirect()).open(request, timeout=REQUEST_TIMEOUT) as response:
            _epmc_url(response.geturl())
            size = response.headers.get("Content-Length", "")
            if size.isdigit() and int(size) > MAX_RESPONSE_BYTES:
                raise ReviewRadarError("Europe PMC 응답이 처리 용량을 초과했습니다.")
            chunks, received = [], 0
            while True:
                if time.monotonic() > deadline:
                    raise ReviewRadarError("Europe PMC 검색 응답 시간이 초과되었습니다.")
                chunk = response.read(min(65536, MAX_RESPONSE_BYTES + 1 - received))
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_RESPONSE_BYTES:
                    raise ReviewRadarError("Europe PMC 응답이 처리 용량을 초과했습니다.")
                chunks.append(chunk)
            return json.loads(b"".join(chunks).decode("utf-8"))
    except HTTPError as error:
        raise ReviewRadarError(f"Europe PMC 검색이 실패했습니다(HTTP {error.code}). 잠시 후 다시 시도해 주세요.") from None
    except (URLError, OSError, TimeoutError):
        raise ReviewRadarError("Europe PMC에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.") from None
    except (ValueError, UnicodeError):
        raise ReviewRadarError("Europe PMC 검색 응답을 읽지 못했습니다.") from None


_SPECIAL_REVIEW = r"(?:systematic(?: literature)? review|(?:network )?meta[ -]analysis)"
_TYPE_TITLE = re.compile(r"(?:^|:\s*)(?:(?:a|an|the)\s+)?(?:(?:updated|living)\s+)?" + _SPECIAL_REVIEW + r"\b", re.I)
_TYPE_ABSTRACT = re.compile(r"\b(?:this|the present|our)\s+" + _SPECIAL_REVIEW + r"\b|\bwe\s+(?:conducted|performed|undertook)\s+(?:a\s+)?" + _SPECIAL_REVIEW + r"\b", re.I)


def _review_subtype(paper):
    types = {re.sub(r"[\s_-]+", " ", value.lower()) for value in paper["publicationTypes"]}
    if (types & {"systematic review", "meta analysis", "network meta analysis"}
            or _TYPE_TITLE.search(paper["title"]) or _TYPE_ABSTRACT.search(paper["abstract"])):
        return "systematic_meta"
    if "narrative review" in types or re.search(r"\bnarrative review\b", paper["title"], re.I):
        return "narrative"
    return "unspecified"


def search_reviews(payload, today=None):
    if not isinstance(payload, dict) or set(payload) != {"area", "keywords", "sort"}:
        raise ValueError("분야·검색어·정렬 항목을 확인해 주세요.")
    area, keywords, order = payload["area"], payload["keywords"], payload["sort"]
    if not isinstance(area, str) or area not in AREA_QUERIES:
        raise ValueError("기존 6개 연구 분야 중 하나를 선택해 주세요.")
    if not isinstance(keywords, str) or len(keywords) > 120 or re.search(r"[\x00-\x1f\x7f]", keywords):
        raise ValueError("검색어는 제어 문자 없이 120자 이내로 입력해 주세요.")
    if order not in ("relevance", "newest"):
        raise ValueError("정렬은 관련도 또는 최신순을 선택해 주세요.")
    start, end = _window(_today(today))
    query = f'({AREA_QUERIES[area]}) AND PUB_TYPE:review AND (SRC:MED OR SRC:PMC) AND FIRST_PDATE:[{start} TO {end}]'
    if keywords.strip():
        literal = keywords.strip().replace("\\", "\\\\").replace('"', '\\"')
        query += f' AND TITLE_ABS:"{literal}"'
    if order == "newest":
        query += " sort_date:y"
    params = {"query": query, "format": "json", "resultType": "core", "pageSize": PAGE_SIZE, "cursorMark": "*"}
    url = API_URL + "?" + urlencode(params)
    response = _fetch_page(url)
    if (not isinstance(response, dict) or type(response.get("hitCount")) is not int or response["hitCount"] < 0
            or not isinstance(response.get("resultList"), dict) or not isinstance(response["resultList"].get("result"), list)):
        raise ReviewRadarError("Europe PMC 응답에 검색 건수와 결과 목록이 없습니다. 검색 실패를 0건으로 처리하지 않았습니다.")
    records = response["resultList"]["result"]
    if len(records) > PAGE_SIZE or response["hitCount"] < len(records) or response["hitCount"] > 0 and not records:
        raise ReviewRadarError("Europe PMC 검색 건수와 첫 페이지 결과가 일치하지 않습니다.")
    candidates, seen, excluded = [], set(), Counter()
    observed = now()
    for record in records:
        try:
            if not isinstance(record, dict):
                raise ValueError
            paper = metadata(record)
            if (not paper["title"] or not paper["date"] or paper["source"] not in {"MED", "PMC"}
                    or not re.fullmatch(r"\d+" if paper["source"] == "MED" else r"PMC\d+", paper["sourceId"])):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            excluded["invalidMetadata"] += 1
            continue
        if not start <= paper["date"] <= end:
            excluded["outsideWindow"] += 1
            continue
        classification = classify_candidate(paper)
        if classification["kind"] != "review":
            excluded["notReview"] += 1
            continue
        subtype = _review_subtype(paper)
        if subtype == "systematic_meta":
            excluded["systematicOrMetaAnalysis"] += 1
            continue
        aliases = {"source:" + paper["source"] + ":" + paper["sourceId"]}
        if paper["doi"]:
            aliases.add("doi:" + paper["doi"])
        duplicate = bool(aliases & seen)
        seen.update(aliases)
        if duplicate:
            excluded["duplicate"] += 1
            continue
        identity = "doi:" + paper["doi"] if paper["doi"] else "source:" + paper["source"] + ":" + paper["sourceId"]
        count = record.get("citedByCount")
        label = "Narrative review · 메타데이터 기준" if subtype == "narrative" else "Review · 세부 유형 미확인"
        candidates.append({**paper, "id": "review-" + hashlib.sha256(identity.encode()).hexdigest()[:24],
                           "area": area, "areas": [area], "classification": {**classification, "label": label},
                           "reviewSubtype": subtype, "observedAt": observed, "selectionStatus": "unreviewed",
                           "citedByCount": count if type(count) is int and count >= 0 else None})
    return {"candidates": candidates, "query": query, "sourceUrl": url, "observedAt": observed,
            "hitCount": response["hitCount"], "fetched": len(records), "shown": len(candidates),
            "truncated": response["hitCount"] > len(records), "excludedCounts": dict(excluded), "from": start, "to": end}
