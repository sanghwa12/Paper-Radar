/* Focused-card navigation and state regressions using actual application functions. */
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

function harness(hash = '#/card/selected') {
  const elements = new Map();
  const location = {hash};
  const window = {scrollY: 0, scrollTo({top}) { this.scrollY = top; }};
  const entries = [{hash, state: null}];
  let index = 0;
  let context;
  const history = {
    get state() { return entries[index].state; },
    replaceState(state, _title, hash) {
      entries[index] = {state, hash: hash ?? location.hash};
      location.hash = entries[index].hash;
    },
    pushState(state, _title, hash) {
      entries.splice(++index, entries.length, {state, hash});
      location.hash = hash;
    },
    back() {
      assert.ok(index > 0);
      location.hash = entries[--index].hash;
      vm.runInContext('route()', context);
    },
  };
  const main = {
    set innerHTML(value) {
      this.html = value;
      elements.delete('#paper-results');
      elements.delete('#filter-reset');
      if (value.includes('id="paper-results"')) elements.set('#paper-results', {innerHTML: ''});
      if (value.includes('id="filter-reset"')) elements.set('#filter-reset', {hidden: false});
    },
  };
  const paper = id => ({id, metadata: {title: `Fixture ${id}`}, state: {read: false, saved: false}});
  const notifications = [];
  context = vm.createContext({
    location, history, window, main, document: {title: ''}, clearTimeout() {}, roundsTimer: null,
    filters: {collection: 'saved', search: 'different paper', area: 'unrelated', from: '2026-09-23', to: '2026-09-01'},
    feed: {collection: 'unread', area: 'CADD·AI', search: 'earlier query'},
    discovery: {search: 'collection query', page: 1}, evaluation: {}, generationPilotView: {},
    papers: [paper('selected'), paper('other')], currentId: null,
    isCardFeed: () => ['', '#/', '#/discover'].includes(location.hash),
    $: selector => elements.get(selector) || null,
    $$: () => [],
    renderCard: paper => `<article data-paper="${paper.id}" data-read="${paper.state.read}" data-saved="${paper.state.saved}"></article>`,
    renderSidebar() {},
    matches() { throw new Error('Focused card must ignore Library filters'); },
    feedMatches() { throw new Error('Focused card must ignore feed filters'); },
    renderCollection() { main.innerHTML = 'collection view'; },
    renderDiscover() { main.innerHTML = 'discover view'; },
    renderPaper(paper, tab) { main.innerHTML = `brief ${paper.id} ${tab}`; },
    renderLibrary() { main.innerHTML = 'library view'; },
    async patchState(id, changes) {
      Object.assign(context.papers.find(paper => paper.id === id).state, changes);
    },
    notify: message => notifications.push(message),
  });
  vm.runInContext([
    section('function rememberView()', 'function notify('),
    section('function renderResults()', 'function renderLibrary()'),
    section('async function toggleState(', 'function showDocumentPage('),
    section('function renderFocusedCard(', "document.addEventListener('click'"),
  ].join('\n'), context);
  return {
    run: code => vm.runInContext(code, context),
    html: () => elements.get('#paper-results')?.innerHTML,
    elements, main, context, location, window, notifications,
  };
}

test('direct focused-card route ignores conflicting list filters without requiring filter controls', () => {
  const ui = harness();
  ui.run('route()');
  assert.equal(ui.elements.has('#filter-reset'), false);
  assert.match(ui.html(), /data-paper="selected"/);
  assert.doesNotMatch(ui.html(), /other|empty-state/);
  assert.match(ui.main.html, /href="#\/discover"/);
  assert.equal(ui.context.currentId, null);
});

test('read and saved toggles keep the same focused card visible', async () => {
  const ui = harness();
  ui.run('route()');
  await ui.run('toggleState({dataset:{id:"selected",state:"read"},disabled:false})');
  assert.match(ui.html(), /data-read="true"/);
  assert.doesNotMatch(ui.html(), /other/);
  await ui.run('toggleState({dataset:{id:"selected",state:"saved"},disabled:false})');
  assert.match(ui.html(), /data-saved="true"/);
  assert.equal(ui.location.hash, '#/card/selected');
  assert.equal(ui.context.papers[1].state.read, false);
  assert.equal(ui.context.papers[1].state.saved, false);
  assert.equal(ui.notifications.length, 2);
});

test('collection to card to briefing can return through the card with original filters and scroll', () => {
  const ui = harness('#/collection');
  ui.run('route()');
  ui.window.scrollY = 420;
  ui.run('navigate("#/card/selected")');
  assert.equal(ui.window.scrollY, 0);
  assert.match(ui.html(), /selected/);
  ui.window.scrollY = 160;
  ui.run('navigate("#/paper/selected/summary")');
  assert.equal(ui.main.html, 'brief selected summary');
  ui.run('goBack()');
  assert.equal(ui.location.hash, '#/card/selected');
  assert.equal(ui.window.scrollY, 160);
  assert.match(ui.html(), /selected/);
  ui.run('goBack()');
  assert.equal(ui.location.hash, '#/collection');
  assert.equal(ui.window.scrollY, 420);
  assert.equal(ui.context.discovery.search, 'collection query');
  assert.equal(ui.context.feed.search, 'earlier query');
  assert.equal(ui.context.filters.search, 'different paper');
});

test('a directly opened focused card has a usable back button and returns to the card feed', () => {
  const ui = harness();
  ui.run('route()');
  assert.doesNotMatch(ui.run('backButton()'), /disabled/);
  ui.run('goBack()');
  assert.equal(ui.location.hash, '#/discover');
  assert.equal(ui.main.html, 'discover view');
});

test('prepared-material dialog acknowledges an existing draft without claiming generation is waiting', async () => {
  const reader = {open: false, showModal() { this.open = true; }};
  const body = {innerHTML: ''};
  const elements = {'#preparation-reader': reader, '#preparation-reader-body': body, '#preparation-reader-title': {textContent: ''}};
  const candidate = {id: 'selected', title: 'Fixture paper', generatedCard: {paperId: 'selected', reviewStatus: 'partial'}};
  const context = vm.createContext({
    candidates: [candidate], preparationRequestId: 0, preparationOpenId: null,
    preparationStatusNames: {ready: '생성 대기'},
    $: selector => elements[selector] || null,
    escape: value => String(value),
    renderCandidateResults() {},
    async discoveryRequest() { return {preparation: {status: 'ready', generationStatus: 'waiting', reviewStatus: 'unreviewed'}}; },
  });
  vm.runInContext(section('function hasPreparedBody(', 'function renderCandidatePreparation(')
    + section('async function openPreparation(', 'async function openSource('), context);
  await vm.runInContext('openPreparation("selected")', context);
  assert.match(body.innerHTML, /브리핑 초안 있음/);
  assert.match(body.innerHTML, /실제 검토 범위는 상세 브리핑에서/);
  assert.doesNotMatch(body.innerHTML, /생성 대기|검토 완료/);
  assert.equal(candidate.preparation.reviewStatus, 'unreviewed');
});
