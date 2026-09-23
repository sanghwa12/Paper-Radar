"""Deterministic source acquisition, parser safety and durable worker checks."""
import io
import json
import socket
import sqlite3
import sys
import threading
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import acquisition


BODY = "We measured binding in independent cell experiments and compared matched controls. " * 35


def paper(identifier="one", **changes):
    return {"id": identifier, "title": "Independent binding experiments", "doi": "10.1234/example",
            "pmcid": "PMC123", "pmid": "123", "abstract": "A short research abstract.",
            "sourceUrl": "https://europepmc.org/article/MED/123", "publicationTypes": ["Research Article"],
            **changes}


def xml(doi="10.1234/example", body=BODY):
    return (f'<!DOCTYPE article PUBLIC "JATS" "https://example.org/never-load.dtd">'
            f'<article><front><article-meta><article-id pub-id-type="doi">{doi}</article-id>'
            '<article-id pub-id-type="pmcid">PMC123</article-id>'
            '<permissions><license>CC BY 4.0</license></permissions></article-meta></front>'
            f'<body><sec><title>Results</title><p>{body}</p><sec><title>Validation</title>'
            '<p>Held-out measurements supported the comparison.</p></sec></sec></body></article>').encode()


def html(body=BODY, doi="10.1234/example"):
    return (f'<html><head><meta name="citation_doi" content="{doi}"></head>'
            f'<body><div class="article-body"><h2>Results</h2><p>{body}</p>'
            '<script>doNotKeep()</script><nav>Navigation</nav></div></body></html>').encode()


def response(data, url, content_type="text/html"):
    result = io.BytesIO(data)
    result.headers = {"Content-Type": content_type}
    result.geturl = lambda: url
    return result


def pdf(doi="10.1172/jci.insight.205218", body=BODY, pages=2, encrypted=False):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(400, 500)
        if body is not None:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            text = (doi + "\n" if index == 0 else "") + body
            text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 12 Tf 20 40 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("not-for-automatic-access")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def jci_article(doi="10.1172/jci.insight.205218"):
    return (f'<meta name="citation_doi" content="{doi}">'
            '<a href="/articles/view/205218/pdf">View PDF</a><p>Abstract only</p>').encode()


def jci_viewer(action="/articles/view/205218/version/7/pdf/render.pdf", method="get", source=None):
    source = action if source is None else source
    return (f'<form id="download_pdf_form" action="{action}" method="{method}">'
            '<input type="hidden" name="unused" value="must-not-submit"></form>'
            "<iframe id='asset_source' src=''></iframe>"
            f'<script>document.getElementById("asset_source").src = "{source}";</script>').encode()


class ParsingTests(unittest.TestCase):
    def test_jats_identity_sections_license_and_no_external_entity_requests(self):
        sections, license_text = acquisition.parse_xml(xml(), paper())
        self.assertEqual([item["heading"] for item in sections], ["Results", "Validation"])
        self.assertNotIn("Held-out", sections[0]["text"])
        self.assertEqual(license_text, "CC BY 4.0")
        with self.assertRaises(acquisition.SourceUnavailable):
            acquisition.parse_xml(xml(doi="10.1234/wrong"), paper())
        with self.assertRaises(acquisition.SourceUnavailable):
            acquisition.parse_xml(xml().replace(b'<body>', b'<other>').replace(b'</body>', b'</other>'), paper())

    def test_entity_declarations_and_utf16_are_rejected(self):
        for data in (b'<!DOCTYPE article [<!ENTITY bad "expanded">]>' + xml(),
                     ('<!DOCTYPE article [<!ENTITY bad "expanded">]>' + xml().decode()).encode("utf-16")):
            with self.subTest(data=data[:20]), self.assertRaises(acquisition.SourceUnavailable):
                acquisition.parse_xml(data, paper())

    def test_html_requires_identity_real_body_and_discards_executable_text(self):
        sections, _ = acquisition.parse_html(html(), paper())
        self.assertEqual(sections[0]["heading"], "Results")
        self.assertNotIn("doNotKeep", sections[0]["text"])
        self.assertNotIn("Navigation", sections[0]["text"])
        for data in (html(doi="10.1234/wrong"), b'<html><article><p>' + BODY.encode() + b'</p></article></html>',
                     html(body="Are you a robot? " + BODY), html(body="Sign in to read the full text. " + BODY)):
            with self.subTest(data=data[:60]), self.assertRaises(acquisition.SourceUnavailable):
                acquisition.parse_html(data, paper())

    def test_long_abstract_and_landing_page_cannot_be_fulltext(self):
        abstract = "We describe a measured result in the abstract. " * 30
        with self.assertRaises(acquisition.SourceUnavailable):
            acquisition.parse_html(html(body=abstract + " Related article links and navigation."), paper(abstract=abstract))
        with self.assertRaises(acquisition.SourceUnavailable):
            acquisition.parse_html(html(body="<h2>Abstract</h2>" + BODY), paper())

    def test_structured_abstract_subheadings_are_never_main_body(self):
        methods = "We measured compound activities in cells. " * 20
        results = "The compounds reduced target activity. " * 20
        abstract = "A short background. " + methods + results
        structured = f'<h2>Abstract</h2><p>A short background.</p><h3>Methods</h3><p>{methods}</p><h3>Results</h3><p>{results}</p>'
        for content in (structured, '<section class="abstract">' + structured + '</section>'):
            with self.subTest(content=content[:60]), self.assertRaises(acquisition.SourceUnavailable):
                acquisition.parse_html(html(body=content), paper(abstract=abstract))

    def test_jsonld_body_must_belong_to_requested_article(self):
        graph = [{"@type": "ScholarlyArticle", "identifier": "10.1234/wrong", "articleBody": BODY},
                 {"@type": "ScholarlyArticle", "identifier": "10.1234/example"}]
        data = ('<script type="application/ld+json">' + json.dumps(graph) + '</script>').encode()
        with self.assertRaises(acquisition.SourceUnavailable):
            acquisition.parse_html(data, paper())
        graph[1]["articleBody"] = BODY
        data = ('<script type="application/ld+json">' + json.dumps(graph) + '</script>').encode()
        sections, _ = acquisition.parse_html(data, paper())
        self.assertGreater(len(sections[0]["text"]), 2000)

    def test_public_https_only_and_redirect_guard(self):
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with patch.object(acquisition.socket, "getaddrinfo", return_value=public):
            self.assertEqual(acquisition.validate_url("https://example.org/article"), "https://example.org/article")
            for url in ("http://example.org", "https://user:password@example.org", "https://example.org:8443", "file:///secret"):
                with self.subTest(url=url), self.assertRaises(acquisition.SourceUnavailable):
                    acquisition.validate_url(url)
        for address in ("127.0.0.1", "192.168.1.1", "169.254.169.254", "::1", "10.1.2.3"):
            with patch.object(acquisition.socket, "getaddrinfo", return_value=[(2, 1, 6, "", (address, 443))]):
                with self.subTest(address=address), self.assertRaises(acquisition.SourceUnavailable):
                    acquisition.SafeRedirect().redirect_request(Request("https://doi.org/10.1234/example"), None,
                                                                 302, "", {}, "https://internal.example/article")

    def test_url_guard_records_reason_and_redacts_embedded_credentials(self):
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        cases = [("http://example.org/article", "https_required", "http://example.org/article"),
                 ("https://user:secret@example.org/article", "credentials_in_url", "https://example.org/article"),
                 ("https://example.org:8443/article", "unsupported_port", "https://example.org:8443/article"),
                 ("https://user:secret@[invalid", "invalid_url", None)]
        with patch.object(acquisition.socket, "getaddrinfo", return_value=public):
            for url, code, stored_url in cases:
                with self.subTest(url=stored_url), self.assertRaises(acquisition.SourceUnavailable) as raised:
                    acquisition.validate_url(url)
                self.assertEqual(raised.exception.reason_code, code)
                self.assertEqual(raised.exception.url, stored_url)
                self.assertNotIn("secret", str(raised.exception))

    def test_rejected_redirect_is_preserved_without_issuing_destination_request(self):
        initial = "https://doi.org/10.1234/example"
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        cases = [("http://publisher.example/article", public, "https_required"),
                 ("https://internal.example/article", private, "non_public_address")]
        for target, addresses, code in cases:
            def reject(url):
                acquisition.SafeRedirect().redirect_request(Request(url), None, 302, "", {}, target)

            with self.subTest(code=code), patch.object(acquisition.socket, "getaddrinfo", return_value=addresses), \
                    patch.object(acquisition.HTTPRedirectHandler, "redirect_request") as allowed_redirect, \
                    patch.object(acquisition, "fetch_url", side_effect=reject) as fetch:
                document = acquisition.retrieve(paper(pmcid=""))
            self.assertEqual(document["status"], "abstract_only")
            self.assertEqual(document["sections"], [])
            self.assertEqual(document["sourceUrl"], initial)
            self.assertEqual(document["attempts"][0]["url"], target)
            self.assertEqual(document["attempts"][0]["requestedUrl"], initial)
            self.assertEqual(document["attempts"][0]["reasonCode"], code)
            fetch.assert_called_once_with(initial)
            allowed_redirect.assert_not_called()

    def test_response_size_and_timeout_are_bounded(self):
        response = io.BytesIO(b"abcdef")
        response.headers = {"Content-Type": "text/html"}
        response.geturl = lambda: "https://example.org/article"
        with patch.object(acquisition, "validate_url", side_effect=lambda url: url), \
                patch.object(acquisition, "build_opener") as opener, patch.object(acquisition, "MAX_BYTES", 3):
            opener.return_value.open.return_value = response
            with self.assertRaises(acquisition.SourceUnavailable):
                acquisition.fetch_url("https://example.org/article")
            self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"], acquisition.REQUEST_TIMEOUT)

    def test_doi_requests_html_and_only_pmc_endpoint_prefers_xml(self):
        for url, expected in (("https://doi.org/10.1234/example", "text/html"),
                              ("https://www.ebi.ac.uk/europepmc/webservices/rest/PMC123/fullTextXML", "application/xml")):
            response = io.BytesIO(b"content")
            response.headers = {"Content-Type": "text/plain"}
            response.geturl = lambda: url
            with self.subTest(url=url), patch.object(acquisition, "validate_url", side_effect=lambda value: value), \
                    patch.object(acquisition, "build_opener") as opener:
                opener.return_value.open.return_value = response
                acquisition.fetch_url(url)
                request = opener.return_value.open.call_args.args[0]
                self.assertTrue(request.get_header("Accept").startswith(expected))
                if "doi.org" in url:
                    self.assertNotIn("application/xml", request.get_header("Accept"))

    def test_standard_meta_refresh_follows_validated_relative_url_without_script_execution(self):
        initial = "https://publisher.example/retrieve/article"
        target = "https://publisher.example/retrieve/paper?source=doi&format=html"
        # The observed publisher page uses a quoted, relative HTTP-EQUIV navigation target.
        redirect = (b'<meta HTTP-EQUIV="REFRESH" content="2; url=\'paper?source=doi&amp;format=html\'">'
                    b'<script>window.location="https://ignored.example/script";</script>')
        with patch.object(acquisition, "validate_url", side_effect=lambda url: url) as validate, \
                patch.object(acquisition, "build_opener") as opener:
            opener.return_value.open.side_effect = [response(redirect, initial), response(html(), target)]
            data, content_type, final = acquisition.fetch_url(initial)
        self.assertEqual((data, content_type, final), (html(), "text/html", target))
        self.assertEqual([call.args[0].full_url for call in opener.return_value.open.call_args_list], [initial, target])
        self.assertIn(((target,), {}), [(call.args, call.kwargs) for call in validate.call_args_list])

    def test_missing_or_malformed_meta_refresh_never_executes_script_navigation(self):
        data = (b'<meta http-equiv><meta http-equiv="refresh" content>'
                b'<meta http-equiv="refresh" content="0;url=\'https://publisher.example/unclosed">'
                b'<script>window.location="https://ignored.example/script";</script>')
        parser = acquisition.MetaRefresh()
        parser.feed(data.decode())
        self.assertIsNone(parser.target)

    def test_meta_refresh_cannot_follow_http_private_or_script_targets(self):
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        initial = "https://publisher.example/article"
        cases = [("http://publisher.example/paper", "https_required"),
                 ("https://internal.example/paper", "non_public_address"),
                 ("javascript:alert(1)", "https_required")]
        for target, reason in cases:
            redirect = f'<meta http-equiv="refresh" content="0;url={target}">'.encode()
            with self.subTest(target=target), \
                    patch.object(acquisition.socket, "getaddrinfo", side_effect=lambda host, *a, **k: private if host == "internal.example" else public), \
                    patch.object(acquisition, "build_opener") as opener, \
                    self.assertRaises(acquisition.SourceUnavailable) as raised:
                opener.return_value.open.return_value = response(redirect, initial)
                acquisition.fetch_url(initial)
            self.assertEqual(raised.exception.reason_code, reason)
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_meta_refresh_rejects_cycles_and_more_than_three_hops(self):
        for cycle in (True, False):
            urls = [f"https://publisher.example/{index}" for index in range(5)]
            targets = [urls[1], urls[0]] if cycle else urls[1:]
            responses = [response(f'<meta http-equiv="refresh" content="0;url={target}">'.encode(), urls[index])
                         for index, target in enumerate(targets)]
            with self.subTest(cycle=cycle), patch.object(acquisition, "validate_url", side_effect=lambda url: url), \
                    patch.object(acquisition, "build_opener") as opener, \
                    self.assertRaises(acquisition.SourceUnavailable) as raised:
                opener.return_value.open.side_effect = responses
                acquisition.fetch_url(urls[0])
            self.assertEqual(raised.exception.reason_code, "redirect_cycle" if cycle else "redirect_limit")
            self.assertEqual(opener.return_value.open.call_count, 2 if cycle else 4)

    def test_meta_refresh_keeps_one_cumulative_size_and_time_budget(self):
        initial, target = "https://publisher.example/start", "https://publisher.example/paper"
        redirect = b'<meta http-equiv="refresh" content="0;url=/paper">'
        with patch.object(acquisition, "validate_url", side_effect=lambda url: url), \
                patch.object(acquisition, "build_opener") as opener, \
                patch.object(acquisition, "MAX_BYTES", len(redirect) + 2), self.assertRaises(acquisition.SourceUnavailable):
            opener.return_value.open.side_effect = [response(redirect, initial), response(b"large", target)]
            acquisition.fetch_url(initial)
        with patch.object(acquisition, "validate_url", side_effect=lambda url: url), \
                patch.object(acquisition, "build_opener") as opener, \
                patch.object(acquisition.time, "monotonic", side_effect=[0, 0, 1, 1, 61]), \
                self.assertRaises(TimeoutError):
            opener.return_value.open.return_value = response(redirect, initial)
            acquisition.fetch_url(initial)
        self.assertEqual(opener.return_value.open.call_count, 1)

    def test_meta_refresh_preserves_http_403_and_does_not_retry_it(self):
        initial, target = "https://publisher.example/start", "https://publisher.example/paper"
        redirect = b'<meta http-equiv="refresh" content="0;url=/paper">'
        forbidden = HTTPError(target, 403, "blocked", {}, None)
        with patch.object(acquisition, "validate_url", side_effect=lambda url: url), \
                patch.object(acquisition, "build_opener") as opener, self.assertRaises(HTTPError) as raised:
            opener.return_value.open.side_effect = [response(redirect, initial), forbidden]
            acquisition.fetch_url(initial)
        self.assertIs(raised.exception, forbidden)
        self.assertEqual(opener.return_value.open.call_count, 2)

    def test_jci_https_target_is_separate_from_rejected_http_redirect(self):
        doi = "10.1172/jci.insight.205218"
        blocked = "http://insight.jci.org/articles/view/205218"
        canonical = "https://insight.jci.org/articles/view/205218"
        with patch.object(acquisition, "fetch_url", side_effect=[
                acquisition.SourceUnavailable("HTTP 이동 거절", url=blocked, reason_code="https_required"),
                (html(doi=doi), "text/html", canonical)]) as fetch:
            document = acquisition.retrieve(paper(doi=doi, pmcid=""))
        self.assertEqual(document["status"], "fulltext")
        self.assertEqual(document["attempts"][0]["url"], blocked)
        self.assertEqual(document["attempts"][0]["reasonCode"], "https_required")
        self.assertEqual(document["sourceUrl"], canonical)
        self.assertEqual([call.args[0] for call in fetch.call_args_list], ["https://doi.org/" + doi, canonical])

    def test_pdf_requires_first_page_identity_real_body_and_bounded_unencrypted_document(self):
        target = paper(doi="10.1172/jci.insight.205218", pmcid="")
        sections, _ = acquisition.parse_pdf(pdf(), target)
        self.assertEqual([item["heading"] for item in sections], ["PDF · 1쪽", "PDF · 2쪽"])
        for data in (pdf(doi="10.1172/jci.insight.999999"), pdf(body="Abstract only.", pages=1),
                     pdf(body=None, pages=501), pdf(encrypted=True), b'<html>Not a PDF</html>', b'%PDF-broken'):
            with self.subTest(prefix=data[:10]), self.assertRaises(acquisition.SourceUnavailable):
                acquisition.parse_pdf(data, target)
        with patch.object(acquisition, "MAX_BYTES", 1), self.assertRaises(acquisition.SourceUnavailable):
            acquisition.parse_pdf(pdf(), target)

    def test_jci_pdf_uses_published_static_path_not_fields_or_assumed_version(self):
        doi = "10.1172/jci.insight.205218"
        canonical = "https://insight.jci.org/articles/view/205218"
        download = canonical + "/version/7/pdf/render.pdf"
        delivered = "https://cdn.example/published-article.pdf"
        with patch.object(acquisition, "fetch_url", side_effect=[
                acquisition.SourceUnavailable("HTTP 이동 거절", url=canonical.replace("https:", "http:"), reason_code="https_required"),
                (jci_article(), "text/html", canonical), (jci_viewer(), "text/html", canonical + "/pdf"),
                (pdf(), "application/pdf", delivered)]) as fetch:
            document = acquisition.retrieve(paper(doi=doi, pmcid=""))
        self.assertEqual((document["status"], document["format"], document["sourceUrl"]), ("fulltext", "pdf", delivered))
        self.assertEqual(document["sectionCount"], 2)
        self.assertNotIn("reviewStatus", document)
        self.assertEqual([call.args[0] for call in fetch.call_args_list],
                         ["https://doi.org/" + doi, canonical, canonical + "/pdf", download])

    def test_jci_pdf_does_not_fetch_without_matching_article_doi_or_published_link(self):
        target = paper(doi="10.1172/jci.insight.205218", pmcid="")
        canonical = "https://insight.jci.org/articles/view/205218"
        for article in (jci_article(doi="10.1172/jci.insight.999999"),
                        jci_article().replace(b"205218/pdf", b"999999/pdf")):
            with self.subTest(article=article[:70]), patch.object(acquisition, "fetch_url") as fetch, \
                    self.assertRaises(acquisition.SourceUnavailable):
                acquisition.retrieve_jci_pdf(article, target, canonical, "205218")
            fetch.assert_not_called()

    def test_jci_pdf_refuses_post_external_mismatched_or_dynamic_viewer_paths(self):
        target = paper(doi="10.1172/jci.insight.205218", pmcid="")
        canonical = "https://insight.jci.org/articles/view/205218"
        cases = [jci_viewer(method="post"), jci_viewer(action="https://other.example/article.pdf"),
                 jci_viewer(action="/articles/view/999999/version/1/pdf/render.pdf"),
                 jci_viewer(source="/articles/view/205218/version/9/pdf/render.pdf"),
                 jci_viewer().replace(b'render.pdf";', b'render.pdf" + dynamicToken;'),
                 jci_viewer() + b'<p>Verify that you are human</p>']
        for viewer in cases:
            with self.subTest(viewer=viewer[:60]), patch.object(acquisition, "fetch_url", return_value=(viewer, "text/html", canonical + "/pdf")) as fetch, \
                    self.assertRaises(acquisition.SourceUnavailable):
                acquisition.retrieve_jci_pdf(jci_article(), target, canonical, "205218")
            fetch.assert_called_once_with(canonical + "/pdf")

    def test_jci_pdf_403_and_wrong_pdf_response_remain_unavailable(self):
        target = paper(doi="10.1172/jci.insight.205218", pmcid="")
        canonical = "https://insight.jci.org/articles/view/205218"
        for outcome in (HTTPError(canonical + "/pdf", 403, "blocked", {}, None),
                        (b'<html>Checking your browser</html>', "text/html", "https://cdn.example/blocked"),
                        (pdf(doi="10.1172/jci.insight.999999"), "application/pdf", "https://cdn.example/wrong.pdf")):
            expected = HTTPError if isinstance(outcome, HTTPError) else acquisition.SourceUnavailable
            responses = [outcome] if isinstance(outcome, HTTPError) else [(jci_viewer(), "text/html", canonical + "/pdf"), outcome]
            with self.subTest(outcome=str(outcome)[:60]), patch.object(acquisition, "fetch_url", side_effect=responses) as fetch, \
                    self.assertRaises(expected):
                acquisition.retrieve_jci_pdf(jci_article(), target, canonical, "205218")
            self.assertEqual(fetch.call_count, 1 if isinstance(outcome, HTTPError) else 2)

    def test_jci_canonical_challenge_or_403_is_not_followed_by_pdf_or_duplicate_request(self):
        canonical = "https://insight.jci.org/articles/view/205218"
        for outcome in (HTTPError(canonical, 403, "blocked", {}, None),
                        (jci_article() + b'<p>Are you a robot?</p>', "text/html", canonical)):
            with self.subTest(outcome=str(outcome)[:60]), patch.object(acquisition, "fetch_url") as fetch:
                if isinstance(outcome, HTTPError):
                    fetch.side_effect = outcome
                else:
                    fetch.return_value = outcome
                document = acquisition.retrieve(paper(doi="10.1172/jci.insight.205218", pmcid=""))
            self.assertEqual(document["status"], "abstract_only")
            self.assertEqual(document["attempts"][0]["reasonCode"], "http_403" if isinstance(outcome, HTTPError) else "access_challenge")
            fetch.assert_called_once()


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).parent / ("acquisition-test-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.db_path = self.directory / "test.sqlite3"
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executescript("""
                CREATE TABLE collection_candidates(id TEXT PRIMARY KEY, created_run TEXT, data TEXT);
                CREATE TABLE collection_aliases(alias TEXT PRIMARY KEY, candidate_id TEXT);
                CREATE TABLE paper_state(id TEXT PRIMARY KEY, data TEXT);
                INSERT INTO paper_state VALUES ('saved', '{"note":"preserve"}');
            """)
        self.add_candidate(paper())
        self.client = acquisition.Acquisition(self.db_path)
        self.clients = [self.client]
        self.fetcher = patch.object(acquisition, "fetch_url", return_value=(xml(), "application/xml", "https://europepmc.org/PMC123"))
        self.fetch = self.fetcher.start()
        self.addCleanup(self.fetcher.stop)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for client in self.clients:
            if client._thread:
                client._thread.join(timeout=4)
                self.assertFalse(client._thread.is_alive())
        self.assertTrue(self.directory.resolve().is_relative_to(Path(__file__).parent.resolve()))
        for path in self.directory.iterdir():
            path.unlink()
        self.directory.rmdir()

    def add_candidate(self, item):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("INSERT INTO collection_candidates VALUES (?, 'fixture', ?)", (item["id"], json.dumps(item)))
            for field in ("doi", "pmcid", "pmid"):
                if item.get(field):
                    db.execute("INSERT OR REPLACE INTO collection_aliases VALUES (?, ?)", (f"{field}:{item[field]}", item["id"]))

    def run_acquisition(self, ids=None):
        run = self.client.start(ids or ["one"])
        self.assertEqual(run["status"], "running")
        self.client._thread.join(timeout=4)
        self.assertFalse(self.client._thread.is_alive())
        return self.client.status()["run"]

    def test_persistent_cache_no_metadata_or_user_state_changes(self):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            before = db.execute("SELECT * FROM collection_candidates").fetchall()
        first = self.run_acquisition()
        document = self.client.get("one")
        self.assertEqual((first["processed"], first["fulltext"], first["failed"]), (1, 1, 0))
        self.assertEqual(document["format"], "xml")
        self.assertEqual(self.client.summaries()["one"]["status"], "fulltext")
        self.assertNotIn("sections", self.client.summaries()["one"])
        self.run_acquisition()
        self.assertEqual(self.fetch.call_count, 1)
        reopened = acquisition.Acquisition(self.db_path)
        self.assertEqual(reopened.get("one"), document)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            self.assertEqual(db.execute("SELECT * FROM collection_candidates").fetchall(), before)
            self.assertEqual(db.execute("SELECT data FROM paper_state").fetchone()[0], '{"note":"preserve"}')

    def test_europepmc_absence_uses_publisher_html_then_caches(self):
        self.fetch.side_effect = [HTTPError("https://europepmc.org/PMC123", 404, "absent", {}, None),
                                 (html(), "text/html", "https://publisher.example/article")]
        self.run_acquisition()
        document = self.client.get("one")
        self.assertEqual((document["status"], document["format"], document["provider"]), ("fulltext", "html", "Publisher"))
        self.assertEqual(len(document["attempts"]), 2)
        self.assertEqual(document["sourceUrl"], "https://publisher.example/article")

    def test_blocked_pdf_abstract_and_malformed_xml_never_claim_fulltext(self):
        cases = [
            (HTTPError("https://publisher.example/article", 403, "blocked", {}, None), "abstract_only"),
            ((b"%PDF-1.5 body", "application/pdf", "https://publisher.example/article.pdf"), "abstract_only"),
            ((b"<html>Are you a robot?</html>", "text/html", "https://publisher.example/article"), "abstract_only"),
            ((b"<article><body>", "text/xml", "https://publisher.example/article"), "failed"),
            (URLError("offline"), "failed"),
        ]
        for outcome, status in cases:
            self.fetch.side_effect = None
            if isinstance(outcome, Exception):
                self.fetch.side_effect = outcome
            else:
                self.fetch.return_value = outcome
            with self.subTest(status=status, outcome=str(outcome)[:80]):
                result = acquisition.retrieve(paper(pmcid=""))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["abstract"], paper()["abstract"])
                self.assertEqual(result["sections"], [])

    def test_failed_and_blocked_requests_can_be_explicitly_retried(self):
        self.fetch.side_effect = URLError("offline")
        run = self.run_acquisition()
        self.assertEqual((run["status"], run["failed"]), ("failed", 1))
        self.assertEqual(self.client.get("one")["status"], "failed")
        self.fetch.side_effect = None
        self.run_acquisition()
        self.assertEqual(self.client.get("one")["status"], "fulltext")
        self.assertEqual(self.client.status()["counts"], {"fulltext": 1, "abstract": 0, "failed": 0})

    def test_http_failure_records_actual_endpoint_without_replacing_paper_link(self):
        actual = "https://publisher.example/article"
        self.fetch.side_effect = HTTPError(actual, 403, "blocked", {}, None)
        document = acquisition.retrieve(paper(pmcid=""))
        self.assertEqual(document["sourceUrl"], "https://doi.org/10.1234/example")
        self.assertEqual(document["attempts"][0]["url"], actual)

    def test_missing_abstract_does_not_claim_to_display_one(self):
        document = acquisition.retrieve(paper(doi="", pmcid="", abstract=""))
        self.assertEqual(document["status"], "abstract_only")
        self.assertIn("제공된 초록도 없습니다", document["reason"])
        self.assertNotIn("초록을 표시", document["reason"])

    def test_validates_ids_types_limits_and_distinct_canonical_ids(self):
        for ids in (None, [], "one", ["one", "one"], [1], [str(value) for value in range(25)]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.client.start(ids)
        with self.assertRaises(KeyError):
            self.client.start(["missing"])
        self.add_candidate(paper("preprint", doi="", pmcid="", pmid="", publicationTypes=["Preprint"]))
        with self.assertRaises(ValueError):
            self.client.start(["preprint"])
        self.assertIsNone(self.client.get("one"))
        with self.assertRaises(KeyError):
            self.client.get("missing")
        self.assertEqual(self.fetch.call_count, 0)

    def test_cross_instance_lock_and_recovery_preserve_durable_sources(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def wait_fetch(url):
            entered.set()
            release.wait(timeout=3)
            return xml(), "application/xml", url

        self.fetch.side_effect = wait_fetch
        self.client.start(["one"])
        self.assertTrue(entered.wait(timeout=2))
        second = acquisition.Acquisition(self.db_path)
        self.clients.append(second)
        self.assertEqual(second.status()["run"]["status"], "running")
        with self.assertRaises(RuntimeError):
            second.start(["one"])
        release.set()
        self.client._thread.join(timeout=4)
        with closing(sqlite3.connect(self.db_path)) as db, db:
            run = self.client.status()["run"]
            run.update(status="running", finishedAt=None)
            db.execute("UPDATE acquisition_runs SET data=? WHERE id=?", (json.dumps(run), run["id"]))
        recovered = acquisition.Acquisition(self.db_path)
        self.assertEqual(recovered.status()["run"]["status"], "interrupted")
        self.assertEqual(recovered.get("one")["status"], "fulltext")

    def test_merged_candidate_resolves_old_id_and_retains_cache(self):
        self.run_acquisition()
        self.add_candidate(paper("survivor"))
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("INSERT INTO collection_aliases VALUES ('candidate:one', 'survivor')")
            db.execute("DELETE FROM collection_candidates WHERE id='one'")
        self.assertEqual(self.client.get("one")["candidateId"], "survivor")
        self.assertEqual(set(self.client.summaries()), {"survivor"})
        with self.assertRaises(ValueError):
            self.client.start(["one", "survivor"])
        self.run_acquisition(["one"])
        self.assertEqual(self.fetch.call_count, 1)
        self.assertEqual(self.client.status()["counts"]["fulltext"], 1)


if __name__ == "__main__":
    unittest.main()
