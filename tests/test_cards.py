"""Validate the reading-card evidence boundary and usable paper data."""
import copy
import json
import re
import sys
import unittest
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

try:
    from PIL import Image
except ImportError:
    Image = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cards import ASSET_DIRECTORY, BRIEF_DIRECTORY, REVIEW_PATH, load_brief, load_cards, load_review, validate_card
from evaluation import load_evaluation


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def temporary_directory():
    directory = Path(__file__).parent / ("paper-radar-card-tests-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        for path in directory.iterdir():
            path.unlink()
        directory.rmdir()


def objects(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from objects(item)


class CardTests(unittest.TestCase):
    def assert_source(self, source):
        self.assertIsInstance(source, dict)
        self.assertTrue(source.get("label", "").strip())
        url = urlsplit(source.get("url", ""))
        self.assertEqual(url.scheme, "https")
        self.assertTrue(url.netloc)

    def assert_local_asset(self, url):
        parsed = urlsplit(url)
        self.assertFalse(parsed.scheme or parsed.netloc)
        self.assertTrue(parsed.path.startswith("/assets/briefs/"))
        path = (ROOT / "public" / unquote(parsed.path).lstrip("/")).resolve()
        self.assertTrue(path.is_relative_to((ROOT / "public" / "assets" / "briefs").resolve()))
        self.assertTrue(path.is_file(), url)
        data = path.read_bytes()
        self.assertTrue(data, url)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            self.assertTrue(data.startswith(b"%PDF-"), url)
            self.assertIn(b"%%EOF", data[-2048:], url)
        elif suffix == ".svg":
            self.assertEqual(ET.fromstring(data).tag.rsplit("}", 1)[-1], "svg")
        else:
            signatures = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff",
                          ".jpeg": b"\xff\xd8\xff", ".webp": b"RIFF"}
            self.assertIn(suffix, signatures, url)
            self.assertTrue(data.startswith(signatures[suffix]), url)
            if suffix == ".webp":
                self.assertEqual(data[8:12], b"WEBP", url)
            if Image is not None:
                with Image.open(path) as image:
                    self.assertGreater(image.width, 0)
                    self.assertGreater(image.height, 0)
                    image.verify()

    def test_pilot_cards_cover_six_areas_with_stable_ids_and_honest_sources(self):
        papers = load_cards()
        original = {paper["id"]: paper for paper in load_evaluation()["papers"]}
        self.assertEqual(set(papers), set(original))
        self.assertEqual(len(papers), 12)
        self.assertEqual(sorted(Counter(p["metadata"]["categories"][0] for p in papers.values()).values()), [2] * 6)
        self.assertEqual(Counter(p["cardOrigin"]["basis"] for p in papers.values()),
                         {"fulltext": 7, "prior_fulltext_review": 4, "abstract": 1})
        for paper_id, paper in papers.items():
            with self.subTest(paper=paper_id):
                self.assertEqual(paper["candidateId"], paper_id)
                self.assertEqual(paper["metadata"]["doi"], original[paper_id]["doi"])
                self.assertEqual(paper["scoreSnapshot"]["score"], original[paper_id]["score"])
                self.assertTrue(paper["abstract"]["paragraphs"])
                self.assertTrue(paper["tabs"]["methods"])
                self.assert_source(paper["abstract"]["source"])
                for pair in paper["card"]["pairs"]:
                    self.assert_source(pair["source"])
                if original[paper_id]["reviewBasis"] == "abstract":
                    self.assertEqual(paper["cardOrigin"]["basis"], "abstract")

    def test_twelve_brief_files_have_matching_ids_tabs_and_attributed_figures(self):
        papers = load_cards()
        self.assertEqual({path.stem for path in BRIEF_DIRECTORY.glob("*.json")}, set(papers))
        figures = 0
        for paper_id in papers:
            with self.subTest(paper=paper_id):
                brief = load_brief(paper_id)
                self.assertEqual(brief["candidateId"], paper_id)
                self.assertTrue(brief["evidenceNote"].strip())
                self.assertEqual(set(brief["tabs"]), {"summary", "overview", "methods", "evidence"})
                for sections in brief["tabs"].values():
                    self.assertTrue(sections)
                    for section in sections:
                        self.assertTrue(section.get("title", "").strip())
                        self.assertTrue(section["blocks"])
                for block in objects(brief["tabs"]):
                    if block.get("type") == "figure":
                        figures += 1
                        for field in ("title", "alt", "caption"):
                            self.assertTrue(block.get(field, "").strip(), field)
                        self.assert_source(block["source"])
                        self.assertTrue(block["explanation"])
                        for panel in block["explanation"]:
                            self.assertTrue(panel["label"].strip())
                            self.assertTrue(panel["text"].strip())
                        self.assert_local_asset(block["image"])
                    elif block.get("type") == "image":
                        self.assertTrue(block["alt"].strip())
                        self.assertTrue(block["caption"].strip())
                        self.assert_local_asset(block["src"])
                    elif block.get("type") == "links":
                        for source in block["items"]:
                            self.assert_source(source)
        self.assertGreater(figures, 0, "The acquired figures must be exercised by this test")

    def test_published_image_and_document_links_refer_to_real_local_assets(self):
        documents = images = 0
        for paper_id, paper in load_cards().items():
            with self.subTest(paper=paper_id):
                for key in ("pdfUrl", "siUrl"):
                    url = paper["metadata"].get(key)
                    if url:
                        if url.startswith("/"):
                            documents += 1
                            self.assert_local_asset(url)
                        else:
                            self.assert_source({"label": key, "url": url})
                image = paper["card"].get("image")
                if image:
                    images += 1
                    self.assertTrue(image["alt"].strip())
                    self.assert_source(image["source"])
                    self.assert_local_asset(image["src"])
        self.assertGreater(documents, 0)
        self.assertGreater(images, 0)

    def test_figure_labels_and_source_anchors_match_asset_manifests(self):
        matched = 0
        for manifest_path in ASSET_DIRECTORY.glob("*/sources.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            paper_id = manifest_path.parent.name
            self.assertEqual(manifest["candidateId"], paper_id)
            figures = {figure["path"]: figure for figure in manifest["figures"]}
            for block in objects(load_brief(paper_id)["tabs"]):
                if block.get("type") != "figure":
                    continue
                with self.subTest(paper=paper_id, image=block["image"]):
                    self.assertIn(block["image"], figures)
                    source = figures[block["image"]]
                    # A file's sequence number can include graphical abstracts or schemes.
                    # The original label and element ID, not the filename, identify a figure.
                    original_label = re.sub(r"^(?:Figure|Fig\.)\s*", "", source["label"], flags=re.I).strip(". ")
                    display_label = re.sub(r"^(?:Figure|Fig\.)\s*", "", block["eyebrow"].split("·")[0], flags=re.I).strip(". ")
                    self.assertEqual(display_label, original_label)
                    self.assertEqual(urlsplit(block["source"]["url"]).fragment, source["figureId"])
                    matched += 1
        self.assertGreater(matched, 0)

    def test_missing_review_stays_unverified_without_an_invented_date(self):
        with temporary_directory() as directory:
            path = directory / "reviews.json"
            for contents in (None, {}):
                if contents is not None:
                    path.write_text(json.dumps(contents), encoding="utf-8")
                review = load_review("unknown-paper", path=path)
                self.assertEqual(review["status"], "unverified")
                self.assertEqual(review["checkedAt"], "")
                self.assertEqual(set(review["acquired"]), {"abstract", "body", "figures", "supplement"})
                self.assertTrue(all(value is None for value in review["acquired"].values()))
                self.assertTrue(all(value == "unverified" for value in review["checked"].values()))
                self.assertEqual(review["holds"], [])

    def test_review_records_cover_all_twelve_cards_without_conflating_acquisition(self):
        reviews = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
        papers = load_cards()
        self.assertEqual(set(reviews), set(papers))
        scopes = {"abstract", "body", "figures", "supplement"}
        for paper_id, paper in papers.items():
            with self.subTest(paper=paper_id):
                review = load_review(paper_id)
                self.assertIn(review["status"], {"reviewed", "partial", "unverified", "held"})
                self.assertEqual(date.fromisoformat(review["checkedAt"]).isoformat(), review["checkedAt"])
                self.assertEqual(set(review["acquired"]), scopes)
                self.assertEqual(set(review["checked"]), scopes)
                for scope in scopes:
                    self.assertIs(type(review["acquired"][scope]), bool)
                    if review["checked"][scope] == "reviewed":
                        self.assertTrue(review["acquired"][scope])
                if review["status"] == "reviewed":
                    self.assertEqual(review["checked"]["body"], "reviewed")
                    self.assertEqual(review["holds"], [])
                self.assertEqual(paper["briefOrigin"]["review"], review)
                self.assertEqual(paper["metadata"]["reviewedAt"], review["checkedAt"])

    def test_fulltext_acquisition_does_not_imply_completed_review(self):
        with temporary_directory() as directory:
            unverified = load_review("unknown", path=directory / "missing.json")
        with patch("cards.load_review", return_value=unverified):
            papers = load_cards()
        fulltext = [paper for paper in papers.values() if paper["briefOrigin"]["basis"] == "fulltext"]
        self.assertTrue(fulltext)
        for paper in fulltext:
            with self.subTest(paper=paper["id"]):
                self.assertEqual(paper["briefOrigin"]["review"]["status"], "unverified")
                self.assertIn("미검증", paper["metadata"]["reviewStatus"])
                self.assertEqual(paper["metadata"]["reviewedAt"], "")

    def test_source_and_safety_holds_are_distinct_and_cannot_be_reviewed(self):
        review = {"status": "partial", "checkedAt": "2026-09-23",
                  "acquired": {key: True for key in ("abstract", "body", "figures", "supplement")},
                  "checked": {key: "partial" for key in ("abstract", "body", "figures", "supplement")},
                  "note": "일부 자료의 확인을 보류했습니다.",
                  "holds": [{"scope": "supplement", "reason": "source", "note": "자료 미확인"},
                            {"scope": "methods", "reason": "safety", "note": "해당 세부 범위 보류"}]}
        with temporary_directory() as directory:
            path = directory / "reviews.json"
            path.write_text(json.dumps({"example": review}), encoding="utf-8")
            loaded = load_review("example", path=path)
            self.assertEqual(loaded["holds"], review["holds"])
            for mutate in (lambda value: value.update(status="reviewed"),
                           lambda value: value["holds"][0].update(reason="unknown"),
                           lambda value: value["holds"][0].update(scope=""),
                           lambda value: value["acquired"].update(body="yes")):
                invalid = copy.deepcopy(review)
                mutate(invalid)
                path.write_text(json.dumps({"example": invalid}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_review("example", path=path)

    def test_held_brief_keeps_card_and_memo_without_publishing_held_tabs(self):
        held = {"status": "held", "checkedAt": "2026-09-23", "note": "검토 보류 안내",
                "acquired": {key: True for key in ("abstract", "body", "figures", "supplement")},
                "checked": {key: "unverified" for key in ("abstract", "body", "figures", "supplement")},
                "holds": [{"scope": "brief", "reason": "source", "note": "연결 확인 대기"}]}
        with patch("cards.load_review", return_value=held):
            papers = load_cards()
        self.assertEqual(len(papers), 12)
        for paper_id, paper in papers.items():
            with self.subTest(paper=paper_id):
                self.assertTrue(paper["card"]["purpose"])
                self.assertEqual(paper["tabs"]["memo"], [])
                self.assertNotIn("image", paper["card"])
                self.assertIn("보류", paper["metadata"]["reviewStatus"])
                for tab in ("summary", "overview", "methods", "evidence"):
                    self.assertNotEqual(paper["tabs"][tab], load_brief(paper_id)["tabs"][tab])
                    self.assertIn(held["note"], json.dumps(paper["tabs"][tab], ensure_ascii=False))

    def test_missing_mismatched_or_empty_brief_cannot_be_loaded(self):
        paper_id = next(iter(load_cards()))
        original = load_brief(paper_id)
        with temporary_directory() as directory:
            with self.assertRaises(ValueError):
                load_brief(paper_id, directory=directory)
            for mutate in (lambda value: value.update(candidateId="different-paper"),
                           lambda value: value.update(evidenceNote=""),
                           lambda value: value["tabs"].update(overview=[]),
                           lambda value: value["tabs"]["methods"][0].update(blocks=[])):
                brief = copy.deepcopy(original)
                mutate(brief)
                (Path(directory) / f"{paper_id}.json").write_text(
                    json.dumps(brief, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_brief(paper_id, directory=directory)

    def test_incomplete_or_unattributed_card_is_not_publishable(self):
        source = {"label": "Results", "url": "https://example.org/paper"}
        content = {"candidateId": "a", "titleKo": "제목", "purpose": "목적", "significance": "의미",
                   "application": "적용", "limits": "한계", "evidenceNote": "본문", "basis": "fulltext",
                   "abstractKo": ["초록"], "briefSummary": ["요약"], "caveats": ["한계"], "flow": ["측정"],
                   "pairs": [{"label": "실험", "method": "측정", "result": "결과", "source": source}] * 2,
                   "methods": [{"label": "조건", "text": "조건 값", "source": source}], "references": [source]}
        validate_card(content)
        for mutate in (lambda x: x.update(abstractKo=[]), lambda x: x.update(basis="unverified"),
                       lambda x: x["pairs"][0].pop("source"), lambda x: x["methods"][0].update(text=""),
                       lambda x: x["references"][0].update(url="javascript:alert(1)")):
            value = copy.deepcopy(content)
            mutate(value)
            with self.assertRaises(ValueError):
                validate_card(value)


if __name__ == "__main__":
    unittest.main()
