"""Local work records; PDF acquisition and scientific review are separate steps."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_workflows():
    return {record['id']: record for record in
            (json.loads(path.read_text(encoding='utf-8'))
             for path in sorted((ROOT / 'data' / 'workflows').glob('*.json')))}


def source_file(record):
    path = Path(record['source']['path'])
    if not path.is_file():
        return None
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['source']['sha256']:
        return None
    return path


def public_workflows(papers):
    result = []
    for record in load_workflows().values():
        record['source']['available'] = source_file(record) is not None
        record['source']['url'] = '/api/workflows/' + record['id'] + '/source.pdf'
        for item in record['papers']:
            for key in ('summaryPaperId', 'analysisPaperId'):
                if item.get(key) not in papers:
                    item[key] = None
        result.append(record)
    return result
