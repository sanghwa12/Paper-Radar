"""Collect Europe PMC metadata into durable candidates; never fetch full text."""
import errno
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode
from urllib.request import Request, urlopen


API_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
PAGE_SIZE = 100
REQUEST_INTERVAL = 1.0
REQUEST_TIMEOUT = 30
DRUG_CONTEXT = 'TITLE_ABS:(drug OR ligand OR inhibitor OR therapeutic OR pharmacolog*)'
AREAS = [
    {"name": "CADD·AI", "query":
     'TITLE_ABS:("virtual screening" OR "molecular docking" OR "structure-based drug design" '
     'OR "ligand-based drug design" OR "molecular generation" OR "de novo drug design" '
     'OR "free energy perturbation") OR '
     '(TITLE_ABS:("machine learning" OR "deep learning" OR "artificial intelligence" '
     'OR "molecular dynamics") AND TITLE_ABS:("drug discovery" OR "drug design" '
     'OR ligand OR "binding affinity" OR ADMET))'},
    {"name": "Medicinal chemistry", "query":
     'TITLE_ABS:("medicinal chemistry" OR "lead optimization" OR "hit-to-lead" '
     'OR "structure-activity relationship" OR "scaffold hopping" OR bioisoster*) '
     f'AND {DRUG_CONTEXT}'},
    {"name": "Target·기전", "query":
     'TITLE_ABS:("target validation" OR "target engagement" OR "chemical probe" '
     'OR "mechanism of action" OR "binding mechanism" OR "drug resistance") '
     f'AND {DRUG_CONTEXT}'},
    {"name": "Drug modality", "query":
     'TITLE_ABS:(PROTAC* OR "molecular glue" OR "targeted protein degradation" '
     'OR "covalent inhibitor" OR "macrocyclic peptide" OR "therapeutic peptide" '
     'OR "peptide drug" OR "small molecule drug" OR "antibody-drug conjugate" '
     'OR "RNA therapeutics")'},
    {"name": "실험·평가 기술", "query":
     'TITLE_ABS:("high-throughput screening" OR "phenotypic screening" '
     'OR "biochemical assay" OR "cell-based assay" OR "target engagement assay" '
     'OR "thermal shift assay" OR "cryo-EM" OR "crystal structure") '
     f'AND {DRUG_CONTEXT}'},
    {"name": "ADME·PK/PD·개발 전환", "query":
     'TITLE_ABS:(ADME OR ADMET OR pharmacokinetic* OR "PK/PD" '
     'OR "pharmacokinetic-pharmacodynamic" OR "drug metabolism" '
     'OR "drug-induced toxicity" OR "drug safety" OR "drug exposure" '
     f'OR "translational biomarker") AND {DRUG_CONTEXT}'},
]
AREAS = [{**area, "query": f"({area['query']}) AND (SRC:MED OR SRC:PMC OR SRC:PPR)"} for area in AREAS]


def now():
    return datetime.now(timezone.utc).isoformat()


class PlainText(HTMLParser):
    block_tags = {"p", "div", "br", "title", "sec", "section", "abstract", "h1", "h2", "h3", "h4", "h5", "h6",
                  "li", "ul", "ol", "blockquote", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot",
                  "tr", "td", "th", "hr", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in self.block_tags:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in self.block_tags:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    parser = PlainText()
    parser.feed(unescape(str(value or "")))
    return " ".join("".join(parser.parts).split())


def normalize_doi(value):
    value = unquote(str(value or "").strip())
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    return value.lower() if re.fullmatch(r'10\.\d{4,9}/[^\s<>"\x00-\x1f]+', value) else ""


def metadata(record):
    source = str(record.get("source") or "").strip().upper()
    source_id = str(record.get("id") or "").strip()
    if not source or not source_id:
        raise ValueError("Europe PMC 응답에 source/id가 없습니다.")
    doi = normalize_doi(record.get("doi"))
    pmid = str(record.get("pmid") or (source_id if source == "MED" else ""))
    pmid = pmid if re.fullmatch(r"\d+", pmid) else ""
    pmcid = str(record.get("pmcid") or (source_id if source == "PMC" else "")).upper()
    pmcid = pmcid if re.fullmatch(r"PMC\d+", pmcid) else ""
    publication_date = str(record.get("firstPublicationDate") or "")
    try:
        if date.fromisoformat(publication_date).isoformat() != publication_date:
            publication_date = ""
    except ValueError:
        publication_date = ""
    types = (record.get("pubTypeList") or {}).get("pubType") or []
    if isinstance(types, str):
        types = [types]
    authors = record.get("authorString") or ", ".join(
        author.get("fullName", "") for author in (record.get("authorList") or {}).get("author", []))
    journal = (record.get("journalInfo") or {}).get("journal") or {}
    return {
        "title": plain_text(record.get("title")), "authors": plain_text(authors),
        "journal": plain_text(journal.get("title") or record.get("journalTitle")),
        "date": publication_date,
        "dateSource": "Europe PMC firstPublicationDate" if publication_date else "",
        "doi": doi, "pmid": pmid, "pmcid": pmcid, "source": source, "sourceId": source_id,
        "abstract": plain_text(record.get("abstractText")),
        "publicationTypes": list(dict.fromkeys(plain_text(item) for item in types)),
        "sourceUrl": f"https://europepmc.org/article/{quote(source, safe='')}/{quote(source_id, safe='')}",
        "doiUrl": "https://doi.org/" + quote(doi, safe="/") if doi else "",
        "openAccess": record.get("isOpenAccess") == "Y", "fullTextStatus": "not_retrieved",
    }


def merge_metadata(previous, incoming):
    merged = {**previous, **{key: value for key, value in incoming.items() if value not in ("", [], None)}}
    merged["categories"] = [area["name"] for area in AREAS
                            if area["name"] in previous.get("categories", []) + incoming.get("categories", [])]
    merged["publicationTypes"] = list(dict.fromkeys(
        previous.get("publicationTypes", []) + incoming.get("publicationTypes", [])))
    merged["openAccess"] = previous.get("openAccess", False) or incoming.get("openAccess", False)
    merged["firstSeenAt"] = min(previous["firstSeenAt"], incoming["firstSeenAt"])
    merged["lastSeenAt"] = max(previous["lastSeenAt"], incoming["lastSeenAt"])
    return merged


class Collector:
    def __init__(self, db_path, library_papers):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        papers = library_papers.values() if isinstance(library_papers, dict) else library_papers
        self.library_dois = {normalize_doi(paper.get("metadata", {}).get("doi")) for paper in papers}
        self.library_dois.discard("")
        self._lock = threading.Lock()
        self._thread = None
        self._last_request = 0
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS collection_candidates (
                    id TEXT PRIMARY KEY, created_run TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_aliases (
                    alias TEXT PRIMARY KEY, candidate_id TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS collection_alias_candidates ON collection_aliases(candidate_id);
                CREATE TABLE IF NOT EXISTS collection_runs (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_run_items (
                    run_id TEXT NOT NULL, candidate_id TEXT NOT NULL, was_new INTEGER NOT NULL,
                    PRIMARY KEY(run_id, candidate_id));
            """)
        self._recover_interrupted()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def candidates(self):
        with self._db() as db:
            papers = [json.loads(row[0]) for row in db.execute("SELECT data FROM collection_candidates")]
        for paper in papers:
            paper["inLibrary"] = paper["doi"] in self.library_dois
        return sorted(papers, key=lambda paper: (paper["date"], paper["firstSeenAt"], paper["id"]), reverse=True)

    def status(self):
        self._recover_interrupted()
        with self._db() as db:
            latest = db.execute("SELECT data FROM collection_runs ORDER BY rowid DESC LIMIT 1").fetchone()
            papers = [json.loads(row[0]) for row in db.execute("SELECT data FROM collection_candidates")]
        return {"areas": [dict(area) for area in AREAS], "run": json.loads(latest[0]) if latest else None,
                "counts": {"total": len(papers), "areas": {
                    area["name"]: sum(area["name"] in paper["categories"] for paper in papers) for area in AREAS}}}

    def start(self, from_date, to_date):
        try:
            begin, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
            if begin.isoformat() != from_date or end.isoformat() != to_date or begin > end:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("시작일과 종료일을 YYYY-MM-DD로 입력하고 시작일이 종료일보다 늦지 않게 지정하세요.") from None
        return self._start(from_date, to_date)

    def retry(self, run_id):
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("다시 시도할 수집 기록을 지정하세요.")
        return self._start(None, None, retry_of=run_id)

    def _start(self, from_date, to_date, retry_of=None):
        with self._lock:
            worker_lock = self._acquire_worker_lock()
            if worker_lock is None:
                raise RuntimeError("이미 논문 수집이 진행 중입니다.")
            try:
                self._interrupt_stale_runs()
                with self._db() as db:
                    selected = AREAS
                    if retry_of is not None:
                        latest = db.execute("SELECT data FROM collection_runs ORDER BY rowid DESC LIMIT 1").fetchone()
                        previous = json.loads(latest[0]) if latest else None
                        if not previous or previous["id"] != retry_of:
                            raise ValueError("가장 최근 수집의 실패한 분야만 다시 시도할 수 있습니다. 화면을 새로고침하세요.")
                        if previous["status"] == "running":
                            raise RuntimeError("이미 논문 수집이 진행 중입니다.")
                        selected = [area for area in previous["areas"] if area["status"] in ("failed", "pending")]
                        if not selected:
                            raise ValueError("다시 시도할 실패 또는 미완료 분야가 없습니다.")
                        from_date, to_date = previous["from"], previous["to"]
                    run = {"id": uuid.uuid4().hex, "status": "running", "from": from_date, "to": to_date,
                           "startedAt": now(), "finishedAt": None, "added": 0, "updated": 0,
                           "areas": [{"name": area["name"], "status": "pending", "pages": 0,
                                      "matched": 0, "processed": 0, "error": ""} for area in selected]}
                    if retry_of is not None:
                        run["retryOf"] = retry_of
                    self._save_run(db, run)
                snapshot = json.loads(json.dumps(run))
                self._thread = threading.Thread(target=self._work, args=(run, worker_lock), daemon=True)
                self._thread.start()
                return snapshot
            except Exception:
                self._release_worker_lock(worker_lock)
                raise

    def _acquire_worker_lock(self):
        handle = self.db_path.with_name(self.db_path.name + ".collection.lock").open("a+b")
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

    @staticmethod
    def _release_worker_lock(handle):
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def _recover_interrupted(self):
        handle = self._acquire_worker_lock()
        if handle is not None:
            try:
                self._interrupt_stale_runs()
            finally:
                self._release_worker_lock(handle)

    def _interrupt_stale_runs(self):
        with self._db() as db:
            for row in db.execute("SELECT data FROM collection_runs").fetchall():
                run = json.loads(row[0])
                if run["status"] == "running":
                    run["status"], run["finishedAt"] = "interrupted", now()
                    for area in run["areas"]:
                        if area["status"] == "running":
                            area["status"] = "failed"
                            area["error"] = "수집이 중단되었습니다. 같은 기간으로 다시 수집할 수 있습니다."
                    self._save_run(db, run)

    def _save_run(self, db, run):
        counts = db.execute("SELECT COUNT(*), COALESCE(SUM(was_new), 0) FROM collection_run_items WHERE run_id=?",
                            (run["id"],)).fetchone()
        run["added"], run["updated"] = counts[1], counts[0] - counts[1]
        db.execute("INSERT INTO collection_runs(id, data) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                   (run["id"], json.dumps(run, ensure_ascii=False)))

    def _store_candidate(self, db, record, category, run_id):
        paper = metadata(record)
        stamp = now()
        paper.update(categories=[category], firstSeenAt=stamp, lastSeenAt=stamp)
        aliases = [f"{field}:{paper[field]}" for field in ("doi", "pmid", "pmcid") if paper[field]]
        aliases.append(f"source:{paper['source']}:{paper['sourceId']}")
        matches = []
        for alias in aliases:
            row = db.execute("SELECT candidate_id FROM collection_aliases WHERE alias=?", (alias,)).fetchone()
            if row and row[0] not in matches:
                matches.append(row[0])
        candidate_id = matches[0] if matches else uuid.uuid4().hex
        created_run = run_id
        if matches:
            previous = []
            for old_id in matches:
                row = db.execute("SELECT created_run, data FROM collection_candidates WHERE id=?", (old_id,)).fetchone()
                previous.append((row[0], json.loads(row[1])))
            created_run = min(previous, key=lambda entry: entry[1]["firstSeenAt"])[0]
            for _, old in reversed(previous):
                paper = merge_metadata(old, paper)
            for old_id in matches[1:]:
                db.execute("UPDATE collection_aliases SET candidate_id=? WHERE candidate_id=?", (candidate_id, old_id))
                for item in db.execute("SELECT run_id, was_new FROM collection_run_items WHERE candidate_id=?", (old_id,)).fetchall():
                    db.execute("""INSERT INTO collection_run_items VALUES (?, ?, ?)
                        ON CONFLICT(run_id, candidate_id) DO UPDATE SET was_new=MIN(was_new, excluded.was_new)""",
                               (item[0], candidate_id, item[1]))
                db.execute("DELETE FROM collection_run_items WHERE candidate_id=?", (old_id,))
                db.execute("DELETE FROM collection_candidates WHERE id=?", (old_id,))
        paper["id"] = candidate_id
        db.execute("""INSERT INTO collection_candidates VALUES (?, ?, ?) ON CONFLICT(id)
            DO UPDATE SET created_run=excluded.created_run, data=excluded.data""",
                   (candidate_id, created_run, json.dumps(paper, ensure_ascii=False)))
        for alias in aliases:
            db.execute("INSERT OR REPLACE INTO collection_aliases VALUES (?, ?)", (alias, candidate_id))
        db.execute("""INSERT INTO collection_run_items VALUES (?, ?, ?)
            ON CONFLICT(run_id, candidate_id) DO UPDATE SET was_new=MIN(was_new, excluded.was_new)""",
                   (run_id, candidate_id, int(created_run == run_id)))

    def _fetch_page(self, query, cursor):
        url = API_URL + "?" + urlencode({"query": query, "format": "json", "resultType": "core",
                                          "cursorMark": cursor, "pageSize": PAGE_SIZE})
        for attempt in range(3):
            time.sleep(max(0, REQUEST_INTERVAL - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            try:
                request = Request(url, headers={"User-Agent": "PaperRadar/1.0 (personal literature monitor)",
                                               "Accept": "application/json"})
                with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError(f"Europe PMC HTTP {error.code}. 나중에 같은 기간으로 다시 수집하세요.") from error
                delay = 2 ** (attempt + 1)
                retry_after = error.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        try:
                            delay = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                        except (TypeError, ValueError):
                            pass
                if delay > 30:
                    raise RuntimeError("Europe PMC가 긴 재시도 대기를 요청했습니다. 나중에 다시 수집하세요.") from error
                time.sleep(max(0, delay))
            except (OSError, URLError) as error:
                if attempt == 2:
                    raise RuntimeError("Europe PMC 연결이 실패했습니다. 네트워크를 확인하고 다시 수집하세요.") from error
                time.sleep(2 ** (attempt + 1))

    def _work(self, run, worker_lock):
        try:
            self._collect(run)
        except Exception as error:
            run["status"], run["finishedAt"] = "failed", now()
            for area in run["areas"]:
                if area["status"] in ("running", "pending"):
                    area["status"], area["error"] = "failed", str(error)[:400]
            try:
                with self._db() as db:
                    self._save_run(db, run)
            except sqlite3.Error:
                pass  # An available worker lock lets status()/the next launch recover this run.
        finally:
            self._release_worker_lock(worker_lock)

    def _collect(self, run):
        definitions = {area["name"]: area for area in AREAS}
        for area in run["areas"]:
            definition = definitions[area["name"]]
            area["status"] = "running"
            with self._db() as db:
                self._save_run(db, run)
            try:
                cursor, seen_cursors = "*", set()
                query = f"({definition['query']}) AND FIRST_PDATE:[{run['from']} TO {run['to']}]"
                while True:
                    response = self._fetch_page(query, cursor)
                    records = response["resultList"]["result"]
                    matched = response["hitCount"]
                    if not isinstance(records, list) or type(matched) is not int or matched < 0:
                        raise ValueError("Europe PMC 검색 응답 형식이 올바르지 않습니다.")
                    with self._db() as db:
                        for record in records:
                            self._store_candidate(db, record, area["name"], run["id"])
                        area["pages"] += 1
                        area["matched"] = matched
                        area["processed"] += len(records)
                        self._save_run(db, run)
                    if area["processed"] >= matched:
                        break
                    next_cursor = response.get("nextCursorMark")
                    if not records or not next_cursor or next_cursor == cursor or next_cursor in seen_cursors:
                        raise ValueError("전체 결과를 받기 전에 페이지 이동이 중단되었습니다. 같은 기간으로 다시 수집하세요.")
                    seen_cursors.add(cursor)
                    cursor = next_cursor
                area["status"] = "completed"
            except Exception as error:
                area["status"] = "failed"
                area["error"] = str(error)[:400] or type(error).__name__
            with self._db() as db:
                self._save_run(db, run)
        failed = sum(area["status"] == "failed" for area in run["areas"])
        run["status"] = "completed" if failed == 0 else (
            "partial" if failed < len(run["areas"]) or any(area["processed"] for area in run["areas"]) else "failed")
        run["finishedAt"] = now()
        with self._db() as db:
            self._save_run(db, run)
