"""Check pilot provenance without changing real briefs, inputs, or review records."""
import copy
import hashlib
import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generation


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).parent / ("paper-radar-generation-tests-" + uuid.uuid4().hex)
        self.assertTrue(self.directory.resolve().is_relative_to(Path(__file__).parent.resolve()))
        self.directory.mkdir()
        self.addCleanup(self.cleanup_directory)
        for group in ("runs", "inputs", "drafts", "baselines", "reviews", "public/assets"):
            (self.directory / group).mkdir(parents=True)
        root_patch = patch.object(generation, "ROOT", self.directory)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        self.asset_path = self.directory / "public/assets/figure-a.svg"
        self.asset_path.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        self.package = {"schemaVersion": 1, "candidateId": "fixture-paper",
                        "metadata": {"title": "Prediction error comparison"}, "sources": []}
        for source_id, kind, value in (
                ("abstract-1", "abstract", "The study compares three prediction methods."),
                ("body-1", "body", "The model was evaluated on 120 held-out observations."),
                ("figure-1", "figure", "Figure 1. Comparison of prediction errors.")):
            self.package["sources"].append({
                "id": source_id, "kind": kind, "label": source_id, "text": value,
                "url": "https://example.org/paper#" + source_id,
                "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()})
        self.package["sources"][2].update(asset="/assets/figure-a.svg",
                                           assetSha256=generation.digest(self.asset_path))
        pair = {"label": "비교", "method": "검증 집합에서 예측 오차를 비교했다.",
                "result": "120개 관측값을 평가했다.", "sourceIds": ["body-1"],
                "source": {"label": "결과", "url": "https://example.org/paper#body-1"}}
        self.draft = {
            "candidateId": "fixture-paper",
            "card": {"titleKo": "예측 오차 비교", "purpose": "예측 방법을 비교한다.",
                     "significance": "외부 검증의 중요성을 보여준다.", "application": "비교 기준을 검토한다.",
                     "limits": "다른 집합으로 일반화할 수 있는지는 미확인이다.", "flow": ["비교", "평가"],
                     "sourceIds": ["abstract-1", "body-1"], "pairs": [copy.deepcopy(pair), copy.deepcopy(pair)]},
            "abstract": {"paragraphs": ["세 가지 예측 방법을 비교한 연구다."],
                         "source": {"url": "https://example.org/paper#abstract-1"}},
            "tabs": {tab: [{"title": tab, "blocks": [{"type": "paragraph", "text": "평가 범위를 확인한다.",
                                                        "sourceIds": ["body-1"]}]}]
                     for tab in generation.TABS},
            "claims": [{"id": "claim-1", "text": "120개 관측값에서 평가했다.", "kind": "data",
                        "support": [{"sourceId": "body-1", "quote": "evaluated on 120 held-out observations"}]}],
            "readSourceIds": ["abstract-1", "body-1", "figure-1"], "viewedFigureIds": ["figure-1"],
            "limitations": ["보충자료는 검토하지 않았다."]}
        self.draft["tabs"]["evidence"][0]["blocks"].append({
            "type": "figure", "title": "Figure 1", "image": "/assets/figure-a.svg",
            "caption": "Figure 1. Comparison of prediction errors.",
            "sourceIds": ["figure-1"], "source": {"label": "Figure 1", "url": "https://example.org/paper#figure-1"},
            "explanation": [{"label": "비교", "text": "방법별 예측 오차를 표시한다."}]})
        self.baseline = {"candidateId": "fixture-paper",
                         **copy.deepcopy({key: self.draft[key] for key in ("card", "abstract", "tabs")})}
        self.run = {"schemaVersion": 1, "runId": "fixture-run", "candidateId": "fixture-paper",
                    "generatedAt": "2026-09-23T00:00:00Z",
                    "generation": {"mode": "codex-assisted-pilot", "label": "Codex 세션"},
                    "inputFile": "fixture.json", "draftFile": "fixture.json", "baselineFile": "fixture.json"}
        self.write_json("inputs", "fixture.json", self.package)
        self.write_json("drafts", "fixture.json", self.draft)
        self.write_json("baselines", "fixture.json", self.baseline)
        self.bind_run()

    def cleanup_directory(self):
        for path in sorted(self.directory.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        self.directory.rmdir()

    def write_json(self, group, name, value):
        (self.directory / group / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def bind_run(self):
        self.run.update(inputSha256=generation.digest(self.directory / "inputs/fixture.json"),
                        baselineSha256=generation.digest(self.directory / "baselines/fixture.json"))
        self.write_json("runs", "fixture-run.json", self.run)

    def write_review(self, status="partial", **changes):
        review = {"inputSha256": generation.digest(self.directory / "inputs/fixture.json"),
                  "draftSha256": generation.digest(self.directory / "drafts/fixture.json"),
                  "status": status, "summary": "일부 근거를 확인했다.",
                  "checks": [{"label": "표본 수", "status": "pass", "note": "원문과 수치를 대조했다."}],
                  "differences": ["비교 기준을 명확히 했다."], "unresolved": ["보충자료 미확인"],
                  "checked": {"abstract": "reviewed", "body": "partial", "figure": "partial"}}
        review.update(changes)
        self.write_json("reviews", "fixture-run.json", review)

    def load(self):
        return generation.load_runs(directory=self.directory)

    def write_second_run(self):
        package = copy.deepcopy(self.package)
        package["candidateId"] = "second-paper"
        package["metadata"]["title"] = "Independent validation comparison"
        body = package["sources"][1]
        body["text"] = "The second model was evaluated on 48 held-out observations."
        body["sha256"] = hashlib.sha256(body["text"].encode("utf-8")).hexdigest()
        draft = copy.deepcopy(self.draft)
        draft["candidateId"] = "second-paper"
        draft["card"]["titleKo"] = "두 번째 시범본"
        for pair in draft["card"]["pairs"]:
            pair["result"] = "48개 관측값을 평가했다."
        draft["claims"][0].update(text="48개 관측값에서 평가했다.", support=[{
            "sourceId": "body-1", "quote": "evaluated on 48 held-out observations"}])
        baseline = copy.deepcopy(self.baseline)
        baseline["candidateId"] = "second-paper"
        baseline["card"]["titleKo"] = "두 번째 기존본"
        for group, value in (("inputs", package), ("drafts", draft), ("baselines", baseline)):
            self.write_json(group, "second.json", value)
        run = {**self.run, "runId": "second-run", "candidateId": "second-paper",
               "inputFile": "second.json", "draftFile": "second.json", "baselineFile": "second.json",
               "inputSha256": generation.digest(self.directory / "inputs/second.json"),
               "baselineSha256": generation.digest(self.directory / "baselines/second.json")}
        self.write_json("runs", "second-run.json", run)
        self.write_json("reviews", "second-run.json", {
            "inputSha256": run["inputSha256"],
            "draftSha256": generation.digest(self.directory / "drafts/second.json"),
            "status": "held", "summary": "두 번째 논문만 추가 검토가 필요하다.",
            "checks": [{"label": "두 번째 검토", "status": "unverified", "note": "추가 확인 필요"}],
            "differences": ["두 번째 비교"], "unresolved": ["두 번째 미확인 사항"],
            "checked": {"abstract": "reviewed", "body": "unverified", "figure": "unverified"}})

    def test_two_runs_keep_each_papers_sources_content_and_review_separate(self):
        self.write_review()
        self.write_second_run()
        runs = {run["runId"]: run for run in self.load()}
        self.assertEqual(set(runs), {"fixture-run", "second-run"})
        first, second = runs["fixture-run"], runs["second-run"]
        self.assertEqual(first["candidateId"], "fixture-paper")
        self.assertEqual(first["baseline"]["card"], self.baseline["card"])
        self.assertEqual(first["draft"]["card"]["pairs"][0]["result"], "120개 관측값을 평가했다.")
        self.assertEqual(first["validation"]["status"], "partial")
        self.assertEqual(first["sourceScope"][1]["checked"], "partial")
        self.assertEqual(second["candidateId"], "second-paper")
        self.assertEqual(second["title"], "Independent validation comparison")
        self.assertEqual(second["baseline"]["card"]["titleKo"], "두 번째 기존본")
        self.assertEqual(second["draft"]["card"]["titleKo"], "두 번째 시범본")
        self.assertEqual(second["draft"]["card"]["pairs"][0]["result"], "48개 관측값을 평가했다.")
        self.assertEqual(second["validation"]["status"], "held")
        self.assertEqual(second["validation"]["differences"], ["두 번째 비교"])
        self.assertEqual(second["sourceScope"][1]["checked"], "unverified")

    def test_review_from_another_run_cannot_certify_the_second_paper(self):
        self.write_review()
        self.write_second_run()
        wrong_review = generation.read_json(self.directory / "reviews/fixture-run.json")
        self.write_json("reviews", "second-run.json", wrong_review)
        runs = {run["runId"]: run for run in self.load()}
        self.assertEqual(runs["fixture-run"]["validation"]["status"], "partial")
        second = runs["second-run"]
        self.assertEqual(second["validation"]["status"], "unverified")
        self.assertEqual(second["validation"]["differences"], [])
        self.assertEqual(len(second["validation"]["checks"]), 1)
        self.assertEqual(second["sourceScope"][0]["checked"], "unverified")

    def test_missing_review_remains_unverified_and_does_not_rewrite_artifacts(self):
        before = {str(path.relative_to(self.directory)): generation.digest(path)
                  for path in self.directory.rglob("*") if path.is_file()}
        runs = self.load()
        self.assertEqual(len(runs), 1)
        result = runs[0]
        self.assertEqual(result["validation"]["status"], "unverified")
        self.assertEqual(len(result["validation"]["checks"]), 1)
        self.assertIn("과학적 정확성 검증과는 별도", result["validation"]["checks"][0]["note"])
        self.assertEqual([item["checked"] for item in result["sourceScope"]],
                         ["unverified", "unverified", "unverified", "unavailable"])
        self.assertIn("근거:", result["draft"]["tabs"]["summary"][0]["blocks"][-1]["blocks"][0]["text"])
        self.assertEqual(result["baseline"]["card"], self.baseline["card"])
        self.assertEqual(before, {str(path.relative_to(self.directory)): generation.digest(path)
                                 for path in self.directory.rglob("*") if path.is_file()})

    def test_unknown_source_id_is_rejected(self):
        self.draft["card"]["pairs"][0]["sourceIds"] = ["missing"]
        self.write_json("drafts", "fixture.json", self.draft)
        with self.assertRaisesRegex(generation.PilotError, "출처 ID"):
            self.load()

    def test_generated_paraphrase_cannot_be_labeled_original_caption(self):
        self.draft["tabs"]["evidence"][0]["blocks"][1]["caption"] = "작성한 한국어 해설"
        self.write_json("drafts", "fixture.json", self.draft)
        with self.assertRaisesRegex(generation.PilotError, "원문 caption"):
            self.load()

    def test_string_instead_of_list_is_rejected_before_rendering(self):
        self.draft["card"]["flow"] = "A string would crash the browser map operation."
        self.write_json("drafts", "fixture.json", self.draft)
        with self.assertRaises(generation.PilotError):
            self.load()
        self.draft["card"]["flow"] = ["비교", "평가"]
        self.draft["tabs"]["summary"][0]["blocks"][0] = {
            "type": "list", "items": "Not an array", "sourceIds": ["body-1"]}
        self.write_json("drafts", "fixture.json", self.draft)
        with self.assertRaises(generation.PilotError):
            self.load()

    def test_changed_input_file_is_rejected(self):
        self.package["metadata"]["title"] = "Changed input"
        self.write_json("inputs", "fixture.json", self.package)
        with self.assertRaisesRegex(generation.PilotError, "입력 또는 비교 기준"):
            self.load()

    def test_changed_source_text_hash_is_rejected(self):
        self.package["sources"][1]["text"] = "A changed observation count."
        self.write_json("inputs", "fixture.json", self.package)
        self.bind_run()
        with self.assertRaisesRegex(generation.PilotError, "입력 원문 구간의 해시"):
            self.load()

    def test_changed_original_asset_is_rejected(self):
        self.asset_path.write_text("changed image", encoding="utf-8")
        with self.assertRaisesRegex(generation.PilotError, "원본 자료의 해시"):
            self.load()

    def test_claim_quote_not_in_original_is_rejected(self):
        self.draft["claims"][0]["support"][0]["quote"] = "evaluated on 130 held-out observations"
        self.write_json("drafts", "fixture.json", self.draft)
        with self.assertRaisesRegex(generation.PilotError, "원문에 없는 근거"):
            self.load()

    def test_mismatched_draft_paper_is_rejected(self):
        self.draft["candidateId"] = "another-paper"
        self.write_json("drafts", "fixture.json", self.draft)
        with self.assertRaisesRegex(generation.PilotError, "논문 ID"):
            self.load()

    def test_unknown_block_type_is_rejected(self):
        self.draft["tabs"]["methods"][0]["blocks"][0]["type"] = "unknown"
        self.write_json("drafts", "fixture.json", self.draft)
        with self.assertRaisesRegex(generation.PilotError, "알 수 없는 본문 블록"):
            self.load()

    def test_figure_asset_and_source_id_must_match(self):
        figure = self.draft["tabs"]["evidence"][0]["blocks"][1]
        for change in ({"sourceIds": ["body-1"]}, {"image": "/assets/another.svg"}):
            with self.subTest(change=change):
                changed = copy.deepcopy(self.draft)
                changed["tabs"]["evidence"][0]["blocks"][1] = {**figure, **change}
                self.write_json("drafts", "fixture.json", changed)
                with self.assertRaisesRegex(generation.PilotError, "그림 경로와 출처 ID"):
                    self.load()

    def test_matching_partial_review_is_used(self):
        self.write_review()
        result = self.load()[0]
        self.assertEqual(result["validation"]["status"], "partial")
        self.assertEqual(len(result["validation"]["checks"]), 2)
        self.assertEqual(result["sourceScope"][1]["checked"], "partial")

    def test_changed_draft_does_not_inherit_old_review(self):
        self.write_review()
        self.draft["card"]["purpose"] = "새 비교 설명이다."
        self.write_json("drafts", "fixture.json", self.draft)
        result = self.load()[0]
        self.assertEqual(result["validation"]["status"], "unverified")
        self.assertEqual(len(result["validation"]["checks"]), 1)
        self.assertEqual(result["validation"]["differences"], [])
        self.assertEqual(result["sourceScope"][1]["checked"], "unverified")

    def test_completed_review_status_is_rejected(self):
        self.write_review(status="reviewed")
        with self.assertRaisesRegex(generation.PilotError, "검토 완료로 승격"):
            self.load()

    def test_unavailable_supplement_cannot_be_marked_reviewed(self):
        self.write_review(checked={"supplement": "reviewed"})
        with self.assertRaisesRegex(generation.PilotError, "없는 자료를 검토"):
            self.load()


if __name__ == "__main__":
    unittest.main()
