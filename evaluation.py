"""Serve the reviewed pilot snapshot and calculate scores from recorded evidence."""
import json
import math
from collections import Counter
from pathlib import Path

from collector import AREAS


PILOT_DIRECTORY = Path(__file__).resolve().parent / "data" / "pilot"
WEIGHTS = {"content": 60, "citation": 20, "momentum": 10, "journal": 10}
PRIVATE_REPRODUCTION_PENALTY = 3
CONTENT_RUBRIC = [
    {"id": "novelty", "label": "새로움·동향상 의미", "maximum": 15, "levels": [
        {"level": 0, "points": 0, "description": "검토한 자료에서 새 기여가 없음을 확인"},
        {"level": 1, "points": 5, "description": "기존 접근의 제한적인 조정·적용"},
        {"level": 2, "points": 10, "description": "구분 가능한 새 방법·설계 또는 의미 있는 확장"},
        {"level": 3, "points": 15, "description": "기존 접근의 범위를 바꾸는 새 원리·플랫폼·기전적 기여"},
    ]},
    {"id": "evidence", "label": "근거의 탄탄함", "maximum": 15, "levels": [
        {"level": 0, "points": 0, "description": "핵심 주장을 뒷받침하는 결과가 없음을 확인"},
        {"level": 1, "points": 5, "description": "핵심 주장에 대한 직접적인 초기 관찰·시험"},
        {"level": 2, "points": 10, "description": "정량 결과와 적절한 대조·비교로 핵심 주장을 지지"},
        {"level": 3, "points": 15, "description": "다른 측정 원리나 독립 검증 자료로 핵심 주장을 교차 지지"},
    ]},
    {"id": "reproducibility", "label": "재현 가능성", "maximum": 15, "levels": [
        {"level": 0, "points": 0, "description": "재구현에 필요한 방법 설명이 없음을 확인"},
        {"level": 1, "points": 5, "description": "핵심 자원과 절차의 개요 제시"},
        {"level": 2, "points": 10, "description": "주요 조건·분석·자원으로 방법 구현 경로 파악 가능"},
        {"level": 3, "points": 15, "description": "핵심 절차·조건·계산식·분석 입력을 재구현할 수준으로 연결"},
    ]},
    {"id": "utility", "label": "연구 활용 가치", "maximum": 15, "levels": [
        {"level": 0, "points": 0, "description": "적용 대상·사용 사례가 없음을 확인"},
        {"level": 1, "points": 5, "description": "적용 대상과 단일 사용 사례 제시"},
        {"level": 2, "points": 10, "description": "도입 경로·조건·상충 관계가 구체적"},
        {"level": 3, "points": 15, "description": "여러 대상·조건에서 활용 시험과 도입 판단에 필요한 정보 제공"},
    ]},
]
CONTENT_IDS = {axis["id"] for axis in CONTENT_RUBRIC}
RUBRIC = [
    {"id": "design", "label": "비교·설계의 적절성", "checks": [
        {"id": "d1", "label": "연구 질문과 주요 평가 결과가 명시되어 있다."},
        {"id": "d2", "label": "핵심 주장에 적합한 대조군 또는 비교 대상이 있다."},
        {"id": "d3", "label": "주요 비교의 조건·데이터·평가 방식이 맞춰져 있다."},
        {"id": "d4", "label": "해당 연구의 주요 편향·교란·데이터 누출 방지 조치가 설명되어 있다."},
    ]},
    {"id": "evidence", "label": "결과를 뒷받침하는 근거", "checks": [
        {"id": "e1", "label": "핵심 주장을 직접 측정하거나 시험하는 결과가 있다."},
        {"id": "e2", "label": "핵심 결과의 효과 크기 또는 성능이 수치로 제시되어 있다."},
        {"id": "e3", "label": "반복·표본 수와 오차·불확실성 분석이 평가에 충분히 보고되어 있다."},
        {"id": "e4", "label": "핵심 주장을 다른 측정 원리 또는 독립 검증 자료로 확인한다."},
    ]},
    {"id": "contribution", "label": "기존 연구 대비 기여", "checks": [
        {"id": "n1", "label": "해결하려는 기존 접근의 구체적인 한계를 설명한다."},
        {"id": "n2", "label": "추가한 방법·기전·결과를 기존 접근과 구분할 수 있다."},
        {"id": "n3", "label": "기존 접근 대비 개선 또는 기존 결론의 수정이 직접 비교로 뒷받침된다."},
        {"id": "n4", "label": "기여의 차별성을 판단할 관련 선행연구 비교가 충분히 제시되어 있다."},
    ]},
    {"id": "reproducibility", "label": "재현 가능성", "checks": [
        {"id": "r1", "label": "실험·계산 조건과 절차가 재현할 수준으로 제시되어 있다."},
        {"id": "r2", "label": "사용한 물질·세포·데이터·모델 등 핵심 자원을 식별할 수 있다."},
        {"id": "r3", "label": "핵심 결과의 원자료 또는 검증용 데이터 접근 방법이 제공된다."},
        {"id": "r4", "label": "분석 코드·계산식·상세 분석 절차로 결과를 재계산할 수 있다."},
    ]},
    {"id": "utility", "label": "적용 가능성과 범위", "checks": [
        {"id": "u1", "label": "적용 대상과 사용할 수 있는 조건이 구체적으로 제시되어 있다."},
        {"id": "u2", "label": "하나의 예시를 넘어 다른 대상·조건에서 적용 범위를 시험했다."},
        {"id": "u3", "label": "적용에 중요한 자원·비용·안전성·성능 상충 관계 중 해당 사항을 측정했다."},
        {"id": "u4", "label": "실패 조건·한계 또는 적용 경계를 명시한다."},
    ]},
]
CHECK_IDS = {check["id"] for group in RUBRIC for check in group["checks"]}


class EvaluationDataError(ValueError):
    """The reviewed snapshot is incomplete or fails its evidence contract."""


def validate_checks(checks):
    if not isinstance(checks, list) or len(checks) != len(CHECK_IDS):
        raise EvaluationDataError("각 논문에는 평가 항목 20개가 필요합니다.")
    if any(not isinstance(check, dict) for check in checks):
        raise EvaluationDataError("평가 항목 형식을 확인해 주세요.")
    if {check.get("id") for check in checks} != CHECK_IDS:
        raise EvaluationDataError("평가 항목이 누락되거나 중복되었습니다.")
    if any(check.get("status") not in {"met", "not_met", "unknown"} for check in checks):
        raise EvaluationDataError("평가 판정은 충족·미충족·미확인 중 하나여야 합니다.")


def metric_score(metric, field, maximum):
    value = metric.get(field)
    if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100):
        raise EvaluationDataError("지표 백분위는 0–100 범위여야 합니다.")
    if metric.get("status") != "verified" or value is None:
        return None
    return round(value * maximum / 100, 4)


def validate_ratings(ratings, adjustment):
    if not isinstance(ratings, list) or len(ratings) != len(CONTENT_IDS):
        raise EvaluationDataError("내용 평가에는 네 축의 판정이 필요합니다.")
    if any(not isinstance(rating, dict) for rating in ratings) or {rating.get("id") for rating in ratings} != CONTENT_IDS:
        raise EvaluationDataError("내용 평가 축이 누락되거나 중복되었습니다.")
    for rating in ratings:
        level = rating.get("level")
        if "level" not in rating or (level is not None and (type(level) is not int or not 0 <= level <= 3)):
            raise EvaluationDataError("내용 등급은 0–3 또는 미평가여야 합니다.")
    if not isinstance(adjustment, dict) or adjustment.get("status") not in {"none", "exempt", "pending", "applied"}:
        raise EvaluationDataError("재현 제약 조정 상태를 확인해 주세요.")
    for item in [*ratings, adjustment]:
        references = item.get("checkIds")
        if not item.get("reason") or not isinstance(references, list) or any(not isinstance(key, str) or key not in CHECK_IDS for key in references):
            raise EvaluationDataError("내용 판정의 이유와 연결된 확인 항목이 필요합니다.")
        if item.get("level") is not None and not references:
            raise EvaluationDataError("점수를 부여한 내용 축에는 근거 항목이 필요합니다.")
        if item.get("status") in {"applied", "exempt", "pending"} and not references:
            raise EvaluationDataError("재현 제약 조정에는 근거 항목이 필요합니다.")


def calculate_score(checks, metrics, ratings, adjustment):
    validate_checks(checks)
    validate_ratings(ratings, adjustment)
    content_base = sum(rating["level"] * 5 for rating in ratings if rating["level"] is not None)
    content_known_max = sum(15 for rating in ratings if rating["level"] is not None)
    penalty = PRIVATE_REPRODUCTION_PENALTY if adjustment["status"] == "applied" else 0
    penalty_pending = adjustment["status"] == "pending"
    content = max(0, content_base - penalty)
    content_lower = max(0, content - (PRIVATE_REPRODUCTION_PENALTY if penalty_pending else 0))
    content_upper = max(0, content_base + 60 - content_known_max - penalty)
    values = {
        "citation": metric_score(metrics.get("citations", {}), "normalizedPercentile", 20),
        "journal": metric_score(metrics.get("journal", {}), "percentile", 10),
        "momentum": metric_score(metrics.get("momentum", {}), "percentile", 10),
    }
    metric_subtotal = sum(value for value in values.values() if value is not None)
    subtotal = round(content + metric_subtotal, 4)
    lower = round(content_lower + metric_subtotal, 4)
    known_max = content_known_max + sum(WEIGHTS[key] for key, value in values.items() if value is not None)
    upper = round(content_upper + sum(WEIGHTS[key] if value is None else value for key, value in values.items()), 4)
    return {"content": content, "contentBase": content_base, "contentKnownMax": content_known_max,
            "contentLower": content_lower, "contentUpper": content_upper, "penalty": penalty,
            "penaltyPending": penalty_pending, "penaltyMaximum": PRIVATE_REPRODUCTION_PENALTY,
            **values, "subtotal": subtotal, "total": subtotal if known_max == 100 and not penalty_pending else None,
            "knownMax": known_max, "lower": lower, "upper": upper}


def read_snapshot(directory, name):
    try:
        return json.loads((directory / name).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise EvaluationDataError("시범 평가 자료가 아직 준비되지 않았습니다. 잠시 후 다시 확인해 주세요.") from error


def load_evaluation(directory=None):
    directory = Path(directory) if directory else PILOT_DIRECTORY
    selected = read_snapshot(directory, "selected.json")
    reviews_a = read_snapshot(directory, "reviews-a.json")
    reviews_b = read_snapshot(directory, "reviews-b.json")
    ratings_a = read_snapshot(directory, "ratings-a.json")
    ratings_b = read_snapshot(directory, "ratings-b.json")
    citations = read_snapshot(directory, "citation-metrics.json")
    journals = read_snapshot(directory, "journal-metrics.json")
    if not all(isinstance(value, list) for value in (selected, reviews_a, reviews_b, ratings_a, ratings_b, journals)) or not isinstance(citations, dict):
        raise EvaluationDataError("시범 평가 자료의 목록 형식을 확인해 주세요.")
    try:
        reviews = reviews_a + reviews_b
        selected_ids = [item["id"] for item in selected]
        review_ids = [item["candidateId"] for item in reviews]
        assessments = ratings_a + ratings_b
        assessment_ids = [item["candidateId"] for item in assessments]
        if len(selected_ids) != 12 or len(set(selected_ids)) != 12:
            raise EvaluationDataError("시범 평가에는 중복 없는 논문 12편이 필요합니다.")
        if len(review_ids) != 12 or set(review_ids) != set(selected_ids):
            raise EvaluationDataError("선택한 논문 12편의 평가가 모두 준비되어야 합니다.")
        if len(assessment_ids) != 12 or set(assessment_ids) != set(selected_ids):
            raise EvaluationDataError("선택한 논문 12편의 새 기준 평가가 모두 필요합니다.")
        if Counter(item["area"] for item in reviews) != Counter({area["name"]: 2 for area in AREAS}):
            raise EvaluationDataError("시범 평가는 6개 분야에 2편씩 배정되어야 합니다.")
        by_id = {item["candidateId"]: item for item in reviews}
        by_assessment = {item["candidateId"]: item for item in assessments}
        by_journal = {item["journal"].strip().casefold(): item for item in journals}
        if len(by_journal) != len(journals):
            raise EvaluationDataError("저널 지표에 중복된 저널이 있습니다.")
        papers = []
        for candidate in selected:
            review = by_id[candidate["id"]]
            assessment = by_assessment[candidate["id"]]
            source_ids = {item["id"] for item in review["sources"]}
            validate_checks(review["checks"])
            for check in review["checks"]:
                if not check.get("reason") or (check.get("sourceId") is not None and check["sourceId"] not in source_ids):
                    raise EvaluationDataError("평가 이유와 연결된 출처를 확인해 주세요.")
                if check["status"] != "unknown" and check.get("sourceId") not in source_ids:
                    raise EvaluationDataError("확인된 평가 항목에는 출처가 필요합니다.")
            recorded = citations.get(candidate["id"], {})
            metrics = {
                "citations": recorded.get("citations", {"status": "unavailable", "reason": "인용 지표 미확보"}),
                "momentum": recorded.get("momentum", {"status": "no_baseline", "reason": "이전 인용 관측값이 없어 최근 증가량은 미평가입니다."}),
                "journal": by_journal.get(candidate.get("journal", "").strip().casefold(),
                                          {"status": "unavailable", "reason": "확인된 JCR 저널 지표가 없습니다."}),
            }
            papers.append({**candidate, **review, **assessment, "id": candidate["id"], "metrics": metrics,
                           "score": calculate_score(review["checks"], metrics, assessment["ratings"], assessment["reproducibilityAdjustment"])})
    except (KeyError, TypeError, AttributeError) as error:
        raise EvaluationDataError("시범 평가 자료의 필수 항목을 확인해 주세요.") from error
    return {
        "id": "pilot-2026-09-21", "evaluatedAt": "2026-09-21", "weights": WEIGHTS, "policyVersion": "v2",
        "contentRubric": CONTENT_RUBRIC,
        "method": "사용자 합의에 따라 내용 60점·인용 영향 20점·최근 증가 10점·저널 10점을 유지합니다. "
                  "내용은 네 축에 15점씩 배정하고 확인된 강점을 0·5·10·15점으로 평가하는 시험 척도입니다. "
                  "비교의 불공정성·검증 부족 등은 근거를 남기며 별도 감점하지 않습니다. "
                  "명시적 비공개로 재현이 막히고 대안도 없을 때만 논문당 3점의 시험 감점을 적용합니다. "
                  "대체 경로가 확인되면 면제하고, 판단할 수 없으면 감점을 보류합니다. "
                  "인용 영향은 보정 백분위 × 0.2, 저널은 확인된 JCR 분야 백분위 × 0.1로 계산합니다. "
                  "여러 JCR 분류에 속한 저널은 모든 분류 백분위의 중앙값을 사용하는 시험 규칙을 적용했습니다. "
                  "최근 증가 점수는 별도 관측 기간의 증가 백분위를 확보한 뒤 계산합니다.",
        "rubric": RUBRIC, "papers": papers,
        "limitations": [
            "분야별 사례를 의도적으로 고른 기준 조정용 표본이며 전체 후보의 대표 표본이나 상위 12편이 아닙니다.",
            "내용 점수는 네 축의 확인된 강점을 구조화한 판단입니다. 작은 점수 차이를 논문 품질의 확실한 차이로 해석하지 않습니다. 기존 20개 조건은 점수 없는 증거 기록으로 보존합니다.",
            "초록만 확인한 평가는 저자가 보고한 주장에 근거한 잠정 판정입니다. 본문·보충자료 확인과 독립적인 재현 검증을 대신하지 않습니다.",
            "자료 미확보는 연구의 결함이나 0점으로 취급하지 않습니다. 모든 항목과 지표가 확인되기 전에는 총점과 순위를 확정하지 않습니다.",
            "인용이 쌓이는 중인 신규 논문은 실제 인용수를 표시하되 인용 배점을 유예합니다. 첫 관측의 누적 인용수로 최근 증가량을 대신하지 않습니다.",
            "내용 60·객관적 지표 40 비중은 확정했으며 세부 척도와 3점 조정은 시험 규칙입니다. 통과점·선정 편수는 미정입니다. 저널 지표는 개별 논문의 연구 품질을 직접 측정하지 않습니다.",
            "검증이 부족하거나 일부 자료가 미확보인 논문도 표시합니다. 불확실성은 숨기지 않고 사용자가 근거를 읽어 판단하도록 합니다. 개인 환경에서 실제 재현했는지는 확인하지 않았습니다.",
        ],
    }
