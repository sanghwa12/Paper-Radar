"""Load source-grounded reading cards prepared from the pilot, without a remote model."""
import json
from pathlib import Path

from evaluation import load_evaluation


CARD_DIRECTORY = Path(__file__).resolve().parent / "data" / "cards"
BRIEF_DIRECTORY = CARD_DIRECTORY.parent / "briefs"
ASSET_DIRECTORY = CARD_DIRECTORY.parent.parent / "public" / "assets" / "briefs"
REVIEW_PATH = CARD_DIRECTORY.parent / "brief-reviews.json"
BASIS_LABELS = {"fulltext": "본문 기반 초안", "prior_fulltext_review": "기존 본문 검토 기반 초안",
                "abstract": "초록 기반 초안"}
BRIEF_LABELS = {"fulltext": "본문 재검토", "partial": "일부 자료 확인 필요", "abstract": "초록 기반 · 상세 미완성"}
REVIEW_LABELS = {"reviewed": "주요 근거 확인", "partial": "일부 검증 · 초안",
                 "unverified": "미검증 초안", "held": "검토 보류"}
REVIEW_SCOPES = ("abstract", "body", "figures", "supplement")


def load_review(candidate_id, path=REVIEW_PATH):
    reviews = json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else {}
    review = reviews.get(candidate_id)
    if review is None:
        return {"status": "unverified", "checkedAt": "", "acquired": {key: None for key in REVIEW_SCOPES},
                "checked": {key: "unverified" for key in REVIEW_SCOPES},
                "note": "브리핑 검증 기록이 없습니다. 자료 확보와 내용 검토를 확인해야 합니다.", "holds": []}
    if review.get("status") not in REVIEW_LABELS or not review.get("note"):
        raise ValueError("브리핑 검증 상태를 확인해 주세요.")
    for scope in REVIEW_SCOPES:
        if type(review.get("acquired", {}).get(scope)) is not bool or review.get("checked", {}).get(scope) not in (
                "reviewed", "partial", "unverified", "unavailable"):
            raise ValueError("자료 확보와 검토 범위를 구분해 주세요.")
        if review["checked"][scope] in ("reviewed", "partial") and not review["acquired"][scope]:
            raise ValueError("확보하지 않은 자료를 검토했다고 표시할 수 없습니다.")
    if not isinstance(review.get("holds"), list) or any(
            item.get("reason") not in ("source", "safety") or not item.get("scope") or not item.get("note")
            for item in review["holds"]):
        raise ValueError("보류 범위와 사유를 확인해 주세요.")
    if review["status"] == "reviewed" and (review["holds"] or review["checked"]["body"] != "reviewed"):
        raise ValueError("미검증·보류 자료를 검토 완료로 표시할 수 없습니다.")
    return review


def load_brief(candidate_id, directory=BRIEF_DIRECTORY):
    path = Path(directory) / f"{candidate_id}.json"
    if not path.is_file():
        raise ValueError(f"상세 브리핑 자료가 없습니다: {candidate_id}")
    brief = json.loads(path.read_text(encoding="utf-8"))
    if brief.get("candidateId") != candidate_id or brief.get("evidenceStatus") not in BRIEF_LABELS:
        raise ValueError("상세 브리핑의 논문·근거 범위를 확인해 주세요.")
    if not isinstance(brief.get("evidenceNote"), str) or not brief["evidenceNote"].strip():
        raise ValueError("상세 브리핑의 확인 범위가 누락되었습니다.")
    for tab in ("summary", "overview", "methods", "evidence"):
        sections = brief.get("tabs", {}).get(tab)
        if not isinstance(sections, list) or not sections or any(
                not isinstance(section, dict) or not section.get("blocks") for section in sections):
            raise ValueError(f"상세 브리핑 탭이 비어 있습니다: {tab}")
    return brief


def validate_card(content):
    for field in ("candidateId", "titleKo", "purpose", "significance", "application", "limits", "evidenceNote"):
        if not isinstance(content.get(field), str) or not content[field].strip():
            raise ValueError(f"카드 필수 항목을 확인해 주세요: {field}")
    if content.get("basis") not in BASIS_LABELS:
        raise ValueError("카드의 본문·초록 근거를 확인해 주세요.")
    for field in ("abstractKo", "briefSummary", "caveats", "flow"):
        if not isinstance(content.get(field), list) or not content[field] or any(
                not isinstance(value, str) or not value.strip() for value in content[field]):
            raise ValueError(f"카드 내용이 비어 있습니다: {field}")
    if not isinstance(content.get("pairs"), list) or not 2 <= len(content["pairs"]) <= 3:
        raise ValueError("카드에는 방법과 결과 2~3쌍이 필요합니다.")
    if not isinstance(content.get("methods"), list) or not content["methods"]:
        raise ValueError("상세 브리핑의 방법을 확인해 주세요.")
    for items, fields in ((content["pairs"], ("label", "method", "result")),
                         (content["methods"], ("label", "text"))):
        for item in items:
            if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip() for key in fields):
                raise ValueError("방법·결과 내용이 누락되었습니다.")
            source = item.get("source", {})
            if not source.get("label") or not str(source.get("url", "")).startswith("https://"):
                raise ValueError("방법·결과에는 원문 위치와 출처가 필요합니다.")
    references = content.get("references")
    if not isinstance(references, list) or not references or any(
            not isinstance(source, dict) or not source.get("label")
            or not str(source.get("url", "")).startswith("https://") for source in references):
        raise ValueError("카드의 출처를 확인해 주세요.")


def load_cards(directory=None):
    """Keep prepared cards independent of acquisition state, so they can be read offline."""
    directory = Path(directory) if directory else CARD_DIRECTORY
    files = sorted(directory.glob("*.json"))
    if not files:
        return {}
    snapshot = load_evaluation()
    candidates = {paper["id"]: paper for paper in snapshot["papers"]}
    result = {}
    for path in files:
        contents = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(contents, list):
            raise ValueError("카드 파일은 목록이어야 합니다.")
        for content in contents:
            validate_card(content)
            candidate_id = content["candidateId"]
            if candidate_id not in candidates or candidate_id in result:
                raise ValueError("카드의 논문 ID가 없거나 중복되었습니다.")
            paper = candidates[candidate_id]
            if (paper["reviewBasis"] == "abstract") != (content["basis"] == "abstract"):
                raise ValueError("카드의 본문·초록 표시가 검토 자료와 다릅니다.")
            brief = load_brief(candidate_id)
            review = load_review(candidate_id)
            abstract_source = next((source for source in paper["sources"] if source["kind"] == "abstract"), paper["sources"][0])
            title = paper["title"]
            date = paper.get("sourceDate", {}).get("date") or paper.get("date", "")
            card = {key: content[key] for key in ("purpose", "pairs", "significance", "application", "limits", "flow")}
            card["selectionReason"] = paper["selectionReason"]
            metadata = {"title": title, "translation": content["titleKo"], "authors": paper["authors"],
                        "journal": paper["journal"], "date": date, "doi": paper["doi"],
                        "categories": [paper["area"]], "tags": [paper["area"]],
                        "peerReview": "Peer-reviewed", "reviewStatus": REVIEW_LABELS[review["status"]],
                        "reviewedAt": review.get("checkedAt", ""), "sourceUrl": "https://doi.org/" + paper["doi"],
                        "pdfUrl": "", "siUrl": "", "availability": review["note"],
                        "license": "원논문의 권리는 저자·출판사에 있습니다. 한국어 해설과 연구 적용은 카드 작성자의 해석·제안입니다."}
            asset_manifest = ASSET_DIRECTORY / candidate_id / "sources.json"
            if asset_manifest.is_file():
                assets = json.loads(asset_manifest.read_text(encoding="utf-8"))
                metadata["pdfUrl"] = assets.get("pdfUrl", "")
                supplements = assets.get("supplements", [])
                metadata["siUrl"] = supplements[0].get("path", "") if supplements else ""
                if assets.get("license"):
                    metadata["license"] += f' 원본 자료: {assets["source"]} · {assets["license"]}. 그림은 원본 그대로 제공하며 한국어 해설을 별도로 작성했습니다.'
            for resource in ("pdfUrl", "siUrl"):
                if brief.get(resource):
                    metadata[resource] = brief[resource]
            figures = [block for section in brief["tabs"]["evidence"] for block in section["blocks"]
                       if block.get("type") == "figure" and block.get("image")]
            if figures:
                figure = figures[0]
                card["image"] = {"src": figure["image"], "alt": figure.get("alt", figure["title"]),
                                 "title": figure["title"], "caption": figure.get("description", ""),
                                 "source": figure["source"]}
            tabs = brief["tabs"]
            if review["status"] == "held":
                tabs = {tab: [{"title": "상세 브리핑 검토 보류",
                               "blocks": [{"type": "callout", "text": review["note"]}]}]
                        for tab in ("summary", "overview", "methods", "evidence")}
                card.pop("image", None)
            result[candidate_id] = {
                "id": candidate_id, "candidateId": candidate_id, "kind": "discovery", "metadata": metadata,
                "abstract": {"paragraphs": content["abstractKo"], "source": {"label": "출판 논문 Abstract", "url": abstract_source["url"]}},
                "card": card,
                "cardOrigin": {"basis": content["basis"], "evidenceNote": content["evidenceNote"], "preparedAt": "2026-09-21"},
                "briefOrigin": {"basis": brief["evidenceStatus"], "evidenceNote": review["note"], "review": review},
                "scoreSnapshot": {"score": paper["score"], "metrics": paper["metrics"], "observedAt": snapshot["evaluatedAt"]},
                "tabs": {**tabs, "memo": []},
            }
    return result
