"""Paper Radar: local server, durable reading state, and original-material preparation."""
import argparse
import json
import mimetypes
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from workflow import load_workflows, public_workflows, source_file
import pdf_links
import generation_requests
import codex_generation


ROOT = Path(__file__).resolve().parent


def load_papers():
    papers = [json.loads(path.read_text(encoding="utf-8"))
              for path in sorted((ROOT / "data" / "papers").glob("*.json"))]
    return {paper["id"]: paper for paper in papers}


@contextmanager
def connect(db_path):
    db = sqlite3.connect(db_path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS paper_state (
            paper_id TEXT PRIMARY KEY, is_read INTEGER NOT NULL DEFAULT 0,
            saved INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '')""")


def read_state(db, paper_id):
    row = db.execute("SELECT * FROM paper_state WHERE paper_id=?", (paper_id,)).fetchone()
    return {"read": bool(row["is_read"]) if row else False,
            "saved": bool(row["saved"]) if row else False,
            "notes": row["notes"] if row else "",
            "updatedAt": row["updated_at"] if row else ""}


class Handler(BaseHTTPRequestHandler):
    server_version = "PaperRadar/1.0"

    def json_response(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path in ('/api/papers','/api/generation-requests'):
            self.server.papers = {**load_papers(), **codex_generation.completed_papers(self.server.db_path)}
        if path == '/api/generation-requests':
            return self.json_response(200, {'targets': [{k:v for k,v in t.items() if k in ('key','title','origin','groupId','groupName','section')} for t in generation_requests.targets(self.server.papers,self.server.db_path)], 'requests': generation_requests.list_requests(self.server.db_path)})
        if path == "/api/workflows":
            records = public_workflows(self.server.papers)
            for record in records:
                record['pdfLinks'] = pdf_links.load_report(self.server.db_path, record['id'])
            return self.json_response(200, {"workflows": records})
        if path == "/api/papers":
            with connect(self.server.db_path) as db:
                papers = [{**paper, "state": read_state(db, key)}
                          for key, paper in self.server.papers.items()]
            return self.json_response(200, {"papers": papers})
        if path == "/api/health":
            return self.json_response(200, {"status": "ok", "papers": len(self.server.papers)})
        generated_asset = re.fullmatch(r'/api/generated/(\d+)/(source\.pdf|page-(\d+)\.png|figure-\d+\.png)',path)
        workflow_source = re.fullmatch(r"/api/workflows/([a-z0-9-]+)/source\.pdf", path)
        linked_pdf = re.fullmatch(r"/api/workflows/([a-z0-9-]+)/pdf/(\d+)/(\d+)", path)
        if generated_asset:
            item = next((r for r in generation_requests.list_requests(self.server.db_path) if r['id']==int(generated_asset[1]) and r['status']=='complete'),None)
            if not item:
                return self.json_response(404,{'error':'완료된 결과가 없습니다.'})
            import hashlib
            original = Path(item['path'])
            if not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest()!=item['sha256']:
                return self.json_response(409,{'error':'원문이 변경되거나 이동되었습니다.'})
            file_path = original if generated_asset[2]=='source.pdf' else ROOT/'.runtime'/'generation'/generated_asset[1]/generated_asset[2]
            allowed_root = file_path.parent
        elif linked_pdf:
            try:
                record = load_workflows()[linked_pdf[1]]
                doi = record['papers'][int(linked_pdf[2])]['doi']
                file_path = pdf_links.candidate_file(self.server.db_path, record['id'], doi, int(linked_pdf[3]))
                allowed_root = file_path.parent
            except (KeyError, IndexError, ValueError, OSError):
                return self.json_response(404, {"error": "PDF 연결을 확인할 수 없습니다. 다시 검사하세요."})
        elif workflow_source:
            record = load_workflows().get(workflow_source[1])
            file_path = source_file(record) if record else None
            if file_path is None:
                return self.json_response(404, {"error": "등록된 원본 파일을 확인하지 못했습니다."})
            allowed_root = file_path.parent
        elif path in ("/", "/index.html", "/app.js", "/workflow.js", "/generators.js", "/generated-results.js", "/styles.css"):
            file_path = ROOT / "public" / ("index.html" if path == "/" else path[1:])
            allowed_root = ROOT / "public"
        elif path.startswith("/exports/choi-2025-aiml-special-issue/"):
            file_path = ROOT / path[1:]
            allowed_root = ROOT / "exports" / "choi-2025-aiml-special-issue"
        elif path.startswith("/assets/"):
            file_path = ROOT / "public" / path[1:]
            allowed_root = ROOT / "public" / "assets"
        elif path.startswith("/reference/"):
            file_path = ROOT / path[1:]
            allowed_root = ROOT / "reference"
        else:
            return self.json_response(404, {"error": "자료를 찾을 수 없습니다."})
        file_path = file_path.resolve()
        if not file_path.is_relative_to(allowed_root.resolve()) or not file_path.is_file():
            return self.json_response(404, {"error": "자료를 찾을 수 없습니다."})
        size = file_path.stat().st_size
        start, end, status = 0, size - 1, 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            if not match or not any(match.groups()):
                return self.invalid_range(size)
            first, last = match.groups()
            start = int(first) if first else max(0, size - int(last))
            end = min(int(last), size - 1) if first and last else size - 1
            if start >= size or start > end:
                return self.invalid_range(size)
            status = 206
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        prepared_attachment = path.startswith("/assets/prepared/") and file_path.suffix.lower() not in (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp")
        if prepared_attachment:
            content_type = "application/octet-stream"
        elif file_path.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-cache")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if file_path.suffix == ".pdf":
            self.send_header("Content-Disposition", "inline")
        elif prepared_attachment:
            self.send_header("Content-Disposition", "attachment")
        self.end_headers()
        if self.command != "HEAD":
            try:
                with file_path.open("rb") as source:
                    source.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = source.read(min(65536, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    def invalid_range(self, size):
        self.send_response(416)
        self.send_header("Content-Range", f"bytes */{size}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def local_write_allowed(self):
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        valid_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        return host in valid_hosts and (not origin or origin == f"http://{host}")

    def do_POST(self):
        if urlsplit(self.path).path == '/api/generation-requests':
            if not self.local_write_allowed():
                return self.json_response(403, {'error': '로컬 앱에서만 요청할 수 있습니다.'})
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 16000 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('요청 형식을 확인하세요.')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data,dict) or set(data) != {'kind','keys'}:
                    raise ValueError('요청 형식을 확인하세요.')
                result = generation_requests.create_requests(self.server.db_path,self.server.papers,data['kind'],data['keys'])
                if self.server.generator:
                    self.server.generator.start(data['keys'],data['kind'])
                    result['requests'] = generation_requests.list_requests(self.server.db_path)
                return self.json_response(200,result)
            except (ValueError,UnicodeDecodeError) as error:
                return self.json_response(400,{'error':str(error)})
            except (OSError,sqlite3.Error):
                return self.json_response(500,{'error':'요청을 저장하지 못했습니다. PDF 연결을 확인하세요.'})
        match = re.fullmatch(r"/api/workflows/([a-z0-9-]+)/(scan|confirm)", urlsplit(self.path).path)
        if not match:
            return self.json_response(404, {"error": "요청을 찾을 수 없습니다."})
        if not self.local_write_allowed():
            return self.json_response(403, {"error": "로컬 앱에서만 실행할 수 있습니다."})
        try:
            record = load_workflows()[match[1]]
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096 or self.headers.get_content_type() != 'application/json':
                raise ValueError('요청 형식을 확인하세요.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('요청 형식을 확인하세요.')
            if match[2] == 'scan':
                if data:
                    raise ValueError('등록된 폴더만 검사할 수 있습니다.')
                result = pdf_links.scan(self.server.db_path, record)
            else:
                if set(data) != {'doi', 'index'} or not isinstance(data['doi'], str) or data['doi'] not in {p['doi'] for p in record['papers']}:
                    raise ValueError('작업에 등록된 논문을 선택하세요.')
                result = pdf_links.confirm(self.server.db_path, record['id'], data['doi'], data['index'])
            return self.json_response(200, result)
        except KeyError:
            return self.json_response(404, {"error": "작업을 찾을 수 없습니다."})
        except (ValueError, UnicodeDecodeError) as error:
            return self.json_response(400, {"error": str(error)})
        except RuntimeError as error:
            return self.json_response(409, {"error": str(error)})
        except (OSError, sqlite3.Error):
            return self.json_response(500, {"error": "PDF 연결 정보를 읽거나 저장하지 못했습니다."})

    def do_PATCH(self):
        if not self.local_write_allowed():
            return self.json_response(403, {"error": "로컬 앱에서만 저장할 수 있습니다."})
        paper_id = unquote(urlsplit(self.path).path).removeprefix("/api/state/")
        if not self.path.startswith("/api/state/") or paper_id not in self.server.papers:
            return self.json_response(404, {"error": "논문을 찾을 수 없습니다."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 500000:
                raise ValueError("invalid length")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("invalid content type")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict) or not data or set(data) - {"read", "saved", "notes"}:
                raise ValueError("invalid fields")
            for field in ("read", "saved"):
                if field in data and type(data[field]) is not bool:
                    raise ValueError("invalid boolean")
            if "notes" in data and (not isinstance(data["notes"], str) or len(data["notes"]) > 100000):
                raise ValueError("invalid notes")
        except (ValueError, UnicodeDecodeError):
            return self.json_response(400, {"error": "올바르지 않은 저장 요청입니다."})
        fields = {"read": "is_read", "saved": "saved", "notes": "notes"}
        updated_at = datetime.now(timezone.utc).isoformat()
        try:
            with connect(self.server.db_path) as db:
                db.execute("INSERT OR IGNORE INTO paper_state(paper_id) VALUES (?)", (paper_id,))
                assignments = ", ".join(f"{fields[key]}=?" for key in data)
                db.execute(f"UPDATE paper_state SET {assignments}, updated_at=? WHERE paper_id=?",
                           [*data.values(), updated_at, paper_id])
                state = read_state(db, paper_id)
            return self.json_response(200, {"state": state})
        except sqlite3.Error:
            return self.json_response(500, {"error": "DB 저장에 실패했습니다. 다시 시도해 주세요."})


def create_server(port=8765, db_path=None, enable_generation=False):
    db_path = Path(db_path) if db_path else ROOT / "data" / "paper-radar.sqlite3"
    initialize(db_path)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.db_path = db_path
    server.papers = load_papers()
    server.generator = codex_generation.Worker(db_path) if enable_generation else None
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paper Radar 로컬 앱")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, help="별도 DB 경로 (기본: data/paper-radar.sqlite3)")
    args = parser.parse_args()
    try:
        server = create_server(args.port, args.db, enable_generation=True)
    except OSError as error:
        parser.exit(1, f"서버를 시작하지 못했습니다: {error}\n다른 포트: python server.py --port 8766\n")
    print(f"Paper Radar  http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Database: {server.db_path}\nStop: Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
