"""Validate and compare a Codex-assisted pilot; this module does not call an AI API."""
import copy
import datetime
import hashlib
import html
import json
import platform
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PILOT_ROOT = ROOT / "data" / "generation-pilot"
TABS = ("summary", "overview", "methods", "evidence")
KINDS = ("abstract", "body", "figure", "supplement")
BLOCKS = {"paragraph", "callout", "list", "pairs", "table", "figure"}


class PilotError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PilotError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def artifact(directory, group, name):
    require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]+\.json", name),
            "시범 자료의 파일 이름이 올바르지 않습니다.")
    path = (Path(directory) / group / name).resolve()
    require(path.is_relative_to((Path(directory) / group).resolve()), "시범 자료 경로를 확인하세요.")
    return path


def asset_file(url):
    require(isinstance(url, str) and url.startswith("/assets/"), "로컬 원본 자료 경로가 필요합니다.")
    path = (ROOT / "public" / url.split("#", 1)[0].lstrip("/")).resolve()
    require(path.is_relative_to(ROOT / "public" / "assets") and path.is_file(), "원본 자료 파일이 없습니다.")
    return path


def text(value):
    return isinstance(value, str) and bool(value.strip())


def text_list(value):
    return isinstance(value, list) and bool(value) and all(text(i) for i in value)


def normalized(value):
    return " ".join(value.split())


def source_ids(ids, sources):
    require(isinstance(ids, list) and ids and all(isinstance(i, str) and i in sources for i in ids),
            "입력에 없는 출처 ID 또는 비어 있는 출처가 있습니다.")


def validate_input(package):
    require(package.get("schemaVersion") == 1, "지원하지 않는 입력 형식입니다.")
    sources = {}
    for entry in package.get("sources", []):
        require(entry.get("kind") in KINDS and text(entry.get("id")) and text(entry.get("text")),
                "입력 자료 구간을 확인하세요.")
        require(entry["id"] not in sources, "중복된 출처 ID입니다.")
        require(entry.get("sha256") == hashlib.sha256(entry["text"].encode("utf-8")).hexdigest(),
                "입력 원문 구간의 해시가 다릅니다.")
        require(str(entry.get("url", "")).startswith(("https://", "/assets/")), "입력 출처 URL이 없습니다.")
        if entry.get("asset"):
            require(digest(asset_file(entry["asset"])) == entry.get("assetSha256"), "원본 자료의 해시가 다릅니다.")
        sources[entry["id"]] = entry
    require(sources, "입력 자료가 비어 있습니다.")
    return sources


def validate_block(block, sources):
    require(isinstance(block, dict) and block.get("type") in BLOCKS, "알 수 없는 본문 블록입니다.")
    source_ids(block.get("sourceIds"), sources)
    kind = block["type"]
    if kind in ("paragraph", "callout"):
        require(text(block.get("text")), "본문이 비어 있습니다.")
    elif kind == "list":
        require(text_list(block.get("items")), "목록 내용이 비어 있습니다.")
    elif kind == "pairs":
        require(isinstance(block.get("items"), list) and block["items"] and all(isinstance(i, dict) and text(i.get("label")) and text(i.get("text"))
                                         for i in block["items"]), "설명 쌍을 확인하세요.")
    elif kind == "table":
        headers, rows = block.get("headers"), block.get("rows")
        require(isinstance(headers, list) and headers and all(text(h) for h in headers), "표 머리글이 없습니다.")
        require(isinstance(rows, list) and rows and all(isinstance(r, list) and len(r) == len(headers)
                and all(isinstance(c, str) for c in r) for r in rows), "표 열과 행이 일치하지 않습니다.")
    elif kind == "figure":
        matches = [sources[i] for i in block["sourceIds"]
                   if sources[i]["kind"] == "figure" and sources[i].get("asset") == block.get("image")]
        require(matches and text(block.get("title")), "그림 경로와 출처 ID가 일치하지 않습니다.")
        require(block.get("source", {}).get("url") in [s["url"] for s in matches], "그림 출처 URL이 다릅니다.")
        require(text(block.get("caption")) and normalized(block["caption"]) == normalized(matches[0]["text"]),
                "원문 caption에 생성한 해설을 넣을 수 없습니다.")
        require(isinstance(block.get("explanation"), list) and block["explanation"] and all(isinstance(i, dict) and text(i.get("label")) and text(i.get("text"))
                                                for i in block["explanation"]), "그림 해설이 없습니다.")


def validate_draft(draft, package, sources):
    require(draft.get("candidateId") == package["candidateId"], "입력과 초안의 논문 ID가 다릅니다.")
    card = draft.get("card", {})
    require(all(text(card.get(k)) for k in ("titleKo", "purpose", "significance", "application", "limits")),
            "카드의 필수 내용이 없습니다.")
    require(text_list(card.get("flow")), "카드 연구 흐름이 없습니다.")
    source_ids(card.get("sourceIds"), sources)
    pairs = card.get("pairs", [])
    require(isinstance(pairs, list) and 2 <= len(pairs) <= 3, "카드에는 방법·결과 2~3쌍이 필요합니다.")
    for pair in pairs:
        require(all(text(pair.get(k)) for k in ("label", "method", "result")), "카드 방법·결과가 비어 있습니다.")
        source_ids(pair.get("sourceIds"), sources)
        require(pair.get("source", {}).get("url") in [sources[i]["url"] for i in pair["sourceIds"]],
                "카드 출처 URL이 입력 구간과 다릅니다.")
    abstract = draft.get("abstract", {})
    require(text_list(abstract.get("paragraphs")), "초록 번역이 없습니다.")
    require(abstract.get("source", {}).get("url") in [s["url"] for s in sources.values() if s["kind"] == "abstract"],
            "초록 출처를 확인하세요.")
    for tab in TABS:
        sections = draft.get("tabs", {}).get(tab)
        require(isinstance(sections, list) and sections, f"상세 탭이 비어 있습니다: {tab}")
        for section in sections:
            require(text(section.get("title")) and section.get("blocks"), "본문 절이 비어 있습니다.")
            for block in section["blocks"]:
                validate_block(block, sources)
    claims = draft.get("claims", [])
    require(isinstance(claims, list) and claims, "주요 주장 근거 기록이 없습니다.")
    seen = set()
    for claim in claims:
        require(text(claim.get("id")) and claim["id"] not in seen and text(claim.get("text"))
                and claim.get("kind") in ("author", "data", "inference"), "주장의 종류·식별자를 확인하세요.")
        seen.add(claim["id"])
        require(claim.get("support"), "주장에 원문 근거가 없습니다.")
        for support in claim["support"]:
            source_ids([support.get("sourceId")], sources)
            require(text(support.get("quote")) and normalized(support["quote"]) in
                    normalized(sources[support["sourceId"]]["text"]), "원문에 없는 근거 인용문입니다.")
    source_ids(draft.get("readSourceIds"), sources)
    require(isinstance(draft.get("viewedFigureIds"), list) and all(
        i in sources and sources[i]["kind"] == "figure" for i in draft["viewedFigureIds"]),
        "시각 검토 그림 ID를 확인하세요.")
    require(text_list(draft.get("limitations")), "미확인 범위 기록이 없습니다.")


def display_draft(draft, sources):
    result = copy.deepcopy({k: draft[k] for k in ("card", "abstract", "tabs")})
    figures = [b for section in draft["tabs"]["evidence"] for b in section["blocks"] if b["type"] == "figure"]
    if figures:
        figure = figures[0]
        result["card"]["image"] = {"src": figure["image"], "alt": figure.get("alt", figure["title"]),
                                    "caption": figure["title"], "source": figure["source"]}
    for sections in result["tabs"].values():
        for section in sections:
            ids = list(dict.fromkeys(i for b in section["blocks"] for i in b["sourceIds"]))
            links = [f'<a href="{html.escape(sources[i]["url"], quote=True)}">{html.escape(sources[i]["label"])}</a>' for i in ids]
            section["blocks"].append({"type": "details", "title": f"근거 위치 · {len(ids)}개 구간",
                                       "blocks": [{"type": "paragraph", "text": "근거: " + " · ".join(links)}]})
    return result


def load_runs(directory=PILOT_ROOT):
    results = []
    for run_path in sorted((Path(directory) / "runs").glob("*.json")):
        run = read_json(run_path)
        require(run.get("schemaVersion") == 1 and run.get("runId") == run_path.stem, "실행 기록 ID가 다릅니다.")
        require(run.get("generation", {}).get("mode") == "codex-assisted-pilot", "생성 실행 방식을 확인하세요.")
        input_path = artifact(directory, "inputs", run.get("inputFile"))
        draft_path = artifact(directory, "drafts", run.get("draftFile"))
        baseline_path = artifact(directory, "baselines", run.get("baselineFile"))
        require(digest(input_path) == run.get("inputSha256") and digest(baseline_path) == run.get("baselineSha256"),
                "실행 당시 입력 또는 비교 기준이 변경됐습니다.")
        package, draft, baseline = map(read_json, (input_path, draft_path, baseline_path))
        require(run.get("candidateId") == package["candidateId"] == baseline.get("candidateId"), "비교 논문 ID가 다릅니다.")
        sources = validate_input(package)
        validate_draft(draft, package, sources)
        review_path = artifact(directory, "reviews", run_path.name)
        review = read_json(review_path) if review_path.is_file() else {}
        current = review.get("inputSha256") == digest(input_path) and review.get("draftSha256") == digest(draft_path)
        if not current:
            review = {"status": "unverified", "summary": "형식·출처 연결 검사를 통과한 초안입니다. 내용 검증은 아직 적용되지 않았습니다.",
                      "checks": [], "differences": [], "unresolved": ["현재 입력·초안에 대한 독립 내용 검증 필요"], "checked": {}}
        require(review.get("status") in ("unverified", "partial", "held"), "시범본을 검토 완료로 승격할 수 없습니다.")
        for key in ("checks", "differences", "unresolved"):
            require(isinstance(review.get(key), list), "검증 기록이 올바르지 않습니다.")
        require(all(c.get("status") in ("pass", "fail", "unverified") and text(c.get("label")) and text(c.get("note"))
                    for c in review["checks"]), "검증 항목을 확인하세요.")
        validation = {k: review[k] for k in ("status", "summary", "checks", "differences", "unresolved")}
        validation["checks"] = [{"label": "형식·출처 연결", "status": "pass",
                                  "note": f'{len(sources)}개 입력 구간·원본 해시·4개 탭·{len(draft["claims"])}개 주장 인용 검사 통과. 과학적 정확성 검증과는 별도입니다.'}, *validation["checks"]]
        scopes = []
        for kind, label in zip(KINDS, ("초록", "본문", "그림", "보충자료")):
            available = any(s["kind"] == kind for s in sources.values())
            checked = review.get("checked", {}).get(kind, "unverified" if available else "unavailable")
            require(checked in ("reviewed", "partial", "unverified", "unavailable"), "검토 범위가 올바르지 않습니다.")
            require(available or checked not in ("reviewed", "partial"), "없는 자료를 검토했다고 표시할 수 없습니다.")
            scopes.append({"label": label, "acquired": available, "provided": available, "checked": checked})
        result = {k: run[k] for k in ("runId", "candidateId", "generatedAt", "generation")}
        result.update(title=package["metadata"]["title"], baseline={k: baseline[k] for k in ("card", "abstract", "tabs")},
                      draft=display_draft(draft, sources), validation=validation, sourceScope=scopes)
        results.append(result)
    return results


def main():
    print(f"# run {datetime.datetime.now():%Y-%m-%d %H:%M} | python {platform.python_version()} | seed 0 | argv {sys.argv[1:]}")
    report = {"mode": "validate-existing-codex-pilot", "runs": [], "errors": []}
    try:
        report["runs"] = [{"runId": r["runId"], "status": r["validation"]["status"],
                           "checks": r["validation"]["checks"]} for r in load_runs()]
    except (ValueError, OSError, KeyError, TypeError) as error:
        report["errors"].append(str(error))
    path = ROOT / ".runtime" / "generation-pilot" / "validation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Validated runs: {len(report['runs'])}; errors: {len(report['errors'])}")
    print(f"Saved report: {path}")
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
