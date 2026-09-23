"""Bounded recommendation manifests, unknown scores, real workflow states and read-only HTTP."""
import copy
import http.client
import json
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import evaluation
import rounds
import server


class RoundTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).parent / ("round-tests-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.addCleanup(self.cleanup)
        self.manifests = self.directory / "rounds"
        self.manifests.mkdir()
        self.candidates = [{"id": f"fixture-{index}", "title": f"Comparison {index}", "doi": f"10.1234/fixture-{index}",
                            "source": "MED", "publicationTypes": ["Research Article"], "categories": [area],
                            "date": "2026-09-01", "firstSeenAt": "2026-09-23T00:00:00Z"}
                           for index, area in enumerate(rounds.AREA_NAMES)]
        self.document = {"schemaVersion": 1, "id": "fixture-round", "createdAt": "2026-09-23T00:00:00Z", "title": "이번 추천 6편",
            "selection": {"mode": "codex-assisted", "from": "2026-08-23", "to": "2026-09-23", "source": "Europe PMC",
                "policyVersion": "v2", "weights": dict(evaluation.WEIGHTS), "note": "분야별 1편의 잠정 추천. 전체 후보 상위순위가 아니다.",
                "searches": [{"area": area, "query": "fixture query", "fetched": 8, "hitCount": 80, "observedAt": "2026-09-23"}
                             for area in rounds.AREA_NAMES]},
            "items": [{"candidateId": candidate["id"], "area": candidate["categories"][0], "reason": "분야별 비교 관점을 제공한다.",
                "reviewBasis": "abstract", "evaluatedAt": "2026-09-23", "sources": [{"id": "abstract", "kind": "abstract",
                    "label": "Fixture Abstract", "url": "https://example.org/paper"}],
                "checks": [{"id": key, "status": "unknown", "reason": "본문 미확인", "sourceId": None}
                           for key in sorted(evaluation.CHECK_IDS)],
                "ratings": [{"id": key, "level": None, "reason": "본문 미확인", "checkIds": []}
                            for key in sorted(evaluation.CONTENT_IDS)],
                "reproducibilityAdjustment": {"status": "pending", "reason": "핵심 자원 접근성 미확인", "checkIds": ["r3", "r4"]},
                "metrics": {"citations": {"status": "unavailable", "count": None}, "momentum": {"status": "no_baseline"},
                            "journal": {"status": "unavailable", "jif": None}}}
                for candidate in self.candidates]}
        self.write()

    def cleanup(self):
        self.assertTrue(self.directory.resolve().is_relative_to(Path(__file__).parent.resolve()))
        for path in sorted(self.directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        self.directory.rmdir()

    def write(self):
        (self.manifests / "fixture-round.json").write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")

    def load(self, preparations=None, papers=None):
        return rounds.load_rounds(self.candidates, preparations or {}, papers or {}, self.manifests)

    def test_missing_manifest_directory_returns_empty_rounds(self):
        self.assertEqual(rounds.load_rounds([], {}, {}, self.directory / "absent"), [])

    def test_six_originals_remain_in_area_order_and_unknown_is_not_a_total(self):
        self.document["items"].reverse()
        self.write()
        before = copy.deepcopy(self.candidates)
        selected = self.load()[0]["items"]
        self.assertEqual([item["area"] for item in selected], rounds.AREA_NAMES)
        self.assertEqual(self.candidates, before)
        for item in selected:
            self.assertIsNone(item["score"]["total"])
            self.assertIsNone(item["score"]["citation"])
            self.assertEqual(item["score"]["knownMax"], 0)
            self.assertEqual(item["workflow"]["status"], "selected")
            self.assertIsNone(item["paperId"])

    def test_partial_scores_use_existing_calculation_without_fake_full_ranking(self):
        item = self.document["items"][0]
        for rating in item["ratings"]:
            if rating["id"] in ("novelty", "evidence"):
                rating.update(level=2, checkIds=["e1"])
        item["metrics"]["citations"] = {"status": "verified", "count": 4, "normalizedPercentile": 60}
        self.write()
        score = self.load()[0]["items"][0]["score"]
        self.assertEqual(score, evaluation.calculate_score(item["checks"], item["metrics"], item["ratings"], item["reproducibilityAdjustment"]))
        self.assertEqual((score["subtotal"], score["knownMax"]), (32, 50))
        self.assertIsNone(score["total"])

    def test_states_follow_materials_and_registered_papers_without_mutating_source_review(self):
        prepared = {f"fixture-{index}": {"status": status, "generationStatus": "waiting", "reviewStatus": "unreviewed", "stage": "fixture stage"}
                    for index, status in enumerate(("ready", "preparing", "partial", "failed", "ready"))}
        before = copy.deepcopy(prepared)
        selected = self.load(prepared, {"fixture-4": {"id": "fixture-4"}})[0]["items"]
        self.assertEqual([item["workflow"]["status"] for item in selected],
                         ["writing_waiting", "materials_preparing", "materials_partial", "materials_failed", "brief_registered", "selected"])
        self.assertEqual(selected[1]["workflow"]["stage"], "fixture stage")
        self.assertEqual(selected[4]["paperId"], "fixture-4")
        self.assertEqual(prepared, before)

    def test_partial_body_availability_uses_usable_body_coverage_only(self):
        prepared = {"status": "partial", "coverage": [{"kind": "body", "acquired": 1, "usable": 4}],
                    "reviewStatus": "unreviewed", "generationStatus": "needs_sources"}
        result = rounds.workflow(prepared, None)
        self.assertEqual(result["status"], "materials_partial")
        self.assertTrue(result["bodyAvailable"])
        self.assertEqual(result["label"], "본문 확보 · 일부 자료 확인 필요")
        prepared["coverage"][0]["usable"] = 0
        prepared["coverage"].append({"kind": "figures", "usable": 5})
        result = rounds.workflow(prepared, None)
        self.assertFalse(result["bodyAvailable"])
        self.assertIn("본문 미확보", result["label"])
        prepared["status"] = "failed"
        self.assertEqual(rounds.workflow(prepared, None)["label"], "본문 미확보 · 자료 준비 실패")
        self.assertEqual(prepared["reviewStatus"], "unreviewed")

    def test_invalid_count_duplicate_id_and_duplicate_area_are_rejected(self):
        original = copy.deepcopy(self.document)
        for case in ("count", "id", "area"):
            with self.subTest(case=case):
                self.document = copy.deepcopy(original)
                if case == "count":
                    self.document["items"].pop()
                else:
                    key = "candidateId" if case == "id" else "area"
                    self.document["items"][1][key] = self.document["items"][0][key]
                self.write()
                with self.assertRaises(rounds.RoundDataError):
                    self.load()

    def test_reviews_preprints_and_missing_candidates_cannot_be_served_as_six_originals(self):
        for kind in ("Review", "Preprint"):
            with self.subTest(kind=kind):
                self.candidates[0]["publicationTypes"] = [kind]
                with self.assertRaisesRegex(rounds.RoundDataError, "원저 목록"):
                    self.load()
        self.candidates.pop(0)
        with self.assertRaisesRegex(rounds.RoundDataError, "보관 후보에 없습니다"):
            self.load()

    def test_weight_changes_and_source_free_confirmed_checks_are_rejected(self):
        self.document["selection"]["weights"]["content"] = 70
        self.write()
        with self.assertRaisesRegex(rounds.RoundDataError, "배점"):
            self.load()
        self.document["selection"]["weights"] = dict(evaluation.WEIGHTS)
        self.document["items"][0]["checks"][0]["status"] = "met"
        self.write()
        with self.assertRaisesRegex(rounds.RoundDataError, "출처가 필요"):
            self.load()

    def test_category_mismatch_and_out_of_window_publication_are_rejected(self):
        original = copy.deepcopy(self.candidates[0])
        self.candidates[0]["categories"] = [rounds.AREA_NAMES[1]]
        with self.assertRaisesRegex(rounds.RoundDataError, "선정 분야"):
            self.load()
        self.candidates[0] = copy.deepcopy(original)
        for value in ("2026-08-22", "2026-09-24"):
            with self.subTest(date=value):
                self.candidates[0]["date"] = value
                with self.assertRaisesRegex(rounds.RoundDataError, "검색 기간 밖"):
                    self.load()
        for value in ("2026-08-23", "2026-09-23"):
            self.candidates[0]["date"] = value
            self.assertEqual(len(self.load()[0]["items"]), 6)

    def test_explicit_source_doi_must_match_the_candidate_after_normalization(self):
        source = self.document["items"][0]["sources"][0]
        source["doi"] = "https://doi.org/10.1234/FIXTURE-0"
        self.write()
        self.assertEqual(len(self.load()), 1)
        source["doi"] = "10.1234/different-paper"
        self.write()
        with self.assertRaisesRegex(rounds.RoundDataError, "출처의 DOI"):
            self.load()

    def test_failed_search_is_unknown_and_each_area_still_requires_a_success(self):
        failed = {"area": rounds.AREA_NAMES[-1], "query": "failed query", "observedAt": "2026-09-23", "fetched": 0,
                  "hitCount": None, "status": "failed", "reason": "API returned no result count"}
        self.document["selection"]["searches"].append(failed)
        self.write()
        self.assertEqual(len(self.load()), 1)
        self.document["selection"]["searches"].pop(-2)
        self.write()
        with self.assertRaisesRegex(rounds.RoundDataError, "완료된 검색"):
            self.load()

    def test_get_is_read_only_and_invalid_manifest_returns_descriptive_error(self):
        with patch.object(rounds, "DIRECTORY", self.manifests), patch.object(server.Handler, "log_message", lambda *args: None):
            httpd = server.create_server(port=0, db_path=self.directory / "state.sqlite3")
            thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
            thread.start()
            try:
                with server.connect(httpd.db_path) as db:
                    for candidate in self.candidates:
                        db.execute("INSERT INTO collection_candidates VALUES (?, 'fixture', ?)", (candidate["id"], json.dumps(candidate)))
                    db.execute("INSERT INTO paper_state VALUES ('adaptiveflow-2026', 1, 1, '기존 메모', 'fixture')")
                    before = "\n".join(db.iterdump())
                original_papers = copy.deepcopy(httpd.papers)

                def request(method, path):
                    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
                    try:
                        connection.request(method, path)
                        response = connection.getresponse()
                        return response.status, response.read()
                    finally:
                        connection.close()

                with patch.object(httpd.collector, "start", side_effect=AssertionError("Read must not collect")), \
                        patch.object(httpd.preparation, "start", side_effect=AssertionError("Read must not prepare")), \
                        patch.object(httpd.preparation, "get", side_effect=AssertionError("Read must not mutate source validation")):
                    status, body = request("GET", "/api/rounds")
                    self.assertEqual(status, 200)
                    self.assertEqual(len(json.loads(body)["rounds"][0]["items"]), 6)
                    status, body = request("HEAD", "/api/rounds")
                    self.assertEqual((status, body), (200, b""))
                self.document["items"].pop()
                self.write()
                status, body = request("GET", "/api/rounds")
                self.assertEqual(status, 503)
                self.assertIn("여섯 편", json.loads(body)["error"])
                self.assertEqual(request("POST", "/api/rounds")[0], 404)
                with server.connect(httpd.db_path) as db:
                    self.assertEqual("\n".join(db.iterdump()), before)
                self.assertEqual(httpd.papers, original_papers)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=3)
                self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
