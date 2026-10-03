import hashlib
import uuid
import shutil
from contextlib import contextmanager
import unittest
from pathlib import Path
from unittest.mock import patch
import pdf_links


@contextmanager
def temporary():
    base=Path(__file__).resolve().parent
    root=base/('pdf-links-test-'+uuid.uuid4().hex)
    root.mkdir()
    try:yield str(root)
    finally:
        assert root.resolve().is_relative_to(base)
        shutil.rmtree(root)


class PdfLinksTests(unittest.TestCase):
    def test_doi_in_reference_is_not_enough(self):
        paper = {'title':'A specific article title','doi':'10.1000/test'}
        item = {'name':'other.pdf','path':'other.pdf','sha256':'a','text':'A different article citing this work','dois':{'10.1000/test'}}
        result = pdf_links.match_paper(paper,[item])
        self.assertEqual(result['status'],'review')

    def test_exact_duplicate_versions_and_title_only(self):
        paper = {'title':'A specific article title','doi':'10.1000/test'}
        item = {'name':'a.pdf','path':'a.pdf','sha256':'a','text':paper['title'],'dois':{paper['doi']}}
        self.assertEqual(pdf_links.match_paper(paper,[item,item])['status'],'linked')
        self.assertEqual(pdf_links.match_paper(paper,[item,{**item,'sha256':'b'}])['status'],'review')
        self.assertEqual(pdf_links.match_paper(paper,[{**item,'dois':set()}])['status'],'review')
        self.assertEqual(pdf_links.match_paper(paper,[])['status'],'missing')
        self.assertEqual(pdf_links.match_paper(paper,[],True)['status'],'review')

    def test_scan_persists_and_never_modifies_source(self):
        with temporary() as temp:
            root=Path(temp); folder=root/'pdfs'; folder.mkdir()
            path=folder/'a.pdf'; path.write_bytes(b'%PDF-fixture')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            item={'name':path.name,'path':str(path),'sha256':digest,'bytes':path.stat().st_size,'mtimeNs':path.stat().st_mtime_ns,'pages':1,'text':'A specific article title','dois':{'10.1000/test'}}
            record={'id':'test','papers':[{'title':item['text'],'doi':'10.1000/test'}]}
            db=root/'state.sqlite3'
            with patch('pdf_links.inspect_pdf',return_value=item):
                report=pdf_links.scan(db,record,folder)
            self.assertEqual(report['papers']['10.1000/test']['status'],'linked')
            self.assertEqual(pdf_links.candidate_file(db,'test','10.1000/test',0),path)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
            self.assertEqual(len(list(folder.iterdir())),1)
            self.assertEqual(pdf_links.load_report(db,'test')['fileCount'],1)
            with self.assertRaises(ValueError):pdf_links.candidate_file(db,'test','10.1000/test',-1)
            with patch('pdf_links.inspect_pdf',return_value={**item,'dois':set()}):
                self.assertEqual(pdf_links.scan(db,record,folder)['papers']['10.1000/test']['status'],'review')
                pdf_links.confirm(db,'test','10.1000/test',0)
                self.assertEqual(pdf_links.scan(db,record,folder)['papers']['10.1000/test']['status'],'linked')
            path.write_bytes(b'changed')
            self.assertEqual(pdf_links.load_report(db,'test')['papers']['10.1000/test']['status'],'review')
            with self.assertRaises(ValueError):pdf_links.confirm(db,'test','10.1000/test',0)

    def test_reference_section_is_excluded(self):
        class Page:
            def extract_text(self):return 'Title 10.1000/own References another 10.1000/cited'
        class Reader:
            is_encrypted=False
            pages=[Page()]
        with temporary() as temp:
            path=Path(temp)/'a.pdf';path.write_bytes(b'%PDF-test')
            with patch('pdf_links.PdfReader',return_value=Reader()):
                result=pdf_links.inspect_pdf(path)
            self.assertEqual(result['dois'],{'10.1000/own'})
