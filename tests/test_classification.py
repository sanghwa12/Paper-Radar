"""Prevent metadata routing from silently equating every journal article with original research."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from classification import classify_candidate


class ClassificationTests(unittest.TestCase):
    def classify(self, **changes):
        return classify_candidate({"source": "MED", "title": "A drug discovery study",
                                   "publicationTypes": ["Journal Article"], **changes})

    def test_generic_article_and_missing_metadata_stay_uncertain(self):
        for paper in ({}, {"publicationTypes": ["Journal Article"]},
                      {"publicationTypes": None, "abstract": "Drug discovery is an important challenge."}):
            self.assertEqual(classify_candidate(paper)["kind"], "uncertain")

    def test_explicit_types_take_precedence_and_normalize(self):
        cases = [("research-article", "original"), ("Clinical Trial, Phase II", "original"),
                 ("Randomized Controlled Trial", "original"), ("Review", "review"),
                 ("systematic-review", "review"), ("Meta-Analysis", "review"),
                 ("Preprint", "preprint"), ("Published Erratum", "other"),
                 ("Retracted Publication", "other"), ("Editorial", "other"),
                 ("Clinical Trial Protocol", "other")]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(self.classify(publicationTypes=["Journal Article", value])["kind"], expected)
        self.assertEqual(self.classify(publicationTypes="review-article")["kind"], "review")
        self.assertEqual(self.classify(publicationTypes=["research-article", "Review"])["kind"], "review")
        self.assertEqual(self.classify(publicationTypes=["research-article", "Published Erratum"])["kind"], "other")

    def test_preprint_remains_deferred_even_for_original_or_review(self):
        for types in (["research-article"], ["Review"], []):
            self.assertEqual(self.classify(source="PPR", publicationTypes=types)["kind"], "preprint")

    def test_specific_review_titles_without_catching_reviewed_data(self):
        for title in ("Drug discovery: a review", "A review of drug design",
                      "Drug safety: a systematic review and meta-analysis", "A scoping review of AI"):
            self.assertEqual(self.classify(title=title)["kind"], "review")
        self.assertEqual(self.classify(title="Retrospective review of patient charts")['kind'], "uncertain")
        self.assertEqual(self.classify(title="Peer review quality in drug discovery")['kind'], "uncertain")

    def test_abstract_self_identifies_review(self):
        for abstract in ("This review discusses molecular glues and summarizes their applications.",
                         "This structured narrative review examines the literature.",
                         "We review recent advances in docking. Studies showed improved accuracy.",
                         "This paper provides a comprehensive review of existing methods."):
            self.assertEqual(self.classify(abstract=abstract)["kind"], "review")

    def test_original_abstract_requires_both_work_and_results(self):
        cases = ["We developed a docking method. Experiments showed improved pose accuracy.",
                 "This study used fragment-based design. Five promising molecules were identified.",
                 "A new docking approach is introduced in this study. Experimental results demonstrate improved accuracy.",
                 "We systematically assess crystal structures in a benchmark. Variable performance was observed.",
                 "We executed a targeted optimization. These studies delivered a highly potent lead.",
                 "We report a new assay platform. Clinical serum measurements showed reference-method consistency.",
                 "Methods: Patients were enrolled and assigned to two groups. Results: Drug exposure increased by 20%."]
        for abstract in cases:
            result = self.classify(abstract=abstract)
            self.assertEqual(result["kind"], "original")
            self.assertEqual(result["basis"], "abstract")
            self.assertIn("잠정", result["reason"])
        for abstract in ("We propose a new future clinical trial.",
                         "Previous studies showed that drug exposure increased.",
                         "We will develop a new model. Results will show whether it works.",
                         "We developed a protocol. Experiments may show improved accuracy.",
                         "Methods: We plan a clinical trial. Results: will be reported next year."):
            self.assertEqual(self.classify(abstract=abstract)["kind"], "uncertain")

    def test_incidental_review_preprint_and_trial_mentions_do_not_override_original(self):
        abstract = ("Prior literature review and a preprint motivated this study. "
                    "We developed a computational model. Experiments showed improved predictions.")
        self.assertEqual(self.classify(abstract=abstract)["kind"], "original")
        self.assertEqual(self.classify(abstract="We reviewed patient charts. Results showed a 20% decrease.")["kind"], "uncertain")

    def test_protocol_title_and_corrections_are_not_research_results(self):
        for title in ("Correction: A trial of drug X", "Expression of concern: Drug discovery",
                      "Drug safety: study protocol for a randomized trial"):
            self.assertEqual(self.classify(title=title, publicationTypes=["research-article"])["kind"], "other")

    def test_does_not_mutate_metadata_or_gate_by_access_or_journal(self):
        paper = {"title": "A trial", "publicationTypes": ["Clinical Trial"], "openAccess": False,
                 "journal": "Unknown journal", "categories": ["Target·기전"]}
        saved = copy.deepcopy(paper)
        result = classify_candidate(paper)
        self.assertEqual(result["kind"], "original")
        self.assertEqual(set(result), {"kind", "label", "reason", "basis"})
        self.assertEqual(paper, saved)


if __name__ == "__main__":
    unittest.main()
