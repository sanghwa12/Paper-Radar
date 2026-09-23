"""Real HTTP boundaries for preparation using isolated state and inert fixtures."""
import hashlib
import http.client
import json
import shutil
import sqlite3
import sys
import threading
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import preparation
import server


class PreparationServerTests(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(__file__).resolve().parent
        self.directory = self.test_root / ("preparation-http-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.db_path = self.directory / "state.sqlite3"
        self.httpd = None
        self.quiet = patch.object(server.Handler, "log_message", lambda *args: None)
        self.quiet.start()
        self.builder = patch.object(preparation, "prepare", side_effect=self.prepared_result)
        self.prepare = self.builder.start()
        self.start_server()
        self.paper = {"id": "http-fixture", "title": "Source preparation HTTP fixture", "doi": "10.1234/http-fixture",
                      "pmcid": "PMC123", "abstract": "An ordinary fixture abstract.",
                      "date": "2026-09-01", "firstSeenAt": "2026-09-23T00:00:00Z", "categories": [],
                      "sourceUrl": "https://europepmc.org/article/PMC/PMC123", "publicationTypes": ["Research Article"]}
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("INSERT INTO paper_state VALUES ('adaptiveflow-2026', 1, 1, '보존할 메모', 'fixture')")
            db.execute("INSERT INTO collection_candidates VALUES (?, 'fixture', ?)", (self.paper["id"], json.dumps(self.paper)))
            db.execute("INSERT INTO candidate_sources VALUES (?, ?)", (self.paper["id"], json.dumps({
                "candidateId": self.paper["id"], "status": "abstract_only", "sourceUrl": self.paper["sourceUrl"],
                "identifiers": {"doi": self.paper["doi"], "pmcid": self.paper["pmcid"]}, "sections": [],
                "reason": "Fixture has only an abstract before preparation."})))

    def tearDown(self):
        self.stop_server()
        self.builder.stop()
        self.quiet.stop()
        target = self.directory.resolve()
        self.assertTrue(target.is_relative_to(self.test_root) and target.name.startswith("preparation-http-"))
        shutil.rmtree(target)

    def start_server(self):
        self.httpd = server.create_server(port=0, db_path=self.db_path)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def stop_server(self):
        if self.httpd is not None:
            if self.httpd.preparation._thread:
                self.httpd.preparation._thread.join(timeout=5)
                self.assertFalse(self.httpd.preparation._thread.is_alive())
            self.httpd.shutdown()
            self.httpd.server_close()
            self.thread.join(timeout=3)
            self.assertFalse(self.thread.is_alive())
            self.httpd = None

    def request(self, method, path, payload=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=5)
        headers = dict(headers or {})
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers.setdefault("Content-Type", "application/json")
        try:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def prepared_result(self, paper, directory, prefix, *, cached_document, progress):
        progress("표·그림 자료 준비 중")
        files = {"figure.png": b"inert fixture image bytes", "supplement.html": b"<script>window.fixtureOnly = true;</script>",
                 "script.js": b"window.fixtureOnly = true;", "diagram.svg": b"<svg xmlns='http://www.w3.org/2000/svg'/>"}
        assets = []
        for filename, data in files.items():
            (directory / filename).write_bytes(data)
            assets.append({"id": filename, "kind": "figure" if filename.endswith(".png") else "supplement", "label": filename,
                           "localUrl": prefix + "/" + filename, "sourceUrl": paper["sourceUrl"] + "/" + filename,
                           "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "usable": filename.endswith(".png")})
        text = "The fixture describes a measured comparison and its uncertainty."
        package = {"schemaVersion": 1, "candidateId": paper["id"], "metadata": {"title": paper["title"]},
                   "sources": [{"id": "body-1", "kind": "body", "label": "Fixture results", "text": text,
                                "url": paper["sourceUrl"], "sha256": hashlib.sha256(text.encode()).hexdigest()}]}
        return {"status": "ready", "provider": "HTTP fixture", "sourceUrl": paper["sourceUrl"], "license": "Fixture",
                "preparedAt": preparation.now(), "package": package, "assets": assets, "issues": [],
                "reviewStatus": "reviewed", "generationStatus": "published",
                "coverage": [{"kind": "body", "label": "본문", "expected": 1, "acquired": 1, "usable": 1, "state": "complete"}]}

    def complete(self):
        status, _, body = self.request("POST", "/api/preparation", {"candidateIds": [self.paper["id"]]})
        self.assertEqual(status, 202, body)
        self.httpd.preparation._thread.join(timeout=5)
        self.assertFalse(self.httpd.preparation._thread.is_alive())
        status, _, body = self.request("GET", "/api/preparation")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["run"]["status"], "completed")
        status, _, body = self.request("GET", "/api/preparations/" + self.paper["id"])
        self.assertEqual(status, 200)
        return json.loads(body)["preparation"]

    def protected_state(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            return {table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                    for table in ("candidate_sources", "collection_candidates", "paper_state", "acquisition_runs")}

    def test_post_manifest_input_source_reader_and_restart_preserve_existing_state(self):
        before = self.protected_state()
        document = self.complete()
        self.assertEqual((document["status"], document["generationStatus"], document["reviewStatus"]),
                         ("ready", "waiting", "unreviewed"))
        status, headers, body = self.request("GET", document["inputUrl"])
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        package = json.loads(body)
        self.assertEqual(package["candidateId"], self.paper["id"])
        status, _, body = self.request("GET", "/api/sources/" + self.paper["id"])
        self.assertEqual(status, 200)
        source = json.loads(body)["source"]
        self.assertEqual((source["status"], source["format"]), ("fulltext", "prepared"))
        self.assertEqual(source["sections"][0]["text"], package["sources"][0]["text"])
        self.assertIn("아직", source["reason"])
        status, _, body = self.request("GET", "/api/candidates")
        self.assertEqual(status, 200)
        candidate = json.loads(body)["candidates"][0]
        self.assertEqual(candidate["preparation"]["reviewStatus"], "unreviewed")
        self.assertEqual(candidate["fullTextStatus"], "fulltext")
        self.assertEqual(candidate["sourceDocument"]["format"], "prepared")
        self.assertEqual(self.protected_state(), before)
        self.stop_server()
        self.start_server()
        status, _, body = self.request("GET", "/api/preparations/" + self.paper["id"])
        self.assertEqual(status, 200)
        resumed = json.loads(body)["preparation"]
        self.assertEqual(resumed, document)
        self.assertEqual(self.protected_state(), before)

    def test_async_stage_and_active_worker_conflict_are_exposed_over_http(self):
        entered, release = threading.Event(), threading.Event()

        def waiting_builder(*args, **kwargs):
            kwargs["progress"]("원문 확인 중")
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError("fixture was not released")
            return self.prepared_result(*args, **kwargs)

        self.prepare.side_effect = waiting_builder
        try:
            status, _, _ = self.request("POST", "/api/preparation", {"candidateIds": [self.paper["id"]]})
            self.assertEqual(status, 202)
            self.assertTrue(entered.wait(timeout=2))
            status, _, body = self.request("GET", "/api/preparations/" + self.paper["id"])
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["preparation"]["status"], "preparing")
            status, _, _ = self.request("POST", "/api/preparation", {"candidateIds": [self.paper["id"]]})
            self.assertEqual(status, 409)
        finally:
            release.set()

    def test_existing_fulltext_has_priority_without_mutation_or_get_review_promotion(self):
        document = {"candidateId": self.paper["id"], "status": "fulltext", "provider": "Preserved source",
                    "sections": [{"heading": "Existing", "text": "Preserve original acquired text."}]}
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("UPDATE candidate_sources SET data=? WHERE candidate_id=?", (json.dumps(document), self.paper["id"]))
        self.complete()
        before = self.protected_state()
        for _ in range(2):
            status, _, body = self.request("GET", "/api/sources/" + self.paper["id"])
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["source"], document)
            status, _, body = self.request("GET", "/api/preparations/" + self.paper["id"])
            self.assertEqual(json.loads(body)["preparation"]["reviewStatus"], "unreviewed")
        self.assertEqual(self.protected_state(), before)

    def test_bad_ids_external_origin_and_nested_api_paths_are_rejected(self):
        before = self.protected_state()
        for ids, expected in ((["missing"], 404), (["../http-fixture"], 400), ([], 400), ([self.paper["id"]] * 2, 400)):
            with self.subTest(ids=ids):
                status, _, _ = self.request("POST", "/api/preparation", {"candidateIds": ids})
                self.assertEqual(status, expected)
        status, _, _ = self.request("POST", "/api/preparation", {"candidateIds": [self.paper["id"]]},
                                    headers={"Origin": "https://external.example"})
        self.assertEqual(status, 403)
        self.prepare.assert_not_called()
        self.assertEqual(self.protected_state(), before)
        self.complete()
        for prefix in ("/api/preparations/", "/api/preparation-input/"):
            for suffix in ("unexpected/http-fixture", "..%2Fhttp-fixture", "http-fixture%2F..%2Fhttp-fixture"):
                with self.subTest(path=prefix + suffix):
                    status, _, _ = self.request("GET", prefix + suffix)
                    self.assertEqual(status, 404)

    def test_prepared_assets_are_scoped_and_active_formats_are_inert_attachments(self):
        self.complete()
        prefix = "/assets/prepared/" + self.paper["id"] + "/"
        status, headers, image = self.request("GET", prefix + "figure.png")
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        self.assertEqual(image, b"inert fixture image bytes")
        for filename in ("supplement.html", "script.js", "diagram.svg", "input.json"):
            with self.subTest(filename=filename):
                status, headers, body = self.request("GET", prefix + filename)
                self.assertEqual(status, 200)
                self.assertEqual(headers["Content-Type"], "application/octet-stream")
                self.assertEqual(headers["Content-Disposition"], "attachment")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertTrue(body)
        for path in ("/assets/prepared/..%2Fstate.sqlite3", "/assets/prepared/http-fixture/..%2F..%2Fstate.sqlite3"):
            with self.subTest(path=path):
                status, _, _ = self.request("GET", path)
                self.assertEqual(status, 404)

    def test_changed_asset_invalidates_input_without_marking_any_content_reviewed(self):
        document = self.complete()
        (self.httpd.preparation.asset_root / self.paper["id"] / "figure.png").write_bytes(b"changed")
        status, _, body = self.request("GET", "/api/preparations/" + self.paper["id"])
        self.assertEqual(status, 200)
        changed = json.loads(body)["preparation"]
        self.assertEqual((changed["status"], changed["generationStatus"], changed["reviewStatus"]),
                         ("partial", "needs_sources", "unreviewed"))
        self.assertIsNone(changed["inputUrl"])
        status, _, _ = self.request("GET", document["inputUrl"])
        self.assertEqual(status, 409)


if __name__ == "__main__":
    unittest.main()
