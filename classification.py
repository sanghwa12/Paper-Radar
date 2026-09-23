"""Conservative article-type routing from existing metadata, without quality scoring."""
import re


LABELS = {"original": "원저", "review": "Review", "preprint": "Preprint · 보류",
          "other": "기타", "uncertain": "유형 확인 필요"}
REVIEW_TYPES = {"review", "review article", "systematic review", "meta analysis",
                "scoping review", "mini review"}
OTHER_TYPES = {"published erratum", "correction", "erratum", "retraction",
               "retraction of publication", "retracted publication", "expression of concern",
               "editorial", "comment", "news", "letter", "discussion", "meeting report",
               "abstract", "congress", "study guide", "clinical trial protocol", "study protocol"}
ORIGINAL_TYPES = {"research article", "original article", "original research",
                  "original research article", "clinical trial", "randomized controlled trial",
                  "controlled clinical trial", "pragmatic clinical trial", "observational study",
                  "comparative study", "validation study", "multicenter study", "case report",
                  "case reports", "case study", "methods article"}
REVIEW_TITLE = re.compile(
    r"\b(?:systematic|scoping|narrative|comprehensive|critical|mini|literature|state.of.the.art) review\b"
    r"|\bmeta.analysis\b|(?:^|:\s*)(?:a |an |the )?review(?:\s+of\b|\s+on\b|\s*[:.!?]?$)"
    r"|:\s*(?:a |an )?(?:focused |updated )?review(?:\s+(?:and|of|on)\b|\s*[.!?]?$)", re.I)
REVIEW_ABSTRACT = re.compile(
    r"\b(?:this|the present|our)\s+(?:(?:structured|systematic|scoping|narrative|comprehensive|current)\s+){0,2}review\b"
    r"|\b(?:we|this (?:article|paper))\s+(?:systematically\s+)?review(?:s)?\s+"
    r"(?:the (?:literature|current|recent|latest|existing|evidence)|recent|current|existing|advances|progress)\b"
    r"|\b(?:we|this (?:article|paper))\s+(?:present|provide|presents|provides)\s+"
    r"(?:a |an )?(?:comprehensive |systematic |scoping |narrative )?review\b", re.I)
OTHER_TITLE = re.compile(
    r"^(?:correction|erratum|corrigendum|retraction|retracted|editorial|comment(?:ary)?|"
    r"expression of concern)\s*(?::|\bto\b|\bon\b|$)"
    r"|\b(?:study|trial) protocol\b", re.I)
METHOD = re.compile(
    r"\b(?:we|this study|the present study|our study)\s+(?!(?:will|would|may|might|could|should|plan to|aim to)\b)"
    r"(?:\w+\s+){0,2}(?:develop(?:ed)?|design(?:ed)?|synthesi[sz](?:e|ed)|investigat(?:e|ed)|"
    r"evaluat(?:e|ed)|examin(?:e|ed)|analys(?:e|ed)|analyz(?:e|ed)|test(?:ed)?|"
    r"identif(?:y|ied)|introduc(?:e|ed)|propos(?:e|ed)|present(?:ed)?|report(?:ed)?|"
    r"demonstrat(?:e|ed)|show(?:ed)?|used|conduct(?:ed)?|assess(?:ed)?|executed|performed)\b"
    r"|\b(?:is|was|were)\s+(?:introduced|developed|designed|evaluated)\s+in this study\b"
    r"|\b(?:patients|participants|subjects|mice|animals)\s+(?:were\s+)?"
    r"(?:enrolled|randomi[sz]ed|assigned|treated)\b"
    r"|\b(?:methods|materials and methods)\s*:", re.I)
RESULT = re.compile(
    r"\b(?:we|(?:our|these|this) (?:results|findings|studies|study)|the results|results|findings|analysis|analyses|"
    r"experiments|simulations|data|assays|measurements)\s+(?!(?:will|would|may|might|could|should|are expected|is expected)\b)(?:\w+\s+){0,2}"
    r"(?:show(?:ed|s)?|demonstrat(?:e|ed|es)|reveal(?:ed|s)?|confirm(?:ed|s)?|"
    r"indicat(?:e|ed|es)|identified|found|achieved|delivered)\b"
    r"|\b(?:was|were)\s+(?:\w+\s+)?(?:identified|achieved|observed|reduced|increased|improved)\b"
    r"|\bresults\s*:\s*(?!will\b|are expected\b|will be\b)\S", re.I)


def _normalized(value):
    return re.sub(r"[\s_-]+", " ", str(value or "").strip().lower())


def _result(kind, reason, basis):
    return {"kind": kind, "label": LABELS[kind], "reason": reason, "basis": basis}


def classify_candidate(paper):
    """Return kind/label/reason/basis; inferred original research remains explicitly tentative."""
    raw_types = paper.get("publicationTypes") or []
    if isinstance(raw_types, str):
        raw_types = [raw_types]
    types = {_normalized(value) for value in raw_types}
    title = str(paper.get("title") or "").strip()
    abstract = str(paper.get("abstract") or "").strip()
    excluded = sorted(types & OTHER_TYPES)
    if excluded:
        return _result("other", f"출판 유형이 {excluded[0]}로 표시되어 있습니다.", "publication_type")
    if str(paper.get("source") or "").upper() == "PPR":
        return _result("preprint", "Europe PMC의 Preprint 자료로, 정식 원저 선정은 보류합니다.", "source")
    if "preprint" in types or "preprint article" in types:
        return _result("preprint", "출판 유형이 Preprint로 표시되어 있어 선정을 보류합니다.", "publication_type")
    reviews = sorted(types & REVIEW_TYPES)
    if reviews:
        return _result("review", f"출판 유형이 {reviews[0]}로 표시되어 있습니다.", "publication_type")
    # A correction/protocol title can be more specific than the generic research-article tag.
    if OTHER_TITLE.search(title):
        return _result("other", "제목에 정정·논평 또는 연구 계획서 유형이 명시되어 있습니다.", "title")
    originals = sorted(types & ORIGINAL_TYPES)
    trials = sorted(value for value in types if re.fullmatch(r"clinical trial, phase (?:i|ii|iii|iv)", value))
    if originals or trials:
        return _result("original", f"출판 유형이 {(originals or trials)[0]}로 표시되어 있습니다.", "publication_type")
    if REVIEW_TITLE.search(title):
        return _result("review", "제목에 Review 또는 메타분석 유형이 명시되어 있습니다.", "title")
    if REVIEW_ABSTRACT.search(abstract):
        return _result("review", "초록이 이 논문을 문헌 검토·Review로 소개합니다.", "abstract")
    if METHOD.search(abstract) and RESULT.search(abstract):
        return _result("original", "초록에 수행한 연구와 결과가 있어 원저로 잠정 분류했습니다. 본문 확인 전입니다.", "abstract")
    if not abstract:
        return _result("uncertain", "초록이나 명확한 출판 유형이 없어 원저 여부를 확인할 수 없습니다.", "insufficient_metadata")
    return _result("uncertain", "현재 출판 유형과 초록만으로 원저·Review를 확정하기 어렵습니다.", "insufficient_metadata")
