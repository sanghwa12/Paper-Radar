"""Build static document page images for browsers without an embedded PDF viewer."""
import datetime
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

SEED = 0
print(f"# run {datetime.datetime.now():%Y-%m-%d %H:%M} | python {platform.python_version()} | seed {SEED} | argv {sys.argv[1:]}", flush=True)
for package in ("Pillow", "pypdfium2"):
    print(f"# {package} {importlib.metadata.version(package)}", flush=True)

from PIL import Image
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "public" / "assets" / "documents"
print("# rendering 150 dpi | WebP quality 85 | method 5", flush=True)

DOCUMENTS = [
    ("adaptiveflow-paper", "AdaptiveFlow · 본문", "reference/adaptiveflow-assets/paper.pdf"),
    ("adaptiveflow-si", "AdaptiveFlow · Supplementary Information", "reference/adaptiveflow-assets/supplement.pdf"),
    ("sung-paper", "Sung et al. · 본문", "reference/source-paper.pdf"),
]


def render_document(document):
    identifier, title, relative_pdf = document
    source = ROOT / relative_pdf
    pdf = pdfium.PdfDocument(source)
    page_count = len(pdf)
    destination = OUTPUT / identifier
    destination.mkdir(parents=True, exist_ok=True)
    images = []
    byte_count = 0
    for number in range(1, page_count + 1):
        filename = f"page-{number:03}.webp"
        target = destination / filename
        page = pdf[number - 1]
        bitmap = page.render(scale=150 / 72)
        image = bitmap.to_pil()
        image.convert("RGB").save(target, "WEBP", quality=85, method=5)
        image.close()
        bitmap.close()
        page.close()
        with Image.open(target) as check:
            check.verify()
        byte_count += target.stat().st_size
        images.append(f"/assets/documents/{identifier}/{filename}")
    pdf.close()
    print(f"Rendered {identifier}: {page_count} pages, {byte_count / 1024 / 1024:.2f} MiB", flush=True)
    return "/" + relative_pdf, {"id": identifier, "title": title, "pages": images, "pageCount": page_count, "dpi": 150, "format": "webp", "quality": 85, "renderer": "PDFium", "byteCount": byte_count}


OUTPUT.mkdir(parents=True, exist_ok=True)
# PDFium calls run serially because its C API is not thread-safe.
manifest = dict(render_document(document) for document in DOCUMENTS)
manifest_path = OUTPUT / "manifest.json"
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Saved manifest: {manifest_path}", flush=True)
print(f"Total: {sum(doc['pageCount'] for doc in manifest.values())} pages, {sum(doc['byteCount'] for doc in manifest.values()) / 1024 / 1024:.2f} MiB", flush=True)
