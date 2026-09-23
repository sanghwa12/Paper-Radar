"""Review search is bounded metadata reading, not collection or completed review."""
import copy
import io
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import review_radar as radar


TODAY = "2026-09-23"
STAMP = "2026-09-23T01:00:00+00:00"
PAYLOAD = {"area": "CADD·AI", "keywords": "", "sort": "relevance"}


def record(identifier="123", **changes):
    return {"source": "MED", "id": identifier, "doi": "10.1234/review." + identifier,
            "title": "Methods in drug discovery", "firstPublicationDate": "2026-04-02",
            "pubTypeList": {"pubType": ["Review"]}, "abstractText": "A literature discussion.",
            "authorString": "A. Example", "journalTitle": "Example Journal", **changes}


def page(records, count=None):
    return {"version": "6.9", "hitCount": len(records) if count is None else count,
            "nextCursorMark": "next-page-not-to-be-fetched", "resultList": {"result": records}}


def curated():
    return {"id": "review-example", "title": "An example review", "titleKo": "리뷰 예시",
            "doi": "10.1234/review", "pmid": "123", "pmcid": "", "date": "2025-01-01",
            "journal": "Example Journal", "authors": "A. Example", "areas": ["CADD·AI"],
            "sourceUrl": "https://doi.org/10.1234/review", "selectionReason": "방법의 흐름을 살펴봅니다.",
            "summary": {"scope": "검토한 부분의 요약", "takeaways": ["예시 요점"],
                        "limitations": ["원저는 직접 검토하지 않았습니다."]},
            "readingScope": {"abstract": "checked", "fullText": "partial", "figures": "unverified",
                             "supplements": "unverified", "originalPapers": "metadata_only", "note": "부분 검토"},
            "originals": [{"title": "An original reference", "doi": "10.1234/original", "year": 2024,
                           "sourceUrl": "https://doi.org/10.1234/original", "role": "배경 원저",
                           "referenceLabel": "1", "referenceLocation": "References 1",
                           "verification": "citation_metadata", "note": "인용정보만 확인"}],
            "citations": {"count": 3, "observedAt": STAMP, "sourceUrl": "https://europepmc.org/article/MED/123"},
            "journalMetric": {"jif": None, "year": None, "status": "unverified"},
            "provenance": [{"label": "초록", "url": "https://europepmc.org/article/MED/123",
                            "checkedAt": STAMP, "scope": "abstract"}], "summaryStatus": "partial_review"}


def deep_review():
    item = curated()
    item["briefing"] = {
        "version": 1, "updatedAt": STAMP,
        "sources": [{"id": "review-text", "label": "리뷰 본문", "url": "https://example.org/review",
                     "location": "Section 2", "scope": "리뷰 본문의 방법 비교 부분 검토"},
                    {"id": "review-figure-1", "label": "Figure 1", "url": "https://example.org/review#figure-1",
                     "location": "Figure 1", "scope": "리뷰 Figure 1 원본 이미지와 캡션 시각 확인",
                     "kind": "review_figure"}],
        "sections": [{"id": identity, "title": title, "lead": "확인 범위에 따른 설명",
                      "blocks": [{"heading": "검토 내용", "kind": "review_claim", "paragraphs": ["리뷰의 설명"],
                                  "sourceIds": ["review-text"]}]}
                     for identity, title in (("overview", "요약"), ("methods", "방법 비교"),
                                             ("evidence", "근거와 원저"), ("limits", "그림·한계"),
                                             ("application", "연구 적용"))]}
    item["briefing"]["sections"][1]["table"] = {
        "caption": "검토한 비교", "columns": ["항목", "확인 범위"],
        "rows": [{"cells": ["예시", "리뷰 본문"], "sourceIds": ["review-text"]}]}
    item["briefing"]["sections"][0]["flow"] = [{"title": "질문", "text": "분석자가 재구성한 학습 흐름"}]
    item["briefing"]["sections"][3]["blocks"][0]["sourceIds"] = ["review-figure-1"]
    item["briefing"]["sections"][4]["blocks"][0].update(kind="interpretation", sourceIds=[])
    return item


class ReviewSearchTests(unittest.TestCase):
    def search(self, records, payload=None, count=None):
        with patch.object(radar, "_fetch_page", return_value=page(records, count)) as fetch:
            result = radar.search_reviews(payload or PAYLOAD, today=TODAY)
        self.assertEqual(fetch.call_count, 1)
        return result

    def test_calendar_window_is_leap_safe_and_query_restricts_sources(self):
        with patch.object(radar, "_fetch_page", return_value=page([])):
            result = radar.search_reviews(PAYLOAD, today="2024-02-29")
        self.assertEqual((result["from"], result["to"]), ("2021-02-28", "2024-02-29"))
        self.assertIn("PUB_TYPE:review AND (SRC:MED OR SRC:PMC)", result["query"])
        self.assertNotIn("SRC:PPR", result["query"])

    def test_payload_validation_happens_before_any_network(self):
        invalid = [None, {}, {**PAYLOAD, "extra": True}, {**PAYLOAD, "area": "all"},
                   {**PAYLOAD, "keywords": "a" * 121}, {**PAYLOAD, "keywords": "line\nbreak"},
                   {**PAYLOAD, "keywords": []}, {**PAYLOAD, "sort": "score"}]
        with patch.object(radar, "_fetch_page") as fetch:
            for payload in invalid:
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    radar.search_reviews(payload, today=TODAY)
        fetch.assert_not_called()

    def test_user_operators_are_inside_escaped_literal(self):
        literal = 'x" OR SRC:PPR OR TITLE_ABS:"y\\z'
        result = self.search([], {**PAYLOAD, "keywords": literal})
        self.assertTrue(result["query"].endswith(' AND TITLE_ABS:"x\\" OR SRC:PPR OR TITLE_ABS:\\"y\\\\z"'))
        self.assertEqual(parse_qs(urlsplit(result["sourceUrl"]).query)["query"], [result["query"]])

    def test_newest_sort_is_one_core_page_even_if_more_results_exist(self):
        rows = [record(str(n)) for n in range(30)]
        result = self.search(rows, {**PAYLOAD, "sort": "newest"}, count=200)
        params = parse_qs(urlsplit(result["sourceUrl"]).query)
        self.assertNotIn("sort", params)
        self.assertTrue(params["query"][0].endswith(" sort_date:y"))
        self.assertEqual(params["pageSize"], ["30"])
        self.assertEqual(params["resultType"], ["core"])
        self.assertEqual(params["cursorMark"], ["*"])
        self.assertEqual((result["fetched"], result["shown"], result["truncated"]), (30, 30, True))

    def test_missing_or_invalid_result_contract_is_error_not_empty_success(self):
        malformed = [{"version": "6.9"}, {"hitCount": 0}, {"hitCount": "0", "resultList": {"result": []}},
                     {"hitCount": True, "resultList": {"result": []}}, page([], count=1),
                     page([record()], count=0), page([record(str(i)) for i in range(31)])]
        for response in malformed:
            with self.subTest(response=response), patch.object(radar, "_fetch_page", return_value=response):
                with self.assertRaises(radar.ReviewRadarError):
                    radar.search_reviews(PAYLOAD, today=TODAY)
        result = self.search([])
        self.assertEqual((result["hitCount"], result["fetched"], result["shown"]), (0, 0, 0))

    def test_confirmed_specialized_types_are_excluded_but_incidental_mentions_are_not(self):
        rows = [record("1", pubTypeList={"pubType": ["Review", "Meta-Analysis"]}),
                record("2", title="Docking: a systematic review and meta-analysis"),
                record("3", abstractText="We conducted a network meta-analysis of published evidence."),
                record("4", title="Research methods: a guide to systematic review"),
                record("5", abstractText="Previous meta-analysis motivated this review of methods."),
                record("6", title="A narrative review of modeling methods")]
        result = self.search(rows)
        self.assertEqual(result["excludedCounts"], {"systematicOrMetaAnalysis": 3})
        self.assertEqual([p["sourceId"] for p in result["candidates"]], ["4", "5", "6"])
        self.assertEqual(result["candidates"][0]["reviewSubtype"], "unspecified")
        self.assertEqual(result["candidates"][-1]["reviewSubtype"], "narrative")

    def test_invalid_metadata_other_types_and_window_are_not_eligible(self):
        rows = [record("1", source="PPR"), record("2", title=""),
                record("3", firstPublicationDate="2020-01-01"),
                record("4", firstPublicationDate="2026-09-24"),
                record("5", pubTypeList={"pubType": ["Original Article"]}),
                record("6", pubTypeList={"pubType": ["Review", "Preprint"]}),
                record("7", firstPublicationDate="2026-02-31")]
        result = self.search(rows)
        self.assertEqual(result["shown"], 0)
        self.assertEqual(result["excludedCounts"], {"invalidMetadata": 3, "outsideWindow": 2, "notReview": 2})
        self.assertFalse(result["truncated"])

    def test_dedup_uses_doi_and_source_aliases_and_ids_are_stable(self):
        rows = [record("1"), record("PMC123", source="PMC", doi="https://doi.org/10.1234/REVIEW.1"),
                record("1", doi=""), record("2", doi="")]
        result = self.search(rows)
        self.assertEqual(result["excludedCounts"], {"duplicate": 2})
        self.assertEqual(result["shown"], 2)
        again = self.search([record("2", doi=""), record("1")])
        self.assertEqual([p["id"] for p in result["candidates"]], [p["id"] for p in reversed(again["candidates"])])
        self.assertTrue(all(p["id"].startswith("review-") for p in result["candidates"]))

    def test_metadata_results_do_not_claim_selection_or_fulltext_review(self):
        paper = self.search([record()])["candidates"][0]
        self.assertEqual(paper["selectionStatus"], "unreviewed")
        self.assertEqual(paper["fullTextStatus"], "not_retrieved")
        self.assertEqual(paper["classification"]["label"], "Review · 세부 유형 미확인")
        self.assertIsNone(paper["citedByCount"])
        self.assertNotIn("score", paper)

    def test_search_does_not_open_database_or_start_collector(self):
        with patch("collector.sqlite3.connect", side_effect=AssertionError("DB write forbidden")), \
                patch("collector.Collector.start", side_effect=AssertionError("collection forbidden")):
            self.search([record()])


class CuratedReviewTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).resolve().parent / (".review-radar-" + uuid.uuid4().hex)
        self.directory.mkdir()

    def tearDown(self):
        self.assertEqual(self.directory.parent, Path(__file__).resolve().parent)
        shutil.rmtree(self.directory)

    def write(self, value, name="review.json"):
        (self.directory / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_empty_directory_has_policy_and_does_not_create_data(self):
        result = radar.load_radar(today=TODAY, directory=self.directory)
        self.assertEqual(result["reviews"], [])
        self.assertEqual(result["policy"]["windowYears"], 3)
        self.assertEqual(result["policy"]["oldWorkStatus"], "paused")
        self.assertEqual(result["policy"]["scoringStatus"], "not_defined")
        self.assertEqual(len(result["policy"]["areas"]), 6)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_valid_saved_review_remains_after_rolling_search_window(self):
        item = curated()
        item["date"] = "2020-01-01"
        self.write(item)
        before = (self.directory / "review.json").read_bytes()
        result = radar.load_radar(today=TODAY, directory=self.directory)
        self.assertEqual(result["reviews"], [item])
        self.assertEqual((self.directory / "review.json").read_bytes(), before)
        self.assertEqual(result["policy"]["from"], "2023-09-23")

    def test_duplicate_ids_or_normalized_dois_are_rejected(self):
        first = curated()
        self.write(first)
        for second in ({**first, "doi": "10.1234/other", "sourceUrl": "https://doi.org/10.1234/other"},
                       {**first, "id": "another", "doi": "https://doi.org/10.1234/REVIEW"}):
            with self.subTest(second=second):
                self.write(second, "other.json")
                with self.assertRaises(radar.ReviewRadarError):
                    radar.load_radar(today=TODAY, directory=self.directory)

    def test_incomplete_or_unsafe_curated_contract_is_not_served(self):
        changes = [{"date": "2026-09-24"}, {"areas": ["other"]}, {"titleKo": ""},
                   {"sourceUrl": "https://127.0.0.1/private"},
                   {"sourceUrl": "https://doi.org/10.1234/wrong"},
                   {"summary": {"scope": "brief", "takeaways": [], "limitations": ["unknown"]}},
                   {"journalMetric": {"jif": 9, "year": 2025, "status": "unverified"}}]
        for change in changes:
            with self.subTest(change=change):
                self.write({**curated(), **change})
                with self.assertRaises(radar.ReviewRadarError):
                    radar.load_radar(today=TODAY, directory=self.directory)

    def test_original_citation_metadata_never_claims_paper_was_read(self):
        for key, value in (("verification", "fulltext_checked"), ("sourceUrl", "https://doi.org/10.1234/wrong")):
            item = curated()
            item["originals"][0][key] = value
            self.write(item)
            with self.assertRaises(radar.ReviewRadarError):
                radar.load_radar(today=TODAY, directory=self.directory)

    def test_checked_figures_require_briefing_and_supplements_stay_unverified(self):
        for key in ("figures", "supplements"):
            item = curated()
            item["readingScope"][key] = "checked"
            self.write(item)
            with self.assertRaises(radar.ReviewRadarError):
                radar.load_radar(today=TODAY, directory=self.directory)

    def test_optional_briefing_preserves_source_scope_and_all_five_sections(self):
        item = deep_review()
        self.write(item)
        before = (self.directory / "review.json").read_bytes()
        loaded = radar.load_radar(today=TODAY, directory=self.directory)["reviews"][0]
        self.assertEqual(loaded, item)
        self.assertEqual((self.directory / "review.json").read_bytes(), before)
        self.assertEqual(loaded["readingScope"]["originalPapers"], "metadata_only")
        self.assertEqual(loaded["summaryStatus"], "partial_review")

    def test_briefing_version_date_and_section_identity_are_checked(self):
        item = deep_review()
        cases = []
        for version in (True, 2, "1"):
            modified = copy.deepcopy(item)
            modified["briefing"]["version"] = version
            cases.append(modified)
        for timestamp in ("2026-09-23", "2026-09-23T12:00:00", "not-a-date"):
            modified = copy.deepcopy(item)
            modified["briefing"]["updatedAt"] = timestamp
            cases.append(modified)
        missing = copy.deepcopy(item)
        missing["briefing"]["sections"].pop()
        cases.append(missing)
        duplicate = copy.deepcopy(item)
        duplicate["briefing"]["sections"][1] = duplicate["briefing"]["sections"][0]
        cases.append(duplicate)
        for modified in cases:
            with self.subTest(briefing=modified["briefing"]):
                self.write(modified)
                with self.assertRaises(radar.ReviewRadarError):
                    radar.load_radar(today=TODAY, directory=self.directory)

    def test_briefing_sources_are_unique_safe_and_have_actual_scope(self):
        for key, value in (("id", "review-figure-1"), ("id", "INVALID ID"), ("url", "javascript:alert(1)"),
                           ("url", "http://example.org/review"), ("scope", ""), ("location", "")):
            with self.subTest(key=key, value=value):
                item = deep_review()
                item["briefing"]["sources"][0][key] = value
                self.write(item)
                with self.assertRaises(radar.ReviewRadarError):
                    radar.load_radar(today=TODAY, directory=self.directory)

    def test_claims_and_table_rows_must_reference_existing_sources(self):
        for references in ([], ["missing-source"], ["review-text", "review-text"]):
            for target in ("block", "row"):
                with self.subTest(references=references, target=target):
                    item = deep_review()
                    methods = item["briefing"]["sections"][1]
                    entity = methods["blocks"][0] if target == "block" else methods["table"]["rows"][0]
                    entity["sourceIds"] = references
                    self.write(item)
                    with self.assertRaises(radar.ReviewRadarError):
                        radar.load_radar(today=TODAY, directory=self.directory)

    def test_table_cells_and_flow_structure_are_checked(self):
        for field in ("cells", "flow"):
            item = deep_review()
            if field == "cells":
                item["briefing"]["sections"][1]["table"]["rows"][0]["cells"].pop()
            else:
                item["briefing"]["sections"][0]["flow"] = [{"title": "설명"}]
            self.write(item)
            with self.subTest(field=field), self.assertRaises(radar.ReviewRadarError):
                radar.load_radar(today=TODAY, directory=self.directory)

    def test_optional_figure_is_local_svg_with_valid_sources_without_status_promotion(self):
        item = deep_review()
        item["briefing"]["sections"][3]["figure"] = {
            "src": "/assets/review-radar/example/concept.svg", "alt": "학습용 도식",
            "caption": "분석자가 독립적으로 재구성한 학습용 도식", "sourceIds": ["review-text"]}
        self.write(item)
        loaded = radar.load_radar(today=TODAY, directory=self.directory)["reviews"][0]
        self.assertEqual(loaded["readingScope"]["figures"], "unverified")
        self.assertEqual(loaded["briefing"]["sections"][3]["figure"], item["briefing"]["sections"][3]["figure"])
        unsafe = ["https://example.org/concept.svg", "/assets/elsewhere/concept.svg",
                  "/assets/review-radar/../concept.svg", "/assets/review-radar/%2e%2e/concept.svg",
                  "/assets/review-radar/concept%2esvg", "/assets/review-radar/example\\concept.svg",
                  "/assets/review-radar/concept.svg?file=other", "/assets/review-radar/concept.png"]
        for source in unsafe:
            modified = copy.deepcopy(item)
            modified["briefing"]["sections"][3]["figure"]["src"] = source
            self.write(modified)
            with self.subTest(source=source), self.assertRaises(radar.ReviewRadarError):
                radar.load_radar(today=TODAY, directory=self.directory)
        for references in ([], ["missing-source"]):
            modified = copy.deepcopy(item)
            modified["briefing"]["sections"][3]["figure"]["sourceIds"] = references
            self.write(modified)
            with self.subTest(references=references), self.assertRaises(radar.ReviewRadarError):
                radar.load_radar(today=TODAY, directory=self.directory)

    def test_figure_checked_requires_scoped_figure_reference_and_matching_note(self):
        item = deep_review()
        item["readingScope"].update(figures="checked", note="Figure 1 원본 이미지·캡션을 확인했습니다. 원저 본문은 미검토입니다.")
        self.write(item)
        self.assertEqual(radar.load_radar(today=TODAY, directory=self.directory)["reviews"][0], item)
        cases = []
        no_kind = copy.deepcopy(item)
        no_kind["briefing"]["sources"][1].pop("kind")
        cases.append(no_kind)
        no_note = copy.deepcopy(item)
        no_note["readingScope"]["note"] = "본문 일부 검토"
        cases.append(no_note)
        wrong_note = copy.deepcopy(item)
        wrong_note["readingScope"]["note"] = "Figure 2 시각 확인"
        cases.append(wrong_note)
        no_reference = copy.deepcopy(item)
        no_reference["briefing"]["sections"][3]["blocks"][0]["sourceIds"] = ["review-text"]
        cases.append(no_reference)
        wrong_location = copy.deepcopy(item)
        wrong_location["briefing"]["sources"][1]["location"] = "Figure 2"
        cases.append(wrong_location)
        for modified in cases:
            self.write(modified)
            with self.subTest(modified=modified), self.assertRaises(radar.ReviewRadarError):
                radar.load_radar(today=TODAY, directory=self.directory)

    def test_malformed_curated_file_reports_public_error_without_path(self):
        (self.directory / "bad.json").write_text("{", encoding="utf-8")
        with self.assertRaises(radar.ReviewRadarError) as error:
            radar.load_radar(today=TODAY, directory=self.directory)
        self.assertNotIn(str(self.directory), str(error.exception))


class FetchBoundaryTests(unittest.TestCase):
    url = radar.API_URL + "?query=review&format=json"

    def response(self, data, headers=None, url=None):
        response = io.BytesIO(data)
        response.headers = headers or {}
        response.geturl = lambda: url or self.url
        return response

    def test_response_body_and_declared_size_limits_are_enforced(self):
        for headers in ({}, {"Content-Length": "100"}):
            with self.subTest(headers=headers), patch.object(radar, "MAX_RESPONSE_BYTES", 8), \
                    patch.object(radar, "build_opener", return_value=Mock(open=Mock(return_value=self.response(b"x" * 20, headers)))):
                with self.assertRaisesRegex(radar.ReviewRadarError, "용량"):
                    radar._fetch_page(self.url)

    def test_unsafe_endpoints_and_redirects_are_rejected(self):
        for url in ("https://127.0.0.1/europepmc/webservices/rest/search", "http://www.ebi.ac.uk/europepmc/webservices/rest/search",
                    "https://www.ebi.ac.uk/other", "https://example.com/europepmc/webservices/rest/search"):
            with self.subTest(url=url), self.assertRaises(radar.ReviewRadarError):
                radar._epmc_url(url)
        with self.assertRaises(radar.ReviewRadarError):
            radar._EPMCRedirect().redirect_request(None, None, 302, "redirect", {}, "https://127.0.0.1/private")

    def test_upstream_http_failure_does_not_expose_exception_url_or_body(self):
        failure = HTTPError("https://example.com/private-token", 403, "secret internal detail", {}, None)
        with patch.object(radar, "build_opener", return_value=Mock(open=Mock(side_effect=failure))):
            with self.assertRaises(radar.ReviewRadarError) as error:
                radar._fetch_page(self.url)
        self.assertIn("403", str(error.exception))
        self.assertNotIn("private-token", str(error.exception))
        self.assertNotIn("secret", str(error.exception))


if __name__ == "__main__":
    unittest.main()
