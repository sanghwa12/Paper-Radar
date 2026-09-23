"""Isolated preparation worker, persistence, identity and integrity checks."""
import hashlib
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
import acquisition
import preparation


def paper(identifier="one", **changes):
    return {"id": identifier, "title": "A fixture measurement comparison", "doi": "10.1234/fixture",
            "pmcid": "PMC123", "pmid": "123", "abstract": "A fixture abstract.",
            "sourceUrl": "https://europepmc.org/article/MED/123", "publicationTypes": ["Research Article"],
            **changes}


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).parent / ("preparation-test-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.db_path = self.directory / "test.sqlite3"
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executescript("""
                CREATE TABLE collection_candidates(id TEXT PRIMARY KEY, created_run TEXT, data TEXT);
                CREATE TABLE collection_aliases(alias TEXT PRIMARY KEY, candidate_id TEXT);
                CREATE TABLE paper_state(id TEXT PRIMARY KEY, data TEXT);
                CREATE TABLE published_cards(id TEXT PRIMARY KEY, data TEXT);
                INSERT INTO paper_state VALUES ('saved', '{"note":"preserve","saved":true,"read":true}');
                INSERT INTO published_cards VALUES ('existing', '{"title":"Preserve existing card"}');
            """)
        self.add_candidate(paper())
        self.acquisition = acquisition.Acquisition(self.db_path)
        self.source_document = {"candidateId": "one", "status": "fulltext", "title": "Existing body",
                                "identifiers": {"doi": "10.1234/fixture", "pmcid": "PMC123"},
                                "sections": [{"heading": "Existing", "text": "Preserve acquired text."}]}
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("INSERT INTO candidate_sources VALUES (?, ?)", ("one", json.dumps(self.source_document)))
        self.client = preparation.Preparation(self.db_path, self.acquisition)
        self.clients = [self.client]
        self.patch = patch.object(preparation, "prepare", side_effect=self.prepared_result)
        self.prepare = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for client in self.clients:
            if client._thread:
                client._thread.join(timeout=5)
                self.assertFalse(client._thread.is_alive())
        target = self.directory.resolve()
        self.assertTrue(target.is_relative_to(Path(__file__).parent.resolve()))
        self.assertTrue(target.name.startswith("preparation-test-"))
        shutil.rmtree(target)

    def add_candidate(self, item):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("INSERT INTO collection_candidates VALUES (?, 'fixture', ?)", (item["id"], json.dumps(item)))
            for field in ("doi", "pmcid", "pmid"):
                if item.get(field):
                    db.execute("INSERT OR REPLACE INTO collection_aliases VALUES (?, ?)",
                               (f"{field}:{item[field]}", item["id"]))

    def prepared_result(self, item, directory, prefix, *, cached_document, progress, status="ready"):
        progress("그림 준비 중")
        directory.mkdir(parents=True, exist_ok=True)
        data = b"fixture image bytes"
        image = directory / "figure-1.png"
        image.write_bytes(data)
        text = "A fixture measured value was compared with a reference."
        source = {"id": "body-1", "kind": "body", "label": "Results", "url": item["sourceUrl"],
                  "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
        package = {"schemaVersion": 1, "candidateId": item["id"], "metadata": {"title": item["title"]},
                   "sources": [source]}
        return {"package": package, "status": status, "provider": "Fixture", "sourceUrl": item["sourceUrl"],
                "license": "Fixture only", "preparedAt": preparation.now(),
                "coverage": [{"kind": "body", "label": "본문", "expected": 1, "acquired": 1,
                              "usable": 1, "state": "complete", "note": "Content not reviewed."},
                             {"kind": "figures", "label": "그림", "expected": 1, "acquired": 1,
                              "usable": 1, "state": "complete"}],
                "assets": [{"id": "figure-1", "kind": "figure", "label": "Figure 1",
                            "localUrl": prefix + "/figure-1.png", "sourceUrl": item["sourceUrl"] + "/figure-1",
                            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}],
                "issues": ["Some source material is unavailable."] if status != "ready" else []}

    def run_preparation(self, ids=None):
        result = self.client.start(ids or ["one"])
        self.assertEqual(result["status"], "running")
        self.client._thread.join(timeout=5)
        self.assertFalse(self.client._thread.is_alive())
        return self.client.status()["run"]

    def protected_snapshot(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            return {table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                    for table in ("collection_candidates", "collection_aliases", "candidate_sources",
                                  "acquisition_runs", "paper_state", "published_cards")}

    def test_ready_persists_without_granting_review_or_mutating_existing_records(self):
        before = self.protected_snapshot()
        result = self.run_preparation()
        self.assertEqual((result["status"], result["processed"], result["ready"]), ("completed", 1, 1))
        document = self.client.get("one")
        self.assertEqual((document["status"], document["generationStatus"], document["reviewStatus"]),
                         ("ready", "waiting", "unreviewed"))
        self.assertEqual(self.client.asset_root, (self.directory / "test-assets").resolve())
        self.assertEqual(self.prepare.call_args.kwargs["cached_document"]["sections"], self.source_document["sections"])
        self.assertEqual(self.client.input("one")["candidateId"], "one")
        self.assertNotIn("sources", self.client.summaries()["one"])
        self.assertEqual(self.protected_snapshot(), before)
        reopened = preparation.Preparation(self.db_path, self.acquisition)
        self.clients.append(reopened)
        self.assertEqual(reopened.get("one"), document)
        self.assertEqual(reopened.status()["counts"], {"ready": 1, "partial": 0, "failed": 0})

    def test_ready_cache_reuses_files_but_rechecks_integrity(self):
        self.run_preparation()
        first = self.client.get("one")
        self.run_preparation()
        self.assertEqual(self.prepare.call_count, 1)
        self.assertEqual(self.client.get("one")["inputSha256"], first["inputSha256"])
        self.assertEqual(self.client.get("one")["reviewStatus"], "unreviewed")

    def test_partial_sources_stay_partial_and_can_be_retried(self):
        self.prepare.side_effect = lambda *args, **kwargs: self.prepared_result(*args, **kwargs, status="partial")
        run = self.run_preparation()
        self.assertEqual((run["processed"], run["partial"], run["failed"]), (1, 1, 0))
        doc = self.client.get("one")
        self.assertEqual((doc["status"], doc["generationStatus"], doc["reviewStatus"]),
                         ("partial", "needs_sources", "unreviewed"))
        self.assertEqual(self.client.input("one")["candidateId"], "one")
        self.prepare.side_effect = self.prepared_result
        self.run_preparation()
        self.assertEqual((self.prepare.call_count, self.client.get("one")["status"]), (2, "ready"))

    def test_exception_failure_is_persistent_and_explicit_retry_recovers(self):
        self.prepare.side_effect = OSError("fixture unavailable")
        run = self.run_preparation()
        self.assertEqual((run["status"], run["failed"]), ("failed", 1))
        doc = self.client.get("one")
        self.assertEqual((doc["status"], doc["generationStatus"], doc["reviewStatus"]),
                         ("failed", "needs_sources", "unreviewed"))
        self.assertIsNone(doc["inputUrl"])
        with self.assertRaises(ValueError):
            self.client.input("one")
        self.prepare.side_effect = self.prepared_result
        self.run_preparation()
        self.assertEqual(self.client.get("one")["status"], "ready")

    def test_failed_result_does_not_become_ready(self):
        self.prepare.side_effect = lambda *args, **kwargs: self.prepared_result(*args, **kwargs, status="failed")
        run = self.run_preparation()
        self.assertEqual((run["status"], run["failed"]), ("failed", 1))
        self.assertEqual(self.client.get("one")["generationStatus"], "needs_sources")
        self.assertEqual(self.client.get("one")["reviewStatus"], "unreviewed")

    def test_completed_mixed_run_reports_aggregate_results_instead_of_last_failure(self):
        ids = ["one", "two", "three", "four", "five", "six"]
        for index, identifier in enumerate(ids[1:], start=2):
            self.add_candidate(paper(identifier, doi=f"10.1234/{identifier}", pmid=str(120 + index), pmcid=f"PMC{120 + index}"))
        before = self.protected_snapshot()

        def mixed(item, *args, **kwargs):
            if item["id"] in ids[3:]:
                raise OSError("fixture source unavailable")
            return self.prepared_result(item, *args, **kwargs, status="partial")

        self.prepare.side_effect = mixed
        run = self.run_preparation(ids)
        self.assertEqual((run["status"], run["ready"], run["partial"], run["failed"]), ("completed", 0, 3, 3))
        self.assertEqual(run["stage"], "자료 준비 처리 종료 · 준비됨 0편 · 일부 자료 3편 · 실패 3편")
        self.assertIsNone(run["currentId"])
        self.assertEqual(self.protected_snapshot(), before)
        self.assertTrue(all(document["reviewStatus"] == "unreviewed" for document in self.client.summaries().values()))

    def test_input_and_asset_corruption_block_download_and_trigger_rebuild(self):
        for filename in ("input.json", "figure-1.png"):
            with self.subTest(filename=filename):
                self.run_preparation()
                path = self.client.asset_root / "one" / filename
                original = path.read_bytes()
                path.write_bytes(b"X" + original[1:])
                doc = self.client.get("one")
                self.assertEqual((doc["status"], doc["generationStatus"]), ("partial", "needs_sources"))
                self.assertIsNone(doc["inputUrl"])
                self.assertEqual(self.client.summaries()["one"]["status"], "partial")
                self.assertEqual(self.client.status()["counts"], {"ready": 0, "partial": 1, "failed": 0})
                with self.assertRaises(ValueError):
                    self.client.input("one")
                calls = self.prepare.call_count
                self.run_preparation()
                self.assertEqual(self.prepare.call_count, calls + 1)
                self.assertEqual(self.client.get("one")["status"], "ready")

    def test_rejects_duplicate_invalid_unknown_and_ineligible_ids_without_fetch(self):
        for ids in (None, [], "one", [1], ["one", "one"], ["../one"], [str(value) for value in range(25)]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.client.start(ids)
        with self.assertRaises(KeyError):
            self.client.start(["missing"])
        for kind in ("Preprint", "Editorial"):
            self.add_candidate(paper(kind.lower(), doi="", pmid="", pmcid="", publicationTypes=[kind]))
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.client.start([kind.lower()])
        self.assertIsNone(self.client.get("one"))
        self.assertIsNone(self.client.status()["run"])
        self.assertEqual(self.prepare.call_count, 0)

    def test_review_article_is_eligible(self):
        self.add_candidate(paper("review", doi="", pmid="", pmcid="", publicationTypes=["Review"]))
        self.assertEqual(self.run_preparation(["review"])["ready"], 1)

    def test_cross_instance_lock_preserves_live_worker_and_stage(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def delayed(*args, **kwargs):
            kwargs["progress"]("보충자료 준비 중")
            entered.set()
            release.wait(timeout=3)
            return self.prepared_result(*args, **kwargs)

        self.prepare.side_effect = delayed
        self.client.start(["one"])
        self.assertTrue(entered.wait(timeout=2))
        second = preparation.Preparation(self.db_path, self.acquisition)
        self.clients.append(second)
        self.assertEqual(second.status()["run"]["status"], "running")
        self.assertEqual(second.get("one")["stage"], "보충자료 준비 중")
        with self.assertRaises(RuntimeError):
            second.start(["one"])
        release.set()
        self.client._thread.join(timeout=5)
        self.assertEqual(second.status()["run"]["status"], "completed")

    def test_restart_interrupts_abandoned_run_and_preparing_document(self):
        self.run_preparation()
        run = self.client.status()["run"]
        doc = self.client.get("one")
        run.update(status="running", finishedAt=None)
        doc.update(status="preparing", generationStatus="not_started")
        with closing(sqlite3.connect(self.db_path)) as db, db:
            preparation.Preparation._save_run(db, run)
            preparation.Preparation._save_document(db, "one", doc)
        restarted = preparation.Preparation(self.db_path, self.acquisition)
        self.clients.append(restarted)
        self.assertEqual(restarted.status()["run"]["status"], "interrupted")
        self.assertEqual((restarted.get("one")["status"], restarted.get("one")["generationStatus"]),
                         ("failed", "needs_sources"))
        self.assertEqual(restarted.get("one")["reviewStatus"], "unreviewed")

    def test_merged_candidate_requires_repreparation_and_rejects_alias_duplicates(self):
        self.run_preparation()
        self.add_candidate(paper("survivor"))
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("INSERT INTO collection_aliases VALUES ('candidate:one', 'survivor')")
            db.execute("DELETE FROM collection_candidates WHERE id='one'")
        doc = self.client.get("one")
        self.assertEqual((doc["candidateId"], doc["status"], doc["generationStatus"]),
                         ("survivor", "partial", "needs_sources"))
        self.assertIsNone(doc["inputUrl"])
        self.assertEqual(set(self.client.summaries()), {"survivor"})
        with self.assertRaises(ValueError):
            self.client.start(["one", "survivor"])
        self.run_preparation(["one"])
        self.assertEqual(self.prepare.call_count, 2)
        self.assertEqual(self.client.get("one")["status"], "ready")
        self.assertEqual(self.client.input("one")["candidateId"], "survivor")

    def test_prepared_text_reader_is_read_only_and_checks_input_integrity(self):
        before = self.protected_snapshot()
        self.run_preparation()
        document = self.client.text_document("one")
        self.assertEqual((document["status"], document["format"]), ("fulltext", "prepared"))
        self.assertEqual(document["sections"][0]["heading"], "Results")
        self.assertIn("아직", document["reason"])
        self.assertEqual(self.protected_snapshot(), before)
        (self.client.asset_root / "one" / "input.json").write_bytes(b"corrupted")
        self.assertIsNone(self.client.text_document("one"))

    def test_wrong_identity_or_remote_asset_cannot_become_ready(self):
        for change in ("identity", "asset_url"):
            def malformed(*args, **kwargs):
                result = self.prepared_result(*args, **kwargs)
                if change == "identity":
                    result["package"]["candidateId"] = "wrong"
                else:
                    result["assets"][0]["localUrl"] = "https://example.org/figure.png"
                return result

            with self.subTest(change=change):
                self.prepare.side_effect = malformed
                self.run_preparation()
                doc = self.client.get("one")
                self.assertEqual((doc["status"], doc["reviewStatus"]), ("failed", "unreviewed"))
                self.assertIsNone(doc["inputUrl"])


if __name__ == "__main__":
    unittest.main()
