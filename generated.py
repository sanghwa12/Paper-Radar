"""Publish explicitly approved, hash-bound Codex drafts without calling a model."""
import logging
from pathlib import Path

from generation import (KINDS, asset_file, digest, display_draft, read_json, require,
                        text, validate_draft, validate_input)

DIRECTORY = Path(__file__).resolve().parent / "data" / "generated"
LOGGER = logging.getLogger(__name__)


def load_publication(directory):
    paths = {name: directory / f"{name}.json" for name in ("input", "draft", "review", "publication")}
    publication = read_json(paths["publication"])
    require(publication.get("schemaVersion") == 1, "게시 기록 형식을 확인하세요.")
    require(publication.get("generation", {}).get("mode") == "codex-assisted", "생성 방식을 확인하세요.")
    require(text(publication.get("publishedAt")), "게시 시각이 없습니다.")
    for name in ("input", "draft", "review"):
        require(digest(paths[name]) == publication.get(name + "Sha256"),
                f"게시 승인 이후 {name} 자료가 변경됐습니다.")
    package, draft, review = (read_json(paths[name]) for name in ("input", "draft", "review"))
    candidate_id = package.get("candidateId")
    require(text(candidate_id) and publication.get("candidateId") == candidate_id == review.get("candidateId"),
            "게시·입력·검증 기록의 논문 ID가 다릅니다.")
    require(all(review.get(name + "Sha256") == publication[name + "Sha256"] for name in ("input", "draft")),
            "현재 입력·초안에 대한 검증 기록이 아닙니다.")
    require(review.get("status") == "partial", "일부 검증된 초안만 게시할 수 있습니다. 미검증·보류·완료 표시는 게시하지 않습니다.")
    require(text(review.get("summary")), "검증 범위 설명이 없습니다.")
    checks = review.get("checks")
    require(isinstance(checks, list) and checks and all(
        isinstance(check, dict) and check.get("status") in ("pass", "unverified")
        and text(check.get("label")) and text(check.get("note")) for check in checks)
        and any(check["status"] == "pass" for check in checks), "검증 실패 또는 누락된 검증 항목이 있습니다.")
    require(isinstance(review.get("unresolved"), list) and all(text(item) for item in review["unresolved"]),
            "미확인 사항 기록을 확인하세요.")
    holds = review.get("holds")
    require(isinstance(holds, list) and all(isinstance(hold, dict) and hold.get("reason") in ("source", "safety")
            and text(hold.get("scope")) and text(hold.get("note")) for hold in holds), "보류 범위 기록을 확인하세요.")

    sources = validate_input(package)
    validate_draft(draft, package, sources)
    assets = package.get("assets")
    require(isinstance(assets, list) and assets, "복사한 원본 자료 기록이 없습니다.")
    urls = set()
    for asset in assets:
        url = asset.get("localUrl", "")
        require(isinstance(url, str) and url.startswith(f"/assets/briefs/{candidate_id}/")
                and url not in urls, "독립 보관한 원본 자료 경로가 없거나 중복되었습니다.")
        require(digest(asset_file(url)) == asset.get("sha256"), "보관 원본 자료의 해시가 다릅니다.")
        urls.add(url)
    require(all(not source.get("asset") or source["asset"] in urls for source in sources.values()),
            "입력 자료가 보관 원본 목록에 없습니다.")
    acquired, checked = {}, {}
    for kind in KINDS:
        scope = "figures" if kind == "figure" else kind
        acquired[scope] = any(source["kind"] == kind for source in sources.values())
        checked[scope] = review.get("checked", {}).get(kind)
        require(checked[scope] in ("reviewed", "partial", "unverified", "unavailable"), "자료 검토 범위를 확인하세요.")
        require(acquired[scope] or checked[scope] not in ("reviewed", "partial"),
                "확보하지 않은 자료를 검토했다고 표시할 수 없습니다.")
    require(checked["body"] in ("reviewed", "partial"), "본문 검토 기록 없이 본문 기반 카드를 게시할 수 없습니다.")

    metadata = package.get("metadata", {})
    require(all(text(metadata.get(key)) for key in ("title", "authors", "journal", "date", "url")),
            "논문 서지 정보가 없습니다.")
    categories = metadata.get("categories")
    require(isinstance(categories, list) and categories and all(text(value) for value in categories),
            "논문 분야 정보가 없습니다.")
    display = display_draft(draft, sources)
    paper_metadata = {
        "title": metadata["title"], "translation": draft["card"]["titleKo"],
        "authors": metadata["authors"], "journal": metadata["journal"], "date": metadata["date"],
        "doi": metadata.get("doi", ""), "categories": categories, "tags": categories,
        "peerReview": "Peer-reviewed", "reviewStatus": "일부 검증 · 초안",
        "reviewedAt": review.get("checkedAt", ""), "sourceUrl": metadata["url"],
        "pdfUrl": next((asset["localUrl"] for asset in assets if asset.get("kind") == "paper"), ""),
        "siUrl": next((asset["localUrl"] for asset in assets if asset.get("kind") == "supplement"), ""),
        "availability": review["summary"],
        "license": metadata.get("license", "") + " · 그림은 원본 그대로 제공하며 한국어 해설·추론은 별도로 작성했습니다.",
    }
    display_review = {"status": review["status"], "checkedAt": review.get("checkedAt", ""),
                      "note": review["summary"], "acquired": acquired, "checked": checked,
                      "holds": holds, "checks": checks, "unresolved": review["unresolved"]}
    return {
        "id": candidate_id, "candidateId": candidate_id, "kind": "discovery", "metadata": paper_metadata,
        "card": display["card"], "abstract": display["abstract"], "tabs": {**display["tabs"], "memo": []},
        "cardOrigin": {"basis": "fulltext", "evidenceNote": review["summary"], "preparedAt": publication["publishedAt"]},
        "briefOrigin": {"basis": "partial", "evidenceNote": review["summary"], "review": display_review},
        "generationOrigin": {**publication["generation"], "publishedAt": publication["publishedAt"],
                             **{name + "Sha256": publication[name + "Sha256"] for name in ("input", "draft", "review")}},
    }


def load_generated(directory=None, existing_ids=()):
    """Ignore unpublished drafts; report invalid publications without replacing existing papers."""
    result = {}
    for publication in sorted(Path(directory or DIRECTORY).glob("*/publication.json")):
        try:
            paper = load_publication(publication.parent)
            require(paper["id"] not in existing_ids and paper["id"] not in result,
                    "이미 등록된 논문을 생성 초안으로 덮어쓸 수 없습니다.")
            result[paper["id"]] = paper
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
            LOGGER.warning("생성 브리핑 게시 보류 [%s]: %s", publication.parent.name, error)
    return result
