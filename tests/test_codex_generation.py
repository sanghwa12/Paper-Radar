import copy
import json
import shutil
import sys
import unittest
import uuid
import subprocess
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import codex_generation as cg
import generation_requests as gr


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.folder=Path(__file__).parent/('generation-test-'+uuid.uuid4().hex)
        self.folder.mkdir()
        self.db=self.folder/'test.sqlite3'
        self.pages=['Evidence text for exact citation. Accuracy was 92.5% over 10 runs.']
        self.report={'translation':'시험 제목','authors':'Author','journal':'Journal','doi':'10.1/example',
                     'readPages':[1],'visualPages':[1],'unverified':['SI 미검토'],'blockers':[],
                     'sections':[{'title':t,'points':[{'text':'과학적 근거와 비교 기준을 구체적으로 설명하는 시험용 문장입니다. '*5,
                                  'basis':'데이터 관찰','page':1,'quote':self.pages[0]}]} for t in cg.SECTIONS['summary']],
                     'figures':[{'page':1,'label':'Figure 1','interpretation':'그림에서 관찰되는 비교와 해석의 한계를 설명하는 시험용 문장입니다. '*4}],
                     'glance':{'type':'방법 개발','oneLiner':'시험용 한 줄 정의입니다.','problem':'기존 방식의 한계','conclusion':'개선을 확인',
                               'steps':[{'label':'모델 설계','text':'입력과 출력을 정의'},{'label':'검증','text':'기존 방식과 비교'}],
                               'keyResults':[{'value':'92.5%','label':'정확도','context':'기존 방식 대비','page':1},
                                             {'value':'10회','label':'반복 실행','context':'동일 조건','page':1}]}}

    def tearDown(self):
        assert self.folder.resolve().is_relative_to(cg.ROOT/'tests')
        shutil.rmtree(self.folder)

    def test_missing_evidence_and_short_output_block_completion(self):
        self.assertEqual(cg.validate(self.report,'summary',self.pages),[])
        broken=copy.deepcopy(self.report)
        broken['sections'][0]['points'][0]['quote']='Fabricated nonexistent source quote'
        broken['figures']=[]
        self.assertIn('출처 발췌·페이지 불일치',cg.validate(broken,'summary',self.pages))
        self.assertIn('필수 그림 해석 부족',cg.validate(broken,'summary',self.pages))
        self.assertTrue(cg.validate(self.report,'analysis',self.pages))

    def test_glance_must_stay_short_and_cite_real_numbers(self):
        missing=copy.deepcopy(self.report); del missing['glance']
        self.assertIn('한눈에 보기 도식 누락',cg.validate(missing,'summary',self.pages))
        self.assertEqual(cg.validate(missing,'analysis',self.pages)[-1:],cg.validate(self.report,'analysis',self.pages)[-1:])
        long=copy.deepcopy(self.report); long['glance']['oneLiner']='줄글'*60
        self.assertIn('한눈에 보기의 유형·한 줄 정의·문제·결론 누락 또는 과도한 길이',cg.validate(long,'summary',self.pages))
        steps=copy.deepcopy(self.report); steps['glance']['steps']=steps['glance']['steps'][:1]
        self.assertIn('한눈에 보기 흐름 단계는 2~4개, 단계 제목 16자·설명 60자 이내',cg.validate(steps,'summary',self.pages))
        invented=copy.deepcopy(self.report); invented['glance']['keyResults'][0]['value']='87.1%'
        self.assertIn('한눈에 보기 수치가 해당 페이지 원문에 없음',cg.validate(invented,'summary',self.pages))
        page=copy.deepcopy(self.report); page['glance']['keyResults'][0]['page']=5
        self.assertIn('한눈에 보기 수치의 페이지 오류',cg.validate(page,'summary',self.pages))

    def put_request(self,status):
        item={'key':'test','kind':'summary','sha256':'hash','title':'test','status':status}
        with gr.connect(self.db) as db:
            db.execute('INSERT INTO generation_requests(kind,target_key,sha256,data) VALUES (?,?,?,?)',
                       ('summary','test','hash',json.dumps(item)))
        db.close()

    def test_restart_fails_interrupted_and_preserves_saved(self):
        self.put_request('reviewing')
        cg.Worker(self.db)
        self.assertEqual(gr.list_requests(self.db)[0]['status'],'failed')
        cg.update(self.db,1,status='requested')
        cg.Worker(self.db)
        self.assertEqual(gr.list_requests(self.db)[0]['status'],'requested')

    def test_only_verified_complete_results_enter_library(self):
        self.put_request('held')
        cg.update(self.db,1,result=self.report)
        self.assertEqual(cg.completed_papers(self.db),{})
        cg.update(self.db,1,status='complete')
        self.report['date']=''
        cg.update(self.db,1,result=self.report)
        self.assertEqual(cg.completed_papers(self.db)['generated-1']['generatedKind'],'summary')

    def test_worker_failure_is_persisted(self):
        self.put_request('queued')
        worker=cg.Worker(self.db)
        with patch.object(worker,'generate',side_effect=RuntimeError('로그인 실패')):
            worker.run([1])
        item=gr.list_requests(self.db)[0]
        self.assertEqual(item['status'],'failed')
        self.assertEqual(item['error'],'로그인 실패')

    def test_repeated_click_does_not_launch_twice(self):
        self.put_request('requested')
        worker=cg.Worker(self.db)
        with patch.object(cg.threading,'Thread') as thread:
            worker.start(['test'],'summary')
            worker.start(['test'],'summary')
            self.assertEqual(thread.call_count,1)

    def test_execution_uses_readonly_codex_and_no_api_key(self):
        def fake_run(command, **kwargs):
            self.assertEqual(command[command.index('--sandbox')+1],'read-only')
            self.assertNotIn('CODEX_API_KEY',kwargs['env'])
            self.assertNotIn('OPENAI_API_KEY',kwargs['env'])
            Path(command[command.index('-o')+1]).write_text('{"pass":true,"issues":[]}',encoding='utf-8')
            return subprocess.CompletedProcess(command,0)
        with patch.dict(cg.os.environ,{'CODEX_API_KEY':'test-only','OPENAI_API_KEY':'test-only'}), patch.object(cg.subprocess,'run',side_effect=fake_run):
            self.assertTrue(cg.execute('codex','test',cg.REVIEW_SCHEMA,self.folder,'review',[])['pass'])

    def test_failed_execution_never_reuses_previous_output(self):
        (self.folder/'draft.json').write_text('{}',encoding='utf-8')
        with patch.object(cg.subprocess,'run',return_value=subprocess.CompletedProcess([],1)):
            with self.assertRaises(RuntimeError):
                cg.execute('codex','test',cg.SCHEMA,self.folder,'draft',[])
        self.assertFalse((self.folder/'draft.json').exists())
        self.assertEqual(len(list(self.folder.glob('draft-previous-*.json'))),1)
