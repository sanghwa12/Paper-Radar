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

from collector import Collector
from acquisition import Acquisition
from cards import load_cards
from evaluation import EvaluationDataError, load_evaluation
from generation import load_runs
from generated import load_generated
from preparation import Preparation
from rounds import RoundDataError, load_rounds

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
        if path == "/api/papers":
            with connect(self.server.db_path) as db:
                papers = [{**paper, "state": read_state(db, key)}
                          for key, paper in self.server.papers.items()]
            return self.json_response(200, {"papers": papers})
        if path == "/api/health":
            return self.json_response(200, {"status": "ok", "papers": len(self.server.papers)})
        if path == "/api/rounds":
            try:
                rounds = load_rounds(self.server.collector.candidates(), self.server.preparation.summaries(), self.server.papers)
                return self.json_response(200, {"rounds": rounds})
            except (RoundDataError, sqlite3.Error) as error:
                return self.json_response(503, {"error": str(error)})
        if path == "/api/generation-pilot":
            try:
                return self.json_response(200, {"runs": load_runs()})
            except (ValueError, OSError, KeyError, TypeError):
                return self.json_response(503, {"error": "시범 생성 자료의 입력·출처·검증 기록을 확인해 주세요."})
        if path == "/api/collection":
            return self.json_response(200, self.server.collector.status())
        if path == "/api/candidates":
            summaries = self.server.acquisition.summaries()
            prepared = self.server.preparation.summaries()
            candidates = self.server.collector.candidates()
            for candidate in candidates:
                paper = self.server.papers.get(candidate["id"])
                if paper and paper.get("generationOrigin"):
                    candidate["generatedCard"] = {
                        "paperId": paper["id"], "reviewStatus": paper["briefOrigin"]["review"]["status"],
                        "publishedAt": paper["generationOrigin"]["publishedAt"],
                    }
                document = summaries.get(candidate["id"])
                candidate["preparation"] = prepared.get(candidate["id"])
                if candidate["preparation"] and (not document or document["status"] != "fulltext"):
                    material = self.server.preparation.text_document(candidate["id"])
                    if material:
                        document = {key: material[key] for key in ("status", "provider", "sourceUrl", "fetchedAt", "reason", "format", "license", "sectionCount", "textLength")}
                candidate["sourceDocument"] = document
                candidate["fullTextStatus"] = document["status"] if document else "not_retrieved"
            return self.json_response(200, {"candidates": candidates})
        if path == "/api/acquisition":
            return self.json_response(200, self.server.acquisition.status())
        if path == "/api/preparation":
            return self.json_response(200, self.server.preparation.status())
        if path.startswith(("/api/preparations/", "/api/preparation-input/")):
            prefix = "/api/preparation-input/" if path.startswith("/api/preparation-input/") else "/api/preparations/"
            candidate_id = path.removeprefix(prefix)
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", candidate_id):
                return self.json_response(404, {"error": "논문을 찾을 수 없습니다."})
            try:
                if path.startswith("/api/preparation-input/"):
                    return self.json_response(200, self.server.preparation.input(candidate_id))
                document = self.server.preparation.get(candidate_id)
                if document is None:
                    raise KeyError(candidate_id)
                return self.json_response(200, {"preparation": document})
            except KeyError:
                return self.json_response(404, {"error": "아직 준비된 자료가 없습니다."})
            except (ValueError, OSError) as error:
                return self.json_response(409, {"error": str(error)})
        if path.startswith("/api/sources/"):
            candidate_id = path.removeprefix("/api/sources/")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", candidate_id):
                return self.json_response(404, {"error": "논문을 찾을 수 없습니다."})
            try:
                document = self.server.acquisition.get(candidate_id)
                if not document or document["status"] != "fulltext":
                    document = self.server.preparation.text_document(candidate_id) or document
            except KeyError:
                document = None
            if document is None:
                return self.json_response(404, {"error": "아직 가져온 원문이 없습니다."})
            return self.json_response(200, {"source": document})
        if path == "/api/evaluation":
            try:
                return self.json_response(200, load_evaluation())
            except EvaluationDataError as error:
                return self.json_response(503, {"error": str(error)})
        if path in ("/", "/index.html", "/app.js", "/styles.css"):
            file_path = ROOT / "public" / ("index.html" if path == "/" else path[1:])
            allowed_root = ROOT / "public"
        elif path.startswith("/assets/prepared/"):
            file_path = self.server.preparation.asset_root / path.removeprefix("/assets/prepared/")
            allowed_root = self.server.preparation.asset_root
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
        if not self.local_write_allowed():
            return self.json_response(403, {"error": "로컬 앱에서만 수집할 수 있습니다."})
        path = urlsplit(self.path).path
        if path not in ("/api/collection", "/api/collection/retry", "/api/acquisition", "/api/preparation"):
            return self.json_response(404, {"error": "요청을 찾을 수 없습니다."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2048 or self.headers.get_content_type() != "application/json":
                raise ValueError("올바르지 않은 수집 요청입니다.")
            data = json.loads(self.rfile.read(length))
            if path in ("/api/acquisition", "/api/preparation"):
                if not isinstance(data, dict) or set(data) != {"candidateIds"}:
                    raise ValueError("원문을 가져올 논문을 선택해 주세요.")
                worker = self.server.preparation if path == "/api/preparation" else self.server.acquisition
                run = worker.start(data["candidateIds"])
            elif path == "/api/collection/retry":
                if not isinstance(data, dict) or set(data) != {"runId"} or not isinstance(data["runId"], str):
                    raise ValueError("다시 시도할 수집 기록을 확인해 주세요.")
                run = self.server.collector.retry(data["runId"])
            else:
                if not isinstance(data, dict) or set(data) != {"from", "to"}:
                    raise ValueError("수집할 발행일 시작과 종료를 입력해 주세요.")
                run = self.server.collector.start(data["from"], data["to"])
        except (ValueError, UnicodeDecodeError) as error:
            return self.json_response(400, {"error": str(error)})
        except RuntimeError as error:
            return self.json_response(409, {"error": str(error)})
        except KeyError:
            return self.json_response(404, {"error": "선택한 논문을 찾을 수 없습니다."})
        except sqlite3.Error:
            return self.json_response(500, {"error": "수집 기록을 저장하지 못했습니다."})
        return self.json_response(202, {"run": run})

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


def create_server(port=8765, db_path=None):
    db_path = Path(db_path) if db_path else ROOT / "data" / "paper-radar.sqlite3"
    initialize(db_path)
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.db_path = db_path
    server.papers = load_papers()
    server.papers.update(load_cards())
    server.papers.update(load_generated(existing_ids=server.papers))
    server.collector = Collector(db_path, server.papers)
    server.acquisition = Acquisition(db_path)
    server.preparation = Preparation(db_path, server.acquisition)
    return server


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paper Radar 로컬 앱")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, help="별도 DB 경로 (기본: data/paper-radar.sqlite3)")
    args = parser.parse_args()
    try:
        server = create_server(args.port, args.db)
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
