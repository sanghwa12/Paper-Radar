/* Preparation click feedback and retry regressions; no network or project data writes. */
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

function harness(request, {actualFeedback = false} = {}) {
  const snapshots = [];
  const elements = new Map(['#preparation-state', '#preparation-errors'].map(selector => [selector, {}]));
  const cards = ['selected', 'other'].map(id => ({dataset: {preparationCandidate: id}, innerHTML: ''}));
  const buttons = cards.map(() => ({disabled: false}));
  let context;
  const render = () => snapshots.push(vm.runInContext(
    'candidates.map(candidate => ({id:candidate.id,html:renderCandidatePreparation(candidate)}))', context));
  const candidate = id => ({id, title: `Fixture ${id}`, classification: {kind: 'original'}});
  context = vm.createContext({
    candidates: [candidate('selected'), candidate('other')],
    candidatesLoaded: true,
    candidateError: '',
    acquisitionStarting: false,
    acquisitionData: null,
    discoveryRequest: request,
    clearTimeout() {},
    setTimeout() { return 1; },
    renderCandidateResults: render,
    renderFeedback: render,
    $: selector => elements.get(selector),
    $$: selector => selector === '[data-preparation-candidate]' ? cards
      : selector === '[data-preparation-start]' ? buttons : [],
    countText: value => String(Number(value || 0)),
    escape: value => String(value).replace(/[&<>"']/g, character => (
      {'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[character])),
  });
  vm.runInContext([
    section('let preparationData =', 'let papers ='),
    section('const candidateKinds =', 'function candidateMatches()'),
    section('function renderPreparationState()', 'function preparationAsset('),
    // Most tests record requested renders; integration tests exercise the actual DOM updater.
    actualFeedback ? '' : 'renderPreparationState = renderFeedback;',
  ].join('\n'), context);
  return {
    snapshots,
    run: code => vm.runInContext(code, context),
    card: id => vm.runInContext(`renderCandidatePreparation(candidates.find(candidate => candidate.id === ${JSON.stringify(id)}))`, context),
    renderedCard: id => cards.find(card => card.dataset.preparationCandidate === id).innerHTML,
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

test('the clicked card shows a request in progress before POST resolves', async () => {
  const pending = deferred();
  const ui = harness((_url, options) => {
    assert.equal(options.method, 'POST');
    return pending.promise;
  });
  const action = ui.run('startPreparation("selected")');
  try {
    const selected = ui.card('selected');
    assert.match(selected, /요청 중|시작|준비 중|접수/);
    assert.doesNotMatch(selected, /자료 준비 전/);
    assert.match(ui.card('other'), /자료 준비 전/);
    assert.ok(ui.snapshots.some(cards => /요청 중|시작|준비 중|접수/.test(
      cards.find(card => card.id === 'selected').html)), 'Feedback must render before the request resolves');
  } finally {
    pending.reject(new Error('fixture request ended'));
    await action;
  }
});

test('a POST failure is visible on the selected card and not an unrelated card', async () => {
  const ui = harness(async () => { throw new Error('fixture request failure'); });
  await ui.run('startPreparation("selected")');
  assert.match(ui.card('selected'), /fixture request failure/);
  assert.doesNotMatch(ui.card('selected'), /생성 대기/);
  assert.doesNotMatch(ui.card('other'), /fixture request failure/);
  assert.ok(ui.snapshots.some(cards => cards.find(card => card.id === 'selected').html.includes('fixture request failure')));
});

test('retry fetches candidates after a failed read even when the latest run is unchanged', async () => {
  let candidateRequests = 0;
  const completed = {id: 'new-run', status: 'completed', processed: 1, total: 1, ready: 1};
  const ui = harness(async url => {
    if (url === '/api/preparation') return {run: completed};
    assert.equal(url, '/api/candidates');
    candidateRequests++;
    if (candidateRequests === 1) throw new Error('fixture candidate read failure');
    return {candidates: [{id: 'selected', classification: {kind: 'original'}, preparation: {status: 'ready'}}]};
  });
  ui.run('preparationData = {run:{id:"old-run",status:"completed"}}');
  await ui.run('refreshPreparation()');
  assert.match(ui.run('preparationError'), /fixture candidate read failure/);
  await ui.run('refreshPreparation()');
  assert.equal(candidateRequests, 2);
  assert.equal(ui.run('preparationError'), '');
  assert.match(ui.card('selected'), /생성 대기/);
  assert.doesNotMatch(ui.card('selected'), /자료 준비 전/);
});

test('repeated clicks while a request or worker is busy do not send duplicate POSTs', async () => {
  const pending = deferred();
  let posts = 0;
  const ui = harness((_url, options) => {
    assert.equal(options.method, 'POST');
    posts++;
    return pending.promise;
  });
  const first = ui.run('startPreparation("selected")');
  try {
    await ui.run('startPreparation("selected")');
    await ui.run('startPreparation("other")');
    assert.equal(posts, 1);
  } finally {
    pending.reject(new Error('fixture request ended'));
    await first;
  }
  ui.run('preparationData = {run:{id:"running-run",status:"running",currentId:"selected"}}');
  await ui.run('startPreparation("other")');
  assert.equal(posts, 1);
});

test('click and failure update the existing card DOM through renderPreparationState', async () => {
  const pending = deferred();
  const ui = harness(() => pending.promise, {actualFeedback: true});
  ui.run('renderPreparationState()');
  assert.match(ui.renderedCard('selected'), /자료 준비 전/);
  const action = ui.run('startPreparation("selected")');
  try {
    assert.match(ui.renderedCard('selected'), /요청 중|시작|준비 중|접수/);
    assert.doesNotMatch(ui.renderedCard('selected'), /자료 준비 전/);
    assert.match(ui.renderedCard('other'), /자료 준비 전/);
  } finally {
    pending.reject(new Error('fixture <request> failure'));
    await action;
  }
  assert.match(ui.renderedCard('selected'), /fixture &lt;request&gt; failure/);
  assert.match(ui.renderedCard('selected'), /role="alert"/);
  assert.doesNotMatch(ui.renderedCard('other'), /fixture.*failure/);
});

test('card DOM displays the current preparation stage and then the partial-result reason', () => {
  const ui = harness(async () => { throw new Error('No request expected'); }, {actualFeedback: true});
  ui.run(`
    preparationData = {run:{id:'running-run',status:'running',candidateIds:['selected'],stage:'fixture stage'}};
    candidates[0].preparation = {status:'preparing',stage:'fixture figure download'};
    renderPreparationState();
  `);
  assert.match(ui.renderedCard('selected'), /자료 준비 중/);
  assert.match(ui.renderedCard('selected'), /fixture figure download/);
  assert.doesNotMatch(ui.renderedCard('other'), /fixture figure download/);
  ui.run(`
    preparationData.run.status = 'completed';
    candidates[0].preparation = {status:'partial',reason:'fixture supplement unavailable'};
    renderPreparationState();
  `);
  assert.match(ui.renderedCard('selected'), /본문 미확보 · 일부 자료 확인 필요/);
  assert.match(ui.renderedCard('selected'), /fixture supplement unavailable/);
  assert.doesNotMatch(ui.renderedCard('selected'), /fixture figure download|생성 대기/);
});

test('a published draft opens its card first and no longer claims generation is waiting', () => {
  const ui = harness(async () => { throw new Error('No request expected'); }, {actualFeedback: true});
  ui.run(`
    candidates[0].preparation = {status:'ready',generationStatus:'waiting',reviewStatus:'unreviewed'};
    renderPreparationState();
  `);
  assert.match(ui.renderedCard('selected'), /생성 대기/);
  assert.doesNotMatch(ui.renderedCard('selected'), /카드 보기/);
  ui.run(`
    candidates[0].generatedCard = {paperId:'selected',reviewStatus:'partial'};
    renderPreparationState();
  `);
  assert.match(ui.renderedCard('selected'), /href="#\/card\/selected"[^>]*>카드 보기/);
  assert.match(ui.renderedCard('selected'), /브리핑 초안 있음/);
  assert.doesNotMatch(ui.renderedCard('selected'), /생성 대기|검토 완료/);
  assert.equal(ui.run('candidates[0].preparation.reviewStatus'), 'unreviewed');
});

test('a usable body in partial preparation is visible without becoming ready or reviewed', () => {
  const ui = harness(async () => { throw new Error('No request expected'); }, {actualFeedback:true});
  ui.run(`candidates[0].preparation = {status:'partial',reviewStatus:'unreviewed',coverage:[{kind:'body',acquired:1,usable:9}],reason:'fixture figure missing'}; renderPreparationState();`);
  assert.match(ui.renderedCard('selected'), /본문 확보 · 일부 자료 확인 필요/);
  assert.match(ui.renderedCard('selected'), /fixture figure missing/);
  assert.doesNotMatch(ui.renderedCard('selected'), /생성 대기|검토 완료|본문 미확보/);
  ui.run(`candidates[0].preparation.coverage[0].usable = 0; renderPreparationState();`);
  assert.match(ui.renderedCard('selected'), /본문 미확보/);
  assert.equal(ui.run('candidates[0].preparation.reviewStatus'), 'unreviewed');
});
