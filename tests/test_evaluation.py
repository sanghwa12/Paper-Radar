"""Verify evidence completeness and score arithmetic using disposable snapshots."""
import copy
import json
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation import AREAS, CHECK_IDS, CONTENT_IDS, EvaluationDataError, calculate_score, load_evaluation


def checks(status="unknown"):
    return [{"id": key, "status": status, "reason": "Fixture evidence.", "sourceId": "s1",
             "locator": "Abstract"} for key in sorted(CHECK_IDS)]


def ratings(level=None):
    return [{"id": key, "level": level, "reason": "Strength evidence.", "checkIds": ["e1"]}
            for key in sorted(CONTENT_IDS)]


def adjustment(status="none"):
    return {"status": status, "reason": "Reproduction route review.", "checkIds": ["r3", "r4"]}


@contextmanager
def fixture_directory():
    directory = Path(__file__).parent / ("evaluation-tests-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()


class EvaluationTests(unittest.TestCase):
    def test_unknown_is_not_zero_or_normalized_away(self):
        strengths = ratings()
        strengths[0]["level"] = 2
        strengths[1]["level"] = 1
        strengths[2]["level"] = 0
        score = calculate_score(checks(), {}, strengths, adjustment())
        self.assertEqual((score["content"], score["contentKnownMax"], score["contentUpper"]), (15, 45, 30))
        self.assertEqual((score["knownMax"], score["lower"], score["upper"]), (45, 15, 70))
        self.assertIsNone(score["citation"])
        self.assertIsNone(score["total"])

    def test_verified_zero_is_known_and_all_known_can_total_zero(self):
        metrics = {"citations": {"status": "verified", "normalizedPercentile": 0},
                   "journal": {"status": "verified", "percentile": 0},
                   "momentum": {"status": "verified", "percentile": 0}}
        score = calculate_score(checks("not_met"), metrics, ratings(0), adjustment("applied"))
        self.assertEqual((score["knownMax"], score["total"], score["upper"]), (100, 0, 0))
        strengths = ratings(0)
        strengths[0]["level"] = None
        score = calculate_score(checks(), metrics, strengths, adjustment())
        self.assertEqual((score["knownMax"], score["upper"]), (85, 15))
        self.assertIsNone(score["total"])

    def test_accumulating_citations_and_raw_increase_do_not_earn_points(self):
        metrics = {"citations": {"status": "citation_accumulating", "count": 3, "normalizedPercentile": 95},
                   "journal": {"status": "verified", "percentile": 82.5},
                   "momentum": {"status": "verified", "increase": 4}}
        score = calculate_score(checks("met"), metrics, ratings(3), adjustment())
        self.assertEqual((score["journal"], score["knownMax"], score["lower"], score["upper"]), (8.25, 70, 68.25, 98.25))
        self.assertIsNone(score["citation"])
        self.assertIsNone(score["momentum"])
        self.assertIsNone(score["total"])

    def test_confirmed_percentiles_keep_the_agreed_weights(self):
        metrics = {"citations": {"status": "verified", "normalizedPercentile": 80},
                   "journal": {"status": "verified", "percentile": 75},
                   "momentum": {"status": "verified", "percentile": 60}}
        score = calculate_score(checks("met"), metrics, ratings(3), adjustment())
        self.assertEqual((score["citation"], score["journal"], score["momentum"], score["total"]), (16, 7.5, 6, 89.5))

    def test_percentiles_must_be_finite_numbers_in_zero_to_one_hundred(self):
        for field, key in [("citations", "normalizedPercentile"), ("journal", "percentile"), ("momentum", "percentile")]:
            for invalid in [-1, 100.1, float("nan"), float("inf"), "90", True]:
                with self.subTest(field=field, invalid=invalid), self.assertRaises(EvaluationDataError):
                    calculate_score(checks(), {field: {"status": "verified", key: invalid}}, ratings(), adjustment())

    def test_exact_twenty_distinct_expected_checks_and_statuses_are_required(self):
        missing = checks()[:-1]
        duplicate = checks()
        duplicate[-1] = duplicate[0]
        wrong_id = checks()
        wrong_id[0]["id"] = "other"
        wrong_status = checks()
        wrong_status[0]["status"] = "probably"
        for evidence in [missing, duplicate, wrong_id, wrong_status]:
            with self.subTest(evidence=evidence[0]), self.assertRaises(EvaluationDataError):
                calculate_score(evidence, {}, ratings(), adjustment())

    def test_evidence_cautions_do_not_add_deductions(self):
        full = calculate_score(checks("met"), {}, ratings(2), adjustment())
        cautions = calculate_score(checks("not_met"), {}, ratings(2), adjustment())
        self.assertEqual(full, cautions)
        self.assertEqual((cautions["content"], cautions["penalty"]), (40, 0))

    def test_private_penalty_once_exemption_and_pending(self):
        metrics = {"citations": {"status": "verified", "normalizedPercentile": 50},
                   "journal": {"status": "verified", "percentile": 50},
                   "momentum": {"status": "verified", "percentile": 50}}
        applied = calculate_score(checks("not_met"), metrics, ratings(2), adjustment("applied"))
        self.assertEqual((applied["contentBase"], applied["penalty"], applied["content"], applied["total"]), (40, 3, 37, 57))
        exempt = calculate_score(checks("not_met"), metrics, ratings(2), adjustment("exempt"))
        self.assertEqual((exempt["penalty"], exempt["content"], exempt["total"]), (0, 40, 60))
        pending = calculate_score(checks("not_met"), metrics, ratings(2), adjustment("pending"))
        self.assertEqual((pending["penalty"], pending["content"], pending["subtotal"]), (0, 40, 60))
        self.assertEqual((pending["contentLower"], pending["lower"], pending["upper"]), (37, 57, 60))
        self.assertTrue(pending["penaltyPending"])
        self.assertIsNone(pending["total"])

    def test_four_grades_and_evidence_references_are_validated(self):
        cases = []
        for invalid in [-1, 4, 1.5, True, "2"]:
            malformed = ratings()
            malformed[0]["level"] = invalid
            cases.append(malformed)
        duplicate = ratings()
        duplicate[-1] = duplicate[0]
        cases.extend([duplicate, ratings()[:-1]])
        invalid_reference = ratings(1)
        invalid_reference[0]["checkIds"] = ["missing"]
        cases.append(invalid_reference)
        no_reference = ratings(1)
        no_reference[0]["checkIds"] = []
        cases.append(no_reference)
        for malformed in cases:
            with self.subTest(ratings=malformed), self.assertRaises(EvaluationDataError):
                calculate_score(checks(), {}, malformed, adjustment())
        with self.assertRaises(EvaluationDataError):
            calculate_score(checks(), {}, ratings(), adjustment("probably"))

    def make_snapshot(self, directory):
        selected, reviews, assessments = [], [], []
        for area in AREAS:
            for number in range(2):
                identity = f"paper-{len(selected)}"
                selected.append({"id": identity, "title": f"Fixture original {number}", "journal": "Test JOURNAL"})
                reviews.append({"candidateId": identity, "area": area["name"], "checks": checks(),
                                "sources": [{"id": "s1", "url": "https://example.org/source"}]})
                assessments.append({"candidateId": identity, "ratings": ratings(), "reproducibilityAdjustment": adjustment()})
        snapshot = {"selected.json": selected, "reviews-a.json": reviews[:6], "reviews-b.json": reviews[6:],
                    "ratings-a.json": assessments[:6], "ratings-b.json": assessments[6:],
                    "citation-metrics.json": {}, "journal-metrics.json": [
                        {"journal": "test journal", "status": "verified", "percentile": 90, "jif": 2.5, "year": 2025}]}
        for filename, data in snapshot.items():
            (directory / filename).write_text(json.dumps(data), encoding="utf-8")
        return snapshot

    def test_snapshot_loads_twelve_unique_papers_two_per_area_and_exact_journal_match(self):
        with fixture_directory() as directory:
            snapshot = self.make_snapshot(directory)
            result = load_evaluation(directory)
            self.assertEqual(len(result["papers"]), 12)
            self.assertEqual(result["policyVersion"], "v2")
            self.assertEqual(len(result["contentRubric"]), 4)
            self.assertEqual(len({paper["id"] for paper in result["papers"]}), 12)
            self.assertTrue(all(paper["score"]["journal"] == 9 for paper in result["papers"]))
            self.assertEqual(result["papers"][0]["metrics"]["journal"]["year"], 2025)
            snapshot["selected.json"][0]["journal"] = "Test Journal Letters"
            (directory / "selected.json").write_text(json.dumps(snapshot["selected.json"]), encoding="utf-8")
            self.assertIsNone(load_evaluation(directory)["papers"][0]["score"]["journal"])

    def test_missing_and_inconsistent_snapshots_fail_with_controlled_error(self):
        with fixture_directory() as directory:
            with self.assertRaises(EvaluationDataError):
                load_evaluation(directory)
            snapshot = self.make_snapshot(directory)
            invalid_cases = []
            duplicate = copy.deepcopy(snapshot)
            duplicate["selected.json"][-1] = duplicate["selected.json"][0]
            invalid_cases.append(duplicate)
            imbalance = copy.deepcopy(snapshot)
            imbalance["reviews-a.json"][0]["area"] = AREAS[-1]["name"]
            invalid_cases.append(imbalance)
            invalid_source = copy.deepcopy(snapshot)
            invalid_source["reviews-a.json"][0]["checks"][0].update(status="met", sourceId="missing")
            invalid_cases.append(invalid_source)
            invalid_assessment = copy.deepcopy(snapshot)
            invalid_assessment["ratings-a.json"][0]["candidateId"] = "missing"
            invalid_cases.append(invalid_assessment)
            for invalid in invalid_cases:
                for filename, data in invalid.items():
                    (directory / filename).write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(EvaluationDataError):
                    load_evaluation(directory)


if __name__ == "__main__":
    unittest.main()
