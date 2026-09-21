"""Reproduce faithful Sung paper crops and source text without changing references."""
import datetime
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
from pathlib import Path

SEED = 0
print(f"# run {datetime.datetime.now():%Y-%m-%d %H:%M} | python {platform.python_version()} | seed {SEED} | argv {sys.argv[1:]}")
for package in ("Pillow", "pdfplumber", "pypdf"):
    print(f"# {package} {importlib.metadata.version(package)}")

import pdfplumber
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference"
OUTPUT = ROOT / "public" / "assets" / "sung"
OUTPUT.mkdir(parents=True, exist_ok=True)
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
PAGES = [3, 6, 8, 10, 12, 14, 16]
CAPTION_PAGES = [4, 7, 9, 11, 13, 15, 17]
POPPLER = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe"
# Pixel bounds in the supplied 1489 x 1978 page renderings. Figure 3 is shorter.
BOTTOMS = [1640, 1640, 1520, 1630, 1630, 1640, 1640]


def crop_with_white_margin(source, box, target):
    """Trim only outside whitespace; preserve all original figure pixels."""
    region = source.crop(box).convert("RGB")
    mask = ImageChops.difference(region, Image.new("RGB", region.size, "white"))
    bounds = mask.convert("L").point(lambda value: 255 if value > 15 else 0).getbbox()
    if bounds is None:
        raise ValueError("The selected source area is blank")
    left, top, right, bottom = bounds
    tight = (max(0, left - 10), max(0, top - 10), min(region.width, right + 10), min(region.height, bottom + 10))
    region.crop(tight).save(target)
    return [tight[0] + box[0], tight[1] + box[1], tight[2] + box[0], tight[3] + box[1]]


def caption_text(page, number):
    # Figure legends are smaller than body text, and occupy two columns at top.
    bottom = min(char["top"] for char in page.chars if abs(char["size"] - 8.2191) < 0.02 and char["top"] > 45) - 1
    columns = [page.crop((35, 48, 300, bottom)), page.crop((304, 48, 565, bottom))]
    raw = "\n".join(column.extract_text(x_tolerance=1) for column in columns)
    assert raw.startswith(f"Fig. {number} |")
    assert "Source Data file." in raw or "Source Data" in raw
    # Keep source typography/wording. Only repair unambiguous layout word wraps.
    text = raw
    for word in ("thermophoresis", "determined", "overexpressing", "photomicrographs", "representative", "staining", "presented", "supplemented", "experiments", "calculated"):
        for split in range(2, len(word) - 1):
            text = text.replace(word[:split] + "-\n" + word[split:], word)
    text = text.replace("-\n", "-").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text, raw


abstract = (
    "The mitochondrial glutamine transporter SLC1A5_var plays a central role in the "
    "metabolic reprogramming of cancer cells by facilitating glutamine import into "
    "mitochondria for energy production and redox homeostasis. Despite its critical "
    "function, the development of effective and selective inhibitors targeting "
    "SLC1A5_var has remained a significant challenge. Here, we introduce iMQT_020, "
    "a selective allosteric inhibitor identified through structure-based screening. "
    "iMQT_020 disrupts the trimeric assembly of SLC1A5_var, causing metabolic crisis "
    "in cancer cells and selectively suppressing their growth. Mechanistically, "
    "iMQT_020 reduces glutamine anaplerosis and oxidative phosphorylation, resulting "
    "in a broad disruption of cancer metabolism. Additionally, iMQT_020 treatment "
    "epigenetically upregulates PD-L1 expression, enhancing the efficacy of combination "
    "therapies with anti-PD-L1 immune checkpoint inhibitors. These findings highlight "
    "the therapeutic potential of targeting SLC1A5_var as a critical metabolic "
    "vulnerability in cancer and demonstrate that targeting allosteric interprotomer "
    "interactions is a novel and promising therapeutic strategy for cancer treatment."
)

metadata = {
    "sourcePdf": "/reference/source-paper.pdf",
    "doi": "10.1038/s41467-025-64730-2",
    "license": "CC BY-NC-ND 4.0",
    "licenseUrl": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
    "attribution": "Sung et al., Nature Communications 16, 9690 (2025). © The Author(s) 2025.",
    "processing": "Faithful figure-area crops from supplied page PNGs; no recoloring, resampling, redrawing, or panel removal. Ligand panel rendered directly from the source PDF at 600 dpi; page 1 at 180 dpi. English text extracted from the supplied PDF; layout line wraps normalized.",
    "abstractEn": abstract,
    "abstractPage": 1,
    "page1Image": "/assets/sung/source-page-01.png",
    "figures": [],
}

with pdfplumber.open(REFERENCE / "source-paper.pdf") as pdf:
    for number, (page_number, caption_page, bottom) in enumerate(zip(PAGES, CAPTION_PAGES, BOTTOMS), start=1):
        source_name = f"source-page-{page_number:02}.png"
        source = Image.open(REFERENCE / source_name)
        assert source.size == (1489, 1978), f"Unexpected source size: {source_name}"
        asset_name = f"figure-{number}.png"
        bounds = crop_with_white_margin(source, (0, 112, source.width, bottom), OUTPUT / asset_name)
        caption, raw = caption_text(pdf.pages[caption_page - 1], number)
        metadata["figures"].append({"number": number, "src": f"/assets/sung/{asset_name}", "page": page_number, "captionPage": caption_page, "captionEn": caption, "captionRaw": raw, "sourceImage": f"/reference/{source_name}", "cropPixels": bounds})

# Render only original Figure 1D at higher resolution to keep atom labels sharp.
# This includes the panel D label, compound name and every atom, without redrawing.
subprocess.run([str(POPPLER), "-f", "3", "-l", "3", "-r", "600", "-x", "1600", "-y", "1193", "-W", "690", "-H", "1090", "-png", "-singlefile", str(REFERENCE / "source-paper.pdf"), str(OUTPUT / "ligand-imqt-020")], check=True)
metadata["ligand"] = {"src": "/assets/sung/ligand-imqt-020.png", "name": "iMQT_020", "figure": "1D", "page": 3, "sourcePdf": "/reference/source-paper.pdf", "renderDpi": 600, "cropPixelsAtRenderDpi": [1600, 1193, 2290, 2283], "description": "Original chemical structure from Figure 1D; not redrawn or inferred."}
subprocess.run([str(POPPLER), "-f", "1", "-l", "1", "-r", "180", "-png", "-singlefile", str(REFERENCE / "source-paper.pdf"), str(OUTPUT / "source-page-01")], check=True)
metadata_path = DATA / "sung-source-extract.json"
metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Saved 7 complete figure crops, original ligand panel and abstract page to {OUTPUT}")
print(f"Saved full captions, abstract and crop provenance to {metadata_path}")
