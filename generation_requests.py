"""Durable requests; the HTTP server dispatches explicitly submitted work to Codex."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pdf_links
from workflow import ROOT, load_workflows, source_file


def targets(papers, db_path):
    result = []
    for record in load_workflows().values():
        source = source_file(record)
        if source:
            result.append({'key': 'source:' + record['id'], 'title': record['source']['title'],
                           'origin': record['name'], 'groupId': record['id'], 'groupName': record['name'],
                           'section': '제공 논문', 'path': str(source)})
        report = pdf_links.load_report(db_path, record['id'])
        for paper in record['papers']:
            entry = report['papers'].get(paper['doi'])
            if entry and entry['status'] == 'linked':
                result.append({'key': 'linked:' + record['id'] + ':' + paper['doi'],
                               'title': paper['title'], 'origin': record['name'],
                               'groupId': record['id'], 'groupName': record['name'], 'section': '관련 논문',
                               'path': entry['candidates'][entry.get('selected', 0)]['path'],
                               'workflowId': record['id'], 'doi': paper['doi'],
                               'index': entry.get('selected', 0)})
    for paper in papers.values():
        url = paper['metadata'].get('pdfUrl', '')
        if url.startswith(('/reference/', '/assets/')):
            base = ROOT / 'public' if url.startswith('/assets/') else ROOT
            path = (base / url.lstrip('/')).resolve()
            if path.is_relative_to(base.resolve()) and path.is_file():
                result.append({'key': 'library:' + paper['id'], 'title': paper['metadata']['title'],
                               'origin': '기존 작성 사례', 'groupId': 'existing-examples',
                               'groupName': '기존 작성 사례 · 재생성', 'section': '기존 작성 논문', 'path': str(path)})
    return result


def connect(db_path):
    db = sqlite3.connect(db_path)
    db.execute('''CREATE TABLE IF NOT EXISTS generation_requests (
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL, target_key TEXT NOT NULL,
        sha256 TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(kind,target_key,sha256))''')
    return db


def list_requests(db_path):
    with connect(db_path) as db:
        result = [dict(json.loads(row[1]), id=row[0]) for row in
                  db.execute('SELECT id,data FROM generation_requests ORDER BY id DESC')]
    db.close()
    return result


def create_requests(db_path, papers, kind, keys):
    if kind not in ('summary', 'analysis') or not isinstance(keys, list) or not 1 <= len(keys) <= 30 or any(not isinstance(k, str) for k in keys):
        raise ValueError('생성 종류와 논문을 선택하세요.')
    available = {item['key']: item for item in targets(papers, db_path)}
    pending = []
    for key in dict.fromkeys(keys):
        if key not in available:
            raise ValueError('PDF가 연결된 논문을 선택하세요.')
        item = available[key]
        path = pdf_links.candidate_file(db_path, item['workflowId'], item['doi'], item['index']) if 'workflowId' in item else Path(item['path'])
        pending.append({**item, 'kind': kind, 'status': 'requested',
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'requestedAt': datetime.now(timezone.utc).isoformat()})
    added = 0
    with connect(db_path) as db:
        for item in pending:
            added += db.execute('INSERT OR IGNORE INTO generation_requests(kind,target_key,sha256,data) VALUES (?,?,?,?)',
                                (kind,item['key'],item['sha256'],json.dumps(item,ensure_ascii=False))).rowcount
    db.close()
    return {'added': added, 'existing': len(pending)-added, 'requests': list_requests(db_path)}
