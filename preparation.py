"""Durable original-material preparation, separate from writing and scientific review."""
import errno
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from acquisition import Acquisition
from classification import classify_candidate
from collector import now
from sourcepack import prepare

ROOT = Path(__file__).resolve().parent
ID_PATTERN = r"[A-Za-z0-9_-]{1,80}"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Preparation:
    def __init__(self, db_path, acquisition, asset_root=None):
        self.db_path = Path(db_path).resolve()
        self.acquisition = acquisition
        self.asset_root = Path(asset_root or (ROOT / "public/assets/prepared" if self.db_path ==
            (ROOT / "data/paper-radar.sqlite3").resolve() else self.db_path.with_name(self.db_path.stem + "-assets"))).resolve()
        self._lock, self._thread = threading.Lock(), None
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS candidate_preparations (candidate_id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preparation_runs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)
        self._recover()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _worker_lock(self):
        handle = self.db_path.with_name(self.db_path.name + ".preparation.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if handle.seek(0, 2) == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError as error:
            handle.close()
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                return None
            raise

    def _recover(self):
        handle = self._worker_lock()
        if handle is not None:
            try:
                self._interrupt()
            finally:
                Acquisition._release_worker_lock(handle)

    def _interrupt(self):
        with self._db() as db:
            for row in db.execute("SELECT data FROM preparation_runs").fetchall():
                run = json.loads(row[0])
                if run["status"] == "running":
                    run.update(status="interrupted", finishedAt=now(), stage="자료 준비가 중단됐습니다. 다시 시도할 수 있습니다.")
                    self._save_run(db, run)
            for row in db.execute("SELECT candidate_id, data FROM candidate_preparations").fetchall():
                doc = json.loads(row[1])
                if doc["status"] == "preparing":
                    doc.update(status="failed", generationStatus="needs_sources", updatedAt=now(),
                               stage="자료 준비 중단", reason="서버 종료 등으로 준비가 중단됐습니다. 다시 시도해 주세요.")
                    self._save_document(db, row[0], doc)

    @staticmethod
    def _save_run(db, run):
        db.execute("INSERT INTO preparation_runs VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                   (run["id"], json.dumps(run, ensure_ascii=False)))

    @staticmethod
    def _save_document(db, candidate_id, doc):
        db.execute("INSERT INTO candidate_preparations VALUES (?, ?) ON CONFLICT(candidate_id) DO UPDATE SET data=excluded.data",
                   (candidate_id, json.dumps(doc, ensure_ascii=False)))

    def _documents(self, db):
        results = {}
        for row in db.execute("SELECT candidate_id, data FROM candidate_preparations"):
            doc = json.loads(row[1])
            canonical = Acquisition._canonical(db, row[0], doc)
            if not canonical:
                continue
            doc["storageId"] = row[0]
            doc["candidateId"] = canonical
            if canonical != row[0]:
                doc.update(status="partial", generationStatus="needs_sources", inputUrl=None,
                           reason="논문 식별자가 병합됐습니다. 자료를 다시 준비해 연결을 확인하세요.")
            if canonical not in results or doc.get("updatedAt", "") > results[canonical].get("updatedAt", ""):
                results[canonical] = doc
        return results

    def summaries(self):
        fields = ("status", "stage", "reason", "updatedAt", "coverage", "generationStatus", "reviewStatus", "issues")
        with self._db() as db:
            return {key: {name: doc[name] for name in fields if name in doc} for key, doc in self._documents(db).items()}

    def _find(self, candidate_id):
        if not isinstance(candidate_id, str) or not re.fullmatch(ID_PATTERN, candidate_id):
            raise KeyError(candidate_id)
        with self._db() as db:
            canonical = Acquisition._canonical(db, candidate_id)
            if not canonical:
                raise KeyError(candidate_id)
            return self._documents(db).get(canonical)

    def _input_path(self, doc):
        storage_id = doc.get("storageId", doc["candidateId"])
        if not re.fullmatch(ID_PATTERN, storage_id):
            raise ValueError("자료 경로를 확인하세요.")
        path = (self.asset_root / storage_id / "input.json").resolve()
        if not path.is_relative_to(self.asset_root):
            raise ValueError("자료 경로를 확인하세요.")
        return path

    def _read_input(self, doc):
        path = self._input_path(doc)
        if not path.is_file() or digest(path) != doc.get("inputSha256"):
            raise ValueError("입력 자료가 없거나 변경됐습니다. 자료를 다시 준비해 주세요.")
        package = json.loads(path.read_text(encoding="utf-8"))
        if package.get("candidateId") != doc["candidateId"]:
            raise ValueError("논문 식별자가 바뀌었습니다. 자료를 다시 준비해 주세요.")
        return package

    def _validate_files(self, doc):
        self._read_input(doc)
        prefix = f'/assets/prepared/{doc["candidateId"]}/'
        for asset in doc.get("assets", []):
            url = asset.get("localUrl", "")
            if not url.startswith(prefix):
                raise ValueError("확보 파일의 연결이 올바르지 않습니다.")
            path = (self.asset_root / doc["candidateId"] / url.removeprefix(prefix)).resolve()
            if not path.is_relative_to((self.asset_root / doc["candidateId"]).resolve()) or not path.is_file():
                raise ValueError("확보 파일이 없습니다. 자료를 다시 준비해 주세요.")
            if path.stat().st_size != asset.get("bytes") or digest(path) != asset.get("sha256"):
                raise ValueError("확보 파일이 변경됐습니다. 자료를 다시 준비해 주세요.")

    def get(self, candidate_id):
        doc = self._find(candidate_id)
        if doc and doc["status"] in ("ready", "partial") and doc.get("inputUrl"):
            try:
                self._validate_files(doc)
            except (OSError, ValueError) as error:
                doc.update(status="partial", generationStatus="needs_sources", inputUrl=None,
                           reason=str(error), issues=[*doc.get("issues", []), str(error)])
                with self._db() as db:
                    current = db.execute("SELECT data FROM candidate_preparations WHERE candidate_id=?",
                                         (doc["storageId"],)).fetchone()
                    # Do not overwrite a retry that started while this read was validating files.
                    if current and json.loads(current[0]).get("updatedAt") == doc.get("updatedAt"):
                        self._save_document(db, doc["storageId"], doc)
        return doc

    def input(self, candidate_id):
        doc = self.get(candidate_id)
        if not doc or not doc.get("inputUrl"):
            raise ValueError("지금 내려받을 수 있는 입력 자료가 없습니다. 자료를 다시 준비해 주세요.")
        return self._read_input(doc)

    def text_document(self, candidate_id):
        """Expose prepared body to the existing reader without rewriting acquisition records."""
        doc = self._find(candidate_id)
        if not doc or doc["status"] not in ("ready", "partial") or not doc.get("inputUrl"):
            return None
        if not any(item["kind"] == "body" and item.get("usable", 0) for item in doc.get("coverage", [])):
            return None
        try:
            package = self._read_input(doc)
        except (OSError, ValueError):
            return None
        sections = [{"heading": item["label"], "text": item["text"]} for item in package["sources"] if item["kind"] == "body"]
        if not sections:
            return None
        return {"candidateId": doc["candidateId"], "title": doc["title"], "status": "fulltext",
                "abstract": "\n\n".join(item["text"] for item in package["sources"] if item["kind"] == "abstract"),
                "sections": sections, "sectionCount": len(sections), "textLength": sum(len(s["text"]) for s in sections),
                "provider": doc.get("provider", "준비된 원자료"), "sourceUrl": doc.get("sourceUrl", ""),
                "license": doc.get("license", ""), "fetchedAt": doc.get("preparedAt", ""), "format": "prepared",
                "reason": "준비된 원자료의 본문 텍스트입니다. 내용 검토는 아직 하지 않았습니다."}

    def status(self):
        self._recover()
        with self._db() as db:
            row = db.execute("SELECT data FROM preparation_runs ORDER BY rowid DESC LIMIT 1").fetchone()
            docs = self._documents(db).values()
            counts = {state: sum(doc["status"] == state for doc in docs) for state in ("ready", "partial", "failed")}
            return {"run": json.loads(row[0]) if row else None, "counts": counts}

    def start(self, candidate_ids):
        if (not isinstance(candidate_ids, list) or not 1 <= len(candidate_ids) <= 24 or
                any(not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value) for value in candidate_ids) or
                len(set(candidate_ids)) != len(candidate_ids)):
            raise ValueError("서로 다른 논문 ID를 1~24개 지정하세요.")
        with self._lock:
            handle = self._worker_lock()
            if handle is None:
                raise RuntimeError("이미 브리핑 자료를 준비하고 있습니다.")
            try:
                self._interrupt()
                with self._db() as db:
                    ids = []
                    for candidate_id in candidate_ids:
                        canonical = Acquisition._canonical(db, candidate_id)
                        if not canonical or not re.fullmatch(ID_PATTERN, canonical):
                            raise KeyError(candidate_id)
                        paper = json.loads(db.execute("SELECT data FROM collection_candidates WHERE id=?", (canonical,)).fetchone()[0])
                        if classify_candidate(paper)["kind"] not in ("original", "review"):
                            raise ValueError("원저·Review 논문의 자료를 준비할 수 있습니다.")
                        ids.append(canonical)
                    if len(set(ids)) != len(ids):
                        raise ValueError("병합된 동일 논문을 중복 지정했습니다.")
                    run = {"id": uuid.uuid4().hex, "candidateIds": ids, "status": "running", "total": len(ids),
                           "processed": 0, "ready": 0, "partial": 0, "failed": 0, "currentId": ids[0],
                           "stage": "자료 준비 대기", "startedAt": now(), "finishedAt": None}
                    self._save_run(db, run)
                snapshot = dict(run)
                self._thread = threading.Thread(target=self._work, args=(run, handle), daemon=True)
                self._thread.start()
                return snapshot
            except Exception:
                Acquisition._release_worker_lock(handle)
                raise

    def _work(self, run, handle):
        try:
            for candidate_id in run["candidateIds"]:
                with self._db() as db:
                    canonical = Acquisition._canonical(db, candidate_id)
                    if not canonical:
                        raise KeyError(candidate_id)
                    paper = json.loads(db.execute("SELECT data FROM collection_candidates WHERE id=?", (canonical,)).fetchone()[0])
                    previous = self._documents(db).get(canonical)
                run["currentId"] = canonical
                cached = False
                if previous and previous["status"] == "ready":
                    try:
                        self._validate_files(previous)
                        cached = True
                    except (OSError, ValueError):
                        pass
                doc = {"candidateId": canonical, "title": paper.get("title", ""), "status": "preparing",
                       "stage": "원자료 확인 중", "updatedAt": now(), "reviewStatus": "unreviewed",
                       "generationStatus": "not_started", "coverage": [], "assets": [], "issues": [],
                       "identifiers": {key: paper.get(key, "") for key in ("doi", "pmid", "pmcid")}}

                def progress(stage):
                    doc.update(stage=str(stage), updatedAt=now())
                    run["stage"] = str(stage)
                    with self._db() as db:
                        self._save_document(db, canonical, doc)
                        self._save_run(db, run)

                progress("확보한 자료 재사용" if cached else "원자료 확인 중")
                try:
                    if cached:
                        doc = previous
                    else:
                        directory = self.asset_root / canonical
                        directory.mkdir(parents=True, exist_ok=True)
                        result = prepare(paper, directory, f"/assets/prepared/{canonical}",
                                         cached_document=self.acquisition.get(canonical), progress=progress)
                        package = result.pop("package")
                        if package.get("candidateId") != canonical or result.get("status") not in ("ready", "partial", "failed"):
                            raise ValueError("준비 결과의 논문 또는 상태가 올바르지 않습니다.")
                        input_path = directory / "input.json"
                        pending_path = directory / "input.pending.json"
                        pending_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                        pending_path.replace(input_path)
                        doc.update(result, inputUrl=f"/api/preparation-input/{canonical}", inputSha256=digest(input_path))
                    doc.update(updatedAt=now(), stage={"ready": "자료 준비됨", "partial": "일부 자료 확인 필요", "failed": "자료 준비 실패"}[doc["status"]],
                               generationStatus="waiting" if doc["status"] == "ready" else "needs_sources", reviewStatus="unreviewed")
                    # A preparation result cannot grant scientific review or change the Library.
                    self._validate_files(doc)
                except Exception as error:
                    doc.update(status="failed", stage="자료 준비 실패", generationStatus="needs_sources", reviewStatus="unreviewed",
                               updatedAt=now(), inputUrl=None, reason=f"자료를 준비하지 못했습니다. {type(error).__name__}: {error}")
                with self._db() as db:
                    self._save_document(db, canonical, doc)
                    run[doc["status"]] += 1
                    run["processed"] += 1
                    run["stage"] = doc["stage"]
                    self._save_run(db, run)
            run.update(status="failed" if run["failed"] == run["total"] else "completed", finishedAt=now(), currentId=None,
                       stage=f"자료 준비 처리 종료 · 준비됨 {run['ready']}편 · 일부 자료 {run['partial']}편 · 실패 {run['failed']}편")
        except Exception:
            run.update(status="failed", finishedAt=now(), stage="자료 준비가 중단됐습니다. 미완료 논문은 다시 시도할 수 있습니다.")
        finally:
            try:
                with self._db() as db:
                    self._save_run(db, run)
            finally:
                Acquisition._release_worker_lock(handle)
