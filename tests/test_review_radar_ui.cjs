/* Review UI behavior with actual application functions and inert API fixtures. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.join(__dirname, '..');
const reviewScript = fs.readFileSync(path.join(root, 'public', 'review-radar.js'), 'utf8');
const app = fs.readFileSync(path.join(root, 'public', 'app.js'), 'utf8');
function section(from, to) {
  const start = app.indexOf(from), end = app.indexOf(to, start);
  assert.ok(start >= 0 && end > start);
  return app.slice(start, end);
}
const policy = {windowYears:3,focus:'narrative_methods',areas:['Area A','Area B'],from:'2023-09-23',to:'2026-09-23',oldWorkStatus:'paused',scoringStatus:'not_defined'};
const review = {
  id:'review-one',title:'A review fixture',titleKo:'리뷰 시범',date:'2025-02-01',journal:'Fixture Journal',authors:'Reader A',areas:['Area A'],
  sourceUrl:'https://example.org/review',doi:'10.0000/review',selectionReason:'분야의 비교 관점을 정리합니다.',
  summary:{scope:'분야의 방법 변화',takeaways:['검토한 요약'],limitations:['다루지 않은 범위']},
  readingScope:{abstract:'checked',fullText:'partial',figures:'unverified',supplements:'unverified',originalPapers:'metadata_only',note:'본문 일부와 인용 목록을 확인했습니다.'},
  originals:[{title:'Linked original',doi:'10.0000/original',year:2024,sourceUrl:'https://example.org/original',role:'핵심 비교의 사례',referenceLabel:'Ref. 3',referenceLocation:'Section 2',verification:'citation_metadata',note:'원저 내용은 아직 검토하지 않았습니다.'}],
  citations:{count:0,observedAt:'2026-09-23T10:00:00Z',sourceUrl:'https://example.org/citations'},
  journalMetric:{jif:null,year:null,status:'unverified'},provenance:[{label:'Review',url:'https://example.org/review',checkedAt:'2026-09-23',scope:'본문 일부'}],summaryStatus:'partial_review',
};
const catalog = () => ({policy, reviews:[review]});
function detailedReview(id = 'review-one') {
  const paper = JSON.parse(JSON.stringify(review));
  paper.id = id;
  paper.briefing = {version:1,updatedAt:'2026-09-23T12:00:00Z',
    sources:[{id:'review-source',label:'Review source',url:'https://example.org/section',location:'Section 3, Figure 2',scope:'리뷰 본문과 그림 설명 확인'}],
    sections:[['overview','요약'],['methods','방법 비교'],['evidence','근거와 원저'],['limits','그림·한계'],['application','연구 적용']].map(([id,title]) => ({id,title,lead:`Lead for ${id}`,blocks:[{heading:`Heading ${id}`,kind:id === 'application' ? 'interpretation' : 'review_claim',paragraphs:[`Detailed paragraph for ${id}`],sourceIds:['review-source']}]}))};
  paper.briefing.sections[0].flow = [{title:'Question',text:'The conceptual question'},{title:'Comparison',text:'The interpretation of a comparison'}];
  paper.briefing.sections[1].table = {caption:'Method comparison',columns:['Approach','Assumption'],rows:[{cells:['Example approach','Stated assumption'],sourceIds:['review-source']}]};
  paper.briefing.sections[3].figure = {src:'/assets/review-radar/review-one/kinetics-map.svg',alt:'Independent conceptual figure',caption:'분석자가 작성한 해설도',sourceIds:['review-source']};
  return paper;
}
const searchData = (candidates = [{title:'Candidate A',date:'2025-03-01',journal:'Candidate Journal',sourceUrl:'https://example.org/candidate',abstract:'Abstract text',classification:{kind:'review',label:'Review'}}]) => ({candidates,query:'TITLE_ABS:fixture',sourceUrl:'https://example.org/search',observedAt:'2026-09-23',hitCount:42,fetched:30,shown:candidates.length,truncated:true,excludedCounts:{notReview:2},from:policy.from,to:policy.to});
const response = (data, ok = true) => ({ok,json:async () => data});
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness(request, hash = '#/review-radar') {
  const staticElements = new Map();
  for (const id of ['review-radar-link','rounds-link','discover-link','collection-link','evaluation-link','generation-pilot-link','collection-nav','area-nav']) {
    const classes = new Set(), attributes = new Map();
    staticElements.set('#' + id,{innerHTML:'',classes,attributes,classList:{toggle(name,on) {on ? classes.add(name) : classes.delete(name);}},setAttribute(name,value) {attributes.set(name,value);},removeAttribute(name) {attributes.delete(name);}});
  }
  const elements = new Map();
  const location = {hash};
  const window = {scrollY:0,scrollTo({top}) {this.scrollY = top;}};
  const main = {
    html:'',
    set innerHTML(value) {
      this.html = value;
      elements.clear();
      for (const match of value.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g)) {
        const [,tag,id] = match;
        let field = match[0].match(/\bvalue="([^"]*)"/)?.[1] || '';
        if (tag === 'select') {
          const options = value.slice(match.index + match[0].length).split('</select>')[0];
          field = options.match(/<option value="([^"]*)" selected>/)?.[1] || options.match(/<option value="([^"]*)"/)?.[1] || '';
        }
        const attributes = new Map([...match[0].matchAll(/([\w-]+)="([^"]*)"/g)].map(item => [item[1],item[2]]));
        elements.set('#' + id,{value:field,disabled:/\sdisabled(?:\s|>)/.test(match[0]),hidden:/\shidden(?:\s|>)/.test(match[0]),tabIndex:Number(attributes.get('tabindex') || 0),innerHTML:'',attributes,
          getAttribute(name) {return attributes.get(name) ?? null;},setAttribute(name,value) {attributes.set(name,value);},
          focus() {context.document.activeElement = this;}});
      }
    },
  };
  const entries = [{hash,state:null}];
  let index = 0, context;
  const history = {
    get state() {return entries[index].state;},
    replaceState(state,_title,next) {entries[index] = {state,hash:next ?? location.hash};location.hash = entries[index].hash;},
    pushState(state,_title,next) {entries.splice(++index,entries.length,{state,hash:next});location.hash = next;},
    back() {assert.ok(index > 0);location.hash = entries[--index].hash;vm.runInContext('route()',context);},
  };
  const calls = [];
  context = vm.createContext({
    main,window,history,location,document:{title:''},currentId:'old-paper',roundsTimer:null,clearTimeout() {},
    filters:{collection:'saved',area:'Area A',search:'my old query'},feed:{collection:'unread',search:'old feed'},discovery:{page:2},evaluation:{},generationPilotView:{},
    papers:[{id:'old-paper',kind:'discovery',metadata:{categories:['Area A']},state:{read:true,saved:true,notes:'Preserve my memo'}}],
    noteDrafts:new Map([['old-paper','unsaved note']]),
    areaNames:policy.areas,areaDescriptions:{},icon:() => '',
    isCardFeed:() => ['', '#/', '#/discover'].includes(location.hash),
    $:selector => elements.get(selector) || staticElements.get(selector) || null,
    fetch:async (url,options) => {calls.push({url,options});return request(url,options);},
    renderDiscover() {main.innerHTML = 'old discover';},renderLibrary() {main.innerHTML = 'old library';},renderCollection() {main.innerHTML = 'old collection';},renderRounds() {},renderGenerationPilot() {},renderEvaluation() {},
  });
  vm.runInContext([
    section('const escape =', '// Content is local'),
    section('function rememberView()', 'function notify('),
    section('function renderSidebar()', 'function openAreaGuide('),
    reviewScript,
    section('function route()', "document.addEventListener('click'"),
  ].join('\n'),context);
  return {context,elements,staticElements,calls,location,window,main,run:code => vm.runInContext(code,context),
    html:() => main.html,open:() => vm.runInContext('reviewRadar.open()',context),
    submit:() => elements.get('#review-search-form').onsubmit({preventDefault() {}})};
}

test('entering review Radar fetches live registered data without starting a search or changing original records', async () => {
  const ui = harness(async () => response(catalog()));
  const before = JSON.stringify(ui.context.papers);
  await ui.open();
  await ui.open();
  assert.deepEqual(ui.calls.map(call => call.url), ['/api/review-radar','/api/review-radar']);
  assert.ok(ui.calls.every(call => !call.options));
  assert.match(ui.html(), /A review fixture/);
  assert.match(ui.html(), /검색 후보는 최대 30편/);
  assert.match(ui.html(), /id="review-search-keywords"[^>]*maxlength="120"/);
  assert.equal(JSON.stringify(ui.context.papers),before);
  assert.equal(ui.context.noteDrafts.get('old-paper'),'unsaved note');
  assert.equal(ui.staticElements.get('#review-radar-link').attributes.get('aria-current'),'page');
  assert.doesNotMatch(ui.staticElements.get('#collection-nav').innerHTML,/aria-current/);
});

test('explicit search posts the selected criteria once and disables duplicate submissions while pending', async () => {
  let complete;
  const ui = harness(async (url) => url.endsWith('/search') ? new Promise(resolve => {complete = resolve;}) : response(catalog()));
  await ui.open();
  ui.elements.get('#review-search-area').value = 'Area B';
  ui.elements.get('#review-search-keywords').value = '  comparison  ';
  ui.elements.get('#review-search-sort').value = 'newest';
  const pending = ui.submit();
  await tick();
  assert.equal(ui.elements.get('#review-search-submit').disabled,true);
  await ui.submit();
  const posts = ui.calls.filter(call => call.options);
  assert.equal(posts.length,1);
  assert.equal(posts[0].url,'/api/review-radar/search');
  assert.deepEqual(JSON.parse(posts[0].options.body),{area:'Area B',keywords:'comparison',sort:'newest'});
  complete(response(searchData()));
  await pending;
  assert.equal(ui.elements.get('#review-search-submit').disabled,false);
  assert.match(ui.html(), /Candidate A/);
  assert.match(ui.html(), /메타데이터 후보 · 미검토/);
  assert.doesNotMatch(ui.html(), /data-preparation|data-source-fetch|data-state=/);
});

test('a failed new search leaves the earlier result explicitly labelled and keeps the new input', async () => {
  let attempts = 0;
  const ui = harness(async url => !url.endsWith('/search') ? response(catalog()) : ++attempts === 1 ? response(searchData()) : response({error:'Temporary error'},false));
  await ui.open();
  ui.elements.get('#review-search-keywords').value = 'earlier topic';
  await ui.submit();
  ui.elements.get('#review-search-keywords').value = 'new topic';
  await ui.submit();
  assert.match(ui.html(), /검색하지 못했습니다/);
  assert.match(ui.html(), /이전에 성공한 검색 결과/);
  assert.match(ui.html(), /Candidate A/);
  assert.match(ui.html(), /earlier topic/);
  assert.equal(ui.elements.get('#review-search-keywords').value,'new topic');
});

test('late search responses cannot repaint the original-paper page after navigation', async () => {
  let complete;
  const ui = harness(async url => url.endsWith('/search') ? new Promise(resolve => {complete = resolve;}) : response(catalog()));
  await ui.open();
  const pending = ui.submit();
  await tick();
  ui.location.hash = '#/discover';
  ui.main.innerHTML = 'original paper view';
  complete(response(searchData()));
  await pending;
  assert.equal(ui.html(),'original paper view');
});

test('metadata stays escaped, unsafe external links are inert, and only thirty candidates display', async () => {
  const candidates = Array.from({length:31},(_,i) => ({title:`Candidate ${i} <img src=x onerror=bad()>`,sourceUrl:'javascript:bad()',abstract:'<script>bad()</script>',classification:{label:'<b>Review</b>'}}));
  const ui = harness(async url => response(url.endsWith('/search') ? searchData(candidates) : catalog()));
  await ui.open();
  await ui.submit();
  assert.equal((ui.html().match(/class="review-candidate"/g) || []).length,30);
  assert.doesNotMatch(ui.html(), /Candidate 30 /);
  assert.doesNotMatch(ui.html(), /<img|<script|href="javascript:/);
  assert.match(ui.html(), /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
  assert.match(ui.html(), /일부 결과만 표시/);
});

test('registered review detail separates partial reading from unreviewed linked originals and unknown JIF', async () => {
  const ui = harness(async () => response(catalog()), '#/review-radar/review-one');
  await ui.open();
  assert.match(ui.html(), /본문 일부 검토/);
  assert.match(ui.html(), /연결된 원저<\/dt><dd>본문 미검토 · 확인 범위는 출처 참고/);
  assert.match(ui.html(), /원저 본문 미검토/);
  assert.match(ui.html(), /확인한 자료의 범위는 각 근거와 원저 설명에 표시했습니다/);
  assert.match(ui.html(), /Section 2/);
  assert.match(ui.html(), /인용 0회/);
  assert.match(ui.html(), /Journal Impact Factor 미확인/);
  assert.doesNotMatch(ui.html(), /총점|검토 완료|data-state=/);
  assert.doesNotMatch(ui.html(), /id="review-brief-tabs"/);
  assert.match(ui.html(), /검토한 요약/);
  assert.match(ui.html(), /<p>본문 일부와 인용 목록을 확인했습니다\.<\/p><details><summary>검토 범위/);
});

test('a deep briefing has five working tabs, row-level evidence and originals only in the evidence panel', async () => {
  const ui = harness(async () => response({policy,reviews:[detailedReview()]}),'#/review-radar/review-one');
  await ui.open();
  const tabs = ['overview','methods','evidence','limits','application'];
  assert.equal((ui.html().match(/role="tab"/g) || []).length,5);
  assert.equal((ui.html().match(/role="tabpanel"/g) || []).length,5);
  const scope = ui.html().split('<aside class="review-reading-scope">')[1].split('</aside>')[0];
  assert.match(scope, /<\/strong><details><summary>검토 범위<\/summary><p>본문 일부와 인용 목록을 확인했습니다\.<\/p>/);
  for (const selected of tabs) {
    const button = ui.elements.get('#review-brief-tab-' + selected);
    assert.equal(button.getAttribute('aria-controls'),'review-brief-panel-' + selected);
    button.onclick();
    for (const id of tabs) {
      assert.equal(ui.elements.get('#review-brief-tab-' + id).getAttribute('aria-selected'),String(id === selected));
      assert.equal(ui.elements.get('#review-brief-panel-' + id).hidden,id !== selected);
      assert.equal(ui.elements.get('#review-brief-tab-' + id).tabIndex,id === selected ? 0 : -1);
    }
  }
  const evidenceStart = ui.html().indexOf('id="review-brief-panel-evidence"');
  const limitsStart = ui.html().indexOf('id="review-brief-panel-limits"');
  const originalsStart = ui.html().indexOf('class="review-originals"');
  assert.ok(originalsStart > evidenceStart && originalsStart < limitsStart);
  assert.equal((ui.html().match(/class="review-originals"/g) || []).length,1);
  assert.match(ui.html(), /분석자가 재구성한 개념 흐름/);
  assert.match(ui.html(), /class="review-table-scroll" role="region" tabindex="0"/);
  const table = ui.html().split('<table class="review-method-table">')[1].split('</table>')[0];
  assert.match(table, /<caption>Method comparison<\/caption>/);
  assert.match(table, /<th scope="row">Example approach<\/th>/);
  assert.match(table, /<details class="review-block-sources">/);
  assert.match(table, /Section 3, Figure 2/);
  assert.match(table, /리뷰 본문과 그림 설명 확인/);
  assert.equal(ui.location.hash,'#/review-radar/review-one');
});

test('briefing arrow, Home and End keys move focus and selection without changing route or requesting data', async () => {
  const ui = harness(async () => response({policy,reviews:[detailedReview()]}),'#/review-radar/review-one');
  await ui.open();
  let prevented = 0;
  function key(from,key) {
    ui.elements.get('#review-brief-tabs').onkeydown({target:ui.elements.get('#review-brief-tab-' + from),key,preventDefault() {prevented++;}});
  }
  for (const [from,press,to] of [['overview','ArrowRight','methods'],['methods','End','application'],['application','ArrowRight','overview'],['overview','ArrowLeft','application'],['application','Home','overview']]) {
    key(from,press);
    const selected = ui.elements.get('#review-brief-tab-' + to);
    assert.equal(ui.context.document.activeElement,selected);
    assert.equal(selected.getAttribute('aria-selected'),'true');
  }
  key('overview','Tab');
  assert.equal(prevented,5);
  assert.equal(ui.calls.length,1);
  assert.equal(ui.location.hash,'#/review-radar/review-one');
});

test('each review remembers its own tab while the list stays short and original personal state remains unchanged', async () => {
  const reviews = [detailedReview(),detailedReview('review-two')];
  const ui = harness(async () => response({policy,reviews}),'#/review-radar/review-one');
  const before = JSON.stringify(ui.context.papers);
  await ui.open();
  ui.elements.get('#review-brief-tab-methods').onclick();
  ui.location.hash = '#/review-radar/review-two';
  await ui.open();
  assert.equal(ui.elements.get('#review-brief-tab-overview').getAttribute('aria-selected'),'true');
  ui.elements.get('#review-brief-tab-application').onclick();
  ui.location.hash = '#/review-radar';
  await ui.open();
  assert.match(ui.html(), /상세 브리핑 →/);
  assert.doesNotMatch(ui.html(), /Detailed paragraph for|role="tablist"/);
  ui.location.hash = '#/review-radar/review-one';
  await ui.open();
  assert.equal(ui.elements.get('#review-brief-tab-methods').getAttribute('aria-selected'),'true');
  ui.location.hash = '#/review-radar/review-two';
  await ui.open();
  assert.equal(ui.elements.get('#review-brief-tab-application').getAttribute('aria-selected'),'true');
  assert.equal(JSON.stringify(ui.context.papers),before);
  assert.equal(ui.context.noteDrafts.get('old-paper'),'unsaved note');
});

test('missing or broken source links remain explicit and briefing text cannot inject HTML or unsafe URLs', async () => {
  const paper = detailedReview();
  paper.briefing.sources[0] = {id:'review-source',label:'<b>Source</b>',url:'javascript:alert(1)',location:'',scope:''};
  paper.briefing.sections[0].blocks[0].sourceIds = [];
  paper.briefing.sections[1].blocks[0].sourceIds = ['missing'];
  paper.briefing.sections[2].blocks[0].paragraphs = ['<script>unsafe()</script>'];
  paper.briefing.sections[4].blocks[0].sourceIds = [];
  const ui = harness(async () => response({policy,reviews:[paper]}),'#/review-radar/review-one');
  await ui.open();
  assert.match(ui.html(), /근거 미확인 · 연결된 출처가 없습니다/);
  assert.match(ui.html(), /출처 미확인/);
  assert.match(ui.html(), /위치<\/dt><dd>미확인/);
  assert.match(ui.html(), /확인 범위<\/dt><dd>미확인/);
  assert.match(ui.html(), /<span>분석자 해석<\/span>/);
  assert.doesNotMatch(ui.html(), /직접 인용 근거는 연결하지 않았습니다/);
  assert.match(ui.html(), /&lt;script&gt;unsafe\(\)&lt;\/script&gt;/);
  assert.doesNotMatch(ui.html(), /<script>|href="javascript:|<b>Source<\/b>/);
});

test('briefing figures use only local review assets and keep caption evidence beside the figure', async () => {
  const paper = detailedReview();
  const ui = harness(async () => response({policy,reviews:[paper]}),'#/review-radar/review-one');
  await ui.open();
  assert.match(ui.html(), /data-image="\/assets\/review-radar\/review-one\/kinetics-map.svg"/);
  assert.match(ui.html(), /alt="Independent conceptual figure"/);
  const figure = ui.html().split('<figure class="review-brief-figure">')[1].split('</figure>')[0];
  assert.match(figure, /분석자가 작성한 해설도/);
  assert.match(figure, /<details class="review-block-sources">/);
  for (const src of ['https://example.org/external.svg','/assets/review-radar/../private.svg','data:image/svg+xml,unsafe']) {
    paper.briefing.sections[3].figure.src = src;
    await ui.open();
    assert.match(ui.html(), /그림 자료 미확인/);
    assert.doesNotMatch(ui.html(), /<img /);
  }
});

test('backend exclusion reasons display user labels without leaking internal keys', async () => {
  const data = searchData();
  data.excludedCounts = {invalidMetadata:1,outsideWindow:2,notReview:3,systematicOrMetaAnalysis:4,duplicate:5};
  const ui = harness(async url => response(url.endsWith('/search') ? data : catalog()));
  await ui.open();
  await ui.submit();
  for (const label of ['서지정보 확인 필요 1편','기간 밖 2편','리뷰 유형 불일치 3편','체계적 고찰·메타분석 4편','중복 5편']) assert.ok(ui.html().includes(label));
  for (const key of Object.keys(data.excludedCounts)) assert.ok(!ui.html().includes(key));
});

test('a failed refresh marks the retained catalog and does not replace it with an empty success', async () => {
  let attempts = 0;
  const ui = harness(async () => ++attempts === 1 ? response(catalog()) : response({error:'Invalid record'},false));
  await ui.open();
  await ui.open();
  assert.match(ui.html(), /등록 리뷰를 불러오지 못했습니다/);
  assert.match(ui.html(), /이전에 불러온 등록 자료/);
  assert.match(ui.html(), /A review fixture/);
  assert.ok(ui.elements.has('#review-load-retry'));
});

test('review list and detail navigation preserve original filters, memo drafts and back navigation', async () => {
  const ui = harness(async () => response(catalog()), '#/library');
  ui.run('route()');
  ui.window.scrollY = 210;
  const originalFilters = JSON.stringify(ui.context.filters);
  ui.run("navigate('#/review-radar')");
  await tick();
  ui.elements.get('#review-search-keywords').value = 'retained search';
  ui.elements.get('#review-search-keywords').oninput({target:{value:'retained search'}});
  ui.window.scrollY = 120;
  ui.run("navigate('#/review-radar/review-one')");
  await tick();
  assert.match(ui.html(), /핵심 원저/);
  ui.run('goBack()');
  await tick();
  assert.equal(ui.location.hash,'#/review-radar');
  assert.equal(ui.window.scrollY,120);
  assert.equal(ui.elements.get('#review-search-keywords').value,'retained search');
  ui.run('goBack()');
  assert.equal(ui.location.hash,'#/library');
  assert.equal(ui.window.scrollY,210);
  assert.equal(JSON.stringify(ui.context.filters),originalFilters);
  assert.equal(ui.context.noteDrafts.get('old-paper'),'unsaved note');
});

test('unknown direct review links can return to the list and scripts keep original routes available', async () => {
  const ui = harness(async () => response(catalog()), '#/review-radar/missing');
  await ui.open();
  assert.match(ui.html(), /등록된 리뷰를 찾을 수 없습니다/);
  assert.match(ui.html(), /href="#\/review-radar"/);
  const html = fs.readFileSync(path.join(root,'public','index.html'),'utf8');
  assert.ok(html.indexOf('src="/review-radar.js"') < html.indexOf('src="/app.js"'));
  for (const id of ['rounds-link','discover-link','collection-link','evaluation-link','generation-pilot-link','collection-nav']) assert.ok(html.includes(`id="${id}"`));
  assert.match(html, /class="brand" href="#\/discover"/);
});
