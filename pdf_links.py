"""On-demand, read-only matching of local Zotero PDFs to a work's DOI list."""
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from pypdf import PdfReader

PDF_ROOT = Path.home() / 'Dropbox' / 'Zotero_PDF'
SCAN_LOCK = threading.Lock()
DOI = re.compile(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', re.I)


def normalize(text):
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', text).lower())


def inspect_pdf(path):
    data = path.read_bytes()
    if not data.startswith(b'%PDF-'):
        raise ValueError('PDF 형식이 아닙니다.')
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted or not reader.pages:
        raise ValueError('암호화되었거나 페이지를 읽을 수 없습니다.')
    text = reader.pages[0].extract_text() or ''
    # A cited DOI in the bibliography must not identify this article.
    text = re.split(r'\b(?:REFERENCES|References|Bibliography)\b', text)[0]
    if not text.strip():
        raise ValueError('첫 페이지에서 텍스트를 읽지 못했습니다.')
    stat = path.stat()
    return {'path': str(path.resolve()), 'name': path.name,
            'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'mtimeNs': stat.st_mtime_ns, 'pages': len(reader.pages),
            'text': text, 'dois': {m.lower().rstrip('.,;:)') for m in DOI.findall(text)}}


def match_paper(paper, files, incomplete=False):
    title = normalize(paper['title'])
    candidates = []
    for item in files:
        header = re.split(r'\babstract\b', item['text'][:2200], flags=re.I)[0]
        title_match = bool(title) and title in normalize(header)
        doi_match = paper['doi'].lower() in item['dois']
        similar_name = SequenceMatcher(None, title, normalize(item['name'])).ratio() >= .72
        if not (title_match or doi_match or similar_name):
            continue
        candidate = {k: v for k, v in item.items() if k not in ('text', 'dois')}
        candidate['exact'] = title_match and doi_match
        candidate['basis'] = ('첫 페이지 DOI·제목 일치' if candidate['exact'] else
                              '제목은 일치하지만 첫 페이지에서 해당 DOI를 확인하지 못했습니다.' if title_match else
                              'DOI는 일치하지만 첫 페이지 제목을 확인하지 못했습니다.' if doi_match else
                              '파일명이 비슷하지만 본문 제목·DOI를 확인하지 못했습니다.')
        candidates.append(candidate)
    # Identical copies are one document; distinct versions require confirmation.
    unique = {}
    for candidate in candidates:
        unique.setdefault(candidate['sha256'], candidate)
    candidates = list(unique.values())
    if len(candidates) == 1 and candidates[0]['exact']:
        return {'status': 'linked', 'reason': candidates[0]['basis'], 'candidates': candidates}
    if candidates:
        return {'status': 'review', 'reason': '서로 다른 PDF 후보가 여러 개입니다. 사용할 판본을 확인하세요.' if len(candidates) > 1 else candidates[0]['basis'], 'candidates': candidates}
    return {'status': 'review' if incomplete else 'missing',
            'reason': '읽지 못한 파일이 있어 확인이 필요합니다.' if incomplete else '검사한 폴더에서 일치하는 PDF를 찾지 못했습니다.',
            'candidates': []}


def connection(db_path):
    db = sqlite3.connect(db_path, timeout=10)
    db.execute('CREATE TABLE IF NOT EXISTS workflow_pdf_links (workflow_id TEXT PRIMARY KEY, data TEXT NOT NULL)')
    return db


def save_report(db_path, workflow_id, report):
    with connection(db_path) as db:
        db.execute('INSERT OR REPLACE INTO workflow_pdf_links VALUES (?, ?)',
                   (workflow_id, json.dumps(report, ensure_ascii=False)))
    db.close()


def load_report(db_path, workflow_id):
    with connection(db_path) as db:
        row = db.execute('SELECT data FROM workflow_pdf_links WHERE workflow_id=?', (workflow_id,)).fetchone()
    db.close()
    report = json.loads(row[0]) if row else {'folder': str(PDF_ROOT), 'papers': {}, 'errors': []}
    for entry in report['papers'].values():
        if entry['status'] == 'linked':
            selected = entry['candidates'][entry.get('selected', 0)]
            try:
                stat = Path(selected['path']).stat()
                valid = stat.st_size == selected['bytes'] and stat.st_mtime_ns == selected['mtimeNs']
            except OSError:
                valid = False
            if not valid:
                entry.update(status='review', reason='원본이 이동·변경되었습니다. 다시 검사하세요.')
    return report


def scan(db_path, record, folder=None):
    folder = Path(folder) if folder else PDF_ROOT
    if not folder.is_dir():
        raise ValueError('PDF 폴더를 찾지 못했습니다. Dropbox 경로를 확인하세요.')
    if not SCAN_LOCK.acquire(blocking=False):
        raise RuntimeError('다른 PDF 검사가 진행 중입니다.')
    try:
        files, errors = [], []
        def walk_error(error):
            errors.append({'name': str(error.filename), 'reason': '폴더 접근 실패'})
        for root, dirs, names in os.walk(folder, onerror=walk_error):
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            for name in sorted(names):
                path = Path(root) / name
                if path.suffix.lower() != '.pdf' or not path.resolve().is_relative_to(folder.resolve()):
                    continue
                try:
                    files.append(inspect_pdf(path))
                except Exception as error:
                    errors.append({'name': name, 'reason': 'PDF 읽기 실패: ' + type(error).__name__})
        report = {'folder': str(folder), 'scannedAt': datetime.now(timezone.utc).isoformat(),
                  'fileCount': len(files), 'errors': errors,
                  'papers': {p['doi']: match_paper(p, files, bool(errors)) for p in record['papers']}}
        previous = load_report(db_path, record['id'])
        for doi, entry in report['papers'].items():
            old = previous['papers'].get(doi, {})
            if old.get('status') == 'linked' and 'selected' in old:
                digest = old['candidates'][old['selected']]['sha256']
                for index, candidate in enumerate(entry['candidates']):
                    if candidate['sha256'] == digest:
                        entry.update(status='linked', selected=index, reason='사용자가 확인한 동일 PDF · 연결 유지')
        save_report(db_path, record['id'], report)
        return report
    finally:
        SCAN_LOCK.release()


def candidate_file(db_path, workflow_id, doi, index):
    report = load_report(db_path, workflow_id)
    entry = report['papers'].get(doi)
    if not entry or type(index) is not int or index < 0 or index >= len(entry['candidates']):
        raise ValueError('등록된 PDF 후보가 아닙니다.')
    candidate = entry['candidates'][index]
    path = Path(candidate['path'])
    if not path.resolve().is_relative_to(Path(report['folder']).resolve()):
        raise ValueError('검사한 폴더의 PDF가 아닙니다.')
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != candidate['sha256']:
        raise ValueError('파일이 이동·변경되었습니다. 다시 검사하세요.')
    return path


def confirm(db_path, workflow_id, doi, index):
    candidate_file(db_path, workflow_id, doi, index)
    report = load_report(db_path, workflow_id)
    report['papers'][doi].update(status='linked', selected=index, reason='사용자가 PDF를 확인하고 연결함')
    save_report(db_path, workflow_id, report)
    return report
