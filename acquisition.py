"""Retrieve verifiable article text without browser sessions or subscription bypasses."""
import errno
import ipaddress
import io
import json
import os
import re
import socket
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from classification import classify_candidate
from collector import normalize_doi, now, plain_text


MAX_BYTES = 12 * 1024 * 1024
REQUEST_TIMEOUT = 20
MIN_BODY_LENGTH = 1000
SUMMARY_FIELDS = ("status", "provider", "sourceUrl", "fetchedAt", "reason", "format",
                  "license", "sectionCount", "textLength")
ACCESS_CHALLENGE = re.compile(r"(?:verify (?:that )?you are (?:a )?human|are you a robot\?|checking your browser|"
                              r"access to this (?:article|content) (?:is restricted|requires)|"
                              r"purchase (?:this article|access to this article)|sign in to (?:view|read) (?:the )?full text)", re.I)


class SourceUnavailable(ValueError):
    """The response cannot safely establish that this paper's full text was read."""

    def __init__(self, message, *, url=None, reason_code=None):
        super().__init__(message)
        self.url = url
        self.reason_code = reason_code


def validate_url(url):
    reason_code = "invalid_url"
    blocked_url = None
    try:
        parsed = urlsplit(url)
        blocked_url = url
        if parsed.username is not None or parsed.password is not None:
            blocked_url = parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[-1]).geturl()
            reason_code = "credentials_in_url"
            raise ValueError
        if parsed.scheme != "https":
            reason_code = "https_required"
            raise ValueError
        if not parsed.hostname:
            reason_code = "missing_host"
            raise ValueError
        if parsed.port not in (None, 443):
            reason_code = "unsupported_port"
            raise ValueError
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            reason_code = "non_public_address"
            raise ValueError
    except ValueError:
        message = ("HTTPS가 아닌 원문 연결로 이동하려 하여 열지 않았습니다." if reason_code == "https_required"
                   else "공개 HTTPS 주소가 아닌 원문 연결은 열지 않았습니다.")
        raise SourceUnavailable(message, url=blocked_url, reason_code=reason_code) from None
    return url


class SafeRedirect(HTTPRedirectHandler):
    max_redirections = 6
    max_repeats = 2

    def redirect_request(self, request, response, code, message, headers, new_url):
        validate_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


class MetaRefresh(HTMLParser):
    """Read declarative HTML navigation only; scripts and form values are never executed."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.target = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag != "meta" or str(attrs.get("http-equiv") or "").lower() != "refresh" or self.target is not None:
            return
        match = re.fullmatch(r"\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*(.*?)\s*", str(attrs.get("content") or ""), re.I)
        if not match:
            return
        target = match[1]
        if target[:1] in ("'", '"'):
            if len(target) < 2 or target[-1] != target[0]:
                return
            target = target[1:-1]
        if target:
            self.target = target


def fetch_url(url):
    """Bounded normal HTTPS request; environment proxy settings remain in effect."""
    deadline = time.monotonic() + 60
    visited, received = set(), 0
    for hop in range(4):
        validate_url(url)
        if url in visited:
            raise SourceUnavailable("출판사 HTML 이동이 반복되어 중단했습니다.", url=url, reason_code="redirect_cycle")
        visited.add(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("원문 응답 시간 제한을 초과했습니다.")
        # DOI resolution negotiates metadata when XML is preferred; request the human article page.
        parsed = urlsplit(url)
        is_pmc_xml = parsed.hostname == "www.ebi.ac.uk" and parsed.path.endswith("/fullTextXML")
        accept = "application/xml,text/xml;q=0.9" if is_pmc_xml else "text/html,application/xhtml+xml;q=0.9"
        request = Request(url, headers={
            "User-Agent": "PaperRadar/1.0 (personal literature reader)",
            "Accept": accept,
            "Accept-Encoding": "identity",
        })
        with build_opener(SafeRedirect()).open(request, timeout=min(REQUEST_TIMEOUT, remaining)) as response:
            final_url = validate_url(response.geturl())
            if final_url != url and final_url in visited:
                raise SourceUnavailable("출판사 HTML 이동이 반복되어 중단했습니다.", url=final_url, reason_code="redirect_cycle")
            visited.add(final_url)
            size = response.headers.get("Content-Length", "")
            if size.isdigit() and int(size) + received > MAX_BYTES:
                raise SourceUnavailable("원문 응답이 현재 처리 한도(12 MB)를 넘습니다.")
            parts = []
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("원문 응답 시간 제한을 초과했습니다.")
                chunk = response.read(min(65536, MAX_BYTES + 1 - received))
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_BYTES:
                    raise SourceUnavailable("원문 응답이 현재 처리 한도(12 MB)를 넘습니다.")
                parts.append(chunk)
            data, content_type = b"".join(parts), response.headers.get("Content-Type", "")
        refresh = MetaRefresh()
        if "html" in content_type.lower():
            refresh.feed(data.decode("utf-8", errors="replace"))
        if refresh.target is None:
            return data, content_type, final_url
        next_url = urljoin(final_url, refresh.target)
        validate_url(next_url)
        if hop == 3:
            raise SourceUnavailable("출판사 HTML 이동 횟수 한도(3회)를 넘었습니다.", url=next_url, reason_code="redirect_limit")
        url = next_url


def local_name(element):
    return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""


def element_text(element):
    return " ".join(" ".join(element.itertext()).split())


def check_identity(paper, dois=(), pmcids=()):
    doi = normalize_doi(paper.get("doi"))
    pmcid = str(paper.get("pmcid") or "").upper()
    found_dois = {normalize_doi(item) for item in dois} - {""}
    found_pmcids = {"PMC" + re.sub(r"^PMC", "", str(item).upper()) for item in pmcids if item}
    if doi and found_dois and doi not in found_dois:
        raise SourceUnavailable("응답의 DOI가 요청한 논문과 다릅니다.")
    if pmcid and found_pmcids and pmcid not in found_pmcids:
        raise SourceUnavailable("응답의 PMCID가 요청한 논문과 다릅니다.")
    if not ((doi and doi in found_dois) or (pmcid and pmcid in found_pmcids)):
        raise SourceUnavailable("응답에서 요청한 논문의 DOI 또는 PMCID를 확인하지 못했습니다.")


def verify_sections(sections, paper):
    sections = [{"heading": plain_text(item["heading"]), "text": plain_text(item["text"])}
                for item in sections if item.get("text", "").strip()]
    text = " ".join(item["text"] for item in sections)
    abstract = plain_text(paper.get("abstract"))
    normalized = lambda value: re.sub(r"\W+", " ", value).lower().strip()
    body_key, abstract_key = normalized(text), normalized(abstract)
    abstract_dominated = (len(abstract_key) > 100 and abstract_key[:120] in body_key
                          and len(body_key) < len(abstract_key) + MIN_BODY_LENGTH)
    abstract_subset = (len(abstract_key) > 100 and all(normalized(item["text"]) in abstract_key for item in sections))
    if len(text) < MIN_BODY_LENGTH or abstract_dominated or abstract_subset:
        raise SourceUnavailable("초록을 넘어서는 충분한 본문 텍스트를 확인하지 못했습니다.")
    return sections


def parse_xml(data, paper):
    # Standard JATS external DOCTYPEs are harmless to ElementTree; internal entities are not accepted.
    if b"\0" in data[:512]:
        raise SourceUnavailable("UTF-16/32 XML은 현재 지원하지 않습니다.")
    if re.search(br"<!ENTITY\b", data, re.I):
        raise SourceUnavailable("엔터티 선언이 있는 XML은 처리하지 않았습니다.")
    root = ElementTree.fromstring(data)
    if local_name(root) != "article":
        raise SourceUnavailable("응답이 논문 본문 XML 형식이 아닙니다.")
    front = next((item for item in root if local_name(item) == "front"), None)
    ids = list(front.iter()) if front is not None else []
    dois = [element_text(item) for item in ids
            if local_name(item) == "article-id" and item.get("pub-id-type") == "doi"]
    pmcids = [element_text(item) for item in ids
              if local_name(item) == "article-id" and item.get("pub-id-type") in ("pmc", "pmcid")]
    check_identity(paper, dois, pmcids)
    body = next((item for item in root if local_name(item) == "body"), None)
    if body is None:
        raise SourceUnavailable("XML에 본문(body)이 없고 초록만 있거나 연결 정보만 있습니다.")
    sections = []

    def visit(section, heading="본문"):
        title = next((item for item in section if local_name(item) == "title"), None)
        heading = element_text(title) if title is not None else heading
        if heading.strip().lower() in ("abstract", "summary"):
            return
        chunks = []
        for item in section:
            name = local_name(item)
            if name == "sec":
                if chunks:
                    sections.append({"heading": heading, "text": "\n\n".join(chunks)})
                    chunks = []
                visit(item, heading)
            elif name not in ("title", "abstract", "ref-list"):
                chunks.append(element_text(item))
        if chunks:
            sections.append({"heading": heading, "text": "\n\n".join(chunks)})

    visit(body)
    license_text = next((element_text(item) for item in ids if local_name(item) == "license"), "")
    return verify_sections(sections, paper), license_text


class ArticleHTML(HTMLParser):
    """Read only explicit article-body containers and structured articleBody text."""
    void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    body_classes = {"article-body", "article__body", "article__body-content", "article-body-content"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.dois, self.sections, self.json_ld = [], [], [], []
        self.heading, self.buffer, self.heading_buffer = "본문", [], []
        self.body_depth = None
        self.hidden = 0
        self.script_buffer = None
        self.in_heading = False
        self.abstract_depths, self.abstract_heading_level = [], None

    def flush(self):
        text = " ".join(" ".join(self.buffer).split())
        if text and self.heading.lower() not in ("abstract", "summary"):
            self.sections.append({"heading": self.heading, "text": text})
        self.buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and str(attrs.get("name", attrs.get("property", ""))).lower() in (
                "citation_doi", "dc.identifier", "dc.identifier.doi", "prism.doi"):
            self.dois.append(attrs.get("content", ""))
        if tag in self.void_tags:
            if tag == "br" and self.body_depth is not None:
                self.buffer.append(" ")
            return
        self.stack.append(tag)
        if (set(attrs.get("class", "").lower().split()).intersection({"abstract", "article-abstract", "article__abstract"})
                or attrs.get("id", "").lower() in ("abstract", "article-abstract")
                or "abstract" in attrs.get("itemprop", "").lower().split()):
            self.abstract_depths.append(len(self.stack))
        if tag in ("script", "style", "noscript", "nav", "button", "form"):
            self.hidden += 1
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self.script_buffer = []
        if self.body_depth is None and not self.hidden and (
                "articleBody" in attrs.get("itemprop", "").split()
                or self.body_classes.intersection(attrs.get("class", "").split())
                or attrs.get("id") in ("article-body", "articleBody")):
            self.body_depth = len(self.stack)
        if (self.body_depth is not None and not self.hidden and not self.abstract_depths
                and tag in ("h2", "h3", "h4", "h5", "h6")):
            if self.abstract_heading_level is not None and int(tag[1]) > self.abstract_heading_level:
                return
            self.abstract_heading_level = None
            self.flush()
            self.in_heading, self.heading_buffer = True, []

    def handle_endtag(self, tag):
        if tag not in self.stack:
            return
        if tag == "script" and self.script_buffer is not None:
            try:
                self.json_ld.append(json.loads("".join(self.script_buffer)))
            except (ValueError, RecursionError):
                pass
            self.script_buffer = None
        if self.in_heading and tag in ("h2", "h3", "h4", "h5", "h6"):
            self.heading = " ".join(" ".join(self.heading_buffer).split()) or "본문"
            self.in_heading = False
            if self.heading.lower() in ("abstract", "summary"):
                self.abstract_heading_level = int(tag[1])
        closed = len(self.stack) - 1 - self.stack[::-1].index(tag)
        if self.body_depth is not None and closed < self.body_depth:
            self.flush()
            self.body_depth = None
        removed = self.stack[closed:]
        self.abstract_depths = [depth for depth in self.abstract_depths if depth <= closed]
        self.hidden = max(0, self.hidden - sum(item in ("script", "style", "noscript", "nav", "button", "form") for item in removed))
        self.stack = self.stack[:closed]

    def handle_data(self, data):
        if self.script_buffer is not None:
            self.script_buffer.append(data)
        if (self.body_depth is not None and not self.hidden and not self.abstract_depths
                and self.abstract_heading_level is None):
            (self.heading_buffer if self.in_heading else self.buffer).append(data)


def parse_html(data, paper):
    parser = ArticleHTML()
    html = data.decode("utf-8", errors="replace")
    if ACCESS_CHALLENGE.search(html):
        raise SourceUnavailable("출판사에서 브라우저 확인 또는 접근 인증을 요구합니다. 학교 브라우저에서 원문을 확인할 수 있습니다.",
                                reason_code="access_challenge")
    parser.feed(html)
    parser.flush()
    sections, license_text = parser.sections, ""
    document_dois = list(parser.dois)
    nodes = list(parser.json_ld)
    while nodes:
        node = nodes.pop()
        if isinstance(node, list):
            nodes.extend(node)
        elif isinstance(node, dict):
            nodes.extend(value for value in node.values() if isinstance(value, (list, dict)))
            types = node.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if not isinstance(types, list) or not set(types).intersection({"ScholarlyArticle", "MedicalScholarlyArticle", "Article"}):
                continue
            identifiers = [node.get("sameAs", ""), node.get("url", ""), node.get("@id", "")]
            identifier = node.get("identifier", "")
            identifiers.append(identifier.get("value", "") if isinstance(identifier, dict) else identifier)
            node_dois = [value for value in identifiers if isinstance(value, str) and normalize_doi(value)]
            try:
                check_identity(paper, node_dois or document_dois)
            except SourceUnavailable:
                continue
            parser.dois.extend(node_dois)
            if not sections and isinstance(node.get("articleBody"), str):
                sections = [{"heading": "본문", "text": node["articleBody"]}]
            if isinstance(node.get("license"), str):
                license_text = node["license"]
    check_identity(paper, parser.dois)
    if not sections:
        raise SourceUnavailable("출판사 응답에서 확인 가능한 본문을 찾지 못했습니다. 학교 브라우저에서 원문을 열 수는 있습니다.")
    has_body_heading = any(re.search(r"\b(?:introduction|methods|materials|results|discussion|experimental|conclusions?|background|findings)\b",
                                     item["heading"], re.I) for item in sections)
    if not has_body_heading and sum(len(item["text"]) for item in sections) < 2000:
        raise SourceUnavailable("구조화된 본문 구획을 충분히 확인하지 못해 초록·안내 페이지로 처리했습니다.")
    return verify_sections(sections, paper), license_text


def parse_pdf(data, paper):
    """Extract a bounded public PDF after confirming this article's DOI on its first page."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if len(data) > MAX_BYTES or not data.lstrip().startswith(b"%PDF-"):
        raise SourceUnavailable("본문 PDF의 형식 또는 파일 크기를 확인하지 못했습니다.", reason_code="invalid_pdf")
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise SourceUnavailable("암호화된 PDF는 자동 본문 추출에 사용하지 않았습니다.", reason_code="encrypted_pdf")
        if not 0 < len(reader.pages) <= 500:
            raise SourceUnavailable("본문 PDF의 쪽 수가 처리 범위(1–500쪽)를 벗어납니다.", reason_code="pdf_page_limit")
        first = reader.pages[0].extract_text() or ""
        dois = re.findall(r"10\.\d{4,9}/[^\s<>\"]+", first, re.I)
        check_identity(paper, dois)
        sections = [{"heading": "PDF · 1쪽", "text": first}]
        sections.extend({"heading": f"PDF · {index + 1}쪽", "text": page.extract_text() or ""}
                        for index, page in enumerate(reader.pages[1:], start=1))
        return verify_sections(sections, paper), ""
    except SourceUnavailable:
        raise
    except (PdfReadError, ValueError, TypeError, OSError, RecursionError):
        raise SourceUnavailable("본문 PDF의 텍스트를 확인하지 못했습니다.", reason_code="invalid_pdf") from None


class JciDocumentLinks(HTMLParser):
    """Read only the published PDF link and its GET action; ignore all form fields."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.action, self.method = [], None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and isinstance(attrs.get("href"), str):
            self.links.append(attrs["href"])
        if tag == "form" and attrs.get("id") == "download_pdf_form":
            self.action = attrs.get("action")
            self.method = str(attrs.get("method") or "get").lower()


def retrieve_jci_pdf(data, paper, page_url, article_id):
    """Use the static PDF referenced by the verified JCI article and its public viewer."""
    canonical = f"https://insight.jci.org/articles/view/{article_id}"
    if page_url != canonical:
        raise SourceUnavailable("JCI 공식 논문 페이지를 확인하지 못했습니다.")
    article = ArticleHTML()
    article.feed(data.decode("utf-8", errors="replace"))
    check_identity(paper, article.dois)
    links = JciDocumentLinks()
    links.feed(data.decode("utf-8", errors="replace"))
    viewer_url = canonical + "/pdf"
    if viewer_url not in [urljoin(page_url, link) for link in links.links]:
        raise SourceUnavailable("JCI 논문 페이지에서 해당 논문의 공개 PDF 연결을 찾지 못했습니다.")
    viewer_data, viewer_type, viewer_final = fetch_url(viewer_url)
    if viewer_final != viewer_url or "html" not in viewer_type.lower():
        raise SourceUnavailable("JCI 공개 PDF 뷰어 응답을 확인하지 못했습니다.", url=viewer_final)
    viewer_html = viewer_data.decode("utf-8", errors="replace")
    if ACCESS_CHALLENGE.search(viewer_html):
        raise SourceUnavailable("JCI PDF 뷰어에서 브라우저 확인 또는 접근 인증을 요구합니다.",
                                url=viewer_final, reason_code="access_challenge")
    links = JciDocumentLinks()
    links.feed(viewer_html)
    # A literal, published iframe source is data, not executable JavaScript or a form submission.
    sources = re.findall(r"document\.getElementById\(['\"]asset_source['\"]\)\.src\s*=\s*(['\"])([^'\"<>]+)\1\s*;",
                         viewer_html)
    action = urljoin(viewer_url, links.action) if isinstance(links.action, str) else ""
    parsed = urlsplit(action)
    expected_path = rf"/articles/view/{article_id}/version/\d+/pdf/render\.pdf"
    if (links.method != "get" or parsed.scheme != "https" or parsed.netloc != "insight.jci.org"
            or parsed.query or parsed.fragment or not re.fullmatch(expected_path, parsed.path)
            or action not in [urljoin(viewer_url, value) for _, value in sources]):
        raise SourceUnavailable("JCI 뷰어에서 같은 논문의 정적 공개 PDF 경로를 확인하지 못했습니다.",
                                url=viewer_final, reason_code="unverified_pdf_link")
    pdf_data, content_type, final_url = fetch_url(action)
    try:
        if "application/pdf" not in content_type.lower():
            raise SourceUnavailable("JCI 원문 연결이 PDF 응답을 반환하지 않았습니다.", reason_code="invalid_pdf")
        sections, license_text = parse_pdf(pdf_data, paper)
        return sections, license_text, final_url
    except SourceUnavailable as error:
        raise SourceUnavailable(str(error), url=error.url or final_url,
                                reason_code=error.reason_code or "unverified_pdf") from None


def retrieve(paper):
    doi = normalize_doi(paper.get("doi"))
    pmcid = str(paper.get("pmcid") or "").upper()
    publisher_url = "https://doi.org/" + quote(doi, safe="/") if doi else ""
    fallback = "초록을 표시합니다." if str(paper.get("abstract") or "").strip() else "제공된 초록도 없습니다."
    document = {"candidateId": paper["id"], "title": paper.get("title", ""),
                "abstract": paper.get("abstract", ""), "status": "abstract_only", "format": None,
                "provider": "Europe PMC metadata", "sourceUrl": publisher_url or paper.get("sourceUrl", ""),
                "fetchedAt": now(), "reason": "자동으로 확보한 본문이 없습니다. " + fallback,
                "sections": [], "attempts": [], "sectionCount": 0, "textLength": 0,
                "identifiers": {key: paper.get(key, "") for key in ("doi", "pmid", "pmcid")}}
    targets = []
    if re.fullmatch(r"PMC\d+", pmcid):
        targets.append(("Europe PMC", f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"))
    if publisher_url:
        targets.append(("Publisher", publisher_url))
    jci = re.fullmatch(r"10\.1172/jci\.insight\.(\d+)", doi)
    if jci:
        targets.append(("Publisher", f"https://insight.jci.org/articles/view/{jci[1]}"))
    transient = False
    for provider, url in targets:
        if any(attempt["url"] == url for attempt in document["attempts"]):
            continue
        final_url = url
        try:
            data, content_type, final_url = fetch_url(url)
            if provider == "Publisher":
                document["sourceUrl"] = final_url
            if "application/pdf" in content_type.lower() or data.lstrip().startswith(b"%PDF"):
                raise SourceUnavailable("PDF 응답은 확인했지만 현재 자동 본문 추출은 XML/HTML만 지원합니다.")
            is_xml = provider == "Europe PMC" or (
                "xhtml" not in content_type.lower() and (
                    "xml" in content_type.lower() or data.lstrip().startswith((b"<?xml", b"<article", b"<!DOCTYPE article"))))
            source_format = "xml" if is_xml else "html"
            try:
                sections, license_text = (parse_xml if is_xml else parse_html)(data, paper)
            except SourceUnavailable as error:
                canonical_jci = f"https://insight.jci.org/articles/view/{jci[1]}" if jci else None
                if is_xml or final_url != canonical_jci or error.reason_code == "access_challenge":
                    raise
                sections, license_text, final_url = retrieve_jci_pdf(data, paper, final_url, jci[1])
                source_format = "pdf"
            document.update(status="fulltext", provider=provider, sourceUrl=final_url,
                            reason="논문 식별자와 본문 텍스트를 확인했습니다. 표·그림·보충자료 전체를 확보했다는 뜻은 아닙니다.",
                            format=source_format, sections=sections,
                            license=license_text, sectionCount=len(sections),
                            textLength=sum(len(item["text"]) for item in sections))
            document["attempts"].append({"provider": provider, "url": final_url, "status": "fulltext", "reason": "본문 확보"})
            return document
        except HTTPError as error:
            # Keep the stable paper link for fallback, but retain the actual failing endpoint in provenance.
            final_url = error.geturl() or url
            temporary = error.code in (408, 429, 500, 502, 503, 504)
            transient |= temporary
            reason = (f"HTTP {error.code}: 잠시 후 다시 시도할 수 있습니다." if temporary else
                      f"HTTP {error.code}: 자동 요청으로 원문을 열지 못했습니다. 학교 구독 여부를 뜻하지 않습니다.")
            state = "failed" if temporary else "unavailable"
            reason_code = f"http_{error.code}"
        except SourceUnavailable as error:
            reason, state = str(error), "unavailable"
            final_url = error.url or final_url
            reason_code = error.reason_code or "source_unavailable"
        except (ElementTree.ParseError, OSError, URLError, ValueError, RecursionError) as error:
            transient = True
            reason = ("원문 XML 응답을 읽지 못했습니다. 다시 시도할 수 있습니다." if isinstance(error, ElementTree.ParseError)
                      else "원문 연결 또는 응답 처리가 실패했습니다. 다시 시도할 수 있습니다.")
            state = "failed"
            reason_code = "invalid_xml" if isinstance(error, ElementTree.ParseError) else "connection_or_response_error"
        document["attempts"].append({"provider": provider, "url": final_url, "requestedUrl": url,
                                     "status": state, "reason": reason, "reasonCode": reason_code})
    if transient:
        document.update(status="failed", reason="원문 확인 중 연결 또는 응답 오류가 있었습니다. 다시 시도할 수 있습니다. " + fallback)
    elif targets:
        document["reason"] = document["attempts"][-1]["reason"] + " " + fallback
    else:
        document["reason"] = "자동 원문 요청에 필요한 DOI·PMCID가 없습니다. " + fallback
    return document


class Acquisition:
    def __init__(self, db_path):
        self.db_path = Path(db_path).resolve()
        self._lock, self._thread = threading.Lock(), None
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS candidate_sources (candidate_id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS acquisition_runs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)
        self._recover_interrupted()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _canonical(db, candidate_id, document=None):
        row = db.execute("SELECT id FROM collection_candidates WHERE id=?", (candidate_id,)).fetchone()
        if row:
            return row[0]
        aliases = ["candidate:" + candidate_id]
        if document:
            aliases.extend(f"{key}:{value}" for key, value in document.get("identifiers", {}).items() if value)
        for alias in aliases:
            row = db.execute("SELECT c.id FROM collection_aliases a JOIN collection_candidates c ON c.id=a.candidate_id WHERE a.alias=?", (alias,)).fetchone()
            if row:
                return row[0]
        return None

    def _documents(self, db):
        documents = {}
        for row in db.execute("SELECT candidate_id, data FROM candidate_sources"):
            document = json.loads(row[1])
            canonical = self._canonical(db, row[0], document)
            if canonical:
                document["candidateId"] = canonical
                current = documents.get(canonical)
                priority = lambda item: (item["status"] == "fulltext", item.get("fetchedAt", ""))
                if not current or priority(document) > priority(current):
                    documents[canonical] = document
        return documents

    def summaries(self):
        with self._db() as db:
            return {key: {field: document[field] for field in SUMMARY_FIELDS if field in document}
                    for key, document in self._documents(db).items()}

    def get(self, candidate_id):
        with self._db() as db:
            old = db.execute("SELECT data FROM candidate_sources WHERE candidate_id=?", (candidate_id,)).fetchone()
            canonical = self._canonical(db, candidate_id, json.loads(old[0]) if old else None)
            if not canonical:
                raise KeyError(candidate_id)
            return self._documents(db).get(canonical)

    def status(self):
        self._recover_interrupted()
        with self._db() as db:
            row = db.execute("SELECT data FROM acquisition_runs ORDER BY rowid DESC LIMIT 1").fetchone()
            documents = self._documents(db).values()
            counts = {"fulltext": 0, "abstract": 0, "failed": 0}
            for document in documents:
                counts["abstract" if document["status"] == "abstract_only" else document["status"]] += 1
            return {"run": json.loads(row[0]) if row else None, "counts": counts}

    def start(self, candidate_ids):
        if (not isinstance(candidate_ids, list) or not 1 <= len(candidate_ids) <= 24
                or any(not isinstance(item, str) or not item for item in candidate_ids)
                or len(set(candidate_ids)) != len(candidate_ids)):
            raise ValueError("서로 다른 논문 ID를 1~24개 지정하세요.")
        with self._lock:
            handle = self._acquire_worker_lock()
            if handle is None:
                raise RuntimeError("이미 원문 가져오기가 진행 중입니다.")
            try:
                self._interrupt_stale_runs()
                with self._db() as db:
                    ids = []
                    for candidate_id in candidate_ids:
                        old = db.execute("SELECT data FROM candidate_sources WHERE candidate_id=?", (candidate_id,)).fetchone()
                        canonical = self._canonical(db, candidate_id, json.loads(old[0]) if old else None)
                        if not canonical:
                            raise KeyError(candidate_id)
                        paper = json.loads(db.execute("SELECT data FROM collection_candidates WHERE id=?", (canonical,)).fetchone()[0])
                        if classify_candidate(paper)["kind"] not in ("original", "review"):
                            raise ValueError("현재 원문 가져오기는 원저·Review 논문에만 적용합니다.")
                        ids.append(canonical)
                    if len(set(ids)) != len(ids):
                        raise ValueError("병합된 동일 논문을 중복 지정했습니다.")
                    run = {"id": uuid.uuid4().hex, "status": "running", "candidateIds": ids,
                           "total": len(ids), "processed": 0, "fulltext": 0, "abstract": 0, "failed": 0,
                           "startedAt": now(), "finishedAt": None}
                    self._save_run(db, run)
                snapshot = dict(run)
                self._thread = threading.Thread(target=self._work, args=(run, handle), daemon=True)
                self._thread.start()
                return snapshot
            except Exception:
                self._release_worker_lock(handle)
                raise

    def _acquire_worker_lock(self):
        handle = self.db_path.with_name(self.db_path.name + ".acquisition.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if handle.seek(0, 2) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError as error:
            handle.close()
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return None
            raise

    @staticmethod
    def _release_worker_lock(handle):
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    @staticmethod
    def _save_run(db, run):
        db.execute("INSERT INTO acquisition_runs VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                   (run["id"], json.dumps(run, ensure_ascii=False)))

    def _recover_interrupted(self):
        handle = self._acquire_worker_lock()
        if handle is not None:
            try:
                self._interrupt_stale_runs()
            finally:
                self._release_worker_lock(handle)

    def _interrupt_stale_runs(self):
        with self._db() as db:
            for row in db.execute("SELECT data FROM acquisition_runs").fetchall():
                run = json.loads(row[0])
                if run["status"] == "running":
                    run.update(status="interrupted", finishedAt=now(), reason="원문 가져오기가 중단되었습니다. 미완료 논문은 다시 시도할 수 있습니다.")
                    self._save_run(db, run)

    def _work(self, run, handle):
        try:
            for candidate_id in run["candidateIds"]:
                with self._db() as db:
                    canonical = self._canonical(db, candidate_id)
                    if not canonical:
                        raise KeyError(candidate_id)
                    paper = json.loads(db.execute("SELECT data FROM collection_candidates WHERE id=?", (canonical,)).fetchone()[0])
                    cached = self._documents(db).get(canonical)
                document = cached if cached and cached["status"] == "fulltext" else retrieve(paper)
                with self._db() as db:
                    canonical = self._canonical(db, canonical, document)
                    if not canonical:
                        raise KeyError(candidate_id)
                    existing = self._documents(db).get(canonical)
                    if existing and existing["status"] == "fulltext":
                        document = existing
                    document["candidateId"] = canonical
                    db.execute("INSERT INTO candidate_sources VALUES (?, ?) ON CONFLICT(candidate_id) DO UPDATE SET data=excluded.data",
                               (canonical, json.dumps(document, ensure_ascii=False)))
                    run["processed"] += 1
                    run["abstract" if document["status"] == "abstract_only" else document["status"]] += 1
                    self._save_run(db, run)
            run.update(status="failed" if run["failed"] == run["total"] else "completed", finishedAt=now())
        except Exception:
            run.update(status="failed", finishedAt=now(), reason="원문 가져오기가 중단되었습니다. 저장된 본문은 보존되며 미완료 논문은 다시 시도할 수 있습니다.")
        finally:
            try:
                with self._db() as db:
                    self._save_run(db, run)
            finally:
                self._release_worker_lock(handle)
