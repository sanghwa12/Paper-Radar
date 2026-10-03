import copy
import unittest
from unittest.mock import patch
from pathlib import Path
import visual_generation as vg
from visual_generation import validate,build_tabs,TABS
class VisualTests(unittest.TestCase):
 def setUp(self):
  self.report={'sections':[{'points':[{'text':'A < B','basis':'데이터 관찰','quote':'evidence','page':1}]}], 'figures':[{'label':'Figure 1','page':1,'interpretation':'caption'}],'unverified':['SI 미확인']}
  self.plan={'panels':[{'tab':t,'title':t,'intro':'<script>','headers':['대상','결과'],'rows':[['A','1']], 'figures':[0] if t=='summary' else [],'evidence':[{'section':0,'point':0}]} for t in TABS], 'crops':[{'figure':0,'box':[.1,.1,.9,.5]}]}
  self.plan['panels'].append(copy.deepcopy(self.plan['panels'][1]))
 def test_valid_and_escaped(self):
  self.assertEqual(validate(self.plan,self.report),[])
  tabs=build_tabs(self.plan,self.report,8)
  self.assertEqual(tabs['summary'][0]['blocks'][0]['text'],'&lt;script&gt;')
  self.assertEqual(tabs['summary'][0]['blocks'][2]['image'],'/api/generated/8/figure-0.png')
 def test_bad_reference_table_and_crop(self):
  p=copy.deepcopy(self.plan);p['panels'][0]['evidence'][0]['point']=100
  p['panels'][0]['rows']=[['missing']];p['crops'][0]['box']=[0,0,1,1]
  errors=validate(p,self.report)
  self.assertIn('존재하지 않는 근거 참조',errors);self.assertIn('표 열·행 구조 오류',errors);self.assertIn('전체 페이지를 그림으로 지정',errors)
 def test_missing_tab_and_figures(self):
  p=copy.deepcopy(self.plan);p['panels']=p['panels'][1:];p['crops']=[]
  self.assertIn('5개 탭 구성 누락',validate(p,self.report));self.assertIn('화면 그림 배치 누락',validate(p,self.report))

 def test_invalid_plan_stops_before_crop_and_review(self):
  plan=copy.deepcopy(self.plan);plan['crops']=[]
  calls=[]
  def execute(*args): calls.append(args[4]);return plan
  with patch.object(vg,'render_crops') as crop:
   result,issues=vg.generate('codex',execute,self.report,Path('source.pdf'),Path('.'),[],'source','guidelines',8,lambda x:None)
  self.assertIsNone(result);self.assertTrue(issues);crop.assert_not_called();self.assertEqual(len(calls),1)
 def test_failed_visual_review_does_not_publish_tabs(self):
  values=iter([self.plan,{'pass':False,'issues':['그림 축 잘림']}])
  with patch.object(vg,'render_crops',return_value=[]):
   result,issues=vg.generate('codex',lambda *args:next(values),self.report,Path('source.pdf'),Path('.'),[],'source','guidelines',8,lambda x:None)
  self.assertIsNone(result);self.assertEqual(issues,['그림 축 잘림'])
