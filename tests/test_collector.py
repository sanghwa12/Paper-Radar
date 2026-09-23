"""Verify durable collection with deterministic Europe PMC responses, never live queries."""
import io
import json
import sqlite3
import sys
import threading
import unittest
import uuid
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collector


def article(identifier="100", doi="10.1234/example", **changes):
    return {"id": identifier, "source": "MED", "doi": doi,
            "title": "A <i>ligand</i> &amp; its target", "authorString": "Researcher A",
            "firstPublicationDate": "2026-09-01", "isOpenAccess": "N",
            "abstractText": "<p>Purpose &amp; method.</p><p>Measured result.</p>",
            "journalInfo": {"journal": {"title": "Test Journal"}},
            "pubTypeList": {"pubType": ["Journal Article"]}, **changes}


def page(records, total=None, cursor=None):
    response = {"hitCount": len(records) if total is None else total, "resultList": {"result": records}}
    if cursor is not None:
        response["nextCursorMark"] = cursor
    return response


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).parent / ("collector-test-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.db_path = self.directory / "test.sqlite3"
        self.client = collector.Collector(self.db_path, {
            "reviewed": {"metadata": {"doi": "https://doi.org/10.1234/EXAMPLE"}}})
        self.clients = [self.client]
        self.fixtures = {}
        self.requests = []
        self.fetcher = patch.object(self.client, "_fetch_page", side_effect=self.fetch)
        self.fetcher.start()
        self.addCleanup(self.fetcher.stop)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for client in self.clients:
            if client._thread:
                client._thread.join(timeout=3)
                self.assertFalse(client._thread.is_alive(), "Collector worker did not stop")
        self.assertTrue(self.directory.resolve().is_relative_to(Path(__file__).parent.resolve()))
        for path in self.directory.iterdir():
            path.unlink()
        self.directory.rmdir()

    def fetch(self, query, cursor):
        area = next(index for index, item in enumerate(collector.AREAS)
                    if query.startswith(f"({item['query']}) AND FIRST_PDATE:"))
        self.requests.append((area, query, cursor))
        result = self.fixtures.get((area, cursor), page([]))
        if isinstance(result, Exception):
            raise result
        return result

    def run_collection(self):
        snapshot = self.client.start("2026-08-23", "2026-09-21")
        self.assertEqual(snapshot["status"], "running")
        self.client._thread.join(timeout=3)
        self.assertFalse(self.client._thread.is_alive())
        return self.client.status()["run"]

    def test_all_pages_six_queries_deduplication_and_plain_metadata(self):
        self.fixtures = {
            (0, "*"): page([article(doi="DOI:10.1234/EXAMPLE")], total=2, cursor="second"),
            (0, "second"): page([article("200", "10.1234/second", abstractText=None)], total=2),
            (1, "*"): page([article("PMC100", "https://doi.org/10.1234/example", source="PMC", pmid="100")]),
        }
        run = self.run_collection()
        status = self.client.status()
        self.assertEqual((run["status"], run["added"], run["updated"]), ("completed", 2, 0))
        self.assertEqual(run["areas"][0]["pages"], 2)
        self.assertEqual(run["areas"][0]["processed"], 2)
        self.assertEqual(status["counts"]["total"], 2)
        self.assertEqual(status["counts"]["areas"][collector.AREAS[0]["name"]], 2)
        self.assertEqual(status["counts"]["areas"][collector.AREAS[1]["name"]], 1)
        self.assertEqual({request[0] for request in self.requests}, set(range(6)))
        self.assertEqual(len(self.requests), 7)
        for _, query, _ in self.requests:
            self.assertIn("FIRST_PDATE:[2026-08-23 TO 2026-09-21]", query)
            self.assertNotIn("OPEN_ACCESS", query)
            self.assertIn("(SRC:MED OR SRC:PMC OR SRC:PPR)", query)
        papers = {paper["doi"]: paper for paper in self.client.candidates()}
        paper = papers["10.1234/example"]
        self.assertEqual(paper["title"], "A ligand & its target")
        self.assertEqual(paper["abstract"], "Purpose & method. Measured result.")
        self.assertEqual(len(paper["categories"]), 2)
        self.assertTrue(paper["inLibrary"])
        self.assertFalse(paper["openAccess"])
        self.assertEqual(paper["fullTextStatus"], "not_retrieved")
        self.assertEqual(papers["10.1234/second"]["abstract"], "")

    def test_repeat_range_rechecks_existing_records_without_adding(self):
        self.fixtures = {(index, "*"): page([article()]) for index in range(6)}
        first_run = self.run_collection()
        first_paper = self.client.candidates()[0]
        second_run = self.run_collection()
        second_paper = self.client.candidates()[0]
        self.assertEqual((first_run["added"], first_run["updated"]), (1, 0))
        self.assertEqual((second_run["added"], second_run["updated"]), (0, 1))
        self.assertEqual(first_paper["id"], second_paper["id"])
        self.assertEqual(first_paper["firstSeenAt"], second_paper["firstSeenAt"])
        self.assertGreaterEqual(second_paper["lastSeenAt"], first_paper["lastSeenAt"])
        self.assertEqual(len(self.requests), 12)

    def test_encoded_emphasis_and_script_tags_become_safe_plain_text(self):
        record = article(
            title="&lt;i&gt;In vitro, in vivo&lt;/i&gt; &amp; assays on &lt;i&gt;Piper betle&lt;/i&gt;",
            abstractText="&lt;p&gt;Measured result.&lt;/p&gt; &lt;script&gt;alert(1)&lt;/script&gt;"
                         "&lt;img src=x onerror=alert(2)&gt;&lt;style&gt;body{display:none}&lt;/style&gt;",
        )
        self.fixtures = {(0, "*"): page([record])}
        self.run_collection()
        paper = self.client.candidates()[0]
        self.assertEqual(paper["title"], "In vitro, in vivo & assays on Piper betle")
        self.assertEqual(paper["abstract"], "Measured result.")

    def test_block_boundaries_separate_words_without_splitting_inline_units(self):
        self.assertEqual(
            collector.plain_text("<h4>Objectives</h4>Gout study.<h4>Methods</h4>Assay."
                                 "<h4>Results</h4>IC<sub>50</sub> &lt; 10 nM with Mg<sup>2+</sup>."
                                 "<h4>Conclusions</h4>Further validation."),
            "Objectives Gout study. Methods Assay. Results IC50 < 10 nM with Mg2+. Conclusions Further validation.",
        )
        for heading in range(1, 7):
            self.assertEqual(collector.plain_text(f"Before<h{heading}>Heading</h{heading}>After"),
                             "Before Heading After")
        self.assertEqual(collector.plain_text("<div>One</div><table><tr><td>Two</td><td>Three</td></tr></table>"),
                         "One Two Three")

    def test_later_identifiers_merge_two_records_within_the_same_run(self):
        self.fixtures = {
            (0, "*"): page([article(doi="")]),
            (1, "*"): page([article("PMC777", source="PMC")]),
            (2, "*"): page([article(pmcid="PMC777")]),
        }
        run = self.run_collection()
        papers = self.client.candidates()
        self.assertEqual(len(papers), 1)
        self.assertEqual((run["added"], run["updated"]), (1, 0))
        self.assertEqual(papers[0]["pmid"], "100")
        self.assertEqual(papers[0]["pmcid"], "PMC777")
        self.assertEqual(len(papers[0]["categories"]), 3)

    def test_new_doi_merges_with_old_pmid_without_counting_a_new_candidate(self):
        self.fixtures = {(0, "*"): page([article(doi="")])}
        self.run_collection()
        first_seen = self.client.candidates()[0]["firstSeenAt"]
        self.fixtures = {
            (0, "*"): page([article("PMC777", source="PMC")]),
            (1, "*"): page([article(pmcid="PMC777")]),
        }
        run = self.run_collection()
        papers = self.client.candidates()
        self.assertEqual(len(papers), 1)
        self.assertEqual((run["added"], run["updated"]), (0, 1))
        self.assertEqual(papers[0]["firstSeenAt"], first_seen)
        self.assertTrue(papers[0]["inLibrary"])
        third_run = self.run_collection()
        self.assertEqual((third_run["added"], third_run["updated"]), (0, 1))

    def test_merged_candidate_id_remains_resolvable_for_saved_sources(self):
        self.fixtures = {(0, "*"): page([article(doi="")]),
                         (1, "*"): page([article("PMC777", source="PMC")])}
        self.run_collection()
        old_ids = {paper["id"] for paper in self.client.candidates()}
        self.assertEqual(len(old_ids), 2)
        self.fixtures = {(0, "*"): page([article(pmcid="PMC777")])}
        self.run_collection()
        surviving_id = self.client.candidates()[0]["id"]
        removed_id = (old_ids - {surviving_id}).pop()
        with closing(sqlite3.connect(self.db_path)) as db:
            alias = db.execute("SELECT candidate_id FROM collection_aliases WHERE alias=?",
                               ("candidate:" + removed_id,)).fetchone()
        self.assertEqual(alias, (surviving_id,))

    def test_partial_failure_keeps_pages_and_other_areas_continue(self):
        self.fixtures = {
            (0, "*"): page([article()], total=2, cursor="later"),
            (0, "later"): RuntimeError("temporary source failure"),
            (1, "*"): page([article("200", "10.1234/second")]),
        }
        run = self.run_collection()
        self.assertEqual(run["status"], "partial")
        self.assertEqual((run["added"], run["updated"]), (2, 0))
        self.assertEqual(run["areas"][0]["pages"], 1)
        self.assertEqual(run["areas"][0]["processed"], 1)
        self.assertIn("temporary source failure", run["areas"][0]["error"])
        self.assertTrue(all(area["status"] == "completed" for area in run["areas"][1:]))
        self.assertEqual(len(self.client.candidates()), 2)

    def test_broken_pagination_is_not_reported_as_complete(self):
        self.fixtures = {(0, "*"): page([article()], total=2, cursor="*")}
        run = self.run_collection()
        self.assertEqual(run["status"], "partial")
        self.assertEqual(run["areas"][0]["status"], "failed")
        self.assertEqual(run["areas"][0]["processed"], 1)

    def test_retry_only_failed_areas_preserves_dates_and_completed_candidates(self):
        self.fixtures = {
            (0, "*"): page([article()], total=2, cursor="later"),
            (0, "later"): RuntimeError("source unavailable"),
            (1, "*"): page([article("200", "10.1234/completed")]),
            (5, "*"): RuntimeError("source unavailable"),
        }
        original = self.run_collection()
        self.assertEqual(original["status"], "partial")
        completed_paper = next(paper for paper in self.client.candidates() if paper["pmid"] == "200")
        self.requests.clear()
        self.fixtures = {(0, "*"): page([article()]),
                         (5, "*"): page([article("300", "10.1234/recovered")])}
        retry_snapshot = self.client.retry(original["id"])
        self.client._thread.join(timeout=3)
        retried = self.client.status()["run"]
        self.assertEqual(retry_snapshot["retryOf"], original["id"])
        self.assertEqual((retried["from"], retried["to"]), (original["from"], original["to"]))
        self.assertEqual([request[0] for request in self.requests], [0, 5])
        self.assertEqual([area["name"] for area in retried["areas"]],
                         [collector.AREAS[index]["name"] for index in (0, 5)])
        self.assertEqual((retried["status"], retried["added"], retried["updated"]), ("completed", 1, 1))
        self.assertEqual(len(self.client.status()["areas"]), 6)
        self.assertEqual(self.client.status()["counts"]["total"], 3)
        self.assertEqual(next(paper for paper in self.client.candidates() if paper["pmid"] == "200"), completed_paper)
        with self.assertRaises(ValueError):
            self.client.retry(original["id"])
        with self.assertRaises(ValueError):
            self.client.retry(retried["id"])
        self.requests.clear()
        self.run_collection()
        self.assertEqual({request[0] for request in self.requests}, set(range(6)))

    def test_retry_failure_uses_selected_area_count(self):
        self.fixtures = {(5, "*"): RuntimeError("source unavailable")}
        original = self.run_collection()
        self.requests.clear()
        self.client.retry(original["id"])
        self.client._thread.join(timeout=3)
        retried = self.client.status()["run"]
        self.assertEqual([request[0] for request in self.requests], [5])
        self.assertEqual(retried["status"], "failed")

    def test_page_saved_before_next_request_and_parallel_start_rejected(self):
        waiting, release = threading.Event(), threading.Event()
        def blocked_fetch(query, cursor):
            if cursor == "second":
                waiting.set()
                self.assertTrue(release.wait(timeout=3))
            return self.fetch(query, cursor)
        self.fixtures = {
            (0, "*"): page([article()], total=2, cursor="second"),
            (0, "second"): page([article("200", "10.1234/second")], total=2),
        }
        with patch.object(self.client, "_fetch_page", side_effect=blocked_fetch):
            try:
                snapshot = self.client.start("2026-08-23", "2026-09-21")
                self.assertEqual(snapshot["areas"][0]["status"], "pending")
                self.assertTrue(waiting.wait(timeout=3))
                self.assertEqual(len(self.client.candidates()), 1)
                self.assertEqual(self.client.status()["run"]["areas"][0]["pages"], 1)
                with self.assertRaises(RuntimeError):
                    self.client.start("2026-08-23", "2026-09-21")
                other = collector.Collector(self.db_path, [])
                self.clients.append(other)
                self.assertEqual(other.status()["run"]["status"], "running")
                with self.assertRaises(RuntimeError):
                    other.start("2026-08-23", "2026-09-21")
            finally:
                release.set()
                self.client._thread.join(timeout=3)
        self.assertEqual(self.client.status()["run"]["status"], "completed")

    def test_invalid_dates_do_not_create_a_run(self):
        for begin, end in [("2026-02-30", "2026-03-01"), ("2026-09-02", "2026-09-01"),
                           (None, "2026-09-01"), ("20260901", "20260902"), ("", "")]:
            with self.subTest(begin=begin, end=end), self.assertRaises(ValueError):
                self.client.start(begin, end)
        self.assertIsNone(self.client.status()["run"])
        self.assertEqual(self.requests, [])
        for run_id in (None, "", "missing-run"):
            with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                self.client.retry(run_id)
        self.assertIsNone(self.client.status()["run"])

    def test_restart_marks_persisted_running_job_interrupted(self):
        self.fixtures = {(0, "*"): page([article()])}
        run = self.run_collection()
        run["status"], run["finishedAt"] = "running", None
        run["areas"][0]["status"] = "running"
        with closing(sqlite3.connect(self.db_path)) as db:
            with db:
                db.execute("UPDATE collection_runs SET data=? WHERE id=?", (json.dumps(run), run["id"]))
        restarted = collector.Collector(self.db_path, [])
        self.clients.append(restarted)
        status = restarted.status()
        self.assertEqual(status["run"]["status"], "interrupted")
        self.assertIsNotNone(status["run"]["finishedAt"])
        self.assertEqual(status["run"]["areas"][0]["status"], "failed")
        self.assertEqual(status["counts"]["total"], 1)

    def test_worker_status_write_failure_does_not_permanently_block_collection(self):
        original_save = self.client._save_run
        def fail_worker_writes(db, run):
            if threading.current_thread() is self.client._thread:
                raise sqlite3.OperationalError("database is locked")
            return original_save(db, run)
        with patch.object(self.client, "_save_run", side_effect=fail_worker_writes):
            self.client.start("2026-08-23", "2026-09-21")
            self.client._thread.join(timeout=3)
            self.assertFalse(self.client._thread.is_alive())
        self.assertEqual(self.client.status()["run"]["status"], "interrupted")
        self.assertEqual(self.run_collection()["status"], "completed")

    def test_network_parameters_and_bounded_transient_retry(self):
        error = HTTPError(collector.API_URL, 429, "Too Many Requests", {"Retry-After": "1"}, None)
        response = io.BytesIO(json.dumps(page([])).encode())
        with patch("collector.urlopen", side_effect=[error, response]) as request, patch("collector.time.sleep"):
            result = collector.Collector._fetch_page(self.client, "TITLE_ABS:drug", "a+b/=")
        self.assertEqual(result["hitCount"], 0)
        self.assertEqual(request.call_count, 2)
        call = request.call_args
        parameters = parse_qs(urlsplit(call.args[0].full_url).query)
        self.assertEqual(parameters["resultType"], ["core"])
        self.assertEqual(parameters["cursorMark"], ["a+b/="])
        self.assertEqual(parameters["pageSize"], ["100"])
        self.assertEqual(call.kwargs["timeout"], 30)
        with patch("collector.urlopen", side_effect=OSError("offline")) as request, patch("collector.time.sleep"):
            with self.assertRaises(RuntimeError):
                collector.Collector._fetch_page(self.client, "TITLE_ABS:drug", "*")
        self.assertEqual(request.call_count, 3)


if __name__ == "__main__":
    unittest.main()
