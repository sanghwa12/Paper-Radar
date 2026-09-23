/* Recommendation-round UI tests with inert metadata and no network or database writes. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const app = fs.readFileSync(path.join(__dirname, '..', 'public', 'app.js'), 'utf8');
function section(from, to) {
  const start = app.indexOf(from);
  const end = app.indexOf(to, start);
  assert.ok(start >= 0 && end > start, `Application section not found: ${from}`);
  return app.slice(start, end);
}
function fixture() {
  return {rounds: [{id:'fixture',title:'이번 추천 6편',createdAt:'2026-09-23',
    selection:{from:'2026-08-23',to:'2026-09-23',source:'Europe PMC',note:'분야별 잠정 추천'},
    items: Array.from({length:6}, (_, index) => ({candidateId:`selected-${index}`,area:`Area ${index}`,
      candidate:{id:`selected-${index}`,title:`Fixture ${index}`,date:'2026-09-01',journal:'Fixture Journal'},
      reason:'비교 관점',reviewBasis:'abstract',evaluatedAt:'2026-09-23',preparation:null,paperId:null,
      workflow:{status:'selected',label:'선정 완료 · 자료 준비 전',stage:''},
      score:{knownMax:0,subtotal:0,total:null},metrics:{citations:{count:null},journal:{jif:null}}}))}]};
}
function harness(request) {
  const elements = new Map([
    ['#round-results',{innerHTML:''}], ['#round-errors',{innerHTML:'',hidden:true}],
    ['#preparation-reader',{open:false}],
  ]);
  const timers = new Map();
  let nextTimer = 0;
  const context = vm.createContext({
    location:{hash:'#/rounds'},papers:[],candidates:[{id:'old-candidate',title:'Preserved'}],
    preparationData:null,preparationOpenId:null,currentId:null,
    main:{innerHTML:''},document:{title:''},
    $: selector => elements.get(selector),
    escape: value => String(value).replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character])),
    evaluationNumber: value => String(value), evaluationLink: () => '', countText: value => String(value || 0),
    backButton: () => '', renderSidebar() {},
    preparationBusy: () => context.preparationData?.run?.status === 'running',
    discoveryRequest: request,
    setTimeout(fn) { const id = ++nextTimer; timers.set(id, fn); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  vm.runInContext([
    section('let roundsData =', 'let collectionData ='),
    section('function hasPreparedBody(', 'function renderCandidatePreparation('),
    section('function roundScore(', 'function renderFocusedCard('),
  ].join('\n'), context);
  return {context,elements,timers,run: code => vm.runInContext(code, context),
    html: () => elements.get('#round-results').innerHTML};
}

test('reading a round shows only six selected papers and never starts material preparation', async () => {
  const calls = [];
  const data = fixture();
  const ui = harness(async (url, options) => {
    calls.push([url,options]);
    return url === '/api/rounds' ? data : {run:null};
  });
  await ui.run('refreshRounds()');
  assert.deepEqual(calls.map(([url]) => url), ['/api/rounds','/api/preparation']);
  assert.ok(calls.every(([,options]) => !options));
  assert.equal((ui.html().match(/data-round-candidate=/g) || []).length, 6);
  assert.match(ui.html(), /6편 자료 준비/);
  assert.match(ui.html(), /점수 미평가/);
  assert.doesNotMatch(ui.html(), /0 \/ 100|0 \/ 0/);
  assert.match(ui.html(), /인용 미확인 · IF 미확인/);
  assert.equal(ui.context.candidates[0].title, 'Preserved');
  assert.equal(ui.timers.size, 0);
});

test('explicit bulk preparation posts exactly the selected six once and shows immediate feedback', async () => {
  const data = fixture();
  let resolve;
  let posted;
  let posts = 0;
  const ui = harness(async (url, options) => {
    if (options?.method === 'POST') {
      assert.equal(url, '/api/preparation');
      posts++;
      posted = JSON.parse(options.body).candidateIds;
      return await new Promise(yes => { resolve = yes; });
    }
    return url === '/api/rounds' ? data : {run:null};
  });
  await ui.run('refreshRounds()');
  const pending = ui.run('startRoundPreparation("all")');
  assert.deepEqual(posted, data.rounds[0].items.map(item => item.candidateId));
  assert.equal((ui.html().match(/자료 준비 요청 중/g) || []).length, 6);
  await ui.run('startRoundPreparation("all")');
  assert.equal(posts, 1);
  resolve({run:{status:'running'}});
  await pending;
});

test('single-item POST error is shown beside the selected paper and allows retry', async () => {
  const data = fixture();
  const ui = harness(async (url, options) => {
    if (options?.method === 'POST') throw new Error('fixture <request> failed');
    return url === '/api/rounds' ? data : {run:null};
  });
  await ui.run('refreshRounds()');
  await ui.run('startRoundPreparation("selected-2")');
  assert.match(ui.elements.get('#round-errors').innerHTML, /fixture &lt;request&gt; failed/);
  assert.match(ui.run('renderRoundItem(roundsData.rounds[0].items[2])'), /role="alert"[^>]*>자료 준비를 시작하지 못했습니다/);
  assert.doesNotMatch(ui.run('renderRoundItem(roundsData.rounds[0].items[1])'), /fixture.*failed/);
  assert.match(ui.run('renderRoundItem(roundsData.rounds[0].items[2])'), /data-round-prepare="selected-2">/);
});

test('an accepted preparation survives a failed refresh and cannot be submitted twice', async () => {
  const data = fixture();
  let posts = 0;
  const accepted = {run:{status:'running',candidateIds:['selected-2'],processed:0,total:1,stage:'자료 준비 대기'}};
  const ui = harness(async (url, options) => {
    if (options?.method === 'POST') { posts++; return accepted; }
    if (posts) throw new Error('fixture status unavailable');
    return url === '/api/rounds' ? data : {run:null};
  });
  await ui.run('refreshRounds()');
  await ui.run('startRoundPreparation("selected-2")');
  assert.equal(posts, 1);
  assert.match(ui.elements.get('#round-errors').innerHTML, /요청은 접수됐습니다/);
  assert.doesNotMatch(ui.elements.get('#round-errors').innerHTML, /시작하지 못했습니다/);
  assert.equal(ui.context.preparationData.run.status, 'running');
  assert.match(ui.run('renderRoundItem(roundsData.rounds[0].items[2])'), /data-round-prepare="selected-2" disabled/);
  await ui.run('startRoundPreparation("selected-2")');
  assert.equal(posts, 1);
});

test('ready and published states are distinct and the published action opens a card first', async () => {
  const data = fixture();
  data.rounds[0].items[0].workflow = {status:'writing_waiting',label:'자료 준비 완료 · 작성 대기'};
  data.rounds[0].items[0].preparation = {status:'ready',reviewStatus:'unreviewed'};
  data.rounds[0].items[1].workflow = {status:'brief_registered',label:'브리핑 등록'};
  data.rounds[0].items[1].paperId = 'selected-1';
  const ui = harness(async url => url === '/api/rounds' ? data : {run:null});
  await ui.run('refreshRounds()');
  assert.match(ui.html(), /자료 준비 완료 1편/);
  assert.match(ui.html(), /브리핑 등록 1편/);
  assert.match(ui.html(), /href="#\/card\/selected-1">카드 보기/);
  assert.doesNotMatch(ui.html(), /href="#\/paper\/selected-1/);
  assert.doesNotMatch(ui.run('renderRoundItem(roundsData.rounds[0].items[0])'), /data-round-prepare=/);
  assert.equal(ui.context.candidates.find(item => item.id === 'selected-0').preparation.reviewStatus, 'unreviewed');
});

test('running preparation polls only while the round page remains active', async () => {
  const data = fixture();
  const ui = harness(async url => url === '/api/rounds' ? data : {run:{status:'running',candidateIds:['selected-0'],processed:0,total:1,stage:'원자료 확인'}});
  await ui.run('refreshRounds()');
  assert.equal(ui.timers.size, 1);
  assert.match(ui.html(), /자료 준비 0 \/ 1편 · 원자료 확인/);
  ui.context.location.hash = '#/library';
  await ui.run('refreshRounds()');
  assert.equal(ui.timers.size, 0);
});

test('a failed status refresh is explicit and does not pretend the round is complete', async () => {
  const ui = harness(async () => { throw new Error('round fixture unavailable'); });
  await ui.run('refreshRounds()');
  assert.equal(ui.elements.get('#round-errors').hidden, false);
  assert.match(ui.elements.get('#round-errors').innerHTML, /round fixture unavailable/);
  assert.doesNotMatch(ui.html(), /브리핑 등록 6편/);
  assert.equal(ui.timers.size, 0);
});

test('mixed source results show available bodies separately from complete preparation and missing bodies', async () => {
  const data = fixture();
  data.rounds[0].items.forEach((item,index) => {
    const partial = index < 3;
    item.preparation = {status:partial ? 'partial' : 'failed',reviewStatus:'unreviewed',generationStatus:'needs_sources',
      coverage:[{kind:'body',acquired:1,usable:partial ? 8 : 0}],reason:partial ? '첨부자료 확인 필요' : '본문 응답 미확보'};
    item.workflow = {status:partial ? 'materials_partial' : 'materials_failed',
      label:partial ? '본문 확보 · 일부 자료 확인 필요' : '본문 미확보 · 자료 준비 실패'};
  });
  const ui = harness(async url => url === '/api/rounds' ? data : {run:{status:'completed',ready:0,partial:3,failed:3,stage:'자료 준비 실패'}});
  await ui.run('refreshRounds()');
  assert.match(ui.html(), /본문 확보 3 \/ 6편/);
  assert.match(ui.html(), /자료 준비 완료 0편 · 일부 자료 3편 · 본문 미확보 3편/);
  assert.match(ui.html(), /미확보 자료 6편 다시 시도/);
  assert.doesNotMatch(ui.html(), /round-progress|검토 완료|작성 대기/);
  assert.match(ui.run('renderRoundItem(roundsData.rounds[0].items[0])'), /본문 확보 · 일부 자료 확인 필요/);
  assert.equal(ui.context.candidates.find(item => item.id === 'selected-0').preparation.reviewStatus, 'unreviewed');
});

test('bulk retry includes only partial and failed papers in this round', async () => {
  const data = fixture();
  const statuses = ['selected','writing_waiting','materials_partial','materials_failed','brief_registered','materials_preparing'];
  data.rounds[0].items.forEach((item,index) => { item.workflow.status = statuses[index]; });
  let posted;
  const ui = harness(async (url,options) => {
    if (options?.method === 'POST') { posted = JSON.parse(options.body).candidateIds; return {run:{status:'running'}}; }
    return url === '/api/rounds' ? data : {run:null};
  });
  await ui.run('refreshRounds()');
  await ui.run('startRoundPreparation("retry")');
  assert.deepEqual(posted, ['selected-2','selected-3']);
});
