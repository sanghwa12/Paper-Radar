"""Build static document page images for browsers without an embedded PDF viewer."""
import datetime
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

from PIL import Image
import pypdfium2 as pdfium

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "public" / "assets" / "documents"
REPORT = ROOT / ".runtime" / "document-render-results.json"
sys.path.insert(0, str(ROOT))

DOCUMENTS = [
    ("adaptiveflow-paper", "AdaptiveFlow · 본문", "/reference/adaptiveflow-assets/paper.pdf"),
    ("adaptiveflow-si", "AdaptiveFlow · Supplementary Information", "/reference/adaptiveflow-assets/supplement.pdf"),
    ("sung-paper", "Sung et al. · 본문", "/reference/source-paper.pdf"),
]


def documents():
    return list(DOCUMENTS)


def valid_image(path):
    try:
        with Image.open(path) as image:
            image.load()
            return image.format == "WEBP" and min(image.size) > 0
    except (OSError, ValueError):
        return False


def render_document(document, previous=None):
    identifier, title, url = document
    source = (ROOT / "public" if url.startswith("/assets/") else ROOT) / url.lstrip("/")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    pdf = pdfium.PdfDocument(source)
    destination = OUTPUT / identifier
    destination.mkdir(parents=True, exist_ok=True)
    try:
        page_count = len(pdf)
        images = [f"/assets/documents/{identifier}/page-{number:03}.webp"
                  for number in range(1, page_count + 1)]
        reusable = bool(previous and previous.get("pages") == images
                        and previous.get("pageCount") == page_count
                        and previous.get("dpi") == 150 and previous.get("quality") == 85
                        and previous.get("sourceSha256", source_hash) == source_hash)
        rendered = 0
        byte_count = 0
        for number, image_url in enumerate(images):
            target = ROOT / "public" / image_url.lstrip("/")
            if not (reusable and valid_image(target)):
                page = pdf[number]
                bitmap = page.render(scale=150 / 72)
                image = bitmap.to_pil()
                try:
                    with image.convert("RGB") as rgb:
                        rgb.save(target, "WEBP", quality=85, method=5)
                finally:
                    image.close()
                    bitmap.close()
                    page.close()
                if not valid_image(target):
                    raise ValueError(f"Invalid rendered image: {target}")
                rendered += 1
            byte_count += target.stat().st_size
        entry = {**previous, "sourceSha256": source_hash} if reusable and rendered == 0 else {
            "id": identifier, "title": title, "pages": images, "pageCount": page_count,
            "dpi": 150, "format": "webp", "quality": 85, "renderer": "PDFium",
            "byteCount": byte_count, "sourceSha256": source_hash}
        result = {"id": identifier, "url": url, "status": "rendered" if rendered else "reused",
                  "pageCount": page_count, "renderedPages": rendered,
                  "reusedPages": page_count - rendered, "byteCount": byte_count}
        return entry, result
    finally:
        pdf.close()


def main():
    print(f"# run {datetime.datetime.now():%Y-%m-%d %H:%M} | python {platform.python_version()} | seed 0 | argv {sys.argv[1:]}", flush=True)
    for package in ("Pillow", "pypdfium2"):
        print(f"# {package} {importlib.metadata.version(package)}", flush=True)
    print("# rendering 150 dpi | WebP quality 85 | method 5", flush=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUTPUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    results = []
    # PDFium calls run serially because its C API is not thread-safe.
    for document in documents():
        identifier, _, url = document
        try:
            entry, result = render_document(document, manifest.get(url))
            manifest[url] = entry
            print(f"{result['status']}: {identifier}, {result['pageCount']} pages "
                  f"({result['renderedPages']} rendered, {result['reusedPages']} reused)", flush=True)
        except Exception as error:
            result = {"id": identifier, "url": url, "status": "failed", "error": str(error)}
            print(f"Failed: {identifier}: {error}", flush=True)
        results.append(result)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved manifest: {manifest_path}\nSaved results: {REPORT}", flush=True)
    return int(any(result["status"] == "failed" for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
