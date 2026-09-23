"""Review discovery stays independent of the existing collection and personal state."""
import http.client
import json
import sqlite3
import sys
import threading
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class ReviewRadarServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(__file__).parent / ('review-http-' + uuid.uuid4().hex)
        self.directory.mkdir()
        self.db_path = self.directory / 'state.sqlite3'
        self.quiet = patch.object(server.Handler, 'log_message', lambda *args: None)
        self.quiet.start()
        self.httpd = server.create_server(port=0, db_path=self.db_path)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        self.thread.start()
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute("INSERT INTO paper_state VALUES ('adaptiveflow-2026', 1, 1, '기존 메모', 'before')")

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.quiet.stop()
        for path in self.directory.iterdir():
            path.unlink()
        self.directory.rmdir()

    def snapshot(self):
        with closing(sqlite3.connect(self.db_path)) as db:
            return {name: db.execute('SELECT * FROM "' + name + '"').fetchall()
                    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def request(self, method, path, payload=None, origin=None, raw=None, content_type='application/json'):
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=5)
        headers = {'Content-Type': content_type}
        if origin:
            headers['Origin'] = origin
        try:
            connection.request(method, path, body=raw if raw is not None else json.dumps(payload) if payload is not None else None, headers=headers)
            response = connection.getresponse()
            return response.status, response.getheader('Content-Type'), response.read()
        finally:
            connection.close()

    def test_read_only_policy_and_search_do_not_mutate_legacy_tables(self):
        before = self.snapshot()
        policy = {'policy': {'windowYears': 3}, 'reviews': []}
        results = {'candidates': [], 'hitCount': 0}
        with patch.object(server, 'load_radar', return_value=policy), patch.object(server, 'search_reviews', return_value=results) as search:
            status, _, body = self.request('GET', '/api/review-radar')
            self.assertEqual((status, json.loads(body)), (200, policy))
            search.assert_not_called()
            payload = {'area': 'CADD·AI', 'keywords': 'binding', 'sort': 'relevance'}
            status, _, body = self.request('POST', '/api/review-radar/search', payload)
            self.assertEqual((status, json.loads(body)), (200, results))
            search.assert_called_once_with(payload)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_requests_and_cross_origin_do_not_search(self):
        with patch.object(server, 'search_reviews') as search:
            self.assertEqual(self.request('POST', '/api/review-radar/search', {}, origin='https://other.example')[0], 403)
            self.assertEqual(self.request('POST', '/api/review-radar/search', raw=b'{')[0], 400)
            self.assertEqual(self.request('POST', '/api/review-radar/search', {}, content_type='text/plain')[0], 400)
            search.assert_not_called()
        with patch.object(server, 'search_reviews', side_effect=ValueError('입력 확인')):
            self.assertEqual(self.request('POST', '/api/review-radar/search', {})[0], 400)

    def test_source_failure_is_reported_without_breaking_library(self):
        before = self.snapshot()
        with patch.object(server, 'load_radar', side_effect=server.ReviewRadarError('리뷰 확인 필요')):
            self.assertEqual(self.request('GET', '/api/review-radar')[0], 503)
        with patch.object(server, 'search_reviews', side_effect=server.ReviewRadarError('검색 응답 확인 필요')):
            status, _, body = self.request('POST', '/api/review-radar/search', {})
            self.assertEqual(status, 503)
            self.assertIn('검색 응답 확인 필요', json.loads(body)['error'])
        status, _, body = self.request('GET', '/api/papers')
        self.assertEqual(status, 200)
        original = next(p for p in json.loads(body)['papers'] if p['id'] == 'adaptiveflow-2026')
        self.assertEqual(original['state']['notes'], '기존 메모')
        self.assertEqual(self.snapshot(), before)

    def test_review_script_is_served_without_exposing_data_or_backup(self):
        status, kind, body = self.request('GET', '/review-radar.js')
        self.assertEqual(status, 200)
        self.assertEqual(kind, 'text/javascript')
        self.assertTrue(body)
        for path in ('/review_radar.py', '/data/review-radar/', '/.runtime/review-radar-start-20260923/before.sqlite3'):
            self.assertEqual(self.request('GET', path)[0], 404)


if __name__ == '__main__':
    unittest.main()
