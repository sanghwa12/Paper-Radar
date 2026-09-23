"""Selected imports must never merge existing reading candidates or retain a partial round."""
import json
import shutil
import sqlite3
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector import AREAS, Collector


class SelectionImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).parent / ("selection-import-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.client = Collector(self.directory / "test.sqlite3", {"old": {"metadata": {"doi": "10.1234/library"}}})
        self.records = [{"area": area["name"], "record": {
            "source": "MED", "id": str(1000 + index), "doi": f"10.1234/new-{index}",
            "title": f"Selected paper {index}", "firstPublicationDate": "2026-09-01",
            "abstractText": "A test abstract.", "pubTypeList": {"pubType": ["Research Article"]}}}
            for index, area in enumerate(AREAS)]
        with self.client._db() as db:
            self.client._store_candidate(db, {**self.records[0]["record"], "id": "500", "doi": "10.1234/existing"}, AREAS[0]["name"], "old-run")
            db.execute("CREATE TABLE preserved_notes (value TEXT)")
            db.execute("INSERT INTO preserved_notes VALUES ('keep my notes')")
        self.before = self.snapshot()

    def tearDown(self):
        self.assertTrue(self.directory.resolve().is_relative_to(Path(__file__).parent.resolve()))
        shutil.rmtree(self.directory)

    def snapshot(self):
        with self.client._db() as db:
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {table: [tuple(row) for row in db.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
                    for table in tables}

    def run_import(self):
        return self.client.import_selection_round(self.records, "2026-08-25", "2026-09-23", "20260923-01")

    def test_only_six_added_and_old_rows_unchanged_without_network(self):
        with patch.object(self.client, "_fetch_page", side_effect=AssertionError("network forbidden")):
            result = self.run_import()
        self.assertEqual(len(result["items"]), 6)
        self.assertEqual(result["run"]["mode"], "selected_round")
        self.assertEqual((result["run"]["added"], result["run"]["updated"]), (6, 0))
        self.assertEqual(len(self.client.candidates()), 7)
        after = self.snapshot()
        for table, rows in self.before.items():
            self.assertEqual(after[table][:len(rows)], rows)
        snapshot = self.snapshot()
        with self.assertRaisesRegex(ValueError, "이미 등록"):
            self.run_import()
        self.assertEqual(self.snapshot(), snapshot)

    def test_existing_alias_in_last_item_prevents_all_writes(self):
        self.records[-1]["record"]["doi"] = "https://doi.org/10.1234/EXISTING"
        with self.assertRaisesRegex(ValueError, "기존 후보"):
            self.run_import()
        self.assertEqual(self.snapshot(), self.before)

    def test_partial_insert_failure_rolls_back_and_releases_lock(self):
        original = self.client._store_candidate
        calls = 0
        def fail_fourth(*args):
            nonlocal calls
            calls += 1
            if calls == 4:
                raise sqlite3.OperationalError("simulated failed write")
            return original(*args)
        with patch.object(self.client, "_store_candidate", side_effect=fail_fourth):
            with self.assertRaises(sqlite3.OperationalError):
                self.run_import()
        self.assertEqual(self.snapshot(), self.before)
        self.assertEqual(self.run_import()["run"]["added"], 6)

    def test_duplicate_library_review_preprint_dates_and_areas_rejected(self):
        original = json.loads(json.dumps(self.records))
        mutations = [
            lambda: self.records[-1]["record"].update(doi="10.1234/new-0"),
            lambda: self.records[-1]["record"].update(doi="10.1234/library"),
            lambda: self.records[-1]["record"].update(pubTypeList={"pubType": ["Review"]}),
            lambda: self.records[-1]["record"].update(source="PPR"),
            lambda: self.records[-1]["record"].update(firstPublicationDate="2026-08-01"),
            lambda: self.records[-1].update(area=AREAS[0]["name"]),
        ]
        for mutate in mutations:
            self.records = json.loads(json.dumps(original))
            mutate()
            with self.assertRaises(ValueError):
                self.run_import()
            self.assertEqual(self.snapshot(), self.before)

    def test_busy_collector_blocks_import(self):
        handle = self.client._acquire_worker_lock()
        try:
            with self.assertRaises(RuntimeError):
                self.run_import()
            self.assertEqual(self.snapshot(), self.before)
        finally:
            self.client._release_worker_lock(handle)


if __name__ == "__main__":
    unittest.main()
