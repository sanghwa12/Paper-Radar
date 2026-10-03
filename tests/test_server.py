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

    def test_retired_apis_and_preserved_ris(self):
        for path in ('/api/collection','/api/evaluation','/api/rounds','/api/fulltext','/api/generation-pilot'):
            self.assertEqual(self.request('GET',path)[0],404,path)
        for filename in ('research-papers.ris','additional-reading.ris'):
            status, _, body = self.request('GET','/exports/choi-2025-aiml-special-issue/'+filename)
            self.assertEqual(status,200)
            self.assertIn(b'TY  -',body)
        self.assertEqual(set(self.httpd.papers), {'adaptiveflow-2026','sung-2025'})

    def test_workflow_records_and_source_access(self):
        status, _, body = self.request('GET','/api/workflows')
        self.assertEqual(status,200)
        record = json.loads(body)['workflows'][0]
        self.assertEqual(record['id'],'choi-2025-aiml')
        self.assertEqual(len(record['papers']),14)
        self.assertEqual(len({p['doi'] for p in record['papers']}),14)
        self.assertIsNone(record['summary'])
        self.assertTrue(all(p['summaryPaperId'] is None for p in record['papers']))
        self.assertEqual(self.request('GET','/api/workflows/unknown/source.pdf')[0],404)
        source = self.temporary / 'source.pdf'
        source.write_bytes(b'%PDF-test')
        import hashlib
        fixture = {'id':'test','source':{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}}
        with patch('server.load_workflows',return_value={'test':fixture}):
            self.assertEqual(self.request('GET','/api/workflows/test/source.pdf')[2],b'%PDF-test')
            source.write_bytes(b'changed')
            self.assertEqual(self.request('GET','/api/workflows/test/source.pdf')[0],404)

    def test_pdf_scan_is_explicit_and_local(self):
        with patch('server.pdf_links.scan',return_value={'papers':{},'errors':[]}) as scan:
            self.request('GET','/api/workflows')
            scan.assert_not_called()
            path='/api/workflows/choi-2025-aiml/scan'
            self.assertEqual(self.request('POST',path,{},headers={'Origin':'https://example.com'})[0],403)
            self.assertEqual(self.request('POST',path,{'folder':'C:/'})[0],400)
            self.assertEqual(self.request('POST',path,{})[0],200)
            scan.assert_called_once()
        self.assertEqual(self.request('GET','/api/workflows/choi-2025-aiml/pdf/0/99')[0],404)
        self.assertEqual(self.request('POST','/api/workflows/choi-2025-aiml/confirm',{'doi':[], 'index':0})[0],400)

    def test_generation_requests_persist_deduplicate_and_validate(self):
        endpoint='/api/generation-requests'
        status, _, body = self.request('GET',endpoint)
        self.assertEqual(status,200)
        data=json.loads(body)
        self.assertEqual(data['requests'],[])
        key=next(t['key'] for t in data['targets'] if t['key'].startswith('library:'))
        payload={'kind':'summary','keys':[key]}
        self.assertEqual(self.request('POST',endpoint,payload,headers={'Origin':'https://example.com'})[0],403)
        self.assertEqual(self.request('POST',endpoint,{'kind':'summary','keys':['not-real']})[0],400)
        self.assertEqual(self.request('POST',endpoint,{'kind':'summary','keys':[]})[0],400)
        first=json.loads(self.request('POST',endpoint,payload)[2])
        self.assertEqual(first['added'],1)
        self.assertEqual(first['requests'][0]['status'],'requested')
        again=json.loads(self.request('POST',endpoint,payload)[2])
        self.assertEqual(again['existing'],1)
        analysis=json.loads(self.request('POST',endpoint,{'kind':'analysis','keys':[key]})[2])
        self.assertEqual(analysis['added'],1)
        self.stop_server(); self.start_server()
        self.assertEqual(len(json.loads(self.request('GET',endpoint)[2])['requests']),2)

    def state(self):
        status, _, body = self.request("GET", "/api/papers")
        self.assertEqual(status, 200)
        papers = json.loads(body)["papers"]
        return next(paper["state"] for paper in papers if paper["id"] == self.paper_id)

    def update(self, changes):
        status, _, body = self.request("PATCH", "/api/state/" + self.paper_id, changes)
        self.assertEqual(status, 200, body)
        return json.loads(body)["state"]

    def test_removed_review_radar_routes_are_unavailable(self):
        for path in ("/api/review-radar", "/review-radar.js",
                     "/assets/review-radar/binding-energy-kinetics-2024/kinetics-map.svg"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.request("POST", "/api/review-radar/search", {})[0], 404)
        self.assertEqual(self.request("GET", "/api/papers")[0], 200)

    def test_state_survives_server_restart(self):
        self.assertEqual(self.state(), {"read": False, "saved": False, "notes": "", "updatedAt": ""})
        notes = "내 target: FSP1\n조건: 10 μM · <assay> & 재확인"
        expected = self.update({"read": True, "saved": True, "notes": notes})
        self.assertTrue(expected["updatedAt"])
        self.stop_server()
        self.start_server()
        self.assertEqual(self.state(), expected)



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
        self.assertEqual(len(papers), 2)
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




if __name__ == "__main__":
    unittest.main()
