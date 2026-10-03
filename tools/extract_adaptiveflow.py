"""One-time conversion of the reviewed AdaptiveFlow prototype into content data."""

import datetime
import html
import json
import platform
import re
import sys
from pathlib import Path

import bs4
from bs4 import BeautifulSoup, NavigableString

SEED = 0
print(f"# run {datetime.datetime.now():%Y-%m-%d %H:%M} | python {platform.python_version()} | seed {SEED} | argv {sys.argv[1:]}")
print(f"# beautifulsoup4 {bs4.__version__}")

ROOT = Path(__file__).resolve().parents[1]
brief = BeautifulSoup((ROOT / "reference/adaptiveflow-2026-brief.html").read_text(encoding="utf-8"), "html.parser")
card = BeautifulSoup((ROOT / "reference/adaptiveflow-2026-card.html").read_text(encoding="utf-8"), "html.parser")


def url(value):
    return value if value.startswith(("https://", "http://", "#", "/")) else "/reference/" + value


def inline(node):
    if node is None:
        return ""
    if isinstance(node, NavigableString):
        return html.escape(str(node), quote=False)
    contents = "".join(inline(child) for child in node.children)
    if node.name in ("b", "strong", "em", "sub", "sup"):
        return f"<{node.name}>{contents}</{node.name}>"
    if node.name == "br":
        return "<br>"
    if node.name == "a":
        if node.get("href") == "adaptiveflow-assets/summary-flow.svg" and node.has_attr("download"):
            contents = "SVG 원본 보기"
        return '<a href="' + html.escape(url(node["href"]), quote=True) + '">' + contents + "</a>"
    return contents.strip()


def source(node):
    return {"label": node.get_text(" ", strip=True), "url": url(node["href"])} if node else None


def title(node):
    return node.get_text(" ", strip=True) if node else ""


def pairs(node):
    return [{"label": inline(dt), "text": inline(dt.find_next_sibling("dd"))} for dt in node.select("dt")]


def figure(node):
    image = node.select_one("img")
    original = node.select_one(".original-caption")
    explanations = pairs(node.select_one(".figure-explanation dl"))
    note = node.select_one(".caption-note")
    if note:
        explanations.append({"label": "설명 기준", "text": inline(note)})
    return {
        "type": "figure", "id": node.get("id"),
        "title": title(node.select_one(".figure-caption h3")),
        "eyebrow": title(node.select_one(".eyebrow")),
        "image": url(image["src"]), "alt": image.get("alt", ""),
        "description": "<br>".join(inline(p) for p in node.select(".figure-caption p")),
        "explanation": explanations,
        "caption": "<br><br>".join(inline(p) for p in original.select("p")),
        "source": source(original.select_one("a")),
    }


def ligands(node):
    items = []
    for article in node.select(".ligand-card"):
        image = article.select_one("img")
        items.append({"title": title(article.select_one("h3")), "image": url(image["src"]),
                      "alt": image.get("alt", ""), "text": inline(article.select_one("p")),
                      "source": source(article.select_one("a"))})
    return {"type": "ligands", "items": items}


def blocks(node, skip_heading=False):
    result = []
    for child in node.children:
        if isinstance(child, NavigableString):
            if str(child).strip():
                result.append({"type": "paragraph", "text": inline(child)})
            continue
        classes = child.get("class", [])
        if child.name in ("summary", "label", "textarea") or child.get("id") == "status":
            continue
        if any(name in classes for name in ("methods-nav", "figure-index", "goto-figure")):
            continue
        if child.name in ("h2", "h3") and skip_heading:
            skip_heading = False
            continue
        if "figure-sheet" in classes:
            result.append(figure(child))
        elif "ligand-grid" in classes:
            result.append(ligands(child))
        elif child.name == "details":
            result.append({"type": "details", "title": title(child.select_one("summary")), "blocks": blocks(child)})
        elif child.name == "table":
            rows = child.select("tr")
            result.append({"type": "table", "headers": [inline(c) for c in rows[0].select("th")],
                           "rows": [[inline(c) for c in row.select("td")] for row in rows[1:]]})
        elif child.name == "dl":
            result.append({"type": "pairs", "items": pairs(child)})
        elif "evidence-line" in classes:
            result.append({"type": "pairs", "items": [{"label": inline(child.select_one(".label")), "text": inline(child.select_one("p"))}]})
        elif child.name in ("p", "small"):
            text = inline(child)
            if child.find_parent("details", class_="technical") and child.find("b", recursive=False):
                text = text.replace("</b>", "</b><br>", 1)
            result.append({"type": "callout" if "summary-scope" in classes else "paragraph", "text": text})
        elif child.name in ("h2", "h3", "h4"):
            result.append({"type": "paragraph", "text": "<strong>" + inline(child) + "</strong>"})
        elif child.name in ("ul", "ol"):
            result.append({"type": "list", "ordered": child.name == "ol", "items": [inline(li) for li in child.find_all("li", recursive=False)]})
        elif child.name == "button" and child.select_one("img"):
            image = child.select_one("img")
            result.append({"type": "image", "src": url(image["src"]), "alt": image.get("alt", ""), "caption": child.get("data-title", "")})
        elif child.name == "a":
            result.append({"type": "links", "items": [source(child)]})
        elif child.name != "button":
            result.extend(blocks(child))
    return result


def section(node):
    heading = node.find(["h2", "h3"], recursive=False)
    result = {"title": title(heading), "blocks": blocks(node, skip_heading=heading is not None)}
    if node.get("id"):
        result["id"] = node["id"]
    return result


tabs = {name: [] for name in ("summary", "overview", "methods", "evidence", "memo")}
for name in tabs:
    for child in brief.select_one("#panel-" + name).find_all(recursive=False):
        classes = child.get("class", [])
        if "abstract-summary" in classes or "methods-nav" in classes:
            continue
        if "experiment-grid" in classes:
            tabs[name].extend(section(article) for article in child.select(".experiment"))
        elif child.name == "details":
            tabs[name].append({"title": "", "blocks": [{"type": "details", "title": title(child.select_one("summary")), "blocks": blocks(child)}]})
        elif child.name == "p":
            tabs[name].append({"title": "그림 출처·라이선스", "blocks": [{"type": "paragraph", "text": inline(child)}]})
        else:
            tabs[name].append(section(child))

abstract_node = brief.select_one(".abstract-summary")
card_pairs = []
for item in card.select(".pairs > div"):
    full = inline(item.select_one("dd"))
    method, result = full.split("→", 1)
    card_pairs.append({"label": inline(item.select_one("dt")), "method": method.strip(), "result": result.strip()})
card_image = card.select_one(".ligand img")
card_caption = inline(card.select_one(".ligand figcaption")).replace("</strong>", "</strong><br>", 1)
card_caption = card_caption.replace(inline(card.select_one(".ligand .source")), "<br>" + inline(card.select_one(".ligand .source")))
meaning = card.select(".meaning .line p")
data = {
    "id": "adaptiveflow-2026",
    "metadata": {
        "title": brief.select_one("h1").get_text(strip=True),
        "translation": brief.select_one(".original").get_text(strip=True),
        "authors": "Cecchini 외", "journal": "Nature Biotechnology", "date": "2026-09-01",
        "doi": "10.1038/s41587-026-03217-x", "categories": ["CADD·AI", "Medicinal chemistry", "실험·평가 기술"],
        "tags": [tag.get_text(strip=True) for tag in card.select(".tag")],
        "peerReview": "Peer-reviewed", "reviewStatus": "검토 완료", "reviewedAt": "2026-09-16",
        "sourceUrl": "https://www.nature.com/articles/s41587-026-03217-x",
        "pdfUrl": "/reference/adaptiveflow-assets/paper.pdf", "siUrl": "/reference/adaptiveflow-assets/supplement.pdf",
        "availability": "본문·SI·Figure·구조식 로컬 확보",
        "license": '© The Author(s) 2026 · <a href="https://creativecommons.org/licenses/by-nc-nd/4.0/">CC BY-NC-ND 4.0</a>. 한국어 해설·연구 적용은 심층 분석의 해석과 제안.'
    },
    "abstract": {"paragraphs": [inline(p) for p in abstract_node.find_all("p", recursive=False)],
                 "source": {"label": "p.1 · Abstract 원문", "url": "/reference/adaptiveflow-assets/paper.pdf#page=1"},
                 "pageImage": "/reference/adaptiveflow-assets/abstract-page-01.png"},
    "card": {
        "purpose": inline(card.select_one(".purpose p")), "pairs": card_pairs,
        "significance": inline(meaning[0]), "application": inline(meaning[1]),
        "limits": inline(card.select_one(".caution")),
        "image": {"src": url(card_image["src"]), "alt": card_image["alt"],
                  "caption": card_caption,
                  "source": {"label": "Table 1 · p.8", "url": "/reference/adaptiveflow-assets/paper.pdf#page=8"}},
        "selectionReason": card.select_one(".foot").get_text(strip=True).removeprefix("선정 이유: ")
    },
    "tabs": tabs,
}
output = ROOT / "data/papers/adaptiveflow.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
serialized = json.dumps(data, ensure_ascii=False)
missing = []
for match in set(re.findall(r'/reference/[^\s"<>]+', serialized)):
    relative = html.unescape(match).split("#", 1)[0].rstrip("\\")
    if not (ROOT / relative.lstrip("/")).is_file():
        missing.append(relative)
print(f"Saved {output}")
print(f"Abstract paragraphs: {len(data['abstract']['paragraphs'])}; figures: {serialized.count(chr(34) + 'type' + chr(34) + ': ' + chr(34) + 'figure' + chr(34))}; ligand structures: {len(brief.select('.ligand-card'))}")
print(f"Sections by tab: { {name: len(sections) for name, sections in tabs.items()} }")
print(f"Missing local assets: {missing}")
assert not missing
