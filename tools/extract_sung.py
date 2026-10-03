"""Convert the reviewed Sung prototype into the common paper data schema."""

import datetime
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import platform
import re
import sys

SEED = 0
print(f"# run {datetime.datetime.now():%Y-%m-%d %H:%M} | python {platform.python_version()} | seed {SEED} | argv {sys.argv[1:]}")
print("# dependencies Python standard library")

ROOT = Path(__file__).resolve().parents[1]


class Element:
    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or [])
        self.children = []

    def all(self, tag=None, cls=None, ident=None):
        found = []
        for child in self.children:
            if not isinstance(child, Element):
                continue
            if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get("class", "").split()) and (ident is None or ident == child.attrs.get("id")):
                found.append(child)
            found.extend(child.all(tag, cls, ident))
        return found

    def one(self, tag=None, cls=None, ident=None):
        return next(iter(self.all(tag, cls, ident)), None)


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"img", "br", "hr", "input", "meta", "link", "source", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def url(value):
    return value if value.startswith(("https://", "http://", "#", "/")) else "/reference/" + value


def inline(node):
    if isinstance(node, str):
        return html.escape(node, quote=False)
    text = "".join(inline(c) for c in node.children)
    if node.tag == "a":
        href = url(node.attrs.get("href", "#"))
        return f'<a href="{html.escape(href, quote=True)}">{text}</a>'
    if node.tag in {"b", "strong", "em", "sub", "sup"}:
        return f"<{node.tag}>{text}</{node.tag}>"
    if node.tag == "br":
        return "<br>"
    return text


def rich(node):
    return re.sub(r"\s+", " ", inline(node)).strip()


def plain(node):
    return html.unescape(re.sub(r"<[^>]+>", "", rich(node)))


def blocks(node):
    output = []
    for item in node.children:
        if not isinstance(item, Element):
            continue
        if item.tag in {"h2", "h3", "summary", "button", "textarea", "label", "nav"}:
            continue
        if item.tag == "table":
            rows = item.all("tr")
            headers = [rich(c) for c in rows[0].children if isinstance(c, Element) and c.tag in {"th", "td"}]
            output.append({"type": "table", "headers": headers, "rows": [[rich(c) for c in row.children if isinstance(c, Element) and c.tag in {"th", "td"}] for row in rows[1:]]})
        elif item.tag == "details":
            output.append({"type": "details", "title": plain(item.one("summary")), "blocks": blocks(item)})
        elif item.tag in {"ol", "ul"}:
            output.append({"type": "list", "ordered": item.tag == "ol", "items": [rich(c) for c in item.children if isinstance(c, Element) and c.tag == "li"]})
        elif item.tag == "dl":
            output.append({"type": "pairs", "items": [{"label": plain(c.one("dt")), "text": rich(c.one("dd"))} for c in item.children if isinstance(c, Element) and c.one("dt")]})
        elif item.tag == "img":
            output.append({"type": "image", "src": url(item.attrs["src"]), "alt": item.attrs.get("alt", "")})
        elif item.tag in {"p", "small", "a"}:
            text = rich(item)
            if text:
                output.append({"type": "callout" if set(item.attrs.get("class", "").split()) & {"insight", "short-warning"} else "paragraph", "text": text})
        else:
            output.extend(blocks(item))
    return output


parser = Parser()
parser.feed((ROOT / "reference/sung-2025-brief.html").read_text(encoding="utf-8"))
doc = parser.root
summary = doc.one(ident="panel-summary")
overview = doc.one(ident="panel-overview")
methods = doc.one(ident="panel-methods")
evidence = doc.one(ident="panel-evidence")
memo = doc.one(ident="panel-memo")
experiments = overview.all("article", cls="experiment")

paper = {
    "id": "sung-2025",
    "metadata": {
        "title": "Targeting cancer glutamine dependency with a first-in-class inhibitor of the mitochondrial glutamine transporter SLC1A5_var",
        "translation": "미토콘드리아 glutamine transporter SLC1A5_var의 first-in-class 억제제로 암의 glutamine 의존성 표적화",
        "authors": "Yulseung Sung 외 · 교신저자 Jung Min Han",
        "journal": "Nature Communications 16, 9690",
        "date": "2025-11-03",
        "doi": "10.1038/s41467-025-64730-2",
        "categories": ["Medicinal chemistry", "CADD·AI", "Target·기전"],
        "tags": ["SLC1A5_var", "Cancer metabolism", "Virtual screening", "Immunotherapy"],
        "peerReview": "Peer reviewed",
        "reviewStatus": "기존 수동 검토본 기반",
        "reviewedAt": "2026-09-14",
        "sourceUrl": "https://www.nature.com/articles/s41467-025-64730-2",
        "pdfUrl": "/reference/source-paper.pdf",
        "siUrl": None,
        "availability": "본문 PDF 확보 · 별도 SI·Source Data 미확보/미검토",
        "license": "© The Author(s) 2025 · CC BY-NC-ND 4.0",
    },
    "abstract": {
        "paragraphs": [
            "미토콘드리아 glutamine transporter SLC1A5_var는 에너지 생산과 redox homeostasis를 위해 glutamine의 미토콘드리아 유입을 촉진함으로써 암세포의 metabolic reprogramming에서 중심적인 역할을 한다. 이처럼 중요한 기능에도 불구하고, SLC1A5_var를 표적으로 하는 효과적이고 선택적인 억제제의 개발은 여전히 중대한 과제로 남아 있다.",
            "이 연구에서는 structure-based screening으로 확인한 선택적 allosteric inhibitor인 iMQT_020을 소개한다. iMQT_020은 SLC1A5_var의 trimeric assembly를 붕괴시켜 암세포에 metabolic crisis를 유발하고 암세포의 성장을 선택적으로 억제한다. 기전적으로 iMQT_020은 glutamine anaplerosis와 oxidative phosphorylation을 감소시켜 암 대사를 광범위하게 교란한다.",
            "또한 iMQT_020 처리는 epigenetic 기전을 통해 PD-L1 발현을 증가시켜 anti-PD-L1 immune checkpoint inhibitor와의 병용요법 효과를 높인다. 이러한 결과는 암의 핵심적인 대사 취약점인 SLC1A5_var를 표적으로 삼는 치료 가능성을 부각하며, allosteric interprotomer interaction을 표적으로 하는 것이 암 치료를 위한 새롭고 유망한 치료 전략임을 보여준다.",
        ],
        "source": {"label": "Abstract 전문 번역 · 저자 주장 · 본문 p.1", "url": "/reference/source-paper.pdf#page=1"},
        "pageImage": "/assets/sung/source-page-01.png",
    },
    "card": {
        "purpose": rich(summary.one(cls="purpose-summary").one("p")),
        "pairs": [],
        "significance": "Glutamine 대사를 세포 유입이나 대사효소 대신 미토콘드리아 수송체의 protein interface에서 제어하고, anti-PD-L1 병용으로 확장한 접근이다.",
        "application": "예측 구조에 생화학 제약을 반영하고, docking 이후 binding·transport·rescue assay를 연결하는 검증 설계에 참고할 수 있다.",
        "limits": "실측 복합체 구조는 없으며 binding affinity와 transport IC₅₀를 구분해야 한다. 별도 SI는 미검토이고, 사람 대상 치료 효과·경구 노출·장기 안전성은 확립하지 않았다.",
        "image": {"src": "/assets/sung/ligand-imqt-020.png", "alt": "논문 Figure 1D의 iMQT_020 원본 화학구조", "caption": "iMQT_020 · Fig. 1D 원본 구조 · transport IC₅₀ 6.156 μM / MST Kd 4.473 μM", "source": '<a href="/reference/source-paper.pdf#page=3">본문 Fig. 1D, G, L · p.3</a>'},
        "selectionReason": "구조 예측과 virtual screening의 후보를 binding·transport·대사·세포·동물 실험으로 연결해 평가하는 사례.",
    },
    "tabs": {"summary": [], "overview": [], "methods": [], "evidence": [], "memo": []},
}

for experiment in (experiments[0], experiments[1], experiments[-1]):
    lines = experiment.all(cls="evidence-line")
    paper["card"]["pairs"].append({"label": plain(experiment.one("h3")), "method": rich(lines[0].one("p")), "result": rich(lines[1].one("p")), "source": rich(experiment.one("p", cls="ref"))})

paper["tabs"]["summary"] = [
    {"title": "연구 목적", "blocks": blocks(summary.one(cls="purpose-summary"))},
    {"id": "research-flow", "title": "연구 흐름", "blocks": [{"type": "image", "src": "/reference/evidence-map.svg", "alt": "구조 예측부터 가상 스크리닝, 결합과 수송, 대사, 세포, 동물 실험으로 이어지는 연구 흐름도", "caption": "구조 예측 → 후보 선별 → 결합·수송 → 대사 → 세포·동물 반응", "source": "제공된 수동 검토 심층 분석의 연구 흐름도"}]},
    {"title": "주요 결과", "blocks": blocks(summary.one(cls="findings-summary"))},
    {"title": "Ligand structure", "blocks": [{"type": "image", "src": "/assets/sung/ligand-imqt-020.png", "alt": "본문 Figure 1D에 제시된 iMQT_020 원본 구조식", "caption": "iMQT_020 · 원문 Fig. 1D에서 가져온 구조식. 추정 구조를 새로 그리지 않았다.", "source": '<a href="/reference/source-paper.pdf#page=3">본문 Fig. 1D · p.3</a> · © The Author(s) 2025 · CC BY-NC-ND 4.0'}, {"type": "pairs", "items": [{"label": "직접 결합", "text": "MST, 정제 eGFP-SLC1A5_var WT: K<sub>d</sub> 4.473 μM. F97A/I104A/L105A mutant에서는 결합 상수 산출 불가."}, {"label": "Transport 억제", "text": "Mitochondrial glutamine uptake IC₅₀: iMQT_020 6.156 μM, 비교약 V-9302 16.406 μM. <a href=\"/reference/source-paper.pdf#page=3\">Fig. 1G–H, L · p.3</a>"}, {"label": "세포 반응", "text": "MIA PaCa-2 IC₅₀ 13.15 μM는 본문이 인용한 별도 농도반응 보고값이다. Suppl. Fig. 6C 원자료는 미검토. <a href=\"/reference/source-paper.pdf#page=9\">Results p.9</a>"}]}, {"type": "callout", "text": "결합 Kd, 수송 IC₅₀, 세포 IC₅₀는 서로 다른 assay의 지표다. 후속 analog 또는 대사체의 검증된 구조 자료는 이번 제공 자료에서 별도로 확보하지 않았다."}]},
]
paper["tabs"]["overview"].append({"title": "방법과 결과", "blocks": blocks(overview.one(cls="research-intro"))})
for n, experiment in enumerate(experiments):
    lines = experiment.all(cls="evidence-line")
    page = [2, 4, 4, 6, 10, 12][n]
    section = {"title": plain(experiment.one("h3")), "blocks": [{"type": "pairs", "items": [{"label": plain(line.one(cls="label")), "text": rich(line.one("p"))} for line in lines]}, {"type": "paragraph", "text": rich(experiment.one("p", cls="ref")) + f' · <a href="/reference/source-paper.pdf#page={page}">근거 페이지 보기</a>'}]}
    technical = experiment.one("details")
    section["blocks"].append({"type": "details", "title": plain(technical.one("summary")), "blocks": blocks(technical)})
    paper["tabs"]["overview"].append(section)
paper["tabs"]["overview"].append({"title": "연구 의의", "blocks": blocks(overview.one(cls="trend")) + [{"type": "callout", "text": rich(overview.one(cls="short-warning"))}]})

for ident in ("m-software", "m-cells", "m-assays"):
    section = methods.one(ident=ident)
    paper["tabs"]["methods"].append({"id": ident, "title": plain(section.one("h3")), "blocks": blocks(section)})
paper["tabs"]["methods"].insert(0, {"title": "Methods 근거", "blocks": [{"type": "paragraph", "text": "본문 Methods에서 확인한 실제 사용 도구·모델·조건이다. Version은 기재된 경우만 표시한다. 원문에 없는 조건은 추정하지 않았으며, 별도 SI·Source Data는 미확보/미검토 상태다."}]})

figure_pages = [3, 6, 8, 10, 12, 14, 16]
for n, figure in enumerate(evidence.all("article", cls="figure-sheet"), 1):
    caption = figure.one(cls="figure-caption")
    img = figure.one("img")
    source = f'<a href="/reference/source-paper.pdf#page={figure_pages[n-1]}">본문 Fig. {n} · p.{figure_pages[n-1]}</a> · © The Author(s) 2025 · <a href="https://creativecommons.org/licenses/by-nc-nd/4.0/">CC BY-NC-ND 4.0</a>'
    paper["tabs"]["evidence"].append({"id": f"figure-{n}", "title": f"Figure {n} · {plain(caption.one('h3'))}", "blocks": [{"type": "image", "src": f"/assets/sung/figure-{n}.png", "alt": plain(caption.one("h3")), "caption": rich(caption.one("p")) + "<br>" + rich(caption.one("small")), "source": source}]})
limits = evidence.one(ident="limits")
paper["tabs"]["evidence"].append({"id": "limits", "title": plain(limits.one("h2")), "blocks": blocks(limits)})
paper["tabs"]["evidence"].append({"title": "출처와 검토 범위", "blocks": [{"type": "paragraph", "text": "제공 PDF 기반 · 기존 심층 분석 검토 2026-09-14 · 접수 2025-06-03 / 게재 승인 2025-09-22. 별도 Supplementary Figures·SI·Source Data는 확보되지 않아 독립 검토하지 않았다."}, {"type": "paragraph", "text": '원문 및 그림: Sung et al., Nature Communications 16, 9690 (2025). © The Author(s) 2025 · <a href="https://creativecommons.org/licenses/by-nc-nd/4.0/">CC BY-NC-ND 4.0</a>. 한글 해설과 연구 적용 제안은 심층 분석의 해석이다.'}]})
paper["tabs"]["memo"].append({"title": "연구 적용", "blocks": [{"type": "pairs", "items": [{"label": plain(c.one("h3")), "text": rich(c.one("p"))} for c in memo.one(cls="columns").children if isinstance(c, Element)]}]})

source_extract = json.loads((ROOT / "data/sung-source-extract.json").read_text(encoding="utf-8-sig"))
paper["abstract"]["originalEnglish"] = source_extract["abstractEn"]
figure_reading = [
    [
        {"label": "패널·축", "text": "C는 103개 후보의 mitochondrial glutamine uptake(%), H는 ligand log[M]에 따른 MST ΔF norm, K는 SEC retention volume(mL)에 따른 GFP fluorescence, L은 농도에 따른 ³H-Gln uptake를 보여준다."},
        {"label": "색상·해석", "text": "L·N·O에서 녹색은 V-9302, 빨강은 iMQT_020이다. H의 빨간 WT는 결합 곡선을 보이고 검은 FIL/AAA는 Kd 산출 불가다. N은 미토콘드리아, O는 세포 전체 uptake이므로 선택성 해석에서 두 구획을 구분한다."},
    ],
    [
        {"label": "패널·축", "text": "A의 파란 원은 ¹³C, 흰 원은 ¹²C이다. B–K의 x축은 처리 시간(0/12/24 h), y축은 표지 metabolite의 total ion counts이다. L–O는 상대 GSH·ROS·mitochondrial ROS·ATP 수준을 비교한다."},
        {"label": "색상·해석", "text": "L–O에서 회색 vehicle, 빨강 iMQT_020, 녹색 iMQT_020 + DM-αKG를 비교한다. 약물로 변한 redox·ATP 지표가 rescue 조건에서 vehicle 방향으로 돌아간다. Total ion counts의 감소를 정량적 flux 감소율로 치환하지 않는다."},
    ],
    [
        {"label": "패널·축", "text": "A–N은 시간(min)에 따른 OCR 또는 ECAR와 조건별 요약값을 짝지어 제시한다. OCR은 산소 소비, ECAR는 extracellular acidification 지표다. E–F는 DM-αKG rescue, M–N은 분리 미토콘드리아 실험이다."},
        {"label": "색상·해석", "text": "WT·FIL/AAA와 vehicle·iMQT_020의 색은 각 패널 범례를 따른다. O–P에서는 회색 vehicle, 빨강 iMQT_020, 녹색 DM-αKG 병용이다. P의 x축 ECAR·y축 OCR에서 약물 처리군은 낮은 대사활성 쪽으로 이동하고 rescue군은 일부 회복한다."},
    ],
    [
        {"label": "패널·축", "text": "B의 x축은 개별 세포주, y축은 viability 변화(%): 녹색 V-9302, 빨강 iMQT_020이다. C–D와 G는 SLC1A5_var expression과 효능의 상관, F는 organoid 영상과 viability(%), H는 대사·cell death rescue 조건을 비교한다."},
        {"label": "읽는 기준", "text": "B는 10 μM·48 h 단일 농도 비교다. G의 iMQT_020 상관 r = −0.6740은 10개 organoid의 관찰값이며 임상 biomarker 검증은 아니다. F의 48 h 표기와 Methods의 5 days를 구분한다."},
    ],
    [
        {"label": "패널·축", "text": "C·J·N은 날짜에 따른 tumor volume(mm³), D·K·O는 최종 tumor weight(mg), F는 날짜에 따른 bioluminescence 지표다. A–G는 췌장암, H–K는 폐암, L–O는 대장암 xenograft이다."},
        {"label": "색상·해석", "text": "회색 vehicle, 녹색 V-9302, 빨강 iMQT_020이다. 처리군의 종양 성장·무게 감소와 P–R의 cCas3·4-HNE·Cyclin D1·Ki-67 조직 신호를 함께 읽는다. 이 Figure의 단독 효능 75 mg/kg 조건을 Fig. 7의 병용 25 mg/kg과 섞지 않는다."},
    ],
    [
        {"label": "패널·축", "text": "A–C의 y축은 ACTB로 정규화한 상대 PD-L1 expression이다. D는 PD-L1-PE fluorescence 분포와 양성 세포 gate, E는 PD-L1 promoter의 H3K4me3 enrichment(% input)를 보여준다."},
        {"label": "색상·해석", "text": "C에서 회색 vehicle, 빨강 iMQT_020, 녹색 DM-αKG 추가 조건이다. 보라색은 그림의 +/− 표기상 iMQT_020 + DM-αKG + CPI-455 조건이며, caption의 ‘DM-αKG or CPI-455’ 표현과 구분해 확인한다. E의 회색·빨강·녹색은 vehicle·iMQT_020·DM-αKG rescue이다. B는 세포주별 반응이 다르므로 모든 세포주에서 일관되게 증가했다고 읽지 않는다."},
    ],
    [
        {"label": "패널·축", "text": "B·E·H는 날짜에 따른 tumor volume(mm³), C·F·I는 최종 tumor weight(mg)이다. K–L은 Ki-67/cCas3 양성 세포, N–W는 종양 및 면역세포 집단별 비율을 비교한다."},
        {"label": "색상·해석", "text": "회색 vehicle, 녹색 anti-PD-L1, 노랑 V-9302, 빨강 iMQT_020, 파랑 anti-PD-L1 + V-9302, 보라색 anti-PD-L1 + iMQT_020이다. 병용군에서 종양 억제와 CD8⁺ T-cell 기능 지표의 변화가 관찰된다. 단독 대비 개선을 정식 synergy 모델의 검증과 동일시하지 않는다."},
    ],
]
for figure in source_extract["figures"]:
    section = next(s for s in paper["tabs"]["evidence"] if s.get("id") == f"figure-{figure['number']}")
    section["blocks"].extend([
        {"type": "pairs", "items": figure_reading[figure["number"] - 1]},
        {"type": "details", "title": "영문 원문 caption", "blocks": [
            {"type": "paragraph", "text": html.escape(figure["captionEn"], quote=False)},
            {"type": "paragraph", "text": f'<a href="/reference/source-paper.pdf#page={figure["captionPage"]}">원문 caption · PDF p.{figure["captionPage"]}</a> · 원문 표기와 수치를 유지하고 줄바꿈만 정리했다.'},
        ]},
    ])
provenance = paper["tabs"]["evidence"][-1]["blocks"]
provenance.append({"type": "paragraph", "text": "이번 앱 이전에서 PDF p.1의 Abstract 전문 번역과 영문 Figure caption을 추가했다. 그림은 원본 패널·축·라벨을 보존해 Figure 영역만 표시하고, 구조식은 Fig. 1D에서 직접 추출했다. 영문 caption의 패널 표기·조건 불일치는 임의 수정하지 않았다."})
provenance.append({"type": "details", "title": "전체 저자 · 원문 p.1", "blocks": [{"type": "paragraph", "text": "Yulseung Sung, Ya Chun Yu, Mirim Lee, Seonghun Lim, Yechan Lee, Mincheol Kang, Doru Kwon, Apeksha Parajulee, Junjeong Choi, Do Sik Min, Kuglae Kim, Wan Namkung, Yun-Hee Kim, Sang Myung Woo, Nam Doo Kim, Hee Chan Yoo & Jung Min Han."}, {"type": "paragraph", "text": '<a href="/reference/source-paper.pdf#page=1">저자·발행일·Abstract 원본 확인</a>'}]})

output = ROOT / "data/papers/sung.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(paper, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Saved structured Sung paper: {output}")
print(f"Sections: {sum(len(s) for s in paper['tabs'].values())}; full Abstract and 7 original captions preserved")
