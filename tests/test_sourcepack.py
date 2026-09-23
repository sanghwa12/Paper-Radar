"""Offline source-package tests: identity, completeness, bytes and document structure."""
import hashlib
import io
import json
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import acquisition
import sourcepack


BODY = "The source reports ordinary measurements with comparison groups and uncertainty. " * 30
PAPER = {"id": "fixture", "doi": "10.1234/fixture", "pmcid": "PMC123", "title": "Fixture paper",
         "abstract": "A short abstract.", "sourceUrl": "https://europepmc.org/article/PMC/PMC123"}


def xml(extra="", doi="10.1234/fixture", back=""):
    return (f'<article xmlns:xlink="http://www.w3.org/1999/xlink"><front><article-meta>'
            f'<article-id pub-id-type="doi">{doi}</article-id><article-id pub-id-type="pmcid">PMC123</article-id>'
            '<abstract><p>A short abstract.</p></abstract><permissions><license>CC BY</license></permissions>'
            f'</article-meta></front><body><p>Direct body text.</p><sec id="results"><title>Results</title>'
            f'<p>{BODY}</p>{extra}</sec></body><back>{back}</back></article>').encode()


FIGURE = '<fig id="f1"><label>Figure 1</label><caption><p>Original exact caption.</p></caption><graphic xlink:href="figure.webp"/></fig>'
TABLE = ('<table-wrap id="t1"><label>Table 1</label><caption><p>Group comparisons.</p></caption>'
         '<table><thead><tr><th rowspan="2">Group</th><th colspan="2">Value</th></tr>'
         '<tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>Control</td><td>1</td><td>2</td></tr></tbody></table>'
         '<table-wrap-foot><p>Original footnote.</p></table-wrap-foot></table-wrap>')
SI = '<supplementary-material id="s1"><label>Supplement 1</label><media xlink:href="supplement.pdf"/></supplementary-material>'


def png():
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (30, 20), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def pdf(text=True, pages=2):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    for index in range(pages):
        page = writer.add_blank_page(400, 500)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 40 Td (Supplement page {index + 1} measurement.) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class SourcePackTests(unittest.TestCase):
    def setUp(self):
        self.test_root = Path(__file__).resolve().parent
        self.directory = self.test_root / ("sourcepack-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.requests = []
        self.responses = {}
        self.urls = {}
        self.validation = patch.object(acquisition, "validate_url", side_effect=lambda url: url)
        self.validate = self.validation.start()
        self.fetch = patch.object(sourcepack, "fetch_url", side_effect=self.fake_fetch)
        self.fetch.start()
        self.fallback = patch.object(acquisition, "retrieve", return_value={"status": "abstract_only", "sections": [],
                                                                            "reason": "No public body", "sourceUrl": PAPER["sourceUrl"]})
        self.retrieve = self.fallback.start()

    def tearDown(self):
        self.fallback.stop()
        self.fetch.stop()
        self.validation.stop()
        target = self.directory.resolve()
        self.assertTrue(target.is_relative_to(self.test_root) and target.name.startswith("sourcepack-"))
        shutil.rmtree(target)

    def fake_fetch(self, url, limit):
        self.requests.append(url)
        if url not in self.responses:
            raise OSError("Fixture missing response")
        return self.responses[url], "application/octet-stream", url

    def listing(self, versions, more=False, token=None):
        listing = '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        listing += "".join(f"<Contents><Key>PMC123.{v}/PMC123.{v}.json</Key></Contents>" for v in versions)
        listing += "<Contents><Key>PMC1234.99/PMC1234.99.json</Key></Contents>"
        listing += f'<IsTruncated>{str(more).lower()}</IsTruncated>'
        if token:
            listing += f"<NextContinuationToken>{token}</NextContinuationToken>"
        return (listing + "</ListBucketResult>").encode()

    def install(self, content=None, files=None, version=2, manuscript=False):
        base = sourcepack.PMC_BASE + f"PMC123.{version}/"
        files = files or {}
        all_files = {f"PMC123.{version}.xml": content or xml(), **files}
        urls = {name: base + name + "?md5=" + hashlib.md5(data).hexdigest() for name, data in all_files.items()}
        self.responses.update({urls[name]: data for name, data in all_files.items()})
        metadata = {"pmcid": "PMC123", "version": version, "doi": PAPER["doi"], "title": PAPER["title"],
                    "is_manuscript": manuscript, "license_code": "CC BY", "xml_url": urls[f"PMC123.{version}.xml"],
                    "media_urls": [urls[name] for name in files], "pdf_url": None}
        self.responses[base + f"PMC123.{version}.json"] = json.dumps(metadata).encode()
        listing_url = sourcepack.PMC_BASE + "?list-type=2&prefix=PMC123.&max-keys=1000"
        self.responses[listing_url] = self.listing([version])
        self.urls = urls
        return metadata

    def prepare(self, **kwargs):
        return sourcepack.prepare(PAPER, self.directory, "/assets/prepared/fixture", **kwargs)

    def test_complete_jats_preserves_table_relationships_captions_and_si_pages(self):
        self.install(xml(TABLE + FIGURE + SI, back="<sec><title>Additional analysis</title><p>Back scientific data.</p></sec>"),
                     {"figure.png": png(), "supplement.pdf": pdf()})
        stages = []
        result = self.prepare(progress=stages.append)
        self.assertEqual(result["status"], "ready")
        self.assertEqual([row["state"] for row in result["coverage"]], ["complete"] * 4)
        self.assertEqual([row["expected"] for row in result["coverage"]], [1, 1, 1, 1])
        sources = result["package"]["sources"]
        self.assertTrue(any("Direct body text" in item["text"] for item in sources))
        self.assertTrue(any("Back scientific data" in item["text"] for item in sources))
        table = next(item for item in sources if item.get("role") == "table")
        self.assertEqual(table["rows"], [["Group", "Value", "Value"], ["Group", "A", "B"], ["Control", "1", "2"]])
        self.assertIn("Original footnote.", table["text"])
        figure = next(item for item in sources if item["kind"] == "figure")
        self.assertEqual(figure["text"], "Original exact caption.")
        self.assertEqual(figure["asset"], "/assets/prepared/fixture/figure-1-1.png")
        pages = [item for item in sources if item["kind"] == "supplement"]
        self.assertEqual(len(pages), 2)
        self.assertTrue(pages[1]["url"].endswith("#page=2"))
        self.assertTrue(all(item["sha256"] == sourcepack.sha256(item["text"].encode()) for item in sources))
        self.assertFalse(any("reviewed" in item for item in sources))
        self.assertIn("그림 준비 중", stages)
        self.retrieve.assert_not_called()

    def test_publication_metadata_preferred_over_higher_manuscript_version(self):
        self.install(version=2)
        self.install(version=10, manuscript=True)
        self.responses[sourcepack.PMC_BASE + "?list-type=2&prefix=PMC123.&max-keys=1000"] = self.listing([2, 10])
        self.assertEqual(self.prepare()["version"], 2)
        self.assertFalse(any("PMC1234" in url for url in self.requests))

    def test_numeric_version_order_and_paginated_listing(self):
        self.install(version=2)
        self.install(version=10)
        self.responses[sourcepack.PMC_BASE + "?list-type=2&prefix=PMC123.&max-keys=1000"] = self.listing([2], True, "next")
        self.responses[sourcepack.PMC_BASE + "?list-type=2&prefix=PMC123.&max-keys=1000&continuation-token=next"] = self.listing([10])
        self.assertEqual(self.prepare()["version"], 10)

    def test_corrupted_cached_asset_is_fetched_again_and_md5_rechecked(self):
        self.install(xml(FIGURE), {"figure.png": png()})
        self.prepare()
        self.requests.clear()
        self.prepare()
        self.assertNotIn(self.urls["figure.png"], self.requests)
        (self.directory / "figure-1-1.png").write_bytes(b"corrupted cache")
        self.requests.clear()
        result = self.prepare()
        self.assertEqual(result["status"], "ready")
        self.assertIn(self.urls["figure.png"], self.requests)
        self.assertEqual((self.directory / "figure-1-1.png").read_bytes(), png())

    def test_graphic_alternatives_reuse_original_without_duplicate_missing_paths(self):
        figure = FIGURE.replace('<graphic xlink:href="figure.webp"/>',
                                '<alternatives><graphic xlink:href="figure.webp"/>'
                                '<graphic content-type="thumb" xlink:href="figure.gif"/>'
                                '<graphic xlink:href="figure.png"/></alternatives>')
        self.install(xml(figure), {"figure.png": png()})
        result = self.prepare()
        self.assertEqual(result["status"], "ready")
        figures = [item for item in result["assets"] if item["kind"] == "figure"]
        self.assertEqual(len(figures), 1)
        self.assertTrue((self.directory / figures[0]["localUrl"].rsplit("/", 1)[1]).is_file())
        downloads = sourcepack.Downloads(self.directory)
        downloads.get(self.urls["figure.png"], "first.png")
        downloads.get(self.urls["figure.png"], "second.png")
        self.assertEqual((self.directory / "first.png").read_bytes(), (self.directory / "second.png").read_bytes())

    def test_graphical_abstract_and_formula_images_are_not_classified_as_si(self):
        abstracts = ('<abstract abstract-type="graphical"><graphic id="ga" xlink:href="graphical.png"/></abstract>'
                     '<abstract abstract-type="toc-graphic"><graphic xlink:href="toc.png"/></abstract>')
        formula = '<disp-formula id="eq1"><label>(1)</label><alternatives><graphic xlink:href="equation.png"/><math><mi>x</mi><mo>=</mo><mn>1</mn></math></alternatives></disp-formula>'
        document = xml(formula + FIGURE + SI).replace(b'</article-meta>', abstracts.encode() + b'</article-meta>')
        self.install(document, {"graphical.png": png(), "toc.png": png(), "equation.png": png(),
                                "figure.png": png(), "supplement.pdf": pdf()})
        result = self.prepare()
        self.assertEqual(result["status"], "ready")
        coverage = {row["kind"]: row for row in result["coverage"]}
        self.assertEqual((coverage["figures"]["expected"], coverage["inline"]["expected"],
                          coverage["supplements"]["expected"]), (1, 3, 1))
        embedded = [asset for asset in result["assets"] if asset.get("role")]
        self.assertEqual({asset["role"] for asset in embedded}, {"graphical", "toc-graphic", "formula"})
        self.assertTrue(all(asset["captionStatus"] == "not_declared" for asset in embedded))
        standalone_input = json.loads(json.dumps(result["package"]))
        self.assertEqual(standalone_input["assets"], result["assets"])
        self.assertEqual(standalone_input["coverage"], result["coverage"])
        input_visuals = [asset for asset in standalone_input["assets"] if asset.get("role") in ("graphical", "toc-graphic")]
        self.assertEqual(len(input_visuals), 2)
        for asset in input_visuals:
            self.assertEqual(asset["sha256"], sourcepack.sha256((self.directory / asset["localUrl"].rsplit("/", 1)[1]).read_bytes()))
        sources = result["package"]["sources"]
        self.assertEqual(len([item for item in sources if item["kind"] == "figure"]), 1)
        equation = next(item for item in sources if item.get("role") == "formula")
        self.assertEqual(equation["text"], "x = 1")
        self.assertIn("<math>", equation["originalMarkup"])
        self.assertTrue(equation["asset"].endswith("inline-3.png"))

    def test_toc_and_untagged_body_images_follow_xml_location_not_filename(self):
        # RSC JATS uses abstract-type="toc" and p/graphic for image-only equations.
        toc = '<abstract abstract-type="toc"><p><graphic id="ga" xlink:href="paper-ga.webp"/></p></abstract>'
        body = '<p>Original expression.<graphic id="ugt1" xlink:href="paper-t1.webp"/>Original explanation.</p>'
        document = xml(body + SI).replace(b'</article-meta>', toc.encode() + b'</article-meta>')
        self.install(document, {"paper-ga.webp": png(), "paper-t1.webp": png(), "supplement.pdf": pdf()})
        result = self.prepare()
        self.assertEqual(result["status"], "ready")
        by_kind = {item["kind"]: item for item in result["coverage"]}
        self.assertEqual(by_kind["tables"]["expected"], 0)
        self.assertEqual(by_kind["inline"]["expected"], 2)
        self.assertEqual(by_kind["supplements"]["expected"], 1)
        images = [item for item in result["assets"] if item.get("role")]
        self.assertEqual([item["role"] for item in images], ["toc-graphic", "body-graphic"])
        self.assertEqual(images[1]["originalHrefs"], ["paper-t1.webp"])
        sources = result["package"]["sources"]
        self.assertTrue(any('Original expression. [원문 이미지: paper-t1.webp] Original explanation.' in item["text"]
                            for item in sources))
        linked = next(item for item in sources if item.get("role") == "body-graphic")
        self.assertEqual(linked["asset"], images[1]["localUrl"])
        self.assertTrue(linked["url"].endswith("#ugt1"))
        self.assertEqual(linked["text"], "[원문 이미지: paper-t1.webp]")

    def test_table_cell_images_keep_their_positions_and_are_not_supplements(self):
        table = ('<table-wrap id="t1"><label>Table 1</label><caption><p>Original table caption.</p></caption>'
                 '<table><tr><th>Item</th><th>Value</th></tr><tr><td>A</td>'
                 '<td><inline-graphic xlink:href="paper-g003.jpg"/></td></tr>'
                 '<tr><td>B</td><td><inline-graphic xlink:href="paper-g005.jpg"/> annotation</td></tr></table></table-wrap>')
        self.install(xml(table + SI), {"paper-g003.jpg": png(), "paper-g005.jpg": png(), "supplement.pdf": pdf()})
        result = self.prepare()
        self.assertEqual(result["status"], "ready")
        sources = result["package"]["sources"]
        parsed = next(item for item in sources if item.get("role") == "table")
        self.assertEqual(parsed["rows"], [["Item", "Value"], ["A", "[원문 이미지: paper-g003.jpg]"],
                                          ["B", "[원문 이미지: paper-g005.jpg] annotation"]])
        linked = [item for item in sources if item.get("role") == "table-cell"]
        self.assertEqual(len(linked), 2)
        self.assertEqual([item["originalHrefs"][0] for item in linked], ["paper-g003.jpg", "paper-g005.jpg"])
        self.assertTrue(all(item["containerId"] == "t1" and item["url"].endswith("#t1") for item in linked))
        coverage = {item["kind"]: item for item in result["coverage"]}
        self.assertEqual((coverage["inline"]["expected"], coverage["inline"]["usable"]), (2, 2))
        self.assertEqual((coverage["supplements"]["expected"], coverage["supplements"]["usable"]), (1, 1))

    def test_missing_table_cell_image_still_prevents_readiness(self):
        table = '<table-wrap><table><tr><td><inline-graphic xlink:href="missing.jpg"/></td></tr></table></table-wrap>'
        self.install(xml(table))
        result = self.prepare()
        self.assertEqual(result["status"], "partial")
        coverage = next(item for item in result["coverage"] if item["kind"] == "inline")
        self.assertEqual((coverage["expected"], coverage["acquired"], coverage["usable"]), (1, 0, 0))
        table = next(item for item in result["package"]["sources"] if item.get("role") == "table")
        self.assertEqual(table["rows"], [["[원문 이미지: missing.jpg]"]])

    def test_declared_alternatives_and_manifest_format_variants_are_one_visual(self):
        figure = FIGURE.replace('<graphic xlink:href="figure.webp"/>',
                                '<alternatives><graphic xlink:href="figure.webp"/>'
                                '<graphic xlink:href="print-version.png"/>'
                                '<graphic content-type="thumbnail" xlink:href="preview.gif"/></alternatives>')
        self.install(xml(figure + SI), {"figure.webp": png(), "figure.jpg": png(), "print-version.png": png(),
                                       "preview.gif": png(), "supplement.pdf": pdf()})
        result = self.prepare()
        self.assertEqual(result["status"], "ready")
        figures = [item for item in result["assets"] if item["kind"] == "figure"]
        self.assertEqual(len(figures), 1)
        self.assertEqual(set(figures[0]["alternateSourceUrls"]),
                         {self.urls[name] for name in ("figure.jpg", "print-version.png", "preview.gif")})
        self.assertFalse(any(self.urls[name] in self.requests for name in ("figure.jpg", "print-version.png", "preview.gif")))
        self.assertEqual(next(row for row in result["coverage"] if row["kind"] == "supplements")["expected"], 1)

    def test_unreferenced_image_and_real_unread_si_are_not_hidden_by_graphic_classification(self):
        empty_si = '<supplementary-material id="unknown-si"/>'
        docx = '<supplementary-material id="doc-si"><media xlink:href="real-si.docx"/></supplementary-material>'
        self.install(xml(FIGURE + empty_si + docx), {"figure.webp": png(), "figure.jpg": png(),
                                                   "unrelated.jpg": png(), "real-si.docx": b"PK\x03\x04 inert document"})
        result = self.prepare()
        self.assertEqual(result["status"], "partial")
        si = next(row for row in result["coverage"] if row["kind"] == "supplements")
        self.assertEqual((si["expected"], si["acquired"], si["usable"]), (3, 2, 0))
        self.assertTrue(any('원문에 보충자료 파일 링크가 없습니다' in issue for issue in result["issues"]))
        self.assertTrue(any('자동으로 해제하거나 텍스트로 변환하지 않습니다' in issue for issue in result["issues"]))
        self.assertFalse(any(item["kind"] == "supplement" for item in result["package"]["sources"]))

    def test_conflicting_same_named_graphic_manifest_entries_are_not_chosen_arbitrarily(self):
        metadata = self.install(xml(FIGURE), {"figure.webp": png()})
        metadata["media_urls"].append(self.urls["figure.webp"].replace('md5=', 'md5=0'))
        self.responses[sourcepack.PMC_BASE + "PMC123.2/PMC123.2.json"] = json.dumps(metadata).encode()
        result = self.prepare()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(next(row for row in result["coverage"] if row["kind"] == "figures")["usable"], 0)
        self.assertTrue(any('같은 이름' in issue for issue in result["issues"]))

    def test_explicit_figure_and_scheme_types_disambiguate_original_numbers(self):
        first = FIGURE.replace('<fig id="f1">', '<fig id="f1" fig-type="figure">').replace('Figure 1', '1')
        scheme = FIGURE.replace('<fig id="f1">', '<fig id="s1" fig-type="scheme">').replace('Figure 1', '1')
        untyped = FIGURE.replace('id="f1"', 'id="f2"').replace('Figure 1', '2')
        unnumbered = FIGURE.replace('<fig id="f1">', '<fig id="f3" fig-type="figure">').replace('<label>Figure 1</label>', '')
        self.install(xml(first + scheme + untyped + unnumbered), {"figure.png": png()})
        result = self.prepare()
        figures = [item for item in result["package"]["sources"] if item["kind"] == "figure"]
        self.assertEqual([item["label"] for item in figures], ["Figure 1", "Scheme 1", "2", "Figure (원문 번호 없음)"])
        self.assertTrue(all(item["text"] == "Original exact caption." for item in figures))
        self.assertEqual([item["label"] for item in result["assets"]], [item["label"] for item in figures])

    def test_relative_and_publisher_references_count_one_official_si_file(self):
        duplicate = '<p><ext-link xlink:href="https://publisher.example/suppl/supplement.pdf">Supplementary table</ext-link></p>'
        self.install(xml(SI + duplicate), {"supplement.pdf": pdf()})
        result = self.prepare()
        self.assertEqual(result["status"], "ready")
        coverage = next(row for row in result["coverage"] if row["kind"] == "supplements")
        self.assertEqual((coverage["expected"], coverage["acquired"], coverage["usable"]), (1, 1, 1))
        self.assertEqual(len([item for item in result["assets"] if item["kind"] == "supplement"]), 1)
        self.assertEqual(len([item for item in result["package"]["sources"] if item["kind"] == "supplement"]), 2)

    def test_source_md5_mismatch_is_not_a_usable_figure(self):
        self.install(xml(FIGURE), {"figure.png": png()})
        self.responses[self.urls["figure.png"]] = b"tampered"
        result = self.prepare()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"][2]["usable"], 0)
        self.assertTrue(any("MD5" in issue for issue in result["issues"]))

    def test_wrong_metadata_or_xml_identity_cannot_prepare_sources(self):
        for bad in ("metadata", "xml"):
            with self.subTest(bad=bad):
                metadata = self.install(xml(doi="10.1234/wrong") if bad == "xml" else xml())
                if bad == "metadata":
                    metadata["doi"] = "10.1234/wrong"
                    self.responses[sourcepack.PMC_BASE + "PMC123.2/PMC123.2.json"] = json.dumps(metadata).encode()
                result = self.prepare()
                self.assertEqual(result["status"], "failed")
                self.assertFalse(any(item["kind"] == "body" for item in result["package"]["sources"]))
                self.assertTrue(any("DOI" in issue for issue in result["issues"]))

    def test_entity_xml_and_utf16_never_enter_structural_extraction(self):
        for raw in (b'<!DOCTYPE article [<!ENTITY bad "boom">]>' + xml(), xml().decode().encode("utf-16")):
            with self.subTest(prefix=raw[:8]):
                self.install(raw)
                result = self.prepare()
                self.assertEqual(result["status"], "failed")
                self.assertTrue(any("UTF-16" in issue or "엔터티" in issue for issue in result["issues"]))

    def test_missing_figures_image_only_tables_and_external_si_stay_partial(self):
        extra = ('<table-wrap><caption><p>Image table.</p></caption><graphic xlink:href="missing.png"/></table-wrap>'
                 + FIGURE + '<supplementary-material><ext-link xlink:href="https://publisher.example/private.pdf">SI</ext-link></supplementary-material>')
        self.install(xml(extra))
        result = self.prepare()
        self.assertEqual(result["status"], "partial")
        self.assertEqual({row["kind"]: row["usable"] for row in result["coverage"]},
                         {"body": 1, "tables": 0, "figures": 0, "inline": 0, "supplements": 0})
        self.assertFalse(any("publisher.example" in url for url in self.requests))

    def test_scanned_pdf_and_archives_acquired_but_not_usable_or_executed(self):
        self.install(xml(SI), {"supplement.pdf": pdf(text=False), "dataset.zip": b"PK\x03\x04 inert archive"})
        result = self.prepare()
        self.assertEqual(result["status"], "partial")
        si = result["coverage"][3]
        self.assertEqual((si["expected"], si["acquired"], si["usable"]), (2, 2, 0))
        self.assertFalse(any(item["kind"] == "supplement" for item in result["package"]["sources"]))
        self.assertTrue((self.directory / "supplement-2.zip").is_file())
        self.assertEqual(len(list(self.directory.glob("*.zip"))), 1)

    def test_no_jats_references_means_none_declared_not_missing(self):
        self.install()
        result = self.prepare()
        self.assertEqual(result["status"], "ready")
        self.assertEqual([row["state"] for row in result["coverage"]][1:], ["none_declared"] * 3)

    def test_undefined_references_and_ordinary_si_link_are_not_silently_omitted(self):
        self.install(xml('<p><xref ref-type="fig" rid="f9">Figure 9</xref><xref ref-type="table" rid="t9">Table 9</xref>'
                         '<ext-link xlink:href="https://example.org/data.pdf">Supplementary information</ext-link></p>'))
        result = self.prepare()
        self.assertEqual(result["status"], "partial")
        self.assertEqual([row["expected"] for row in result["coverage"]], [1, 1, 1, 1])

    def test_valid_cached_body_fallback_does_not_claim_unknown_assets_complete(self):
        self.install()
        self.responses.clear()
        document = {"status": "fulltext", "identifiers": {"doi": PAPER["doi"], "pmcid": PAPER["pmcid"]},
                    "sections": [{"heading": "Results", "text": BODY}], "provider": "Publisher",
                    "sourceUrl": "https://publisher.example/paper", "license": "CC BY"}
        result = self.prepare(cached_document=document)
        self.assertEqual(result["status"], "partial")
        self.assertEqual([row["expected"] for row in result["coverage"]], [1, None, None, None])
        self.assertEqual(result["package"]["coverage"], result["coverage"])
        self.assertEqual(result["package"]["assets"], [])
        self.retrieve.assert_not_called()
        document["identifiers"]["doi"] = "10.1234/wrong"
        self.assertEqual(self.prepare(cached_document=document)["status"], "failed")
        self.retrieve.assert_called_once()

    def test_fallback_preserves_abstract_origin_and_failed_attempt_provenance(self):
        self.install()
        self.responses.clear()
        attempts = [{"url": "http://publisher.example/redirect", "requestedUrl": "https://publisher.example/start",
                     "reasonCode": "https_required", "reason": "HTTPS required"}]
        self.retrieve.return_value = {"status": "abstract_only", "sections": [], "reason": "No verified body",
                                      "sourceUrl": "https://publisher.example/start", "attempts": attempts}
        result = self.prepare()
        self.assertEqual(result["status"], "failed")
        abstract = next(item for item in result["package"]["sources"] if item["kind"] == "abstract")
        self.assertEqual(abstract["url"], PAPER["sourceUrl"])
        self.assertEqual(result["attempts"], attempts)
        self.assertEqual(result["package"]["attempts"], attempts)

    def test_fallback_reason_and_format_describe_the_final_acquisition_outcome(self):
        paper = {**PAPER, "pmcid": ""}
        for status in ("abstract_only", "fulltext"):
            with self.subTest(status=status):
                self.retrieve.return_value = {
                    "status": status, "sourceUrl": "https://publisher.example/paper.pdf", "format": "pdf",
                    "reason": "Publisher returned HTTP 403; no verified full text.",
                    "sections": [{"heading": "PDF page 1", "text": BODY}] if status == "fulltext" else [],
                }
                result = sourcepack.prepare(paper, self.directory, "/assets/prepared/fixture")
                self.assertIn("PMC 식별자가 없어", result["issues"][0])
                self.assertEqual(result["package"]["metadata"]["format"], "pdf")
                if status == "abstract_only":
                    self.assertEqual(result["status"], "failed")
                    self.assertEqual(result["reason"], self.retrieve.return_value["reason"])
                    self.assertEqual(result["issues"][-1], result["reason"])
                    self.assertFalse(any(item["kind"] == "body" for item in result["package"]["sources"]))
                else:
                    self.assertEqual(result["status"], "partial")
                    self.assertIn("본문 텍스트를 확보", result["reason"])
                    self.assertIn("표·그림·보충자료", result["reason"])
                    self.assertNotIn("403", result["reason"])
                    self.assertEqual(len(result["issues"]), 1)

    def test_bounds_incomplete_listing_and_invalid_media_are_reported(self):
        metadata = self.install()
        metadata["media_urls"] = ["https://example.org/other/file.png"]
        self.responses[sourcepack.PMC_BASE + "PMC123.2/PMC123.2.json"] = json.dumps(metadata).encode()
        self.assertEqual(self.prepare()["status"], "failed")
        self.install(xml(FIGURE), {"figure.png": png()})
        with patch.object(sourcepack, "MAX_ASSETS", 3):
            result = self.prepare()
        self.assertEqual(result["status"], "partial")
        self.assertTrue(any("파일 수" in issue for issue in result["issues"]))
        self.install()
        self.responses[sourcepack.PMC_BASE + "?list-type=2&prefix=PMC123.&max-keys=1000"] = self.listing([2], True, "next")
        with patch.object(sourcepack, "MAX_LIST_PAGES", 1):
            self.assertEqual(self.prepare()["status"], "failed")

    def test_download_size_limit_and_both_initial_and_final_urls_validated(self):
        self.fetch.stop()
        response = io.BytesIO(b"12345")
        response.headers = {"Content-Type": "image/png"}
        response.geturl = lambda: "https://example.org/final.png"
        with patch.object(sourcepack, "build_opener") as opener:
            opener.return_value.open.return_value = response
            with self.assertRaises(acquisition.SourceUnavailable):
                sourcepack.fetch_url("https://example.org/start.png", limit=4)
        self.assertEqual([call.args[0] for call in self.validate.call_args_list],
                         ["https://example.org/start.png", "https://example.org/final.png"])
        self.fetch.start()

    def test_pdf_signature_and_corrupt_structure_are_not_accepted(self):
        for data in (b"<html>login</html>", b"%PDF-1.5 broken"):
            with self.subTest(data=data), self.assertRaises(acquisition.SourceUnavailable):
                sourcepack.pdf_pages(data)


if __name__ == "__main__":
    unittest.main()
