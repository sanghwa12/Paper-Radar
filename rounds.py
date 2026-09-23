"""Read a bounded recommendation round and join its actual preparation/publication state."""
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from classification import classify_candidate
from collector import AREAS, normalize_doi
from evaluation import WEIGHTS, calculate_score

DIRECTORY = Path(__file__).resolve().parent / "data" / "rounds"
AREA_NAMES = [area["name"] for area in AREAS]


class RoundDataError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise RoundDataError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def workflow(preparation, paper):
    body_available = any(item.get("kind") == "body" and item.get("usable", 0) > 0
                         for item in (preparation or {}).get("coverage", []))
    if paper:
        return {"status": "brief_registered", "label": "브리핑 등록", "stage": "", "bodyAvailable": body_available}
    state = (preparation or {}).get("status")
    body_label = "본문 확보" if body_available else "본문 미확보"
    labels = {"ready": ("writing_waiting", "자료 준비 완료 · 작성 대기"),
              "preparing": ("materials_preparing", "자료 준비 중"),
              "partial": ("materials_partial", f"{body_label} · 일부 자료 확인 필요"),
              "failed": ("materials_failed", f"{body_label} · 자료 준비 실패")}
    status, label = labels.get(state, ("selected", "선정 완료 · 자료 준비 전"))
    stage = (preparation or {}).get("stage", "") if state == "preparing" else ""
    return {"status": status, "label": label, "stage": stage, "bodyAvailable": body_available}


def validate_selection(selection):
    require(isinstance(selection, dict) and selection.get("mode") == "codex-assisted", "회차 선정 방식을 확인하세요.")
    require(selection.get("policyVersion") == "v2" and selection.get("weights") == WEIGHTS,
            "선정 회차는 합의한 내용 60·인용 20·증가 10·저널 10 배점을 사용해야 합니다.")
    require(text(selection.get("source")) and text(selection.get("note")), "선정 출처와 표본 범위 설명이 필요합니다.")
    begin, end = date.fromisoformat(selection["from"]), date.fromisoformat(selection["to"])
    require(begin.isoformat() == selection["from"] and end.isoformat() == selection["to"] and begin <= end,
            "선정 검색 기간을 YYYY-MM-DD로 확인하세요.")
    searches = selection.get("searches")
    require(isinstance(searches, list) and searches and {item.get("area") for item in searches} == set(AREA_NAMES),
            "선정 검색 기록에는 여섯 분야가 모두 필요합니다.")
    completed_areas = set()
    for search in searches:
        require(all(text(search.get(key)) for key in ("query", "observedAt")), "검색식과 관측 시각이 필요합니다.")
        if search.get("status") == "failed":
            require(search.get("hitCount") is None and text(search.get("reason")),
                    "실패한 검색의 결과 수는 미확인으로 남기고 사유를 기록하세요.")
            continue
        require(search.get("status", "complete") == "complete", "검색 완료·실패 상태를 확인하세요.")
        require(all(type(search.get(key)) is int and search[key] >= 0 for key in ("fetched", "hitCount")),
                "검색 결과 수와 확인한 자료 수를 구분해 기록하세요.")
        require(search["fetched"] <= search["hitCount"], "확인한 자료 수가 검색 결과 수보다 많습니다.")
        completed_areas.add(search["area"])
    require(completed_areas == set(AREA_NAMES), "각 분야에 완료된 검색 기록이 하나 이상 필요합니다.")


def validate_item(item, candidate, selection):
    require(item.get("reviewBasis") in ("abstract", "fulltext"), "선정 평가의 초록·본문 확인 범위를 기록하세요.")
    require(text(item.get("reason")) and text(item.get("evaluatedAt")), "선정 이유와 평가 시각이 필요합니다.")
    require(classify_candidate(candidate)["kind"] == "original", "회차 원저 목록에는 Review·Preprint·유형 미확인 논문을 넣을 수 없습니다.")
    require(item["area"] in candidate.get("categories", []), "선정 분야가 보관 후보의 분야와 일치하지 않습니다.")
    published = date.fromisoformat(candidate["date"])
    require(published.isoformat() == candidate["date"] and selection["from"] <= candidate["date"] <= selection["to"],
            "선정 논문의 발행일이 회차 검색 기간 밖에 있습니다.")
    sources = item.get("sources")
    require(isinstance(sources, list) and sources and all(isinstance(source, dict)
        and all(text(source.get(key)) for key in ("id", "kind", "label", "url"))
        and source["url"].startswith(("https://", "/assets/")) for source in sources), "선정 평가 출처를 확인하세요.")
    source_ids = {source["id"] for source in sources}
    require(len(source_ids) == len(sources), "선정 평가의 출처 ID가 중복되었습니다.")
    for source in sources:
        if "doi" in source:
            require(normalize_doi(source["doi"]) and normalize_doi(source["doi"]) == normalize_doi(candidate.get("doi")),
                    "선정 평가 출처의 DOI가 보관 후보와 다릅니다.")
    score = calculate_score(item["checks"], item["metrics"], item["ratings"], item["reproducibilityAdjustment"])
    for check in item["checks"]:
        require(text(check.get("reason")), "평가 판정 이유가 없습니다.")
        require(check.get("sourceId") is None or check["sourceId"] in source_ids, "평가 항목의 출처 ID가 없습니다.")
        require(check["status"] == "unknown" or check.get("sourceId") in source_ids, "확인된 평가 항목에는 출처가 필요합니다.")
    return score


def load_rounds(candidates, preparations, papers, directory=None):
    """Pure read: no collection, acquisition, generation, or SQLite writes occur here."""
    by_id = {candidate["id"]: candidate for candidate in candidates}
    rounds = []
    for path in sorted(Path(directory or DIRECTORY).glob("*.json"), reverse=True):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            require(document.get("schemaVersion") == 1 and document.get("id") == path.stem,
                    "선정 회차의 파일 이름·ID·형식이 일치하지 않습니다.")
            require(text(document.get("createdAt")) and text(document.get("title")), "회차 제목과 생성 시각이 필요합니다.")
            validate_selection(document.get("selection"))
            items = document.get("items")
            require(isinstance(items, list) and len(items) == 6 and all(isinstance(item, dict) for item in items),
                    "이번 회차에는 원저 여섯 편이 필요합니다.")
            require(Counter(item.get("area") for item in items) == Counter(AREA_NAMES), "여섯 분야에 한 편씩 배정해야 합니다.")
            ids = [item.get("candidateId") for item in items]
            require(all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) for value in ids)
                    and len(set(ids)) == 6, "회차 논문 ID가 없거나 중복되었습니다.")
            joined = []
            for item in sorted(items, key=lambda item: AREA_NAMES.index(item["area"])):
                candidate_id = item["candidateId"]
                require(candidate_id in by_id, f"선정 논문이 보관 후보에 없습니다: {candidate_id}")
                candidate = by_id[candidate_id]
                score = validate_item(item, candidate, document["selection"])
                preparation, paper = preparations.get(candidate_id), papers.get(candidate_id)
                joined.append({**item, "candidate": candidate, "score": score, "preparation": preparation,
                               "paperId": paper["id"] if paper else None, "workflow": workflow(preparation, paper)})
            rounds.append({**document, "items": joined})
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            raise RoundDataError(f"선정 회차 {path.stem}을 확인해 주세요. {error}") from error
    return rounds
