"""Exercise the real local HTTP server with a disposable SQLite database."""

import http.client
import json
import sys
import threading
import unittest
import uuid
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cards
import server


class AssetLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = set()

    def handle_starttag(self, tag, attrs):
        self.urls.update(value for key, value in attrs if key in ("href", "src") and value)


def local_asset_urls(value):
    if isinstance(value, dict):
        return set().union(*(local_asset_urls(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(local_asset_urls(item) for item in value))
    if not isinstance(value, str):
        return set()
    parser = AssetLinks()
    parser.feed(value)
    return {urlsplit(url).path for url in {value, *parser.urls}
            if url.startswith(("/reference/", "/assets/"))}


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(__file__).parent / ("paper-radar-tests-" + uuid.uuid4().hex)
        self.assertTrue(self.temporary.resolve().is_relative_to(server.ROOT))
        self.temporary.mkdir()
        self.addCleanup(self.cleanup_database)
        self.db_path = self.temporary / "state.sqlite3"
        quiet = patch.object(server.Handler, "log_message", lambda *args: None)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.start_server()
        self.addCleanup(self.stop_server)
        self.paper_id = "adaptiveflow-2026"

    def cleanup_database(self):
        for path in self.temporary.iterdir():
            path.unlink()
        self.temporary.rmdir()

    def start_server(self):
        self.httpd = server.create_server(port=0, db_path=self.db_path)
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={"poll_interval": 0.02}, daemon=True)
        self.thread.start()

    def stop_server(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join(timeout=3)
            self.assertFalse(self.thread.is_alive(), "HTTP server did not stop")
            self.httpd = None

    def request(self, method, path, payload=None, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        request_headers = dict(headers or {})
        body = raw
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def state(self):
        status, _, body = self.request("GET", "/api/papers")
        self.assertEqual(status, 200)
        papers = json.loads(body)["papers"]
        return next(paper["state"] for paper in papers if paper["id"] == self.paper_id)

    def update(self, changes):
        status, _, body = self.request("PATCH", "/api/state/" + self.paper_id, changes)
        self.assertEqual(status, 200, body)
        return json.loads(body)["state"]

    def test_state_survives_server_restart(self):
        self.assertEqual(self.state(), {"read": False, "saved": False, "notes": "", "updatedAt": ""})
        notes = "내 target: FSP1\n조건: 10 μM · <assay> & 재확인"
        expected = self.update({"read": True, "saved": True, "notes": notes})
        self.assertTrue(expected["updatedAt"])
        self.stop_server()
        self.start_server()
        self.assertEqual(self.state(), expected)

    def test_discovery_card_is_readable_and_has_independent_durable_notes(self):
        before = self.state()
        status, _, body = self.request("GET", "/api/papers")
        self.assertEqual(status, 200)
        cards = [paper for paper in json.loads(body)["papers"]
                 if paper.get("kind") == "discovery" and not paper.get("generationOrigin")]
        self.assertEqual(len(cards), 12)
        self.assertEqual({paper["id"] for paper in cards},
                         {paper["id"] for paper in server.load_evaluation()["papers"]})
        saved = {}
        for index, chosen in enumerate(cards):
            with self.subTest(paper=chosen["id"]):
                self.assertEqual(chosen["candidateId"], chosen["id"])
                self.assertTrue(chosen["abstract"]["paragraphs"])
                self.assertGreaterEqual(len(chosen["card"]["pairs"]), 2)
                self.assertTrue({"summary", "overview", "methods", "evidence", "memo"}
                                .issubset(chosen["tabs"]))
                for tab in ("summary", "overview", "methods", "evidence"):
                    self.assertTrue(chosen["tabs"][tab])
                changes = {"read": index % 2 == 0, "saved": index % 3 == 0,
                           "notes": f"논문 {index + 1} 메모\n한글 · <tag> & 보존"}
                status, _, body = self.request("PATCH", "/api/state/" + chosen["id"], changes)
                self.assertEqual(status, 200)
                saved[chosen["id"]] = json.loads(body)["state"]
                self.assertTrue(saved[chosen["id"]]["updatedAt"])
        self.stop_server()
        self.start_server()
        _, _, body = self.request("GET", "/api/papers")
        resumed = {paper["id"]: paper["state"] for paper in json.loads(body)["papers"]
                   if paper.get("kind") == "discovery" and not paper.get("generationOrigin")}
        self.assertEqual(resumed, saved)
        self.assertEqual(self.state(), before)

    def test_review_hold_does_not_erase_discovery_read_saved_or_notes(self):
        chosen = next(paper for paper in self.httpd.papers.values() if paper.get("kind") == "discovery")
        paper_id = chosen["id"]
        status, _, body = self.request("PATCH", "/api/state/" + paper_id,
                                      {"read": True, "saved": True, "notes": "보류 전 저장한 메모"})
        self.assertEqual(status, 200)
        expected = json.loads(body)["state"]
        original_load_review = cards.load_review

        def held_review(candidate_id):
            review = original_load_review(candidate_id)
            if candidate_id == paper_id:
                review = {**review, "status": "held", "note": "검토 대기",
                          "holds": [{"scope": "brief", "reason": "source", "note": "자료 확인 대기"}]}
            return review

        self.stop_server()
        with patch("cards.load_review", side_effect=held_review):
            self.start_server()
            status, _, body = self.request("GET", "/api/papers")
            self.assertEqual(status, 200)
            held = next(paper for paper in json.loads(body)["papers"] if paper["id"] == paper_id)
            self.assertEqual(held["briefOrigin"]["review"]["status"], "held")
            self.assertEqual(held["state"], expected)
            self.assertTrue(held["card"]["purpose"])
            self.assertEqual(held["tabs"]["memo"], [])
            self.stop_server()
        self.start_server()
        _, _, body = self.request("GET", "/api/papers")
        resumed = next(paper for paper in json.loads(body)["papers"] if paper["id"] == paper_id)
        self.assertEqual(resumed["state"], expected)

    def test_partial_updates_preserve_other_fields_and_other_papers(self):
        self.update({"read": True, "saved": True, "notes": "기존 메모"})
        state = self.update({"notes": "수정 메모"})
        self.assertEqual((state["read"], state["saved"], state["notes"]), (True, True, "수정 메모"))
        state = self.update({"saved": False})
        self.assertEqual((state["read"], state["saved"], state["notes"]), (True, False, "수정 메모"))
        state = self.update({"read": False})
        self.assertEqual((state["read"], state["saved"], state["notes"]), (False, False, "수정 메모"))
        _, _, body = self.request("GET", "/api/papers")
        others = [paper for paper in json.loads(body)["papers"] if paper["id"] != self.paper_id]
        self.assertTrue(others, "The second reference paper must be registered")
        self.assertTrue(all(paper["state"]["notes"] == "" for paper in others))

    def test_invalid_updates_leave_state_unchanged(self):
        before = self.state()
        invalid = [{}, [], {"read": 1}, {"read": "true"}, {"saved": None},
                   {"notes": []}, {"notes": "x" * 100001}, {"unexpected": True}]
        for payload in invalid:
            with self.subTest(payload_type=str(payload)[:70]):
                status, _, _ = self.request("PATCH", "/api/state/" + self.paper_id, payload)
                self.assertEqual(status, 400)
        for raw, content_type in [(b"{broken", "application/json"), (b"{}", "text/plain"),
                                  (b"\xff", "application/json")]:
            with self.subTest(raw=raw):
                status, _, _ = self.request("PATCH", "/api/state/" + self.paper_id,
                                             raw=raw, headers={"Content-Type": content_type})
                self.assertEqual(status, 400)
        status, _, _ = self.request("PATCH", "/api/state/unknown-paper", {"saved": True})
        self.assertEqual(status, 404)
        self.assertEqual(self.state(), before)

    def test_cross_origin_state_update_is_rejected(self):
        for headers in [{"Origin": "https://example.com"}, {"Host": "example.com"}]:
            with self.subTest(headers=headers):
                status, _, _ = self.request("PATCH", "/api/state/" + self.paper_id,
                                             {"saved": True}, headers=headers)
                self.assertEqual(status, 403)
        self.assertFalse(self.state()["saved"])

    def test_collection_endpoints_and_job_conflict(self):
        status, _, body = self.request("GET", "/api/collection")
        self.assertEqual(status, 200)
        overview = json.loads(body)
        self.assertEqual(len(overview["areas"]), 6)
        self.assertEqual(overview["counts"]["total"], 0)
        self.assertIsNone(overview["run"])
        status, _, body = self.request("GET", "/api/candidates")
        self.assertEqual((status, json.loads(body)), (200, {"candidates": []}))
        dates = {"from": "2026-09-01", "to": "2026-09-21"}
        with patch.object(self.httpd.collector, "start", return_value={"id": 1, "status": "running"}) as start:
            status, _, body = self.request("POST", "/api/collection", dates)
            self.assertEqual(status, 202)
            self.assertEqual(json.loads(body)["run"]["status"], "running")
            start.assert_called_once_with(dates["from"], dates["to"])
        with patch.object(self.httpd.collector, "start", side_effect=RuntimeError("이미 수집 중입니다.")):
            status, _, body = self.request("POST", "/api/collection", dates)
            self.assertEqual(status, 409)
            self.assertIn("이미 수집 중", json.loads(body)["error"])

    def test_evaluation_endpoint_is_read_only_and_reports_incomplete_snapshot(self):
        before = self.state()
        snapshot = {"id": "test-pilot", "papers": [{"id": "fixture", "score": {"total": None}}]}
        with patch.object(server, "load_evaluation", return_value=snapshot):
            status, headers, body = self.request("GET", "/api/evaluation")
            self.assertEqual((status, json.loads(body)), (200, snapshot))
            self.assertEqual(headers["Cache-Control"], "no-store")
            status, _, body = self.request("HEAD", "/api/evaluation")
            self.assertEqual((status, body), (200, b""))
        with patch.object(server, "load_evaluation", side_effect=server.EvaluationDataError("평가 준비 중")):
            status, _, body = self.request("GET", "/api/evaluation")
            self.assertEqual((status, json.loads(body)["error"]), (503, "평가 준비 중"))
        status, _, _ = self.request("POST", "/api/evaluation", {"score": 100})
        self.assertEqual(status, 404)
        self.assertEqual(self.state(), before)

    def test_generation_pilot_is_read_only_and_separate_from_library_state(self):
        expected_state = self.update({"read": True, "saved": True, "notes": "시범 비교와 독립된 기존 메모"})
        _, _, before = self.request("GET", "/api/papers")
        self.assertEqual(len(json.loads(before)["papers"]), 14 + len(server.load_generated()))
        runs = [{"runId": "fixture-run", "candidateId": "fixture-paper",
                 "validation": {"status": "unverified"}}]
        with patch.object(server, "load_runs", return_value=runs):
            status, headers, body = self.request("GET", "/api/generation-pilot")
            self.assertEqual((status, json.loads(body)), (200, {"runs": runs}))
            self.assertEqual(headers["Cache-Control"], "no-store")
            status, _, body = self.request("HEAD", "/api/generation-pilot")
            self.assertEqual((status, body), (200, b""))
        for method in ("POST", "PATCH"):
            with self.subTest(method=method):
                status, _, _ = self.request(method, "/api/generation-pilot", {"status": "reviewed"})
                self.assertEqual(status, 404)
        for pilot_id in ("fixture-run", "fixture-paper"):
            status, _, _ = self.request("PATCH", "/api/state/" + pilot_id, {"saved": True})
            self.assertEqual(status, 404)
        _, _, after = self.request("GET", "/api/papers")
        self.assertEqual(json.loads(after), json.loads(before))
        self.stop_server()
        self.start_server()
        self.assertEqual(self.state(), expected_state)
        _, _, restarted = self.request("GET", "/api/papers")
        self.assertEqual(json.loads(restarted), json.loads(before))

    def test_generation_pilot_validation_failure_returns_unavailable(self):
        before = self.state()
        with patch.object(server, "load_runs", side_effect=ValueError("invalid fixture")):
            status, _, body = self.request("GET", "/api/generation-pilot")
            self.assertEqual(status, 503)
            self.assertIn("입력·출처·검증 기록", json.loads(body)["error"])
        self.assertEqual(self.state(), before)

    def test_acquisition_endpoints_and_source_document(self):
        before = self.update({"saved": True, "notes": "보존할 메모"})
        status, _, body = self.request("GET", "/api/acquisition")
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)["run"])
        self.assertEqual(json.loads(body)["counts"], {"fulltext": 0, "abstract": 0, "failed": 0})
        with patch.object(self.httpd.acquisition, "start", return_value={"id": "fetch", "status": "running"}) as start:
            status, _, body = self.request("POST", "/api/acquisition", {"candidateIds": ["paper1"]})
            self.assertEqual((status, json.loads(body)["run"]["status"]), (202, "running"))
            start.assert_called_once_with(["paper1"])
        for error, expected in [(RuntimeError("이미 진행 중"), 409), (ValueError("잘못된 후보"), 400),
                                (KeyError("unknown"), 404)]:
            with patch.object(self.httpd.acquisition, "start", side_effect=error):
                status, _, _ = self.request("POST", "/api/acquisition", {"candidateIds": ["paper1"]})
                self.assertEqual(status, expected)
        document = {"candidateId": "paper1", "status": "fulltext", "sections": [
            {"heading": "Results", "text": "안전한 본문 <script> & 결과"}]}
        with patch.object(self.httpd.acquisition, "get", return_value=document) as get:
            status, headers, body = self.request("GET", "/api/sources/paper1")
            self.assertEqual((status, json.loads(body)), (200, {"source": document}))
            self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
            get.assert_called_once_with("paper1")
            status, _, body = self.request("HEAD", "/api/sources/paper1")
            self.assertEqual((status, body), (200, b""))
        for result in [None, KeyError("missing")]:
            with patch.object(self.httpd.acquisition, "get", **(
                    {"side_effect": result} if isinstance(result, Exception) else {"return_value": result})):
                status, _, _ = self.request("GET", "/api/sources/unknown")
                self.assertEqual(status, 404)
        self.assertEqual(self.state(), before)

    def test_acquisition_validation_and_candidate_enrichment(self):
        for payload in [{}, [], {"candidateIds": []}, {"candidateIds": None},
                        {"candidateIds": ["unknown"]}, {"candidateIds": [], "extra": 1}]:
            status, _, _ = self.request("POST", "/api/acquisition", payload)
            self.assertIn(status, (400, 404))
        for headers in [{"Origin": "https://example.com"}, {"Host": "example.com"}]:
            status, _, _ = self.request("POST", "/api/acquisition", {"candidateIds": ["x"]}, headers=headers)
            self.assertEqual(status, 403)
        for path in ["/api/sources/../server.py", "/api/sources/%2e%2e", "/api/sources/a%2fb"]:
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, 404)
        summary = {"status": "fulltext", "provider": "Europe PMC", "format": "xml"}
        with patch.object(self.httpd.collector, "candidates", return_value=[{"id": "a"}, {"id": "b"}]), \
                patch.object(self.httpd.acquisition, "summaries", return_value={"a": summary}):
            status, _, body = self.request("GET", "/api/candidates")
            self.assertEqual(status, 200)
            papers = json.loads(body)["candidates"]
            self.assertEqual(papers[0]["sourceDocument"], summary)
            self.assertEqual(papers[0]["fullTextStatus"], "fulltext")
            self.assertEqual(papers[1]["fullTextStatus"], "not_retrieved")
            self.assertIsNone(papers[1]["sourceDocument"])
        self.assertIsNone(self.httpd.acquisition.status()["run"])

    def test_collection_rejects_invalid_and_cross_origin_requests(self):
        for data in [{}, [], {"from": "2026-09-01"},
                     {"from": "2026-09-21", "to": "2026-09-01"},
                     {"from": "bad", "to": "2026-09-21"},
                     {"from": None, "to": "2026-09-21"},
                     {"from": "2026-09-01", "to": "2026-09-21", "query": "anything"}]:
            with self.subTest(data=data):
                status, _, _ = self.request("POST", "/api/collection", data)
                self.assertEqual(status, 400)
        for headers in [{"Origin": "https://example.com"}, {"Host": "example.com"}]:
            status, _, _ = self.request("POST", "/api/collection",
                                        {"from": "2026-09-01", "to": "2026-09-21"}, headers=headers)
            self.assertEqual(status, 403)
        self.assertIsNone(self.httpd.collector.status()["run"])

    def test_retry_collection_endpoint(self):
        with patch.object(self.httpd.collector, "retry", return_value={"id": "new", "status": "running"}) as retry:
            status, _, body = self.request("POST", "/api/collection/retry", {"runId": "previous"})
            self.assertEqual((status, json.loads(body)["run"]["id"]), (202, "new"))
            retry.assert_called_once_with("previous")
        for payload in [{}, {"from": "2026-09-01"}, {"runId": None}]:
            status, _, _ = self.request("POST", "/api/collection/retry", payload)
            self.assertEqual(status, 400)
        status, _, _ = self.request("POST", "/api/collection/retry", {"runId": "old"}, headers={"Origin": "https://example.com"})
        self.assertEqual(status, 403)

    def test_source_path_traversal_is_blocked(self):
        for path in ["/reference/../server.py", "/reference/%2e%2e/server.py",
                     "/reference/..%5cserver.py", "/reference/%2e%2e%2fdata/papers/adaptiveflow.json",
                     "/assets/../../server.py", "/data/paper-radar.sqlite3"]:
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path)
                self.assertEqual(status, 404)

    def test_pdf_head_and_ranges(self):
        path = "/reference/adaptiveflow-assets/paper.pdf"
        file_path = server.ROOT / path.lstrip("/")
        size = file_path.stat().st_size
        status, headers, body = self.request("HEAD", path)
        self.assertEqual((status, body), (200, b""))
        self.assertEqual(headers["Content-Type"], "application/pdf")
        self.assertEqual(headers["Content-Disposition"], "inline")
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(int(headers["Content-Length"]), size)
        for range_header, start, end in [("bytes=0-31", 0, 31), ("bytes=-16", size - 16, size - 1),
                                         (f"bytes={size - 24}-", size - 24, size - 1),
                                         (f"bytes={size - 8}-{size + 20}", size - 8, size - 1)]:
            with self.subTest(range_header=range_header):
                status, headers, body = self.request("GET", path, headers={"Range": range_header})
                self.assertEqual(status, 206)
                self.assertEqual(headers["Content-Range"], f"bytes {start}-{end}/{size}")
                with file_path.open("rb") as original:
                    original.seek(start)
                    self.assertEqual(body, original.read(end - start + 1))
        for value in [f"bytes={size}-", "bytes=5-1", "bytes=-0", "bytes=bad", "bytes=0-1,4-5"]:
            with self.subTest(invalid_range=value):
                status, headers, body = self.request("GET", path, headers={"Range": value})
                self.assertEqual((status, body), (416, b""))
                self.assertEqual(headers["Content-Range"], f"bytes */{size}")

    def test_all_registered_local_assets_are_served(self):
        references = server.load_papers()
        self.assertEqual(set(references), {"adaptiveflow-2026", "sung-2025"})
        papers = self.httpd.papers
        self.assertEqual(len(papers), 14 + len(server.load_generated()))
        status, headers, body = self.request("GET", "/assets/documents/manifest.json")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        documents = json.loads(body)
        pdf_urls = {path for paper in papers.values() for path in local_asset_urls(paper)
                    if path.endswith(".pdf")}
        self.assertEqual(set(documents), pdf_urls)
        asset_groups = list(papers.values())
        for document in documents.values():
            self.assertTrue(document["id"])
            self.assertTrue(document["title"])
            self.assertGreater(document["pageCount"], 0)
            self.assertEqual(len(document["pages"]), document["pageCount"])
            self.assertEqual(len(set(document["pages"])), document["pageCount"])
            self.assertTrue(all(path.startswith(f"/assets/documents/{document['id']}/")
                                and path.endswith(".webp") for path in document["pages"]))
            asset_groups.append(document)
        expected_mime = {".pdf": "application/pdf", ".png": "image/png", ".svg": "image/svg+xml",
                         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        for paper in asset_groups:
            paths = local_asset_urls(paper)
            self.assertTrue(paths)
            for path in sorted(paths):
                with self.subTest(paper=paper["id"], path=path):
                    status, headers, body = self.request("HEAD", path)
                    self.assertEqual((status, body), (200, b""))
                    self.assertGreater(int(headers["Content-Length"]), 0)
                    suffix = Path(unquote(path)).suffix.lower()
                    if suffix in expected_mime:
                        self.assertEqual(headers["Content-Type"], expected_mime[suffix])

    def test_discovery_documents_serve_original_pdf_bytes_and_ranges(self):
        paths = {path for paper in self.httpd.papers.values() if paper.get("kind") == "discovery"
                 for path in local_asset_urls(paper) if path.endswith(".pdf")}
        self.assertTrue(paths, "Acquired discovery PDFs must be included in the HTTP checks")
        for path in sorted(paths):
            with self.subTest(path=path):
                original = (server.ROOT / "public" / unquote(path).lstrip("/")).read_bytes()
                self.assertTrue(original.startswith(b"%PDF-"))
                status, headers, body = self.request("GET", path, headers={"Range": "bytes=0-63"})
                self.assertEqual(status, 206)
                self.assertEqual(headers["Content-Type"], "application/pdf")
                self.assertEqual(headers["Content-Disposition"], "inline")
                self.assertEqual(headers["Content-Range"], f"bytes 0-63/{len(original)}")
                self.assertEqual(body, original[:64])
                status, headers, body = self.request("GET", path, headers={"Range": "bytes=-32"})
                self.assertEqual(status, 206)
                self.assertEqual(body, original[-32:])

    def test_discovery_card_images_serve_original_image_bytes(self):
        images = {paper["card"]["image"]["src"] for paper in self.httpd.papers.values()
                  if paper.get("kind") == "discovery" and paper["card"].get("image")}
        self.assertTrue(images)
        for path in sorted(images):
            with self.subTest(path=path):
                original = (server.ROOT / "public" / unquote(path).lstrip("/")).read_bytes()
                status, headers, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertTrue(headers["Content-Type"].startswith("image/"))
                self.assertEqual(int(headers["Content-Length"]), len(original))
                self.assertEqual(body, original)


if __name__ == "__main__":
    unittest.main()
