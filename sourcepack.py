"""Prepare attributable article sources; acquisition is never scientific review."""
import hashlib
import io
import json
import re
import time
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import Request, build_opener
from xml.etree import ElementTree

import acquisition
from collector import now


PMC_BASE = "https://pmc-oa-opendata.s3.amazonaws.com/"
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 150 * 1024 * 1024
MAX_ASSETS = 100
MAX_LIST_PAGES = 5
MAX_VERSIONS = 20
MAX_PDF_PAGES = 500
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff"}
XLINK = "{http://www.w3.org/1999/xlink}href"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def official_url(value):
    if value.startswith("s3://pmc-oa-opendata/"):
        return PMC_BASE + value[len("s3://pmc-oa-opendata/"):]
    return value


def fetch_url(url, limit=MAX_FILE_BYTES):
    """Normal, bounded public HTTPS requests, including every redirect."""
    acquisition.validate_url(url)
    request = Request(url, headers={"User-Agent": "PaperRadar/1.0 (personal literature reader)",
                                   "Accept-Encoding": "identity"})
    deadline = time.monotonic() + 60
    with build_opener(acquisition.SafeRedirect()).open(request, timeout=20) as response:
        final_url = acquisition.validate_url(response.geturl())
        size = response.headers.get("Content-Length", "")
        if size.isdigit() and int(size) > limit:
            raise acquisition.SourceUnavailable("자료가 파일·전체 용량 한도를 넘습니다.")
        chunks, received = [], 0
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("자료 응답 시간 제한을 초과했습니다.")
            chunk = response.read(min(65536, limit + 1 - received))
            if not chunk:
                break
            received += len(chunk)
            if received > limit:
                raise acquisition.SourceUnavailable("자료가 파일·전체 용량 한도를 넘습니다.")
            chunks.append(chunk)
        return b"".join(chunks), response.headers.get("Content-Type", ""), final_url


class Downloads:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.received, self.files = 0, 0
        self.cache = {}

    def get(self, url, name=None, limit=MAX_FILE_BYTES):
        url = official_url(url)
        acquisition.validate_url(url)
        path = None
        if name:
            if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", name):
                raise ValueError("자료 파일 이름이 올바르지 않습니다.")
            path = (self.directory / name).resolve()
            if not path.is_relative_to(self.directory):
                raise ValueError("자료 파일 경로가 폴더를 벗어납니다.")
        if self.files >= MAX_ASSETS:
            raise acquisition.SourceUnavailable("자료 파일 수 한도(100개)에 도달했습니다.")
        limit = min(limit, MAX_FILE_BYTES, MAX_TOTAL_BYTES - self.received)
        if limit <= 0:
            raise acquisition.SourceUnavailable("자료 전체 용량 한도(150 MB)에 도달했습니다.")
        if url in self.cache:
            if len(self.cache[url][0]) > limit:
                raise acquisition.SourceUnavailable("자료가 파일·전체 용량 한도를 넘습니다.")
            self.received += len(self.cache[url][0])
            self.files += 1
            if path:
                path.write_bytes(self.cache[url][0])
            return self.cache[url]
        expected = parse_qs(urlsplit(url).query).get("md5", [None])[0]
        if expected and not re.fullmatch(r"[0-9a-fA-F]{32}", expected):
            raise acquisition.SourceUnavailable("자료의 원본 MD5 정보가 올바르지 않습니다.")
        # Only a current upstream checksum permits reuse; metadata is always refreshed.
        data, content_type, final_url = None, "", url
        if path and expected and path.is_file() and path.stat().st_size <= limit:
            cached = path.read_bytes()
            if hashlib.md5(cached).hexdigest().lower() == expected.lower():
                data = cached
        if data is None:
            data, content_type, final_url = fetch_url(url, limit)
        if len(data) > limit:
            raise acquisition.SourceUnavailable("자료가 파일·전체 용량 한도를 넘습니다.")
        self.received += len(data)
        self.files += 1
        if expected and hashlib.md5(data).hexdigest().lower() != expected.lower():
            raise acquisition.SourceUnavailable("자료의 원본 MD5가 일치하지 않습니다.")
        if path:
            path.write_bytes(data)
        result = (data, content_type, final_url)
        self.cache[url] = result
        return result


def safe_xml(data):
    if b"\0" in data[:512] or re.search(br"<!ENTITY\b", data, re.I):
        raise acquisition.SourceUnavailable("엔터티 선언 또는 UTF-16/32 XML은 처리하지 않았습니다.")
    return ElementTree.fromstring(data)


def metadata_for(paper, downloads):
    pmcid = str(paper.get("pmcid") or "").upper()
    if not re.fullmatch(r"PMC\d+", pmcid):
        raise acquisition.SourceUnavailable("PMC 식별자가 없어 공개 구조화 자료를 찾지 못했습니다.")
    pattern = re.compile(re.escape(pmcid) + r"\.(\d+)/" + re.escape(pmcid) + r"\.\1\.json")
    keys, token, seen_tokens = {}, None, set()
    for _ in range(MAX_LIST_PAGES):
        query = {"list-type": "2", "prefix": pmcid + ".", "max-keys": "1000"}
        if token:
            query["continuation-token"] = token
        data, _, _ = downloads.get(PMC_BASE + "?" + urlencode(query), limit=2 * 1024 * 1024)
        root = safe_xml(data)
        for element in root.iter():
            if acquisition.local_name(element) == "Key":
                match = pattern.fullmatch(element.text or "")
                if match:
                    keys[int(match[1])] = element.text
        truncated = next((e.text for e in root.iter() if acquisition.local_name(e) == "IsTruncated"), "false")
        if truncated != "true":
            break
        token = next((e.text for e in root.iter() if acquisition.local_name(e) == "NextContinuationToken"), None)
        if not token or token in seen_tokens:
            raise acquisition.SourceUnavailable("PMC 버전 목록의 다음 페이지를 확인하지 못했습니다.")
        seen_tokens.add(token)
    else:
        raise acquisition.SourceUnavailable("PMC 버전 목록이 처리 한도를 넘어 전체 버전을 확인하지 못했습니다.")
    if not keys or len(keys) > MAX_VERSIONS:
        raise acquisition.SourceUnavailable("PMC 공개 자료의 버전을 찾지 못했거나 확인 한도를 넘었습니다.")
    versions = []
    for version, key in sorted(keys.items(), reverse=True):
        url = PMC_BASE + quote(key, safe="/")
        data, _, _ = downloads.get(url, limit=2 * 1024 * 1024)
        metadata = json.loads(data)
        if not isinstance(metadata, dict) or str(metadata.get("version")) != str(version):
            raise acquisition.SourceUnavailable("PMC 메타데이터의 버전이 목록과 다릅니다.")
        acquisition.check_identity(paper, [metadata.get("doi")], [metadata.get("pmcid")])
        if str(metadata.get("pmcid") or "").upper() != pmcid:
            raise acquisition.SourceUnavailable("PMC 메타데이터의 식별자가 목록과 다릅니다.")
        if not isinstance(metadata.get("xml_url"), str) or not isinstance(metadata.get("media_urls", []), list):
            raise acquisition.SourceUnavailable("PMC 자료 목록 형식을 확인하지 못했습니다.")
        # Version numbers alone do not distinguish author manuscripts from published versions.
        manuscript = metadata.get("is_manuscript") in (True, "yes", "true")
        versions.append((not manuscript, version, metadata, url, data))
    _, version, metadata, url, data = max(versions, key=lambda item: (item[0], item[1]))
    prefix = PMC_BASE + pmcid + "." + str(version) + "/"
    for item in [metadata["xml_url"], metadata.get("pdf_url"), *metadata.get("media_urls", [])]:
        if item is not None and (not isinstance(item, str) or not official_url(item).startswith(prefix)):
            raise acquisition.SourceUnavailable("PMC 파일 주소가 선택한 논문 버전 폴더와 다릅니다.")
    (downloads.directory / "metadata.json").write_bytes(data)
    return metadata, url


def source(identifier, kind, label, text, url, **extra):
    return {"id": identifier, "kind": kind, "label": label, "url": url,
            "text": text, "sha256": sha256(text.encode("utf-8")), **extra}


def coverage(kind, label, expected, acquired, usable, note=""):
    state = ("none_declared" if expected == 0 else "complete" if expected is not None and usable == expected
             else "partial" if acquired else "unavailable")
    return {"kind": kind, "label": label, "expected": expected, "acquired": acquired,
            "usable": usable, "state": state, "note": note}


def child(element, name):
    return next((item for item in element if acquisition.local_name(item) == name), None)


def content(element):
    return acquisition.element_text(element) if element is not None else ""


def descendants(element, name):
    return [item for item in element.iter() if acquisition.local_name(item) == name]


def text_with_graphics(element):
    """Keep image positions visible when JATS stores a cell/formula as pixels."""
    if acquisition.local_name(element) in ("graphic", "inline-graphic"):
        href = element.get(XLINK) or element.get("href", "")
        return "[원문 이미지: " + href + "]"
    pieces = [element.text or ""]
    for item in element:
        pieces.extend((text_with_graphics(item), item.tail or ""))
    return " ".join(" ".join(pieces).split())


def table_text(wrapper):
    """Expand row/column spans into a rectangular grid; never flatten relationships."""
    table = next(iter(descendants(wrapper, "table")), None)
    if table is None:
        raise acquisition.SourceUnavailable("HTML/XML 표 셀이 없어서 행·열 관계를 추출하지 못했습니다.")
    rows = descendants(table, "tr")
    if not rows or len(rows) > 1000:
        raise acquisition.SourceUnavailable("표 행이 없거나 표 처리 한도를 넘었습니다.")
    grid, spans = {}, False
    for row_index, row in enumerate(rows):
        column = 0
        for cell in row:
            if acquisition.local_name(cell) not in ("th", "td"):
                continue
            while (row_index, column) in grid:
                column += 1
            try:
                row_span, col_span = int(cell.get("rowspan", "1")), int(cell.get("colspan", "1"))
            except ValueError:
                raise acquisition.SourceUnavailable("표의 병합 셀 정보를 해석하지 못했습니다.") from None
            if not (1 <= row_span <= len(rows) - row_index and 1 <= col_span <= 100 and column + col_span <= 100):
                raise acquisition.SourceUnavailable("표의 병합 셀이 범위를 벗어납니다.")
            spans |= row_span > 1 or col_span > 1
            for r in range(row_index, row_index + row_span):
                for c in range(column, column + col_span):
                    if (r, c) in grid:
                        raise acquisition.SourceUnavailable("표의 병합 셀이 겹쳐 구조를 확인하지 못했습니다.")
                    grid[r, c] = text_with_graphics(cell)
            column += col_span
    if not grid:
        raise acquisition.SourceUnavailable("추출할 수 있는 표 셀이 없습니다.")
    width = max(c for _, c in grid) + 1
    result = [[grid.get((r, c), "") for c in range(width)] for r in range(len(rows))]
    caption = content(child(wrapper, "caption"))
    footnotes = content(child(wrapper, "table-wrap-foot"))
    lines = [caption, "[표 행·열 / 병합 셀은 해당 위치에 반복]" if spans else "[표 행·열]"]
    lines.extend(" | ".join(value.replace("|", "\\|") for value in row) for row in result)
    if footnotes:
        lines.append(footnotes)
    return "\n".join(line for line in lines if line), result, spans


def body_sources(root, page_url):
    sources = []
    skipped = {"title", "abstract", "ref-list", "fig", "table-wrap", "supplementary-material", "inline-supplementary-material"}

    def prose(element):
        if acquisition.local_name(element) in skipped:
            return ""
        if acquisition.local_name(element) in ("graphic", "inline-graphic"):
            return text_with_graphics(element)
        pieces = [element.text or ""]
        for item in element:
            pieces.extend((prose(item), item.tail or ""))
        return " ".join(" ".join(pieces).split())

    def visit(element, heading="본문"):
        heading = content(child(element, "title")) or heading
        chunks = []

        def flush():
            if chunks:
                identifier = "body-" + str(len(sources) + 1)
                anchor = element.get("id")
                sources.append(source(identifier, "body", heading, "\n\n".join(chunks),
                                      page_url + ("#" + quote(anchor) if anchor else "")))
                chunks.clear()

        for item in element:
            name = acquisition.local_name(item)
            if name in ("sec", "app", "app-group"):
                flush()
                visit(item, heading)
            elif name not in skipped:
                text = prose(item)
                if text:
                    chunks.append(text)
        flush()

    for item in root:
        if acquisition.local_name(item) in ("body", "back"):
            visit(item, "본문" if acquisition.local_name(item) == "body" else "본문 부록·주석")
    return sources


def image_info(data):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > 80_000_000:
            raise acquisition.SourceUnavailable("그림 픽셀 수가 처리 한도를 넘습니다.")
        result = {"width": image.width, "height": image.height, "format": image.format}
        image.verify()
    return result


def pdf_pages(data):
    if not data.startswith(b"%PDF-"):
        raise acquisition.SourceUnavailable("파일이 PDF 형식이 아닙니다.")
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise acquisition.SourceUnavailable("암호화된 PDF는 자동으로 처리하지 않았습니다.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise acquisition.SourceUnavailable("PDF가 처리 한도(500쪽)를 넘습니다.")
        return [page.extract_text() or "" for page in reader.pages]
    except PyPdfError as error:
        raise acquisition.SourceUnavailable("PDF 내부 구조를 읽지 못했습니다.") from error


def file_name(url):
    return PurePosixPath(unquote(urlsplit(url).path)).name


def media_match(href, media):
    """Resolve only an exact basename or a unique stem from this article's metadata."""
    name = file_name(href)
    matches = [url for url in media if file_name(url) == name]
    if not matches:
        stem = PurePosixPath(name).stem
        matches = [url for url in media if PurePosixPath(file_name(url)).stem == stem]
    if len(matches) != 1:
        raise acquisition.SourceUnavailable("원문 링크와 일치하는 자료 파일을 하나로 확인하지 못했습니다.")
    return matches[0]


def graphic_group(graphic, container, parents):
    """An explicit JATS alternatives container describes one visual, not panels."""
    node = graphic
    while node in parents and node is not container:
        node = parents[node]
        if acquisition.local_name(node) == "alternatives":
            return node, [item for item in node.iter()
                          if acquisition.local_name(item) in ("graphic", "inline-graphic")]
    return graphic, [graphic]


def graphic_media(graphics, media):
    """Prefer the declared image; retain manifest format variants as provenance."""
    choices, alternatives = [], []
    for graphic in graphics:
        href = graphic.get(XLINK) or graphic.get("href", "")
        name = file_name(href)
        matches = list(dict.fromkeys(url for url in media if file_name(url) == name))
        if len(matches) > 1:
            raise acquisition.SourceUnavailable("같은 이름의 그림 파일 출처가 여러 개라 확인하지 못했습니다.")
        variants = [url for url in media if PurePosixPath(file_name(url)).stem == PurePosixPath(name).stem
                    and PurePosixPath(file_name(url)).suffix.lower() in IMAGE_SUFFIXES]
        alternatives.extend(matches + variants)
        if graphic.get("content-type") not in ("thumb", "thumbnail"):
            # A unique basename family is an image format conversion, not another SI file.
            choices.extend(matches or sorted(variants))
    if not choices:
        raise acquisition.SourceUnavailable("원문 링크와 일치하는 그림 파일을 확인하지 못했습니다.")
    chosen = choices[0]
    return chosen, list(dict.fromkeys(url for url in alternatives if url != chosen))


def prepare(paper, directory, asset_prefix, cached_document=None, progress=None):
    """Return a source package plus acquisition coverage; never mutate the library/DB."""
    progress = progress or (lambda stage: None)
    if not isinstance(asset_prefix, str) or not re.fullmatch(r"/assets/prepared/[A-Za-z0-9_-]+", asset_prefix):
        raise ValueError("자료 URL 접두사를 확인하세요.")
    downloads = Downloads(directory)
    package = {"schemaVersion": 1, "candidateId": paper["id"],
               "metadata": {key: paper.get(key, "") for key in ("title", "doi", "pmid", "pmcid")}, "sources": []}
    result = {"status": "failed", "provider": "", "sourceUrl": paper.get("sourceUrl", ""), "license": "",
              "preparedAt": now(), "package": package, "coverage": [], "assets": [], "issues": []}
    sources, assets, issues = package["sources"], result["assets"], result["issues"]
    # Input consumers must also see non-text images and the known acquisition gaps.
    package.update(assets=assets, coverage=result["coverage"])
    metadata = None
    progress("원문 확인 중")
    try:
        metadata, metadata_url = metadata_for(paper, downloads)
        raw, _, xml_url = downloads.get(metadata["xml_url"], "article.xml", limit=12 * 1024 * 1024)
        _, license_text = acquisition.parse_xml(raw, paper)
        root = safe_xml(raw)
    except (ValueError, OSError, ElementTree.ParseError, RecursionError) as error:
        issues.append("구조화 원자료: " + str(error)[:240])
        return fallback(paper, cached_document, result, progress)
    page_url = "https://pmc.ncbi.nlm.nih.gov/articles/" + str(metadata["pmcid"]) + "/"
    parents = {item: parent for parent in root.iter() for item in parent}
    result.update(provider="PMC Article Datasets", sourceUrl=page_url,
                  license=license_text or metadata.get("license_code", ""), metadataUrl=metadata_url,
                  xmlUrl=xml_url, version=metadata["version"])
    package["metadata"].update(url=page_url, version=metadata["version"],
                               manuscript=metadata.get("is_manuscript", False), license=result["license"])
    front = child(root, "front")
    if front is not None:
        for index, abstract in enumerate(descendants(front, "abstract"), 1):
            text = content(abstract)
            if text:
                sources.append(source("abstract-" + str(index), "abstract", "초록", text, page_url))
    if not any(s["kind"] == "abstract" for s in sources) and paper.get("abstract"):
        sources.append(source("abstract-metadata", "abstract", "수집 메타데이터 초록", paper["abstract"],
                              paper.get("sourceUrl") or page_url))
    body = body_sources(root, page_url)
    sources.extend(body)
    result["coverage"].append(coverage("body", "본문", 1, int(bool(body)), int(bool(body)),
                                       f"원문 XML의 본문·부록 {len(body)}개 구간 추출. 읽기·내용 검토는 미실시."))
    progress("표 준비 중")
    tables = descendants(root, "table-wrap")
    table_acquired, table_usable = 0, 0
    for index, wrapper in enumerate(tables, 1):
        label = content(child(wrapper, "label")) or f"표 {index}"
        anchor = wrapper.get("id")
        url = page_url + ("#" + quote(anchor) if anchor else "")
        try:
            text, rows, spans = table_text(wrapper)
            sources.append(source("table-" + str(index), "body", label, text, url,
                                  role="table", rows=rows, expandedSpans=spans))
            table_acquired += 1
            table_usable += 1
        except (ValueError, RecursionError) as error:
            text = content(child(wrapper, "caption"))
            if text:
                sources.append(source("table-" + str(index), "body", label, text, url, role="table"))
                table_acquired += 1
            issues.append(label + ": " + str(error))
    table_ids = {item.get("id") for item in tables if item.get("id")}
    missing_tables = {rid for xref in descendants(root, "xref") if xref.get("ref-type") == "table"
                      for rid in xref.get("rid", "").split() if rid not in table_ids}
    if missing_tables:
        issues.append("정의가 없는 표 참조: " + ", ".join(sorted(missing_tables)))
    result["coverage"].append(coverage("tables", "표", len(tables) + len(missing_tables), table_acquired, table_usable,
                                       "행·열 및 병합 셀 구조 추출. 표 수치의 과학적 검토는 미실시."))
    media = [official_url(url) for url in metadata.get("media_urls", [])]
    used_media = set()

    def save_asset(url, kind, label, identifier):
        suffix = PurePosixPath(file_name(url)).suffix.lower()
        # Unrecognized files remain inert binary downloads; archives are never extracted.
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".bin"
        filename = identifier + suffix
        data, _, final_url = downloads.get(url, filename)
        record = {"id": identifier, "kind": kind, "label": label, "sourceUrl": final_url,
                  "localUrl": asset_prefix + "/" + filename, "sha256": sha256(data), "bytes": len(data),
                  "sourceMd5Verified": bool(parse_qs(urlsplit(url).query).get("md5")), "usable": False}
        assets.append(record)
        return data, record

    progress("그림 준비 중")
    figures = descendants(root, "fig")
    figure_acquired, figure_usable = 0, 0
    for index, figure in enumerate(figures, 1):
        label = content(child(figure, "label"))
        figure_type = {"figure": "Figure", "scheme": "Scheme"}.get(figure.get("fig-type", "").lower())
        if label and figure_type and re.fullmatch(r"(?:[A-Za-z]?\d+[A-Za-z]?|[IVXLC]+)\.?", label):
            label = figure_type + " " + label
        if not label:
            label = (figure_type or "그림") + " (원문 번호 없음)"
        caption = content(child(figure, "caption"))
        graphics = [node for node in figure.iter() if acquisition.local_name(node) in ("graphic", "inline-graphic")
                    and node.get("content-type") not in ("thumb", "thumbnail")]
        success, records, figure_urls, groups_seen = True, [], set(), set()
        if not graphics:
            issues.append(label + ": 원문에 그림 파일 링크가 없습니다.")
            success = False
        for number, graphic in enumerate(graphics, 1):
            group, alternatives = graphic_group(graphic, figure, parents)
            if group in groups_seen:
                continue
            groups_seen.add(group)
            try:
                url, alternate_urls = graphic_media(alternatives, media)
                used_media.update([url, *alternate_urls])
                if url in figure_urls:
                    continue
                figure_urls.add(url)
                data, record = save_asset(url, "figure", label, f"figure-{index}-{number}")
                record.update(image_info(data), usable=True, alternateSourceUrls=alternate_urls)
                records.append(record)
            except (ValueError, OSError, ImportError, RecursionError) as error:
                success = False
                issues.append(label + ": " + str(error)[:240])
        if records:
            figure_acquired += 1
        if not caption:
            success = False
            issues.append(label + ": 원문 캡션이 없어 해설 입력으로 완성하지 않았습니다.")
        if caption:
            anchor = figure.get("id")
            url = page_url + ("#" + quote(anchor) if anchor else "")
            if records:
                for number, record in enumerate(records, 1):
                    sources.append(source(record["id"], "figure", label, caption, url,
                                          asset=record["localUrl"], assetSha256=record["sha256"]))
            else:
                sources.append(source(f"figure-{index}", "figure", label, caption, url))
        figure_usable += int(success and bool(records))
    figure_ids = {item.get("id") for item in figures if item.get("id")}
    missing_figures = {rid for xref in descendants(root, "xref") if xref.get("ref-type") == "fig"
                       for rid in xref.get("rid", "").split() if rid not in figure_ids}
    if missing_figures:
        issues.append("정의가 없는 그림 참조: " + ", ".join(sorted(missing_figures)))
    result["coverage"].append(coverage("figures", "그림", len(figures) + len(missing_figures),
                                       figure_acquired, figure_usable, "파일·이미지 형식·원문 캡션 연결 확인. 시각적 검토는 미실시."))
    def inside(node, names):
        while node in parents:
            node = parents[node]
            if acquisition.local_name(node) in names:
                return True
        return False

    # JATS can place abstract/formula images directly in their container, outside <fig>.
    # Their absent captions are not missing SI captions and are never invented here.
    embedded, embedded_seen = [], set()
    for graphic in root.iter():
        if (acquisition.local_name(graphic) not in ("graphic", "inline-graphic")
                or graphic.get("content-type") in ("thumb", "thumbnail")
                or inside(graphic, {"fig", "supplementary-material", "inline-supplementary-material", "ref-list"})):
            continue
        ancestor, container, role, paragraph = graphic, None, None, None
        while ancestor in parents:
            ancestor = parents[ancestor]
            name = acquisition.local_name(ancestor)
            if paragraph is None and name in ("p", "boxed-text", "sec"):
                paragraph = ancestor
            if name in ("disp-formula", "inline-formula"):
                container, role = ancestor, "formula"
                break
            if name == "abstract" and ancestor.get("abstract-type") in ("graphical", "toc-graphic", "toc"):
                container, role = ancestor, "toc-graphic" if ancestor.get("abstract-type") == "toc" else ancestor.get("abstract-type")
                break
            if name == "table-wrap":
                container, role = ancestor, "table-cell" if inside(graphic, {"td", "th"}) else "table-graphic"
                break
            if name in ("body", "back"):
                container, role = paragraph if paragraph is not None else ancestor, "body-graphic"
                break
        if container is None:
            continue
        group, alternatives = graphic_group(graphic, container, parents)
        if (group, role) not in embedded_seen:
            embedded.append((graphic, container, alternatives, role))
            embedded_seen.add((group, role))
    embedded_acquired = 0
    for index, (graphic, container, alternatives, role) in enumerate(embedded, 1):
        label = {"graphical": "그래픽 초록", "toc-graphic": "목차 그래픽", "formula": "본문 수식",
                 "table-cell": "표 셀 이미지", "table-graphic": "표 이미지", "body-graphic": "본문 이미지"}[role]
        anchor = container.get("id") or graphic.get("id")
        original_label = content(child(container, "label"))
        if original_label:
            label += " " + original_label
        try:
            url, alternate_urls = graphic_media(alternatives, media)
            used_media.update([url, *alternate_urls])
            data, record = save_asset(url, "figure", label, f"inline-{index}")
            record.update(image_info(data), usable=True, role=role,
                          originalHrefs=[node.get(XLINK) or node.get("href", "") for node in alternatives],
                          containerId=anchor, alternateSourceUrls=alternate_urls,
                          captionStatus="not_declared" if child(container, "caption") is None else "declared")
            embedded_acquired += 1
            if role == "formula":
                math = next((node for node in container.iter() if acquisition.local_name(node) in ("math", "tex-math")), None)
                if math is not None and content(math):
                    sources.append(source(f"formula-{index}", "body", label, content(math),
                                          page_url + ("#" + quote(anchor) if anchor else ""), role="formula",
                                          asset=record["localUrl"], assetSha256=record["sha256"],
                                          originalMarkup=ElementTree.tostring(math, encoding="unicode")))
            elif role in ("table-cell", "table-graphic", "body-graphic"):
                sources.append(source(f"inline-{index}", "body", label, text_with_graphics(graphic),
                                      page_url + ("#" + quote(anchor) if anchor else ""), role=role,
                                      asset=record["localUrl"], assetSha256=record["sha256"],
                                      originalHrefs=record["originalHrefs"], containerId=anchor))
        except (ValueError, OSError, ImportError, RecursionError) as error:
            issues.append(label + ": " + str(error)[:240])
    if embedded:
        result["coverage"].append(coverage("inline", "본문 이미지", len(embedded), embedded_acquired, embedded_acquired,
                                           "그래픽 초록·수식·본문·표 셀 이미지를 XML 위치와 연결했습니다. 표의 이미지 셀은 원문 링크로 표시하며 시각적 검토는 미실시입니다. 대체 형식은 출처 주소만 보존합니다."))

    progress("보충자료 준비 중")
    supplements, seen = [], set()
    for node in root.iter():
        if acquisition.local_name(node) not in ("supplementary-material", "inline-supplementary-material"):
            continue
        label = content(child(node, "label")) or "보충자료"
        links = [item.get(XLINK) or item.get("href") for item in node.iter() if item.get(XLINK) or item.get("href")]
        if not links:
            supplements.append((None, label, content(child(node, "caption"))))
        for href in links:
            if href in seen:
                continue
            seen.add(href)
            supplements.append((href, label, content(child(node, "caption"))))
    # Some publishers put SI in an ordinary section/ext-link instead of the JATS SI tag.
    for node in root.iter():
        name = acquisition.local_name(node)
        href = node.get(XLINK) or node.get("href")
        if not href or href in seen or inside(node, {"fig", "supplementary-material", "inline-supplementary-material", "ref-list"}):
            continue
        parent_title = content(child(parents[node], "title")) if node in parents else ""
        text = content(node) + " " + parent_title
        if name == "media" or (name == "ext-link" and re.search(r"supplement|supporting (?:information|data)|additional files?", text, re.I)):
            seen.add(href)
            supplements.append((href, content(node) or "보충자료 링크", ""))
    supplement_ids = {node.get("id") for node in root.iter()
                      if acquisition.local_name(node) in ("supplementary-material", "inline-supplementary-material") and node.get("id")}
    missing_supplements = {rid for xref in descendants(root, "xref") if xref.get("ref-type") in ("supplementary-material", "supplement")
                           for rid in xref.get("rid", "").split() if rid not in supplement_ids}
    for rid in sorted(missing_supplements):
        supplements.append((None, "정의가 없는 보충자료 참조 " + rid, ""))
    # Files present in the article's official media manifest are not silently omitted.
    for url in media:
        if url not in used_media and file_name(url) not in {file_name(s[0]) for s in supplements if s[0]}:
            supplements.append((url, "추가 자료 " + file_name(url), ""))
    # A publisher URL and a relative JATS link may both point to the same official SI file.
    unique_supplements, resolved_seen = [], set()
    for href, label, caption in supplements:
        resolved = href
        if href:
            try:
                resolved = media_match(href, media)
            except acquisition.SourceUnavailable:
                pass
            if resolved in resolved_seen:
                continue
            resolved_seen.add(resolved)
        unique_supplements.append((resolved, label, caption))
    supplements = unique_supplements
    supplement_acquired, supplement_usable = 0, 0
    for index, (href, label, caption) in enumerate(supplements, 1):
        try:
            if not href:
                raise acquisition.SourceUnavailable("원문에 보충자료 파일 링크가 없습니다.")
            # External attachments are recorded, not guessed or followed through authentication.
            url = media_match(href, media)
            data, record = save_asset(url, "supplement", label, "supplement-" + str(index))
            supplement_acquired += 1
            suffix = PurePosixPath(file_name(url)).suffix.lower()
            if suffix == ".pdf":
                pages = pdf_pages(data)
                extracted = 0
                for page_index, text in enumerate(pages, 1):
                    if text.strip():
                        sources.append(source(f"supplement-{index}-page-{page_index}", "supplement",
                                              f"{label} · {page_index}쪽", text,
                                              record["localUrl"] + f"#page={page_index}",
                                              asset=record["localUrl"], assetSha256=record["sha256"]))
                        extracted += 1
                record.update(pageCount=len(pages), extractedPageCount=extracted)
                if extracted != len(pages) or not pages:
                    raise acquisition.SourceUnavailable("PDF의 일부 또는 모든 쪽에서 텍스트가 추출되지 않았습니다. 스캔 여부 확인이 필요합니다.")
                record["usable"] = True
                supplement_usable += 1
            elif suffix in IMAGE_SUFFIXES:
                record.update(image_info(data))
                if not caption:
                    raise acquisition.SourceUnavailable("보충 그림은 확보했지만 원문 설명이 없어 별도 검토가 필요합니다.")
                sources.append(source(f"supplement-{index}", "supplement", label, caption, record["sourceUrl"],
                                      asset=record["localUrl"], assetSha256=record["sha256"]))
                record["usable"] = True
                supplement_usable += 1
            else:
                raise acquisition.SourceUnavailable("파일을 보존했습니다. ZIP·문서·데이터 등 이 형식은 자동으로 해제하거나 텍스트로 변환하지 않습니다.")
        except (ValueError, OSError, ImportError, RecursionError) as error:
            issues.append(label + ": " + str(error)[:240])
    result["coverage"].append(coverage("supplements", "보충자료", len(supplements), supplement_acquired,
                                       supplement_usable, "PDF는 쪽별 텍스트 추출만 수행. 그림·표의 시각적 검토와 내용 검증은 미실시."))
    # The paper PDF is optional: structured JATS remains the actual source of body/tables.
    if metadata.get("pdf_url"):
        progress("원본 PDF 준비 중")
        try:
            data, record = save_asset(official_url(metadata["pdf_url"]), "paper", "논문 PDF", "paper")
            record.update(pageCount=len(pdf_pages(data)), usable=True)
        except (ValueError, OSError, ImportError, RecursionError) as error:
            issues.append("논문 PDF: " + str(error)[:240])
    result["status"] = "ready" if body and not issues and all(
        item["state"] in ("complete", "none_declared") for item in result["coverage"]) else "partial" if body else "failed"
    result["preparedAt"] = now()
    return result


def fallback(paper, cached, result, progress):
    progress("기존 본문 확인 중")
    document = None
    if cached and cached.get("status") == "fulltext":
        try:
            ids = cached.get("identifiers", {})
            acquisition.check_identity(paper, [ids.get("doi")], [ids.get("pmcid")])
            acquisition.verify_sections(cached.get("sections", []), paper)
            document = cached
        except (ValueError, KeyError, TypeError):
            result["issues"].append("저장된 본문의 식별자·내용 범위를 확인하지 못해 다시 요청합니다.")
    if document is None:
        document = acquisition.retrieve(paper)
    url = document.get("sourceUrl") or paper.get("sourceUrl") or "https://doi.org/" + str(paper.get("doi", ""))
    result["attempts"] = document.get("attempts", [])
    result["package"]["attempts"] = result["attempts"]
    sources = result["package"]["sources"]
    if paper.get("abstract"):
        sources.append(source("abstract-metadata", "abstract", "수집 메타데이터 초록", paper["abstract"],
                              paper.get("sourceUrl") or url))
    sections = document.get("sections", []) if document.get("status") == "fulltext" else []
    for index, item in enumerate(sections, 1):
        if item.get("text", "").strip():
            sources.append(source("body-" + str(index), "body", item.get("heading") or "본문", item["text"], url))
    result.update(status="partial" if sections else "failed", provider=document.get("provider", ""),
                  sourceUrl=url, license=document.get("license", ""))
    result["package"]["metadata"].update(url=url, license=result["license"], format=document.get("format", ""))
    result["coverage"] = [coverage("body", "본문", 1, int(bool(sections)), int(bool(sections)),
                                   "식별자가 확인된 본문 텍스트. 읽기·내용 검토는 미실시.")]
    result["coverage"].extend(coverage(kind, label, None, 0, 0, "구조화 원문을 확보하지 못해 자료 수와 완전성을 확인할 수 없습니다.")
                              for kind, label in (("tables", "표"), ("figures", "그림"), ("supplements", "보충자료")))
    result["package"]["coverage"] = result["coverage"]
    if not sections:
        result["reason"] = document.get("reason") or "자동으로 확보한 본문이 없습니다."
        result["issues"].append(result["reason"])
    else:
        result["reason"] = "본문 텍스트를 확보했습니다. 표·그림·보충자료의 범위와 완전성은 미확인입니다."
    return result
