"""Verify reviewed publication gates and normal card/state API behavior with inert fixtures."""
import copy
import hashlib
import http.client
import json
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generated
import generation
import server


class GeneratedTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).parent / ("generated-tests-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.addCleanup(self.cleanup)
        self.folder = self.directory / "drafts/example"
        self.folder.mkdir(parents=True)
        self.asset = self.directory / "public/assets/briefs/fixture/figure.svg"
        self.asset.parent.mkdir(parents=True)
        self.asset.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        root = patch.object(generation, "ROOT", self.directory)
        root.start()
        self.addCleanup(root.stop)
        self.package = {
            "schemaVersion": 1, "candidateId": "fixture",
            "metadata": {"title": "Prediction comparison", "authors": "Example A.", "journal": "Fixture Journal",
                         "date": "2026-09-23", "url": "https://example.org/paper", "categories": ["CADD·AI"]},
            "sources": [], "assets": [{"id": "figure", "kind": "figure",
                "localUrl": "/assets/briefs/fixture/figure.svg", "sha256": generation.digest(self.asset)}]}
        for name, kind, value in (("abstract", "abstract", "The study compares prediction methods."),
                                  ("body", "body", "The models were compared on 120 observations."),
                                  ("figure", "figure", "Figure 1. A comparison of prediction errors.")):
            self.package["sources"].append({"id": name, "kind": kind, "text": value, "label": name,
                "url": "https://example.org/paper#" + name, "sha256": hashlib.sha256(value.encode()).hexdigest()})
        self.package["sources"][-1].update(asset="/assets/briefs/fixture/figure.svg", assetSha256=generation.digest(self.asset))
        pair = {"label": "비교", "method": "관측값을 비교했다.", "result": "120개를 비교했다.",
                "sourceIds": ["body"], "source": {"label": "본문", "url": "https://example.org/paper#body"}}
        self.draft = {
            "candidateId": "fixture", "card": {"titleKo": "예측 비교", "purpose": "예측 오차를 비교한다.",
                "significance": "독립 평가의 중요성", "application": "비교 기준 확인", "limits": "외부 검증 미확인",
                "flow": ["자료", "비교"], "sourceIds": ["body"], "pairs": [pair, copy.deepcopy(pair)]},
            "abstract": {"paragraphs": ["예측 방법을 비교한 연구다."], "source": {"url": "https://example.org/paper#abstract"}},
            "tabs": {tab: [{"title": tab, "blocks": [{"type": "paragraph", "text": "독립 비교의 해석 범위.",
                "sourceIds": ["body"]}]}] for tab in generation.TABS},
            "claims": [{"id": "observations", "kind": "data", "text": "120개 관측값을 비교했다.",
                "support": [{"sourceId": "body", "quote": "120 observations"}]}],
            "readSourceIds": ["abstract", "body", "figure"], "viewedFigureIds": ["figure"],
            "limitations": ["보충자료 미확인"]}
        self.draft["tabs"]["evidence"][0]["blocks"].append({"type": "figure", "title": "Figure 1",
            "image": "/assets/briefs/fixture/figure.svg", "caption": self.package["sources"][-1]["text"],
            "sourceIds": ["figure"], "source": {"label": "Figure 1", "url": "https://example.org/paper#figure"},
            "explanation": [{"label": "비교", "text": "방법별 오차를 나타낸다."}]})
        self.write("input", self.package)
        self.write("draft", self.draft)
        self.review = {"candidateId": "fixture", "inputSha256": generation.digest(self.folder / "input.json"),
            "draftSha256": generation.digest(self.folder / "draft.json"), "status": "partial", "summary": "일부 근거를 대조했다.",
            "checked": {"abstract": "reviewed", "body": "partial", "figure": "partial", "supplement": "unavailable"},
            "checks": [{"label": "표본 수", "status": "pass", "note": "원문과 120개를 대조했다."}],
            "unresolved": ["보충자료 미확인"], "holds": []}
        self.write("review", self.review)
        self.publish()

    def cleanup(self):
        self.assertTrue(self.directory.resolve().is_relative_to(Path(__file__).parent.resolve()))
        for path in sorted(self.directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        self.directory.rmdir()

    def write(self, name, value):
        (self.folder / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def publish(self):
        self.write("publication", {"schemaVersion": 1, "candidateId": "fixture", "publishedAt": "2026-09-23T00:00:00Z",
            "generation": {"mode": "codex-assisted", "label": "Codex 세션"},
            **{name + "Sha256": generation.digest(self.folder / (name + ".json")) for name in ("input", "draft", "review")}})

    def load(self, existing_ids=()):
        return generated.load_generated(self.folder.parent, existing_ids)

    def assert_blocked(self):
        with self.assertLogs("generated", level="WARNING") as messages:
            self.assertEqual(self.load(), {})
        self.assertIn("게시 보류", messages.output[0])

    def test_unpublished_draft_is_not_served(self):
        (self.folder / "publication.json").unlink()
        self.assertEqual(self.load(), {})

    def test_publication_keeps_partial_review_and_four_tabs_without_an_invented_score(self):
        paper = self.load()["fixture"]
        self.assertEqual(set(paper["tabs"]), {*generation.TABS, "memo"})
        self.assertEqual(paper["briefOrigin"]["review"]["checked"]["figures"], "partial")
        self.assertFalse(paper["briefOrigin"]["review"]["acquired"]["supplement"])
        self.assertEqual(paper["briefOrigin"]["review"]["status"], "partial")
        self.assertNotIn("scoreSnapshot", paper)
        self.assertEqual(paper["card"]["image"]["src"], "/assets/briefs/fixture/figure.svg")

    def test_input_draft_and_review_changes_do_not_inherit_publication(self):
        for name in ("input", "draft", "review"):
            with self.subTest(name=name):
                path = self.folder / (name + ".json")
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                self.assert_blocked()
                path.write_bytes(original)

    def test_republishing_changed_draft_does_not_inherit_stale_review(self):
        self.draft["card"]["purpose"] = "새로운 비교 설명"
        self.write("draft", self.draft)
        self.publish()
        self.assert_blocked()

    def test_held_unverified_completed_or_failed_review_is_not_served(self):
        for status in ("held", "unverified", "reviewed"):
            with self.subTest(status=status):
                self.review["status"] = status
                self.write("review", self.review)
                self.publish()
                self.assert_blocked()
        self.review["status"] = "partial"
        self.review["checks"][0]["status"] = "fail"
        self.write("review", self.review)
        self.publish()
        self.assert_blocked()

    def test_an_unavailable_source_cannot_be_marked_reviewed(self):
        self.review["checked"]["supplement"] = "reviewed"
        self.write("review", self.review)
        self.publish()
        self.assert_blocked()

    def test_missing_or_changed_copied_asset_blocks_publication(self):
        self.asset.write_bytes(b"changed")
        self.assert_blocked()
        self.asset.unlink()
        self.assert_blocked()

    def test_unreferenced_asset_is_also_hash_checked(self):
        self.package["assets"].append({"id": "paper", "kind": "paper", "localUrl": "/assets/briefs/fixture/missing.pdf", "sha256": "missing"})
        self.write("input", self.package)
        self.review["inputSha256"] = generation.digest(self.folder / "input.json")
        self.write("review", self.review)
        self.publish()
        self.assert_blocked()

    def test_existing_paper_cannot_be_overwritten(self):
        existing = {"fixture": {"id": "fixture", "card": "existing"}}
        with self.assertLogs("generated", level="WARNING"):
            existing.update(self.load(existing))
        self.assertEqual(existing, {"fixture": {"id": "fixture", "card": "existing"}})

    def test_blocked_publication_preserves_existing_fourteen_papers(self):
        baseline = {**server.load_papers(), **server.load_cards()}
        self.review["status"] = "held"
        self.write("review", self.review)
        self.publish()
        with patch.object(server, "load_generated", side_effect=lambda **args: self.load(**args)), \
                self.assertLogs("generated", level="WARNING"):
            httpd = server.create_server(port=0, db_path=self.directory / "state.sqlite3")
        try:
            self.assertEqual(len(httpd.papers), 14)
            self.assertEqual(httpd.papers, baseline)
        finally:
            httpd.server_close()

    def test_api_adds_one_card_with_durable_state_and_leaves_existing_fourteen_unchanged(self):
        baseline = {**server.load_papers(), **server.load_cards()}
        self.assertEqual(len(baseline), 14)
        with patch.object(server, "load_generated", side_effect=lambda **args: self.load(**args)), \
                patch.object(server.Handler, "log_message", lambda *args: None):
            httpd = server.create_server(port=0, db_path=self.directory / "state.sqlite3")
            thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
            thread.start()
            try:
                self.assertEqual({key: httpd.papers[key] for key in baseline}, baseline)
                self.assertEqual(len(httpd.papers), 15)

                def request(method, path, payload=None):
                    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
                    try:
                        connection.request(method, path, body=json.dumps(payload) if payload is not None else None,
                                           headers={"Content-Type": "application/json"})
                        response = connection.getresponse()
                        return response.status, json.loads(response.read())
                    finally:
                        connection.close()

                status, updated = request("PATCH", "/api/state/fixture", {"read": True, "saved": True, "notes": "새 카드 메모"})
                self.assertEqual(status, 200)
                status, response = request("GET", "/api/papers")
                paper = next(paper for paper in response["papers"] if paper["id"] == "fixture")
                self.assertEqual(paper["state"], updated["state"])
                with server.connect(httpd.db_path) as db:
                    self.assertEqual(server.read_state(db, "fixture"), updated["state"])
                    self.assertEqual(db.execute("SELECT count(*) FROM paper_state").fetchone()[0], 1)
                prepared = {"status": "ready", "reviewStatus": "unreviewed", "generationStatus": "waiting"}
                with patch.object(httpd.collector, "candidates", return_value=[{"id": "fixture"}]), \
                        patch.object(httpd.preparation, "summaries", return_value={"fixture": prepared}), \
                        patch.object(httpd.acquisition, "summaries", return_value={"fixture": {"status": "fulltext"}}):
                    status, response = request("GET", "/api/candidates")
                    candidate = response["candidates"][0]
                    self.assertEqual(candidate["generatedCard"], {"paperId": "fixture", "reviewStatus": "partial", "publishedAt": "2026-09-23T00:00:00Z"})
                    self.assertEqual(candidate["preparation"], prepared)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())
            restarted = server.create_server(port=0, db_path=self.directory / "state.sqlite3")
            try:
                self.assertIn("fixture", restarted.papers)
                with server.connect(restarted.db_path) as db:
                    self.assertEqual(server.read_state(db, "fixture"), updated["state"])
            finally:
                restarted.server_close()


if __name__ == "__main__":
    unittest.main()
