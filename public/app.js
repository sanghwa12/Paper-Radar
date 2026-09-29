const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
const main = $('#main');
const icons = {
  library: '<rect x="4" y="4" width="6" height="16" rx="1"/><path d="m14 4 5-1 3 16-5 1z"/>',
  bookmark: '<path d="M6 4h12v17l-6-4-6 4z"/>',
  unread: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
};
const icon = (name) => `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.library}</svg>`;
const escape = (value = '') => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeUrl = (url = '') => /^(https?:\/\/|\/(?!\/)|#)/i.test(url) ? url : '';

// Content is local, reviewed data. Keep only formatting and source links in rich text.
function rich(value = '') {
  const template = document.createElement('template');
  template.innerHTML = String(value);
  const allowed = new Set(['B', 'STRONG', 'EM', 'I', 'BR', 'A', 'SUB', 'SUP', 'CODE']);
  for (const element of [...template.content.querySelectorAll('*')].reverse()) {
    if (!allowed.has(element.tagName)) {
      element.replaceWith(...element.childNodes);
      continue;
    }
    const href = element.tagName === 'A' ? safeUrl(element.getAttribute('href') || '') : '';
    for (const attr of [...element.attributes]) element.removeAttribute(attr.name);
    if (href) {
      element.setAttribute('href', href);
      if (/^https?:/.test(href)) {
        element.setAttribute('target', '_blank');
        element.setAttribute('rel', 'noopener');
      }
    }
  }
  return template.innerHTML;
}

const tabNames = {summary:'요약', overview:'방법과 결과', methods:'Methods', evidence:'그림·한계', memo:'내 메모'};
const areaDescriptions = {
  'CADD·AI': {
    scope:'계산과 AI를 이용한 후보 탐색·분자 설계·성질 예측. Docking, virtual screening, 생성 모델, active learning 등을 다룹니다.',
    checkpoints:'Baseline 비교, 데이터 누수, 외부 검증, 계산 비용과 실험 검증을 확인합니다.',
  },
  'Medicinal chemistry': {
    scope:'분자 구조를 바꾸며 활성·선택성·물성을 개선하는 연구. Hit-to-lead, SAR, scaffold와 합성 전략을 다룹니다.',
    checkpoints:'어떤 구조 변화가 어떤 성질을 바꿨는지, assay 조건과 최적화 과정의 상충 관계를 확인합니다.',
  },
  'Target·기전': {
    scope:'무엇을 표적으로 삼고, 그 표적을 조절하면 어떤 생물학적 변화가 생기는지 다룹니다. Target validation과 작용 기전 연구가 포함됩니다.',
    checkpoints:'Target engagement, 유전학적 검증, rescue 실험과 off-target 가능성을 확인합니다.',
  },
  'Drug modality': {
    scope:'약물의 형태와 표적을 조절·전달하는 방식을 다룹니다. PROTAC·molecular glue, 항체·ADC, peptide, RNA와 전달체 등이 포함됩니다.',
    checkpoints:'Modality를 선택한 이유, 작동 조건, 조직·세포 전달과 기존 방식 대비 이점을 확인합니다.',
  },
  '실험·평가 기술': {
    scope:'후보 물질과 생물학적 반응을 측정·검증하는 방법을 다룹니다. Assay, screening, imaging, omics와 질환 모델 등이 포함됩니다.',
    checkpoints:'무엇을 직접 측정하는지, 대조군, 재현성, 처리량과 적용 가능한 조건을 확인합니다.',
  },
  'ADME·PK/PD·개발 전환': {
    scope:'흡수·분포·대사·배설, 체내 노출과 약효의 관계, 안전성과 개발 가능성을 다룹니다.',
    checkpoints:'노출과 효능의 연결, 용량·시간 조건, 대사체, 독성 및 모델 간 차이를 확인합니다.',
  },
};
const areaNames = Object.keys(areaDescriptions);
const filters = {collection:'all', area:'', search:'', from:'', to:'', sort:'newest'};
const feed = {collection:'all',area:'',search:'',sort:'balanced'};
const isCardFeed = () => ['', '#/', '#/discover'].includes(location.hash);
const localDate = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
const discoveryToday = new Date();
const discoveryStart = new Date(discoveryToday);
discoveryStart.setDate(discoveryStart.getDate()-29);
const discovery = {search:'',area:'',kind:'original',sort:'balanced',page:1,from:localDate(discoveryStart),to:localDate(discoveryToday)};
const evaluation = {area:''};
let evaluationData = null;
let evaluationError = '';
let evaluationLoading = false;
const generationPilotView = {runId:'',version:'draft',tab:'card'};
const generationPilotTabs = {card:'카드',summary:'요약',overview:'방법과 결과',methods:'Methods',evidence:'그림·한계'};
let generationPilotData = null;
let generationPilotLoading = false;
let generationPilotError = '';
let roundsData = null;
let roundsLoading = false;
let roundsError = '';
let roundsStartingIds = [];
let roundsActionIds = [];
let roundsTimer;
let collectionData = null;
let candidates = [];
let candidatesLoaded = false;
let collectionError = '';
let candidateError = '';
let collectionStartError = '';
let discoveryLoading = false;
let collectionStarting = false;
let collectionTimer;
let candidateRunId = null;
let acquisitionData = null;
let acquisitionLoading = false;
let acquisitionStarting = false;
let acquisitionError = '';
let acquisitionTimer;
let sourceRequestId = 0;
let preparationData = null;
let preparationLoading = false;
let preparationStarting = false;
let preparationStartingId = null;
let preparationActionId = null;
let preparationError = '';
let preparationTimer;
let preparationRequestId = 0;
let preparationOpenId = null;
let papers = [];
let currentId = null;
let currentTab = 'summary';
let toastTimer;
const noteDrafts = new Map();
const noteTimers = new Map();
const queues = new Map();
const pending = new Set();
const saveErrors = new Set();
let documentManifest = {};
let openDocument = null;

function rememberView() {
  const index = history.state?.paperRadar?.index || 0;
  history.replaceState({paperRadar:{index,filters:{...filters},feed:{...feed},discovery:{...discovery},evaluation:{...evaluation},generationPilot:{...generationPilotView},scrollY:window.scrollY}},'');
}

function navigate(hash, changes = {}) {
  rememberView();
  const index = history.state.paperRadar.index + 1;
  Object.assign(['#/','#/discover'].includes(hash) ? feed : filters,changes);
  history.pushState({paperRadar:{index,filters:{...filters},feed:{...feed},discovery:{...discovery},evaluation:{...evaluation},generationPilot:{...generationPilotView},scrollY:0}},'',hash);
  route();
}

function backButton() {
  const canGoBack = history.state?.paperRadar?.index > 0 || /^#\/(paper|card)(\/|$)/.test(location.hash) || ['#/library','#/collection','#/evaluation','#/generation-pilot','#/rounds'].includes(location.hash);
  return `<nav class="page-navigation" aria-label="페이지 이동"><button type="button" class="button" data-back${canGoBack ? '' : ' disabled'}>← 뒤로가기</button></nav>`;
}

function goBack() {
  rememberView();
  if (history.state.paperRadar.index > 0) history.back();
  else {
    history.replaceState({paperRadar:{index:0,filters:{...filters},feed:{...feed},discovery:{...discovery},evaluation:{...evaluation},scrollY:0}},'','#/discover');
    route();
  }
}

function notify(message, isError = false) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.className = `visible${isError ? ' error' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.className = '', 4200);
}

function source(value) {
  if (!value) return '';
  if (typeof value === 'string') return rich(value);
  if (Array.isArray(value)) return value.map(source).join(' · ');
  return value.url ? `<a href="${escape(safeUrl(value.url))}">${escape(value.label || '출처 ↗')}</a>` : rich(value.label || '');
}

function zoomImage(src, alt, className = '') {
  return `<button class="image-zoom ${className}" type="button" data-image="${escape(safeUrl(src))}" data-title="${escape(alt)}" aria-label="${escape(alt)} 확대"><img src="${escape(safeUrl(src))}" alt="${escape(alt)}" loading="lazy"><span>확대 ↗</span></button>`;
}

function renderBlock(block) {
  switch (block.type) {
    case 'paragraph': return `<p>${rich(block.text)}</p>`;
    case 'callout': return `<div class="callout">${rich(block.text)}</div>`;
    case 'list': {
      const tag = block.ordered ? 'ol' : 'ul';
      return `<${tag} class="content-list">${(block.items || []).map(item => `<li>${rich(item)}</li>`).join('')}</${tag}>`;
    }
    case 'pairs': return `<dl class="content-pairs">${(block.items || []).map(item => `<div><dt>${rich(item.label)}</dt><dd>${rich(item.text)}</dd></div>`).join('')}</dl>`;
    case 'table': return `<div class="table-scroll" role="region" tabindex="0" aria-label="${escape(block.title || '연구 근거 표')}"><table><thead><tr>${(block.headers || []).map(h => `<th scope="col">${rich(h)}</th>`).join('')}</tr></thead><tbody>${(block.rows || []).map(row => `<tr>${row.map(cell => `<td>${rich(cell)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    case 'details': return `<details class="content-details"${block.open ? ' open' : ''}><summary>${rich(block.title)}</summary><div>${(block.blocks || []).map(renderBlock).join('')}</div></details>`;
    case 'image': return `<figure class="content-image"${block.id ? ` id="${escape(block.id)}"` : ''}>${zoomImage(block.src, block.alt || block.caption || '연구 자료')}<figcaption>${rich(block.caption || '')}${block.source ? `<small>${source(block.source)}</small>` : ''}</figcaption></figure>`;
    case 'figure': return `<figure class="figure-sheet"${block.id ? ` id="${escape(block.id)}"` : ''}><div class="figure-heading"><small>${rich(block.eyebrow || '')}</small><h3>${rich(block.title)}</h3><p>${rich(block.description || '')}</p></div>${zoomImage(block.image || block.src, block.alt || block.title)}<figcaption>${block.explanation?.length ? `<h4>그림 읽기</h4>${renderBlock({type:'pairs', items:block.explanation})}` : ''}${block.caption ? `<details class="original-caption"><summary>영문 원문 caption</summary><p>${rich(block.caption)}</p></details>` : ''}<small>${source(block.source)}</small></figcaption></figure>`;
    case 'ligands': return `<div class="ligand-grid">${(block.items || []).map(item => `<article class="ligand-card"><h3>${rich(item.title)}</h3>${zoomImage(item.image || item.src, item.alt || `${item.title} 구조식`, 'ligand-image')}<p>${rich(item.text)}</p><small>${source(item.source)}</small></article>`).join('')}</div>`;
    case 'links': return `<div class="content-links">${(block.items || []).map(item => `<a href="${escape(safeUrl(item.url || item.href))}">${escape(item.label || item.text)}</a>`).join('')}</div>`;
    case 'grid': return `<div class="content-grid">${(block.blocks || []).map(renderBlock).join('')}</div>`;
    default: return '';
  }
}

function renderSections(sections = []) {
  return sections.map(section => `<section class="content-section"${section.id ? ` id="${escape(section.id)}"` : ''}>${section.title ? `<h2>${rich(section.title)}</h2>` : ''}${(section.blocks || []).map(renderBlock).join('')}</section>`).join('');
}

function renderAbstract(paper, collapsible = false) {
  const body = `<div class="abstract-body">${(paper.abstract?.paragraphs || []).map(p => `<p>${rich(p)}</p>`).join('')}<small>저자 Abstract의 전문 번역 · 전문 용어는 원문 유지 · ${source(paper.abstract?.source)}${paper.abstract?.pageImage ? ` · <a href="${escape(safeUrl(paper.abstract.pageImage))}">원문 페이지 보기 ↗</a>` : ''}</small></div>`;
  return collapsible ? `<details class="abstract"><summary>Abstract <span>전문 번역</span></summary>${body}</details>` : `<section class="content-section"><h2>Abstract · 전문 번역</h2>${body}</section>`;
}

function metadata(paper, full = true, compact = false) {
  const m = paper.metadata;
  const authors = String(m.authors || '').split(',').map(author => author.trim());
  const shortened = compact && paper.kind === 'discovery' && authors.length > 3;
  return `<p class="paper-meta"><b>${escape(m.journal)}</b><span>${escape(m.date)}</span><span${shortened ? ` title="${escape(m.authors)}"` : ''}>${escape(shortened ? authors.slice(0,3).join(', ') + ' 외' : m.authors)}</span><span>${escape(m.peerReview || 'Peer-reviewed')}</span></p>${full ? `<p class="doi">DOI <a href="https://doi.org/${escape(m.doi)}" target="_blank" rel="noopener">${escape(m.doi)}</a></p>` : ''}`;
}

function badges(paper) {
  const originNames = {fulltext:'본문 기반 초안',prior_fulltext_review:'기존 본문 검토 기반 초안',abstract:'초록 기반 초안'};
  const label = paper.cardOrigin ? originNames[paper.cardOrigin.basis] || '카드 초안' : paper.metadata.reviewStatus || '수동 검토';
  return `<div class="tags">${(paper.metadata.tags || []).map(tag => `<span>${escape(tag)}</span>`).join('')}<span class="review-badge${paper.cardOrigin?.basis === 'abstract' ? ' abstract-basis' : ''}"${paper.cardOrigin?.evidenceNote ? ` title="${escape(paper.cardOrigin.evidenceNote)}"` : ''}>${escape(label)}</span>${paper.briefOrigin?.review ? `<span class="review-badge ${paper.briefOrigin.review.status !== 'reviewed' ? 'abstract-basis' : ''}">상세 · ${escape(paper.metadata.reviewStatus)}</span>` : ''}</div>`;
}

function renderReviewScope(paper) {
  const review = paper.briefOrigin?.review;
  if (!review) return '';
  const scopes = {abstract:'초록',body:'본문',figures:'그림',supplement:'보충자료'};
  const states = {reviewed:'검토함',partial:'일부 검토',unverified:'미검증',unavailable:'미확인'};
  return `<aside class="brief-review" aria-label="상세 브리핑 검증 상태"><p><strong>${escape(paper.metadata.reviewStatus)}</strong>${paper.generationOrigin ? '' : ` · ${escape(review.note)}`}</p><details><summary>자료 확보·검토 범위</summary>${paper.generationOrigin ? `<p>${escape(review.note)}</p>` : ''}<div class="table-scroll"><table><thead><tr><th scope="col">자료</th><th scope="col">확보</th><th scope="col">내용 검토</th></tr></thead><tbody>${Object.entries(scopes).map(([key,label]) => `<tr><th scope="row">${label}</th><td>${review.acquired[key] == null ? '미확인' : review.acquired[key] ? '확보함' : '미확보'}</td><td>${states[review.checked[key]] || '미검증'}</td></tr>`).join('')}</tbody></table></div>${review.holds.length ? `<ul>${review.holds.map(hold => `<li><strong>${hold.reason === 'safety' ? '안전상 범위 제한' : '자료 미확인'} · ${escape(hold.scope)}</strong>: ${escape(hold.note)}</li>`).join('')}</ul>` : ''}<small>자료 확보는 다운로드·접근 상태이며, 내용 검토는 이번에 실제 대조한 범위입니다.</small></details></aside>`;
}

function stateButtons(paper) {
  return `<button type="button" class="state-button${paper.state.read ? ' active' : ''}" data-state="read" data-id="${paper.id}" aria-pressed="${paper.state.read}">${icon('check')}<span>${paper.state.read ? '읽음' : '읽음 표시'}</span></button><button type="button" class="state-button${paper.state.saved ? ' active' : ''}" data-state="saved" data-id="${paper.id}" aria-pressed="${paper.state.saved}">${icon('bookmark')}<span>${paper.state.saved ? '저장됨' : '저장'}</span></button>`;
}

function resourceLinks(paper) {
  const m = paper.metadata;
  return `${safeUrl(m.sourceUrl) ? `<a href="${escape(safeUrl(m.sourceUrl))}" target="_blank" rel="noopener">원문 ↗</a>` : ''}${safeUrl(m.pdfUrl) ? `<a href="${escape(safeUrl(m.pdfUrl))}">PDF ↗</a>` : ''}${safeUrl(m.siUrl) ? `<a href="${escape(safeUrl(m.siUrl))}"${/^https?:/.test(m.siUrl) ? ' target="_blank" rel="noopener"' : ''}>SI ↗</a>` : paper.kind === 'discovery' ? '' : '<span class="unavailable" title="제공 자료에 Supplementary Information이 없습니다.">SI 미확보</span>'}`;
}

function renderCardScore(paper) {
  if (!paper.scoreSnapshot) return '';
  const {score = {},metrics = {}} = paper.scoreSnapshot;
  const complete = score.total != null;
  const known = complete || score.contentKnownMax === 60 && score.subtotal != null && score.knownMax > 0;
  const journal = metrics.journal || {};
  const citations = metrics.citations || {};
  const values = [];
  if (journal.jif != null) values.push(`${journal.year ? `${journal.year} ` : ''}IF ${evaluationNumber(journal.jif)}`);
  if (citations.count != null) values.push(`인용 ${evaluationNumber(citations.count)}회`);
  return `<div class="card-score">${known ? `<span>참고 점수 <strong>${evaluationNumber(complete ? score.total : score.subtotal)}<small> / ${evaluationNumber(complete ? 100 : score.knownMax)}</small></strong>${complete ? '' : ' · 잠정'}</span>` : ''}${values.length ? `<span>${values.map(escape).join(' · ')}</span>` : ''}</div>`;
}

function renderResearchFlow(paper) {
  if (!paper.card.flow?.length) return '';
  return `<figure class="research-flow"><figcaption>연구 흐름 요약</figcaption><ol>${paper.card.flow.map(step => `<li>${escape(step)}</li>`).join('')}</ol></figure>`;
}

function renderCard(paper) {
  const {card, metadata:m, id} = paper;
  const representative = card.image || card.representative;
  return `<article class="paper-card" data-paper="${id}"><header class="card-heading"><div class="card-status"><span>${paper.state.read ? '<span class="read-dot"></span> 읽은 논문' : '<span class="new-dot"></span> 읽지 않음'}</span><div data-state-buttons="${id}">${stateButtons(paper)}</div></div><a class="title-link" href="#/paper/${id}/summary"><h2>${escape(m.title)}</h2></a><p class="translation">${escape(m.translation)}</p>${metadata(paper,true,true)}${badges(paper)}${renderCardScore(paper)}</header><div class="card-body">${renderAbstract(paper, true)}<section class="card-purpose"><h3>연구 목적</h3><p>${rich(card.purpose)}</p></section><div class="card-evidence${representative ? '' : ' no-image'}"><section><h3>방법 <span class="arrow">→</span> 결과</h3><dl class="card-pairs">${(card.pairs || []).map(pair => `<div><dt>${rich(pair.label)}</dt><dd>${pair.text ? rich(pair.text) : `${rich(pair.method)} <span class="arrow">→</span> ${rich(pair.result)}`}${pair.source ? `<small>${source(pair.source)}</small>` : ''}</dd></div>`).join('')}</dl></section>${representative ? `<figure class="representative">${zoomImage(representative.src || representative.image, representative.alt || representative.title || '대표 구조식', 'ligand-image')}<figcaption>${representative.title ? `<strong>${rich(representative.title)}</strong>` : ''}${rich(representative.caption || representative.description || '')}<small>${source(representative.source)}</small></figcaption></figure>` : ''}</div>${renderResearchFlow(paper)}<div class="card-interpretation"><div><h3>동향상 의미</h3><p>${rich(card.significance || card.meaning)}</p></div><div><h3>연구 적용</h3><p>${rich(card.application)}</p></div></div><div class="callout">${rich(card.limits || card.caution)}</div><div class="card-actions"><a class="button primary" href="#/paper/${id}/summary">상세 브리핑 ${icon('arrow')}</a><div class="resource-links">${resourceLinks(paper)}</div></div>${card.selectionReason ? `<p class="selection-reason">선정 이유 · ${rich(card.selectionReason)}</p>` : ''}</div></article>`;
}

function renderSidebar() {
  const discovering = isCardFeed() || location.hash.startsWith('#/card/');
  const collecting = location.hash === '#/collection';
  const evaluating = location.hash === '#/evaluation';
  const comparing = location.hash === '#/generation-pilot';
  const inRound = location.hash === '#/rounds';
  const inLibrary = !discovering && !collecting && !evaluating && !comparing && !inRound;
  const roundsLink = $('#rounds-link');
  roundsLink.innerHTML = `${icon('check')}<span>이번 회차</span>`;
  roundsLink.classList.toggle('selected',inRound);
  if (inRound) roundsLink.setAttribute('aria-current','page');
  else roundsLink.removeAttribute('aria-current');
  const discoverLink = $('#discover-link');
  discoverLink.innerHTML = `${icon('search')}<span>논문 카드</span><b>${papers.filter(p => p.kind === 'discovery').length}</b>`;
  discoverLink.classList.toggle('selected',discovering);
  if (discovering) discoverLink.setAttribute('aria-current','page');
  else discoverLink.removeAttribute('aria-current');
  const collectionLink = $('#collection-link');
  collectionLink.innerHTML = `${icon('library')}<span>수집 관리</span>`;
  collectionLink.classList.toggle('selected',collecting);
  if (collecting) collectionLink.setAttribute('aria-current','page');
  else collectionLink.removeAttribute('aria-current');
  const evaluationLink = $('#evaluation-link');
  evaluationLink.innerHTML = `${icon('check')}<span>시범 평가</span>`;
  evaluationLink.classList.toggle('selected',evaluating);
  if (evaluating) evaluationLink.setAttribute('aria-current','page');
  else evaluationLink.removeAttribute('aria-current');
  const generationLink = $('#generation-pilot-link');
  generationLink.innerHTML = `${icon('check')}<span>생성 비교</span>`;
  generationLink.classList.toggle('selected',comparing);
  if (comparing) generationLink.setAttribute('aria-current','page');
  else generationLink.removeAttribute('aria-current');
  const collections = [{id:'all',label:'전체 논문',icon:'library',count:papers.length},{id:'saved',label:'저장한 논문',icon:'bookmark',count:papers.filter(p => p.state.saved).length},{id:'unread',label:'읽지 않은 논문',icon:'unread',count:papers.filter(p => !p.state.read).length}];
  $('#collection-nav').innerHTML = collections.map(c => `<button class="nav-item${inLibrary && filters.collection === c.id && !filters.area ? ' selected' : ''}" data-collection="${c.id}"${inLibrary && filters.collection === c.id && !filters.area ? ' aria-current="page"' : ''}>${icon(c.icon)}<span>${c.label}</span><b>${c.count}</b></button>`).join('');
  const areas = [...new Set([...areaNames, ...papers.flatMap(p => p.metadata.categories || [])])];
  $('#area-nav').innerHTML = areas.map(area => `<div class="area-row"><button class="area-item${(discovering ? feed.area : inLibrary ? filters.area : '') === area ? ' selected' : ''}" data-area="${escape(area)}"${areaDescriptions[area] ? ` title="${escape(areaDescriptions[area].scope)}"` : ''}><span class="area-dot"></span>${escape(area)}</button>${areaDescriptions[area] ? `<button type="button" class="area-info" data-area-help="${escape(area)}" aria-label="${escape(area)} 분야 설명" aria-haspopup="dialog"><span aria-hidden="true">ⓘ</span></button>` : ''}</div>`).join('');
}

function openAreaGuide(area) {
  const names = areaDescriptions[area] ? [area] : areaNames;
  $('#area-guide-title').textContent = names.length === 1 ? area : '연구 분야 안내';
  $('#area-guide-content').innerHTML = `<p class="area-guide-note">분야는 논문을 읽는 관점입니다. 한 논문에 여러 분야가 함께 적용될 수 있습니다.</p>${names.map(name => `<section class="area-guide-section">${names.length > 1 ? `<h3>${escape(name)}</h3>` : ''}<p>${escape(areaDescriptions[name].scope)}</p><div class="area-checkpoints"><strong>확인할 점</strong><p>${escape(areaDescriptions[name].checkpoints)}</p></div><button type="button" class="button" data-area="${escape(name)}">이 분야 논문 보기 →</button></section>`).join('')}`;
  $('#area-guide').showModal();
}

const collectionStatusNames = {running:'수집 중',completed:'수집 완료',partial:'일부 분야 실패',failed:'수집 실패',interrupted:'수집 중단',pending:'대기'};
const countText = value => Number(value || 0).toLocaleString('ko-KR');
const collectionTime = value => value ? new Date(value).toLocaleString('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '';

async function discoveryRequest(url, options) {
  const response = await fetch(url,options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || `요청에 실패했습니다 (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function renderCollectionState() {
  if (!$('#collection-progress')) return;
  const run = collectionData?.run;
  const running = run?.status === 'running';
  const selectedRound = run?.mode === 'selected_round';
  $('#collection-submit').disabled = collectionStarting || discoveryLoading || !collectionData || Boolean(collectionError) || running;
  $('#collection-submit').textContent = collectionStarting ? '수집 요청 중…' : running ? '수집 중…' : '6개 분야 수집';
  for (const id of ['#collection-from','#collection-to']) $(id).disabled = collectionStarting || running;
  $('#collection-errors').innerHTML = [collectionStartError,collectionError].filter(Boolean).map(message => `<p>${escape(message)}</p>`).join('') + (collectionError ? '<button type="button" class="button" data-discovery-retry>다시 불러오기</button>' : '');
  $('#collection-errors').hidden = !collectionStartError && !collectionError;
  const configuredAreas = collectionData?.areas || [];
  $('#collection-queries').innerHTML = configuredAreas.length ? configuredAreas.map(area => `<section class="collection-query"><h3>${escape(area.name)}</h3><p>${escape(areaDescriptions[area.name]?.scope || '')}</p><code>${escape(`(${area.query}) AND FIRST_PDATE:[${discovery.from} TO ${discovery.to}]`)}</code></section>`).join('') : `<p>${collectionError ? '검색식을 불러오지 못했습니다.' : '검색식을 불러오는 중…'}</p>`;
  const summary = !collectionData ? (collectionError ? '수집 정보를 확인할 수 없습니다.' : '수집 정보를 불러오는 중…') : !run ? '아직 수집 기록이 없습니다.' : `${selectedRound ? '선정 논문 등록 · ' : running ? '' : '최근 수집 기록 · '}${collectionStatusNames[run.status] || run.status} · ${run.from} ~ ${run.to}`;
  $('#collection-progress').innerHTML = `<p class="collection-run-summary" role="status">${escape(summary)}${collectionError && run ? ' · 최신 상태 확인 필요' : ''}</p><div class="collection-totals"><span>보관 후보 <strong>${collectionData ? countText(collectionData.counts?.total) : '—'}편</strong></span>${run ? `<span>${running ? '이번 수집 신규' : '당시 신규'} <strong>${countText(run.added)}편</strong></span><span>${running ? '기존 갱신' : '당시 갱신'} <strong>${countText(run.updated)}편</strong></span>` : ''}</div>${run ? `<p class="collection-timing">시작 ${escape(collectionTime(run.startedAt))}${run.finishedAt ? ` · 종료 ${escape(collectionTime(run.finishedAt))}` : ''}</p>` : ''}<div class="collection-area-progress">${(configuredAreas.length ? configuredAreas : areaNames.map(name => ({name}))).map(area => {
    const progress = run?.areas?.find(item => item.name === area.name);
    return `<article><div><h3>${escape(area.name)}</h3><span>${escape(progress ? collectionStatusNames[progress.status] || progress.status : run?.retryOf ? '이전 수집 완료' : '수집 전')}</span></div>${selectedRound ? `<p>선정 논문 ${countText(progress?.processed)}편 등록</p>` : !progress && run?.retryOf ? '<p>이번 재시도에서 제외</p>' : `<p>${run && !running ? '당시 ' : ''}검색 결과 ${progress?.pages ? countText(progress.matched) : '—'} · 처리 ${countText(progress?.processed)} · ${countText(progress?.pages)}페이지</p>`}<small>보관 후보 ${countText(collectionData?.counts?.areas?.[area.name])}편</small>${progress?.error ? `<p class="collection-area-error">${escape(progress.error)}</p>` : ''}</article>`;
  }).join('')}</div><p class="collection-count-note">보관 후보는 중복을 합친 전체 편수입니다. 여러 분야에 일치하는 논문은 분야별 편수에 각각 포함됩니다.</p>`;
  if (run?.retryOf) $('#collection-progress').insertAdjacentHTML('afterbegin', `<p class="collection-date-note">같은 발행일 범위의 실패한 ${run.areas.length}개 분야 재시도</p>`);
  if (run && !running && run.areas.some(area => ['failed','pending'].includes(area.status))) {
    $('#collection-progress').insertAdjacentHTML('beforeend', `<button type="button" class="button" data-collection-retry${collectionStarting || discoveryLoading || collectionError ? ' disabled' : ''}>실패한 분야 재시도</button>`);
  }
}

const candidateKinds = {original:'원저',review:'Review',preprint:'Preprint · 보류',uncertain:'확인 필요',other:'기타'};
const sourceStatusNames = {not_retrieved:'원문 미확보',fulltext:'본문 확보',abstract_only:'초록만 확보',failed:'확보 재시도 필요'};
const candidateKind = candidate => candidate.classification?.kind || 'uncertain';
const candidateEligible = candidate => ['original','review'].includes(candidateKind(candidate));
const sourceStatus = candidate => candidate.fullTextStatus || candidate.sourceDocument?.status || 'not_retrieved';
const acquisitionBusy = () => acquisitionStarting || acquisitionData?.run?.status === 'running';
const preparationBusy = () => preparationStarting || preparationData?.run?.status === 'running';
const preparationStatusNames = {not_started:'자료 준비 전',preparing:'자료 준비 중',ready:'생성 대기',partial:'일부 미확보 · 자료 확인 필요',failed:'자료 준비 실패'};

function hasPreparedBody(prep) {
  return (prep?.coverage || []).some(item => item.kind === 'body' && Number(item.usable) > 0);
}

function preparationLabel(prep, generated = false) {
  if (prep?.status === 'ready') return generated ? '자료 준비 완료 · 브리핑 초안 있음' : '자료 준비 완료 · 생성 대기';
  if (['partial','failed'].includes(prep?.status)) return `${hasPreparedBody(prep) ? '본문 확보' : '본문 미확보'} · ${prep.status === 'partial' ? '일부 자료 확인 필요' : '자료 준비 실패'}`;
  return preparationStatusNames[prep?.status || 'not_started'] || '자료 확인 필요';
}

function preparationReason(prep) {
  const reason = String(prep?.reason || prep?.issues?.[0] || '').trim();
  return reason.length > 170 ? reason.slice(0,167) + '…' : reason;
}

function renderCandidatePreparation(candidate) {
  if (!candidateEligible(candidate)) return '';
  return `<div class="candidate-preparation" data-preparation-candidate="${escape(candidate.id)}">${renderCandidatePreparationContent(candidate)}</div>`;
}

function renderCandidatePreparationContent(candidate) {
  const prep = candidate.preparation;
  const status = prep?.status || 'not_started';
  const busy = preparationBusy() || preparationLoading;
  const starting = preparationStartingId === candidate.id;
  const run = preparationData?.run;
  const active = run?.status === 'running' && run.candidateIds?.includes(candidate.id);
  const localError = preparationError && (preparationActionId === candidate.id || active || status === 'preparing') ? preparationError : '';
  const generated = candidate.generatedCard;
  const label = starting ? '준비 요청 중…' : active && status !== 'ready' ? '자료 준비 중' : preparationLabel(prep,generated);
  const detail = starting ? '자료 준비 요청을 보내고 있습니다.' : localError ? '' : status === 'preparing' || active ? prep?.stage || run?.stage || '원자료 확인 중' : ['partial','failed'].includes(status) ? preparationReason(prep) : busy && status !== 'ready' ? (preparationLoading ? '진행 상태 확인 중…' : '다른 논문의 자료를 준비하고 있습니다.') : '';
  return `<span class="preparation-label ${status === 'ready' && !starting ? 'available' : ''}" role="status">브리핑 자료 · ${escape(label)}</span><div>${generated ? `<a class="button primary" href="#/card/${escape(generated.paperId)}">카드 보기</a>` : ''}${prep ? `<button class="button" type="button" data-preparation-open="${escape(candidate.id)}">준비 자료 보기</button>` : ''}${!['ready','preparing'].includes(status) && !active ? `<button class="button" type="button" data-preparation-start="${escape(candidate.id)}"${busy ? ' disabled' : ''}>${starting ? '준비 요청 중…' : ['partial','failed'].includes(status) ? '자료 준비 다시 시도' : '브리핑 자료 준비'}</button>` : ''}</div>${detail ? `<p class="preparation-card-detail">${escape(detail)}</p>` : ''}${localError ? `<div class="preparation-card-error" role="alert"><p>${escape(localError)}</p><button type="button" class="button" data-preparation-retry>상태 다시 확인</button></div>` : ''}`;
}

function candidateMatches() {
  const term = discovery.search.trim().toLocaleLowerCase();
  const ordered = candidates.filter(candidate => candidateKind(candidate) === discovery.kind && (!discovery.area || (candidate.categories || []).includes(discovery.area)) && (!term || [candidate.title,candidate.authors,candidate.journal,candidate.doi,candidate.pmid,candidate.abstract].join(' ').toLocaleLowerCase().includes(term))).sort((a,b) => String(b.date || '').localeCompare(String(a.date || '')) || String(a.id).localeCompare(String(b.id)));
  if (discovery.sort === 'newest' || discovery.area) return ordered;
  const buckets = areaNames.map(area => ordered.filter(candidate => (candidate.categories || []).includes(area)));
  const positions = buckets.map(() => 0);
  const seen = new Set();
  const balanced = [];
  let added;
  do {
    added = false;
    buckets.forEach((bucket,index) => {
      while (positions[index] < bucket.length && seen.has(bucket[positions[index]].id)) positions[index]++;
      if (positions[index] < bucket.length) {
        const candidate = bucket[positions[index]++];
        seen.add(candidate.id);
        balanced.push(candidate);
        added = true;
      }
    });
  } while (added);
  return balanced.concat(ordered.filter(candidate => !seen.has(candidate.id)));
}

function renderCandidate(candidate) {
  const externalLink = (url,label) => /^https?:\/\//i.test(url || '') ? `<a href="${escape(url)}" target="_blank" rel="noopener">${escape(label)} ↗</a>` : '';
  const kind = candidateKind(candidate);
  const kindLabel = kind === 'original' && candidate.classification?.basis === 'abstract' ? '원저 · 잠정' : candidateKinds[kind] || candidateKinds.uncertain;
  const status = sourceStatus(candidate);
  const retrieved = ['fulltext','abstract_only'].includes(status);
  const textStatusLabel = status === 'abstract_only' && !candidate.abstract ? '원문 미확보' : sourceStatusNames[status] || sourceStatusNames.not_retrieved;
  const publisherUrl = candidate.doiUrl || (candidate.doi ? `https://doi.org/${candidate.doi}` : candidate.sourceUrl);
  const authors = Array.isArray(candidate.authors) ? candidate.authors.join(', ') : candidate.authors;
  const dateSource = ['firstPublicationDate','Europe PMC firstPublicationDate'].includes(candidate.dateSource) ? 'Europe PMC 최초 발행일' : candidate.dateSource;
  return `<article class="candidate-card" data-candidate-id="${escape(candidate.id)}"><div class="candidate-status"><span title="${escape(candidate.classification?.reason || '')}">${escape(kindLabel)}</span><span class="candidate-text-status ${status === 'fulltext' ? 'available' : ''}">${escape(textStatusLabel)}</span>${candidate.inLibrary ? '<span>브리핑 등록됨</span>' : ''}</div><h3>${externalLink(candidate.sourceUrl,candidate.title || '제목 없음') || escape(candidate.title || '제목 없음')}</h3><p class="candidate-meta">${escape(candidate.journal || '저널 정보 없음')} · ${escape(candidate.date || '발행일 정보 없음')}</p>${authors ? `<p class="candidate-authors">${escape(authors)}</p>` : ''}<p class="candidate-categories">${escape((candidate.categories || []).join(' · ') || '분야 정보 없음')}</p>${candidate.abstract ? `<details class="candidate-abstract"><summary>Abstract · 원문</summary><p>${escape(candidate.abstract)}</p></details>` : '<p class="candidate-missing">Abstract 미제공</p>'}<div class="candidate-source"><span>메타데이터 · Europe PMC${candidate.source ? ` (${escape(candidate.source)})` : ''}${candidate.pmid ? ` · PMID ${escape(candidate.pmid)}` : ''}${candidate.pmcid ? ` · PMCID ${escape(candidate.pmcid)}` : ''}</span>${dateSource ? `<span>날짜 기준 · ${escape(dateSource)}</span>` : ''}</div><div class="candidate-actions">${retrieved ? `<button type="button" class="button${status === 'fulltext' ? ' primary' : ''}" data-source-open="${escape(candidate.id)}">${status === 'fulltext' ? '본문 읽기' : candidate.abstract ? '확보한 초록 보기' : '확보 상태 보기'}</button>` : ''}${candidateEligible(candidate) && status !== 'fulltext' ? `<button type="button" class="button" data-source-fetch="${escape(candidate.id)}"${acquisitionBusy() ? ' disabled' : ''}>${status === 'not_retrieved' ? '원문 가져오기' : '원문 다시 시도'}</button>` : ''}<div class="candidate-links">${externalLink(publisherUrl,['abstract_only','failed'].includes(status) ? '학교 원문 열기' : '출판사 원문')}${externalLink(candidate.sourceUrl,'출처')}</div></div>${renderCandidatePreparation(candidate)}</article>`;
}

function renderCandidateResults() {
  if (!$('#candidate-results')) return;
  $('#candidate-errors').innerHTML = candidateError ? `<p>${escape(candidateError)}</p><button type="button" class="button" data-discovery-retry>후보 다시 불러오기</button>` : '';
  $('#candidate-errors').hidden = !candidateError;
  const results = candidateMatches();
  const pages = Math.max(1,Math.ceil(results.length / 24));
  discovery.page = Math.max(1,Math.min(discovery.page,pages));
  $('#candidate-count').textContent = candidatesLoaded ? `${countText(results.length)}편` : candidateError ? '확인 필요' : '불러오는 중…';
  const start = (discovery.page-1)*24;
  const openAbstracts = new Set($$('.candidate-abstract[open]').map(item => item.closest('[data-candidate-id]').dataset.candidateId));
  $('#candidate-results').innerHTML = !candidatesLoaded ? (candidateError ? '' : '<div class="loading">후보 목록을 불러오는 중…</div>') : results.length ? results.slice(start,start+24).map(renderCandidate).join('') : `<div class="empty-state"><h3>${candidates.length ? '조건에 맞는 후보가 없습니다' : '수집한 후보가 없습니다'}</h3><p>${candidates.length ? '검색어나 분야를 변경해 주세요.' : '발행일 범위를 선택하고 수집을 실행해 주세요.'}</p></div>`;
  $$('[data-candidate-id]').forEach(item => {if (openAbstracts.has(item.dataset.candidateId) && $('.candidate-abstract',item)) $('.candidate-abstract',item).open = true;});
  $('#candidate-pagination').innerHTML = results.length ? `<button type="button" class="button" data-candidate-page="${discovery.page-1}"${discovery.page === 1 ? ' disabled' : ''}>← 이전</button><span>${discovery.page} / ${pages}페이지 · ${start+1}–${Math.min(start+24,results.length)}편</span><button type="button" class="button" data-candidate-page="${discovery.page+1}"${discovery.page === pages ? ' disabled' : ''}>다음 →</button>` : '';
  $('#candidate-kinds').innerHTML = Object.entries(candidateKinds).map(([kind,label]) => `<button type="button" data-candidate-kind="${kind}" aria-pressed="${discovery.kind === kind}"${discovery.kind === kind ? ' class="selected"' : ''}>${label}<span>${countText(candidates.filter(candidate => candidateKind(candidate) === kind).length)}</span></button>`).join('');
  renderAcquisitionState();
  renderPreparationState();
}

function acquisitionPageCandidates() {
  return candidateMatches().slice((discovery.page-1)*24,discovery.page*24).filter(candidate => candidateEligible(candidate) && sourceStatus(candidate) !== 'fulltext');
}

function renderAcquisitionState() {
  if (!$('#acquisition-state')) return;
  const run = acquisitionData?.run;
  const busy = acquisitionBusy();
  const eligible = acquisitionPageCandidates();
  const batch = $('#acquisition-submit');
  batch.hidden = !['original','review'].includes(discovery.kind);
  batch.disabled = busy || acquisitionLoading || !eligible.length;
  batch.textContent = acquisitionStarting ? '요청 중…' : `현재 ${eligible.length}편 원문 가져오기`;
  $$('[data-source-fetch]').forEach(button => button.disabled = busy || acquisitionLoading);
  $('#acquisition-state').textContent = acquisitionStarting ? '원문 확보를 시작합니다…' : run ? `${run.status === 'running' ? '원문 확보 중' : ({completed:'원문 확인 완료',interrupted:'원문 확보 중단',failed:'원문 확보 실패'}[run.status] || '원문 확보')} · ${countText(run.processed)} / ${countText(run.total)}편 · 본문 ${countText(run.fulltext)} · 본문 미확보 ${countText(run.abstract)}${run.failed ? ` · 재시도 필요 ${countText(run.failed)}` : ''}` : '';
  $('#acquisition-errors').hidden = !acquisitionError;
  $('#acquisition-errors').innerHTML = acquisitionError ? `<p>${escape(acquisitionError)}</p><button type="button" class="button" data-acquisition-retry>상태 다시 확인</button>` : '';
  $('#acquisition-note').textContent = discovery.kind === 'preprint' ? 'Preprint는 원문 자동 확보를 보류합니다.' : discovery.kind === 'uncertain' ? '원저 여부를 확인할 때까지 자동 확보 대상에서 제외합니다.' : discovery.kind === 'other' ? '원저와 Review를 원문 자동 확보 대상으로 합니다.' : '공개 원문과 현재 네트워크에서 접근 가능한 본문을 확인합니다. 접근이 안 되면 초록을 보관합니다.';
}

async function refreshAcquisition() {
  if (acquisitionLoading) return;
  acquisitionLoading = true;
  clearTimeout(acquisitionTimer);
  renderAcquisitionState();
  const before = JSON.stringify(acquisitionData?.run);
  try {
    acquisitionData = await discoveryRequest('/api/acquisition');
    acquisitionError = '';
    if (acquisitionData.run && before !== JSON.stringify(acquisitionData.run)) {
      try {
        const data = await discoveryRequest('/api/candidates');
        candidates = data.candidates;
        candidatesLoaded = true;
        candidateError = '';
        renderCandidateResults();
      } catch (error) {
        candidateError = `원문 확보 결과를 불러오지 못했습니다. ${error.message}`;
        renderCandidateResults();
      }
    }
  } catch (error) {
    acquisitionError = `원문 확보 상태를 불러오지 못했습니다. ${error.message}`;
  } finally {
    acquisitionLoading = false;
    renderAcquisitionState();
  }
  if (acquisitionData?.run?.status === 'running' && !acquisitionError) acquisitionTimer = setTimeout(refreshAcquisition,2000);
}

async function startAcquisition(ids) {
  if (acquisitionBusy() || acquisitionLoading || !ids.length) return;
  acquisitionStarting = true;
  acquisitionError = '';
  clearTimeout(acquisitionTimer);
  renderAcquisitionState();
  try {
    await discoveryRequest('/api/acquisition',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidateIds:ids})});
    acquisitionStarting = false;
    await refreshAcquisition();
  } catch (error) {
    acquisitionStarting = false;
    if (error.status === 409) await refreshAcquisition();
    else acquisitionError = `원문 확보를 시작하지 못했습니다. ${error.message}`;
  }
  renderAcquisitionState();
}

function renderPreparationState() {
  const state = $('#preparation-state');
  if (!state) return;
  const run = preparationData?.run;
  const running = run?.status === 'running';
  state.textContent = preparationStarting ? '브리핑 자료 준비를 시작합니다…' : run ? `${running ? '브리핑 자료 준비 중' : ({completed:'브리핑 자료 준비 결과',failed:'브리핑 자료 준비 실패',interrupted:'브리핑 자료 준비 중단'}[run.status] || '브리핑 자료 준비')} · ${countText(run.processed)} / ${countText(run.total)}편 · 생성 대기 ${countText(run.ready)} · 일부 미확보 ${countText(run.partial)}${run.failed ? ` · 실패 ${countText(run.failed)}` : ''}${running && run.stage ? ` · ${run.stage}` : ''}` : '';
  state.hidden = !state.textContent;
  $$('[data-preparation-start]').forEach(button => button.disabled = preparationBusy() || preparationLoading);
  $('#preparation-errors').hidden = !preparationError;
  $('#preparation-errors').innerHTML = preparationError ? `<p>${escape(preparationError)}</p><button type="button" class="button" data-preparation-retry>상태 다시 확인</button>` : '';
  $$('[data-preparation-candidate]').forEach(element => {
    const candidate = candidates.find(item => item.id === element.dataset.preparationCandidate);
    if (!candidate) return;
    const content = renderCandidatePreparationContent(candidate);
    if (element.innerHTML !== content) element.innerHTML = content;
  });
}

async function refreshPreparation() {
  if (preparationLoading) return;
  preparationLoading = true;
  clearTimeout(preparationTimer);
  renderPreparationState();
  const before = JSON.stringify(preparationData?.run);
  try {
    const next = await discoveryRequest('/api/preparation');
    const changed = next.run && (before !== JSON.stringify(next.run) || preparationError);
    if (changed) {
      const data = await discoveryRequest('/api/candidates');
      candidates = data.candidates;
      candidatesLoaded = true;
      candidateError = '';
    }
    // Commit the run only after its candidate states were fetched successfully.
    preparationData = next;
    preparationError = '';
    if (changed) {
      renderCandidateResults();
      if (preparationOpenId && $('#preparation-reader').open) await openPreparation(preparationOpenId,true);
    }
  } catch (error) {
    preparationError = `브리핑 자료 준비 상태를 불러오지 못했습니다. ${error.message}`;
  } finally {
    preparationLoading = false;
    renderPreparationState();
  }
  if (preparationData?.run?.status === 'running' && !preparationError) preparationTimer = setTimeout(refreshPreparation,2000);
}

async function startPreparation(id) {
  if (preparationBusy() || preparationLoading) return;
  preparationStarting = true;
  preparationStartingId = id;
  preparationActionId = id;
  preparationError = '';
  clearTimeout(preparationTimer);
  renderPreparationState();
  try {
    await discoveryRequest('/api/preparation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidateIds:[id]})});
    preparationStarting = false;
    preparationStartingId = null;
    await refreshPreparation();
  } catch (error) {
    preparationStarting = false;
    preparationStartingId = null;
    if (error.status === 409) await refreshPreparation();
    else preparationError = `브리핑 자료 준비를 시작하지 못했습니다. ${error.message}`;
  }
  renderPreparationState();
}

function preparationAsset(asset) {
  const localUrl = safeUrl(asset.localUrl);
  const image = asset.kind === 'figure' && /\.(png|jpe?g|webp|gif)(?:\?|$)/i.test(localUrl);
  const title = asset.label || ({figure:'그림',supplement:'보충자료',paper:'원문'}[asset.kind] || '자료');
  return `<li>${image ? zoomImage(localUrl,title) : ''}<div><strong>${escape(title)}</strong><div class="preparation-asset-links">${localUrl ? `<a href="${escape(localUrl)}" target="_blank" rel="noopener">확보한 파일 열기 ↗</a>` : '<span>파일 미확보</span>'}${asset.sourceUrl ? evaluationLink(asset.sourceUrl,'출처') : ''}</div></div></li>`;
}

async function openPreparation(id, refresh = false) {
  const reader = $('#preparation-reader');
  const requestId = ++preparationRequestId;
  preparationOpenId = id;
  const candidate = candidates.find(item => item.id === id);
  if (!refresh) {
    $('#preparation-reader-title').textContent = candidate?.title || '브리핑 준비 자료';
    $('#preparation-reader-body').innerHTML = '<p class="loading" role="status">준비 자료를 불러오는 중…</p>';
  }
  if (!reader.open) reader.showModal();
  try {
    const {preparation:prep} = await discoveryRequest(`/api/preparations/${encodeURIComponent(id)}`);
    if (requestId !== preparationRequestId || !reader.open) return;
    const listedCandidate = candidates.find(item => item.id === id);
    if (listedCandidate) {
      const previous = JSON.stringify(listedCandidate.preparation);
      listedCandidate.preparation = Object.fromEntries(['status','stage','reason','updatedAt','coverage','generationStatus','reviewStatus','issues'].map(key => [key,prep[key]]));
      if (previous !== JSON.stringify(listedCandidate.preparation)) renderCandidateResults();
    }
    const states = {complete:'확보',partial:'일부 미확보',unavailable:'미확보',none_declared:'원문에 별도 자료 없음'};
    const coverage = prep.coverage || [];
    const assets = prep.assets || [];
    const issues = [...new Set([prep.reason,...(prep.issues || [])].filter(Boolean))];
    const openAssets = $('details[open]', $('#preparation-reader-body')) != null;
    const generated = candidate?.generatedCard;
    const preparationNote = generated ? '아래는 자동 확보 시점의 자료 기록입니다. 이 자료로 작성한 브리핑 초안이 있으며, 실제 검토 범위는 상세 브리핑에서 확인할 수 있습니다.' : '검토 전 · 자동 확보한 자료입니다. 본문·그림·보충자료를 실제로 읽고 검토했다는 의미는 아닙니다.' + (prep.status === 'ready' ? ' 생성 대기 상태이며, 브리핑 자동 작성 기능은 아직 연결되지 않았습니다.' : '');
    $('#preparation-reader-title').textContent = prep.title || candidate?.title || '브리핑 준비 자료';
    $('#preparation-reader-body').innerHTML = `<div class="source-reader-meta"><strong>${escape(preparationLabel(prep,generated))}${prep.status === 'preparing' && prep.stage ? ` · ${escape(prep.stage)}` : ''}</strong><span>${escape(prep.provider || '출처 미확인')}${prep.updatedAt ? ` · ${escape(collectionTime(prep.updatedAt))}` : ''}</span>${prep.license ? `<span>${escape(prep.license)}</span>` : ''}${prep.sourceUrl ? `<div>${evaluationLink(prep.sourceUrl,'확보 출처')}</div>` : ''}</div><p class="source-reader-note">${escape(preparationNote)}</p><section><h3>자료 확보 범위</h3><div class="preparation-coverage">${coverage.length ? coverage.map(item => `<article><div><strong>${escape(item.label || item.kind)}</strong><span>${escape(states[item.state] || '확인 필요')}</span></div><p>확보 ${countText(item.acquired)}${item.expected == null ? ' · 전체 수 미확인' : ` / ${countText(item.expected)}`} · 입력에 포함 ${countText(item.usable)}</p>${item.note ? `<small>${escape(item.note)}</small>` : ''}</article>`).join('') : '<p>확보 범위를 확인하는 중입니다.</p>'}</div></section>${issues.length ? `<section><h3>자료 확인 필요</h3><ul class="preparation-issues">${issues.map(issue => `<li>${escape(issue)}</li>`).join('')}</ul></section>` : ''}${assets.length ? `<details class="preparation-assets"${refresh && openAssets ? ' open' : ''}><summary>확보한 파일 · ${countText(assets.length)}개</summary><ul>${assets.map(preparationAsset).join('')}</ul></details>` : ''}${prep.inputUrl ? `<p class="preparation-input"><a href="${escape(safeUrl(prep.inputUrl))}" target="_blank" rel="noopener">생성 입력 자료 보기 (JSON) ↗</a></p>` : ''}${['partial','failed'].includes(prep.status) ? `<button class="button" type="button" data-preparation-start="${escape(id)}"${preparationBusy() || preparationLoading ? ' disabled' : ''}>자료 준비 다시 시도</button>` : ''}`;
  } catch (error) {
    if (requestId !== preparationRequestId || !reader.open) return;
    $('#preparation-reader-body').innerHTML = `<div class="collection-error" role="alert"><p>${escape(error.message)}</p><button class="button" type="button" data-preparation-open="${escape(id)}">다시 불러오기</button></div>`;
  }
}

async function openSource(id) {
  const reader = $('#source-reader');
  const requestId = ++sourceRequestId;
  const candidate = candidates.find(item => item.id === id);
  $('#source-reader-title').textContent = candidate?.title || '확보한 원문';
  $('#source-reader-body').innerHTML = '<p class="loading" role="status">확보한 내용을 불러오는 중…</p>';
  if (!reader.open) reader.showModal();
  reader.scrollTop = 0;
  try {
    const {source:doc} = await discoveryRequest(`/api/sources/${encodeURIComponent(id)}`);
    if (requestId !== sourceRequestId || !reader.open) return;
    const fulltext = doc.status === 'fulltext';
    const externalLink = (url,label) => /^https?:\/\//i.test(url || '') ? `<a href="${escape(url)}" target="_blank" rel="noopener">${escape(label)} ↗</a>` : '';
    const publisherUrl = candidate?.doiUrl || (candidate?.doi ? `https://doi.org/${candidate.doi}` : doc.sourceUrl);
    const paragraphs = text => String(text || '').split(/\n\s*\n/).filter(Boolean).map(paragraph => `<p>${escape(paragraph)}</p>`).join('');
    $('#source-reader-title').textContent = doc.title || candidate?.title || '확보한 원문';
    $('#source-reader-body').innerHTML = `<div class="source-reader-meta"><strong>${fulltext ? '본문 확보' : doc.abstract ? '초록만 확보' : '원문 미확보'}</strong><span>${escape(doc.provider || '출처 미확인')}${doc.fetchedAt ? ` · ${escape(collectionTime(doc.fetchedAt))}` : ''}</span>${doc.license ? `<span>${escape(doc.license)}</span>` : ''}<div>${externalLink(doc.sourceUrl,'확보 출처')}${externalLink(publisherUrl,fulltext ? '출판사 원문' : '학교 원문 열기')}</div></div>${fulltext ? '<p class="candidate-scope">본문 텍스트입니다. 그림·첨부자료(SI)는 포함되지 않습니다.</p>' : ''}${!fulltext ? `<div class="source-reader-note"><p>${escape(doc.reason || (doc.abstract ? '자동으로 본문을 확보하지 못해 초록을 표시합니다.' : '자동으로 본문을 확보하지 못했고 제공된 초록도 없습니다.'))}</p><p>학교 원문 링크는 출판사 페이지를 엽니다. 브라우저에서 접근되더라도 자동 확보가 가능한 것은 아닙니다.</p></div>` : ''}${doc.abstract ? `<section><h3>Abstract · 원문</h3>${paragraphs(doc.abstract)}</section>` : '<p class="candidate-missing">초록이 제공되지 않았습니다.</p>'}${fulltext ? (doc.sections || []).map(section => `<section>${section.heading ? `<h3>${escape(section.heading)}</h3>` : ''}${paragraphs(section.text)}</section>`).join('') : ''}`;
  } catch (error) {
    if (requestId !== sourceRequestId || !reader.open) return;
    $('#source-reader-body').innerHTML = `<div class="collection-error" role="alert"><p>${escape(error.message)}</p><button type="button" class="button" data-source-open="${escape(id)}">다시 불러오기</button></div>`;
  }
}

async function refreshDiscovery(includeCandidates = true) {
  if (discoveryLoading) return;
  discoveryLoading = true;
  clearTimeout(collectionTimer);
  renderCollectionState();
  const requests = [discoveryRequest('/api/collection')];
  if (includeCandidates) requests.push(discoveryRequest('/api/candidates'));
  const results = await Promise.allSettled(requests);
  if (results[0].status === 'fulfilled') {
    collectionData = results[0].value;
    collectionError = '';
    if (collectionData.run?.status === 'running') {
      discovery.from = collectionData.run.from;
      discovery.to = collectionData.run.to;
      if ($('#collection-from')) {
        $('#collection-from').value = discovery.from;
        $('#collection-to').value = discovery.to;
      }
    }
  } else collectionError = `수집 상태를 불러오지 못했습니다. ${results[0].reason.message}`;
  const finishedRun = collectionData?.run && collectionData.run.status !== 'running' ? collectionData.run.id : null;
  let candidateResult = results[1];
  if (!includeCandidates && finishedRun && candidateRunId !== finishedRun) [candidateResult] = await Promise.allSettled([discoveryRequest('/api/candidates')]);
  if (candidateResult) {
    if (candidateResult.status === 'fulfilled') {
      candidates = candidateResult.value.candidates;
      candidatesLoaded = true;
      candidateError = '';
      candidateRunId = finishedRun;
    } else candidateError = `후보 목록을 불러오지 못했습니다. ${candidateResult.reason.message}`;
    renderCandidateResults();
  }
  discoveryLoading = false;
  renderCollectionState();
  if (collectionData?.run?.status === 'running' && !collectionError) collectionTimer = setTimeout(() => refreshDiscovery(false),2000);
}

async function startCollection(event, retry = false) {
  event.preventDefault();
  if (collectionStarting || collectionData?.run?.status === 'running') return;
  collectionStartError = '';
  if (!retry && (!discovery.from || !discovery.to || discovery.from > discovery.to)) {
    collectionStartError = '발행일 시작과 종료 범위를 확인해 주세요.';
    renderCollectionState();
    return;
  }
  collectionStarting = true;
  clearTimeout(collectionTimer);
  renderCollectionState();
  try {
    const payload = retry ? {runId:collectionData.run.id} : {from:discovery.from,to:discovery.to};
    const {run} = await discoveryRequest(retry ? '/api/collection/retry' : '/api/collection',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    collectionData = {...collectionData,run};
    collectionError = '';
    collectionStarting = false;
    renderCollectionState();
    await refreshDiscovery(false);
  } catch (error) {
    collectionStartError = error.status === 409 ? '수집 상태가 변경되었습니다. 현재 진행 상황을 다시 확인합니다.' : `수집을 시작하지 못했습니다. ${error.message}`;
    collectionStarting = false;
    renderCollectionState();
    if (error.status === 409) await refreshDiscovery(false);
  }
}

function renderCollection() {
  currentId = null;
  document.title = '수집 관리 · Paper Radar';
  main.innerHTML = `${backButton()}<div class="library-intro"><h1>수집 관리</h1></div><section class="collection-panel"><form id="collection-form"><div class="collection-dates"><label for="collection-from">발행일 시작<input type="date" id="collection-from" required value="${escape(discovery.from)}"></label><label for="collection-to">발행일 종료<input type="date" id="collection-to" required value="${escape(discovery.to)}"></label><button type="submit" class="button primary" id="collection-submit">6개 분야 수집</button></div></form><p class="collection-scope">Europe PMC · 최초 발행일 기준 · 6개 분야 동일 기간 검색 · 편수 제한 없음</p><p class="collection-date-note">기본 입력은 최근 30일이며 변경할 수 있습니다. 자동 실행은 설정되어 있지 않습니다.</p><div class="collection-error" id="collection-errors" role="alert" hidden></div><div id="collection-progress"></div><details class="collection-settings"><summary>분야별 검색 범위·검색식</summary><p>선택한 최초 발행일 범위를 포함한 검색식입니다. 읽기 전용이며 날짜 입력에 맞춰 바뀝니다.</p><div id="collection-queries"></div></details></section><section aria-labelledby="candidate-heading"><div class="candidate-heading"><h2 id="candidate-heading" tabindex="-1">수집 후보</h2><strong id="candidate-count"></strong></div><p class="candidate-scope">누적 수집 목록 · 메타데이터와 Abstract 원문. 분야 태그는 검색식 일치이며 내용 검토 결과가 아닙니다.</p><p class="candidate-scope">Open access 표기는 출처 정보입니다. PDF·본문은 아직 확보하지 않았습니다.</p><div class="filter-panel"><label class="search-box">${icon('search')}<input id="candidate-search" type="search" aria-label="수집 후보 검색" placeholder="제목, 저자, DOI, Abstract 검색" value="${escape(discovery.search)}"></label><div class="filter-row"><label class="field-select"><span>분야</span><select id="candidate-area" aria-label="수집 후보 분야"><option value="">모든 분야</option>${areaNames.map(area => `<option value="${escape(area)}"${discovery.area === area ? ' selected' : ''}>${escape(area)}</option>`).join('')}</select></label><label class="candidate-sort-label"><span>정렬</span><select id="candidate-sort"><option value="balanced"${discovery.sort === 'balanced' ? ' selected' : ''}>분야 균형순</option><option value="newest"${discovery.sort === 'newest' ? ' selected' : ''}>최근 발행순</option></select></label></div></div><p class="candidate-order-note">분야 균형순은 각 분야의 최신 논문을 한 편씩 번갈아 보여줍니다. 중복 논문은 한 번만 표시합니다.</p><div class="collection-error" id="candidate-errors" role="alert" hidden></div><div id="candidate-results"></div><nav id="candidate-pagination" class="candidate-pagination" aria-label="수집 후보 페이지"></nav></section>`;
  $('.library-intro').insertAdjacentHTML('beforeend','<a class="button" href="#/discover">논문 카드 보기 →</a>');
  const scopeNotes = $$('.candidate-scope');
  scopeNotes[0].textContent = '원저 중심으로 확인합니다. 논문 유형은 수집한 출처 정보와 제목·초록을 기준으로 구분합니다.';
  scopeNotes[1].remove();
  scopeNotes[0].insertAdjacentHTML('afterend','<div id="candidate-kinds" class="candidate-kinds" role="group" aria-label="논문 유형"></div>');
  $('#candidate-errors').insertAdjacentHTML('beforebegin','<div class="acquisition-toolbar"><button type="button" class="button primary" id="acquisition-submit" data-source-batch>현재 페이지 원문 가져오기</button><p id="acquisition-state" role="status"></p></div><p class="candidate-scope" id="acquisition-note"></p><div class="collection-error" id="acquisition-errors" role="alert" hidden></div>');
  $('#candidate-errors').insertAdjacentHTML('beforebegin','<p class="candidate-scope preparation-scope">각 논문의 브리핑 자료 준비에서 본문·표·그림·보충자료를 함께 확보할 수 있습니다.</p><p id="preparation-state" class="preparation-progress" role="status" hidden></p><div class="collection-error" id="preparation-errors" role="alert" hidden></div>');
  renderSidebar();
  renderCollectionState();
  renderCandidateResults();
  $('#collection-form').addEventListener('submit',startCollection);
  for (const [selector,key] of [['#collection-from','from'],['#collection-to','to']]) $(selector).addEventListener('change',event => {discovery[key] = event.target.value;renderCollectionState();rememberView();});
  for (const [selector,key,eventName] of [['#candidate-search','search','input'],['#candidate-area','area','change'],['#candidate-sort','sort','change']]) $(selector).addEventListener(eventName,event => {discovery[key] = event.target.value;discovery.page = 1;renderCandidateResults();rememberView();});
  refreshDiscovery();
  refreshAcquisition();
  refreshPreparation();
}

const evaluationNumber = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('ko-KR',{maximumFractionDigits:1}) : '—';
const evaluationLink = (url,label) => /^https?:\/\//i.test(safeUrl(url || '')) ? `<a href="${escape(safeUrl(url))}" target="_blank" rel="noopener">${escape(label)} ↗</a>` : escape(label);
const evaluationParagraphs = value => (Array.isArray(value) ? value : [value]).filter(Boolean).map(item => `<p>${escape(item)}</p>`).join('');

function renderEvaluationPaper(paper) {
  const score = paper.score || {};
  const {journal = {},citations = {}} = paper.metrics || {};
  const complete = score.total != null;
  const hasScore = complete || score.contentKnownMax === 60 && score.subtotal != null && score.knownMax > 0;
  const points = complete ? score.total : score.subtotal;
  const maximum = complete ? 100 : score.knownMax;
  const scoreLabel = hasScore ? `참고 점수 ${evaluationNumber(points)} / ${evaluationNumber(maximum)}${complete ? '' : ' · 잠정'}` : '평가 중';
  const scoreBadge = `<div class="evaluation-compact-score" aria-label="${escape(scoreLabel)}">${hasScore ? `<span>참고 점수</span><strong>${evaluationNumber(points)}<small> / ${evaluationNumber(maximum)}</small></strong>${complete ? '' : '<span>잠정</span>'}` : '<span>평가 중</span>'}</div>`;
  const basis = paper.reviewBasis === 'abstract' ? '<span class="evaluation-basis">초록 기준</span>' : '';
  const paperUrl = paper.doi ? `https://doi.org/${paper.doi}` : paper.sourceUrl;
  const date = paper.sourceDate?.date || paper.date;
  const metrics = [`${journal.year ? `${journal.year} ` : ''}IF ${journal.jif == null ? '미확인' : evaluationNumber(journal.jif)}`,`인용 ${citations.count == null ? '미확인' : `${evaluationNumber(citations.count)}회`}`];
  return `<article class="evaluation-card"><header><div class="evaluation-card-topline">${scoreBadge}${basis}</div><h3>${evaluationLink(paperUrl,paper.titleKo || paper.title)}</h3>${paper.titleKo ? `<p class="evaluation-original-title">${escape(paper.title)}</p>` : ''}<p class="candidate-meta">${escape(paper.journal || '저널 미확인')}${date ? ` · ${escape(date)}` : ''}</p></header><div class="evaluation-card-body"><div class="evaluation-summary">${evaluationParagraphs(paper.summary)}</div><div class="evaluation-card-footer"><span>${metrics.map(escape).join(' · ')}</span>${evaluationLink(paperUrl,'원문 보기')}</div></div></article>`;
}

function renderEvaluationResults() {
  if (!$('#evaluation-results') || !evaluationData) return;
  const selected = (evaluationData.papers || []).filter(paper => !evaluation.area || paper.area === evaluation.area);
  const areas = [...new Set([...areaNames,...selected.map(paper => paper.area)])].filter(area => selected.some(paper => paper.area === area));
  $('#evaluation-count').textContent = `${selected.length}편 · ${areas.length}개 분야`;
  $('#evaluation-results').innerHTML = areas.map(area => `<section class="evaluation-area" aria-label="${escape(area)} 시범 평가"><div class="evaluation-area-heading"><h2>${escape(area)}</h2><span>${selected.filter(paper => paper.area === area).length}편</span></div>${selected.filter(paper => paper.area === area).map(renderEvaluationPaper).join('')}</section>`).join('') || '<div class="empty-state"><p>이 분야의 시범 평가가 없습니다.</p></div>';
}

function renderEvaluation() {
  currentId = null;
  document.title = '시범 평가 · Paper Radar';
  main.innerHTML = `${backButton()}<div class="library-intro evaluation-intro"><div><h1>시범 평가</h1></div>${evaluationData ? `<div class="library-stamp"><b>${(evaluationData.papers || []).length}</b><span>평가한 원저</span></div>` : ''}</div><div id="evaluation-content"></div>`;
  renderSidebar();
  const content = $('#evaluation-content');
  if (!evaluationData) {
    content.innerHTML = evaluationError ? `<div class="collection-error" role="alert"><p>${escape(evaluationError)}</p><button type="button" class="button" data-evaluation-retry>다시 불러오기</button></div>` : '<div class="loading" role="status">시범 평가를 불러오는 중…</div>';
    if (!evaluationLoading && !evaluationError) refreshEvaluation();
    return;
  }
  const areas = areaNames.filter(area => evaluationData.papers.some(paper => paper.area === area));
  content.innerHTML = `<div class="evaluation-toolbar"><label>분야 <select id="evaluation-area" aria-label="시범 평가 분야"><option value="">6개 분야 모두</option>${areas.map(area => `<option value="${escape(area)}"${evaluation.area === area ? ' selected' : ''}>${escape(area)}</option>`).join('')}</select></label><span id="evaluation-count"></span></div><p class="evaluation-score-note">점수는 참고용이며, 잠정 점수는 확인된 항목의 배점 기준입니다.</p><div id="evaluation-results"></div>`;
  $('#evaluation-area').addEventListener('change',event => {evaluation.area = event.target.value;renderEvaluationResults();rememberView();});
  renderEvaluationResults();
}

async function refreshEvaluation() {
  if (evaluationLoading) return;
  evaluationLoading = true;
  evaluationError = '';
  if (location.hash === '#/evaluation') renderEvaluation();
  try {
    evaluationData = await discoveryRequest('/api/evaluation');
  } catch (error) {
    evaluationError = `시범 평가를 불러오지 못했습니다. ${error.message}`;
  } finally {
    evaluationLoading = false;
  }
  if (location.hash === '#/evaluation') renderEvaluation();
}

function generationPilotRun() {
  return generationPilotData?.runs.find(run => run.runId === generationPilotView.runId);
}

function renderGenerationCard(card) {
  return `<article class="paper-card generation-card"><div class="card-body">${card.titleKo ? `<h2>${escape(card.titleKo)}</h2>` : ''}<section class="card-purpose"><h3>연구 목적</h3><p>${rich(card.purpose)}</p></section><section><h3>방법 <span class="arrow">→</span> 결과</h3><dl class="card-pairs">${(card.pairs || []).map(pair => `<div><dt>${rich(pair.label)}</dt><dd>${pair.text ? rich(pair.text) : `${rich(pair.method)} <span class="arrow">→</span> ${rich(pair.result)}`}${pair.source ? `<small>${source(pair.source)}</small>` : ''}</dd></div>`).join('')}</dl></section>${card.image ? renderBlock({type:'image',...card.image}) : ''}${renderResearchFlow({card})}<div class="card-interpretation"><div><h3>동향상 의미</h3><p>${rich(card.significance || card.meaning)}</p></div><div><h3>연구 적용</h3><p>${rich(card.application)}</p></div></div><div class="callout">${rich(card.limits || card.caution)}</div></div></article>`;
}

function renderGenerationPilotPanel() {
  const run = generationPilotRun();
  const panel = $('#generation-pilot-panel');
  if (!run || !panel) return;
  const version = generationPilotView.version === 'baseline' ? 'baseline' : 'draft';
  const tab = generationPilotView.tab in generationPilotTabs ? generationPilotView.tab : 'card';
  const content = run[version];
  $$('[data-generation-version]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.generationVersion === version)));
  $$('[data-generation-tab]').forEach(button => {
    const selected = button.dataset.generationTab === tab;
    button.setAttribute('aria-selected',String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  panel.setAttribute('aria-labelledby',`generation-tab-${tab}`);
  $('#generation-version-label').textContent = version === 'baseline' ? '기존 브리핑' : '시범 생성본 · 초안';
  if (version === 'draft' && run.validation.status === 'held') {
    panel.innerHTML = `<div class="collection-error"><p>시범 생성본은 검토 보류 상태입니다.</p><p>${escape(run.validation.summary)}</p></div>`;
    return;
  }
  panel.innerHTML = tab === 'card' ? renderGenerationCard(content.card) : `${tab === 'summary' && content.abstract?.paragraphs?.length ? `<section class="content-section"><h2>초록</h2>${content.abstract.paragraphs.map(text => `<p>${rich(text)}</p>`).join('')}</section>` : ''}${renderSections(content.tabs?.[tab])}`;
}

function renderGenerationPilot() {
  currentId = null;
  document.title = '생성 비교 · Paper Radar';
  main.innerHTML = `${backButton()}<div class="library-intro"><h1>생성 비교</h1></div><p class="generation-note">현재 Codex 세션에서 만든 시범본과 기존 브리핑을 비교합니다.</p><div id="generation-pilot-content"></div>`;
  renderSidebar();
  const container = $('#generation-pilot-content');
  if (!generationPilotData) {
    container.innerHTML = generationPilotError ? `<div class="collection-error" role="alert"><p>${escape(generationPilotError)}</p><button class="button" type="button" data-generation-retry>다시 불러오기</button></div>` : '<div class="loading" role="status">생성 비교를 불러오는 중…</div>';
    if (!generationPilotLoading && !generationPilotError) refreshGenerationPilot();
    return;
  }
  if (!generationPilotData.runs.length) {
    container.innerHTML = '<div class="empty-state"><h2>아직 생성 비교 자료가 없습니다</h2></div>';
    return;
  }
  if (!generationPilotRun()) generationPilotView.runId = generationPilotData.runs[0].runId;
  const run = generationPilotRun();
  const review = run.validation;
  const statusNames = {partial:'일부 검증 · 초안',unverified:'미검증 초안',held:'검토 보류'};
  const checkNames = {pass:'확인',fail:'수정 필요',unverified:'미검증'};
  const scopeNames = {reviewed:'검토함',partial:'일부 검토',unverified:'미검증',unavailable:'미확인'};
  container.innerHTML = `<div class="generation-toolbar"><label for="generation-run">논문 선택<select id="generation-run">${generationPilotData.runs.map(item => `<option value="${escape(item.runId)}"${run.runId === item.runId ? ' selected' : ''}>${escape(item.title)}</option>`).join('')}</select></label><a class="button" href="#/paper/${encodeURIComponent(run.candidateId)}/summary">기존 상세 브리핑 ↗</a></div><h2 class="generation-title">${escape(run.title)}</h2><aside class="generation-validation" aria-label="시범 생성 검증 결과"><p><strong>${statusNames[review.status] || '미검증 초안'}</strong> · ${escape(review.summary)}</p><details><summary>자료 확보·입력·검토 범위</summary><div class="table-scroll"><table><thead><tr><th scope="col">자료</th><th scope="col">확보</th><th scope="col">생성 입력</th><th scope="col">검토</th></tr></thead><tbody>${run.sourceScope.map(item => `<tr><th scope="row">${escape(item.label)}</th><td>${item.acquired ? '확보함' : '미확보'}</td><td>${item.provided ? '제공함' : '미제공'}</td><td>${scopeNames[item.checked] || '미검증'}</td></tr>`).join('')}</tbody></table></div><p class="generation-note">자료 확보·생성 입력·내용 검토는 서로 다른 상태입니다.</p></details><details><summary>검증 항목과 남은 확인 사항</summary><ul class="generation-checks">${review.checks.map(item => `<li><span class="generation-check-status ${item.status === 'fail' ? 'needs-review' : ''}">${checkNames[item.status] || '미검증'}</span><div><strong>${escape(item.label)}</strong><p>${escape(item.note)}</p></div></li>`).join('')}</ul>${review.differences.length ? `<h3>기존본과의 차이</h3><ul>${review.differences.map(text => `<li>${escape(text)}</li>`).join('')}</ul>` : ''}${review.unresolved.length ? `<h3>남은 확인 사항</h3><ul>${review.unresolved.map(text => `<li>${escape(text)}</li>`).join('')}</ul>` : ''}<p class="generation-note">${escape(run.generation.label)}${run.generatedAt ? ` · ${escape(collectionTime(run.generatedAt))}` : ''}</p></details></aside><div class="generation-version" role="group" aria-label="비교할 브리핑"><button type="button" data-generation-version="baseline" aria-pressed="false">기존 브리핑</button><button type="button" data-generation-version="draft" aria-pressed="true">시범 생성본</button></div><div class="tabs generation-tabs" id="generation-pilot-tabs" role="tablist" aria-label="생성 비교 내용">${Object.entries(generationPilotTabs).map(([id,label]) => `<button type="button" role="tab" id="generation-tab-${id}" data-generation-tab="${id}" aria-controls="generation-pilot-panel" aria-selected="false" tabindex="-1">${label}</button>`).join('')}</div><p class="generation-version-label" id="generation-version-label"></p><div id="generation-pilot-panel" role="tabpanel" tabindex="0"></div>`;
  renderGenerationPilotPanel();
  $('#generation-run').addEventListener('change',event => {
    generationPilotView.runId = event.target.value;
    rememberView();
    renderGenerationPilot();
    $('#generation-run').focus({preventScroll:true});
  });
  $('#generation-pilot-tabs').addEventListener('keydown',event => {
    const buttons = $$('[data-generation-tab]');
    const current = buttons.indexOf(event.target);
    if (current < 0) return;
    const next = event.key === 'ArrowRight' ? (current+1)%buttons.length : event.key === 'ArrowLeft' ? (current+buttons.length-1)%buttons.length : event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length-1 : null;
    if (next === null) return;
    event.preventDefault();
    generationPilotView.tab = buttons[next].dataset.generationTab;
    renderGenerationPilotPanel();
    rememberView();
    buttons[next].focus({preventScroll:true});
  });
}

async function refreshGenerationPilot() {
  if (generationPilotLoading) return;
  generationPilotLoading = true;
  generationPilotError = '';
  if (location.hash === '#/generation-pilot') renderGenerationPilot();
  try {
    generationPilotData = await discoveryRequest('/api/generation-pilot');
  } catch (error) {
    generationPilotError = `생성 비교를 불러오지 못했습니다. ${error.message}`;
  } finally {
    generationPilotLoading = false;
  }
  if (location.hash === '#/generation-pilot') renderGenerationPilot();
}

function feedMatches() {
  const term = feed.search.trim().toLocaleLowerCase();
  const ordered = papers.filter(p => p.kind === 'discovery' &&
    (feed.collection !== 'saved' || p.state.saved) &&
    (feed.collection !== 'unread' || !p.state.read) &&
    (feed.collection !== 'read' || p.state.read) &&
    (!feed.area || (p.metadata.categories || []).includes(feed.area)) &&
    (!term || [p.metadata.title,p.metadata.translation,p.metadata.authors,p.metadata.doi,p.card.purpose,...(p.metadata.tags || [])].join(' ').toLocaleLowerCase().includes(term))
  ).sort((a,b) => b.metadata.date.localeCompare(a.metadata.date) || a.id.localeCompare(b.id));
  if (feed.sort === 'newest' || feed.area) return ordered;
  const buckets = areaNames.map(area => ordered.filter(p => (p.metadata.categories || []).includes(area)));
  const result = [];
  const seen = new Set();
  while (buckets.some(bucket => bucket.length)) {
    for (const bucket of buckets) {
      while (bucket.length && seen.has(bucket[0].id)) bucket.shift();
      if (!bucket.length) continue;
      const paper = bucket.shift();
      seen.add(paper.id);
      result.push(paper);
    }
  }
  return result.concat(ordered.filter(p => !seen.has(p.id)));
}

function renderDiscover() {
  currentId = null;
  document.title = '논문 카드 · Paper Radar';
  const count = papers.filter(p => p.kind === 'discovery').length;
  main.innerHTML = `${backButton()}<div class="library-intro feed-intro"><div><h1>논문 카드</h1><p>카드 초안 ${count}편</p></div><a class="button" href="#/collection">수집 관리 →</a></div><section class="filter-panel" aria-label="논문 카드 필터"><label class="search-box">${icon('search')}<input id="search" type="search" placeholder="제목, 키워드, 저자 또는 DOI 검색" aria-label="논문 카드 검색" value="${escape(feed.search)}"><kbd aria-hidden="true">/</kbd></label><div class="filter-row"><label class="field-select"><span>분야</span><select id="feed-area" aria-label="논문 카드 분야"><option value="">모든 분야</option>${areaNames.map(area => `<option value="${escape(area)}"${feed.area === area ? ' selected' : ''}>${escape(area)}</option>`).join('')}</select></label><button type="button" class="text-button area-filter-help" data-area-help="${escape(feed.area)}" aria-haspopup="dialog">ⓘ 분야 설명</button><label class="field-select feed-state-filter"><span>보기</span><select id="feed-state" aria-label="논문 카드 읽기 상태"><option value="all"${feed.collection === 'all' ? ' selected' : ''}>전체</option><option value="unread"${feed.collection === 'unread' ? ' selected' : ''}>읽지 않음</option><option value="read"${feed.collection === 'read' ? ' selected' : ''}>읽음</option><option value="saved"${feed.collection === 'saved' ? ' selected' : ''}>저장한 논문</option></select></label><button type="button" class="text-button" id="filter-reset" data-reset>초기화</button></div></section>${areaDescriptions[feed.area] ? `<section class="area-context" aria-label="선택한 연구 분야 설명"><h2>${escape(feed.area)}</h2><p>${escape(areaDescriptions[feed.area].scope)}</p></section>` : ''}<div class="results-bar"><p>${feed.area ? escape(feed.area) : '모든 분야'} <strong id="result-count"></strong></p><select id="feed-sort" aria-label="논문 카드 정렬"><option value="balanced"${feed.sort === 'balanced' ? ' selected' : ''}>분야 균형순</option><option value="newest"${feed.sort === 'newest' ? ' selected' : ''}>최근 발행순</option></select></div><div id="paper-results" aria-live="polite"></div>`;
  renderSidebar();
  renderResults();
  $('#search').addEventListener('input',event => {feed.search = event.target.value;renderResults();rememberView();});
  $('#feed-area').addEventListener('change',event => navigate('#/discover',{area:event.target.value}));
  for (const [selector,key] of [['#feed-state','collection'],['#feed-sort','sort']]) $(selector).addEventListener('change',event => {feed[key] = event.target.value;renderResults();rememberView();});
}

function matches() {
  const term = filters.search.toLocaleLowerCase();
  return papers.filter(p => {
    const m = p.metadata;
    return (filters.collection !== 'saved' || p.state.saved) &&
      (filters.collection !== 'unread' || !p.state.read) &&
      (!filters.area || (m.categories || []).includes(filters.area)) &&
      (!filters.from || m.date >= filters.from) && (!filters.to || m.date <= filters.to) &&
      (!term || [m.title,m.translation,m.authors,m.doi,...(m.tags || []),...(m.categories || [])].join(' ').toLocaleLowerCase().includes(term));
  }).sort((a,b) => filters.sort === 'oldest' ? a.metadata.date.localeCompare(b.metadata.date) : b.metadata.date.localeCompare(a.metadata.date));
}

function renderResults() {
  if (!$('#paper-results')) return;
  const focusedId = location.hash.match(/^#\/card\/([^/]+)$/)?.[1];
  const active = isCardFeed() ? feed : filters;
  const results = focusedId ? papers.filter(p => p.id === focusedId) : isCardFeed() ? feedMatches() : matches();
  const isInvalid = !focusedId && active.from && active.to && active.from > active.to;
  const openAbstracts = new Set($$('.paper-card .abstract[open]').map(item => item.closest('[data-paper]').dataset.paper));
  if ($('#result-count')) $('#result-count').textContent = `${isInvalid ? 0 : results.length}편`;
  $('#paper-results').innerHTML = isInvalid ? '<div class="empty-state"><h2>날짜 범위를 확인해 주세요</h2><p>시작일은 종료일보다 이전이어야 합니다.</p></div>' : results.length ? results.map(renderCard).join('') : `<div class="empty-state">${icon(active.collection === 'saved' ? 'bookmark' : 'search')}<h2>${active.collection === 'saved' ? '조건에 맞는 저장한 논문이 없습니다' : '조건에 맞는 논문이 없습니다'}</h2><p>검색어나 필터를 변경해 보세요.</p><button data-reset class="button">필터 초기화</button></div>`;
  $$('.paper-card .abstract').forEach(item => {if (openAbstracts.has(item.closest('[data-paper]').dataset.paper)) item.open = true;});
  if ($('#filter-reset')) $('#filter-reset').hidden = !Object.entries(active).some(([key,value]) => key === 'collection' ? isCardFeed() && value !== 'all' : key !== 'sort' && value);
}

function renderLibrary() {
  currentId = null;
  document.title = 'Paper Radar';
  const title = filters.collection === 'saved' ? '저장한 논문' : filters.collection === 'unread' ? '읽지 않은 논문' : '논문 라이브러리';
  main.innerHTML = `${backButton()}<div class="library-intro"><div><h1>${title}</h1></div><div class="library-stamp"><b>${String(papers.length).padStart(2,'0')}</b><span>논문과 브리핑</span></div></div><section class="filter-panel" aria-label="논문 필터"><label class="search-box">${icon('search')}<input id="search" type="search" placeholder="제목, 키워드, 저자 또는 DOI 검색" aria-label="논문 검색" value="${escape(filters.search)}"><kbd aria-hidden="true">/</kbd></label><div class="filter-row"><label class="field-select"><span>분야</span><select id="area-filter" aria-label="분야 필터"><option value="">모든 분야</option>${[...new Set([...areaNames,...papers.flatMap(p=>p.metadata.categories || [])])].map(a=>`<option value="${escape(a)}"${filters.area===a?' selected':''}>${escape(a)}</option>`).join('')}</select></label><div class="date-range"><span>발행일</span><input id="date-from" type="date" aria-label="발행일 시작" value="${filters.from}"><span>–</span><input id="date-to" type="date" aria-label="발행일 종료" value="${filters.to}"></div><button class="text-button" id="filter-reset" data-reset>초기화</button></div></section><div class="results-bar"><p>${filters.area ? escape(filters.area) : '모든 분야'} <strong id="result-count"></strong></p><select id="sort" aria-label="논문 정렬"><option value="newest"${filters.sort==='newest'?' selected':''}>최근 발행순</option><option value="oldest"${filters.sort==='oldest'?' selected':''}>과거 발행순</option></select></div><div id="paper-results" aria-live="polite"></div>`;
  renderSidebar();
  renderResults();
  $('.field-select').insertAdjacentHTML('afterend', `<button type="button" class="text-button area-filter-help" data-area-help="${escape(filters.area)}" aria-haspopup="dialog">ⓘ 분야 설명</button>`);
  if (areaDescriptions[filters.area]) {
    $('.filter-panel').insertAdjacentHTML('afterend', `<section class="area-context" aria-label="선택한 연구 분야 설명"><h2>${escape(filters.area)}</h2><p>${escape(areaDescriptions[filters.area].scope)}</p><p class="area-context-checkpoints"><strong>확인할 점</strong> ${escape(areaDescriptions[filters.area].checkpoints)}</p></section>`);
  }
  $('#search').addEventListener('input', e => {filters.search = e.target.value.trim(); renderResults(); rememberView();});
  for (const [selector,key] of [['#area-filter','area'],['#date-from','from'],['#date-to','to'],['#sort','sort']]) {
    $(selector).addEventListener('change', e => {if (key === 'area') {navigate('#/library',{area:e.target.value});return;} filters[key] = e.target.value; renderResults(); renderSidebar(); rememberView();});
  }
}

function renderPaper(paper, tab) {
  currentId = paper.id;
  currentTab = tab in tabNames ? tab : 'summary';
  document.title = `${paper.metadata.title} · Paper Radar`;
  const m = paper.metadata;
  main.innerHTML = `${backButton()}<article class="brief"><header class="brief-header"><div class="brief-topline"><div data-state-buttons="${paper.id}">${stateButtons(paper)}</div></div><h1>${escape(m.title)}</h1><p class="translation">${escape(m.translation)}</p>${metadata(paper,true)}${badges(paper)}${renderCardScore(paper)}<div class="brief-resources resource-links">${resourceLinks(paper)}<span class="review-date">${paper.briefOrigin ? '검증 기록' : '검토'} ${escape((paper.generationOrigin ? m.reviewedAt?.split('T')[0] : m.reviewedAt) || (paper.briefOrigin ? '없음' : '원본 시안 기준'))}</span></div></header>${renderReviewScope(paper)}<div class="tabs" role="tablist" aria-label="상세 브리핑">${Object.entries(tabNames).map(([id,name])=>`<button role="tab" id="tab-${id}" aria-controls="panel-${id}" data-tab="${id}" aria-selected="${id === currentTab}" tabindex="${id === currentTab ? 0 : -1}">${name}</button>`).join('')}</div>${Object.keys(tabNames).map(id => `<div role="tabpanel" id="panel-${id}" aria-labelledby="tab-${id}"${id === currentTab ? '' : ' hidden'}>${id === 'summary' ? renderAbstract(paper) : ''}${renderSections(paper.tabs?.[id])}${id === 'memo' ? `<section class="content-section memo-section"><div class="memo-heading"><div><h2><label for="notes">내 메모</label></h2></div><span id="note-status" role="status"></span></div><textarea id="notes" maxlength="100000" placeholder="메모 입력">${escape(noteDrafts.get(paper.id) ?? paper.state.notes)}</textarea><div class="memo-footer"><span>자동 저장</span><button class="button" id="save-note">메모 저장</button></div></section>` : ''}</div>`).join('')}<div class="brief-provenance"><p>${rich(m.availability || '제공된 원문과 수동 검토 브리핑 기반')}</p><p>${source(m.license)}</p></div></article>`;
  renderSidebar();
  paintNoteStatus();
  $('#notes').addEventListener('input', e => {
    noteDrafts.set(paper.id, e.target.value);
    clearTimeout(noteTimers.get(paper.id));
    noteTimers.set(paper.id, setTimeout(() => saveNote(paper.id), 550));
    paintNoteStatus();
  });
  $('#save-note').addEventListener('click', () => saveNote(paper.id));
  $$('.tabs [role="tab"]').forEach((button,index,buttons) => button.addEventListener('keydown', e => {
    let next;
    if (e.key === 'ArrowRight') next = (index + 1) % buttons.length;
    if (e.key === 'ArrowLeft') next = (index + buttons.length - 1) % buttons.length;
    if (e.key === 'Home') next = 0;
    if (e.key === 'End') next = buttons.length - 1;
    if (next !== undefined) {e.preventDefault(); activateTab(buttons[next].dataset.tab); $(`#tab-${buttons[next].dataset.tab}`).focus();}
  }));
}

function activateTab(tab) {
  if (!(tab in tabNames) || !currentId) return;
  currentTab = tab;
  $$('.tabs [role="tab"]').forEach(button => {const active=button.dataset.tab===tab;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
  $$('[role="tabpanel"]').forEach(panel => panel.hidden = panel.id !== `panel-${tab}`);
  history.replaceState(history.state,'',`#/paper/${currentId}/${tab}`);
}

function paintNoteStatus() {
  const status = $('#note-status');
  if (!status || !currentId) return;
  const dirty = noteDrafts.has(currentId);
  status.textContent = saveErrors.has(currentId) ? '저장 실패 · 다시 저장해 주세요' : pending.has(currentId) ? '저장 중…' : dirty ? '저장 대기 중…' : 'PC에 저장됨';
  status.className = saveErrors.has(currentId) ? 'save-error' : '';
}

function patchState(id, changes) {
  const previous = queues.get(id) || Promise.resolve();
  const operation = previous.catch(() => {}).then(async () => {
    pending.add(id);
    paintNoteStatus();
    try {
      const response = await fetch(`/api/state/${id}`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(changes)});
      if (!response.ok) throw new Error('저장에 실패했습니다. 서버가 실행 중인지 확인하고 다시 시도해 주세요.');
      const {state} = await response.json();
      papers.find(p => p.id === id).state = state;
      saveErrors.delete(id);
      return state;
    } catch (error) {
      saveErrors.add(id);
      notify(error.message, true);
      throw error;
    } finally {
      pending.delete(id);
      paintNoteStatus();
    }
  });
  queues.set(id, operation);
  operation.finally(() => {if (queues.get(id) === operation) queues.delete(id);}).catch(() => {});
  return operation;
}

async function saveNote(id) {
  clearTimeout(noteTimers.get(id));
  noteTimers.delete(id);
  if (!noteDrafts.has(id)) return;
  const text = noteDrafts.get(id);
  try {
    await patchState(id,{notes:text});
    if (noteDrafts.get(id) === text) noteDrafts.delete(id);
  } catch { /* Keep the draft and offer an explicit retry. */ }
  paintNoteStatus();
}

async function toggleState(button) {
  const paper = papers.find(p => p.id === button.dataset.id);
  const field = button.dataset.state;
  button.disabled = true;
  try {
    await patchState(paper.id,{[field]:!paper.state[field]});
    renderSidebar();
    if (currentId) $$(`[data-state-buttons="${paper.id}"]`).forEach(el => el.innerHTML = stateButtons(paper));
    else renderResults();
    notify(field === 'saved' ? (paper.state.saved ? '논문을 저장했습니다.' : '저장 목록에서 제외했습니다.') : (paper.state.read ? '읽은 논문으로 표시했습니다.' : '읽지 않은 논문으로 표시했습니다.'));
  } catch {button.disabled = false;}
}

function showDocumentPage(page) {
  if (!openDocument) return;
  const {document:doc, url} = openDocument;
  const requested = Number(page);
  openDocument.page = Number.isFinite(requested) ? Math.min(doc.pageCount,Math.max(1,Math.floor(requested))) : 1;
  $('#viewer-title').textContent = `${doc.title} · p.${openDocument.page}`;
  $('#page-number').value = openDocument.page;
  $('#page-number').max = doc.pageCount;
  $('#page-total').textContent = `/ ${doc.pageCount}`;
  $('#page-previous').disabled = openDocument.page === 1;
  $('#page-next').disabled = openDocument.page === doc.pageCount;
  const img = $('#viewer-body img');
  img.src = doc.pages[openDocument.page-1];
  img.alt = `${doc.title} 원문 ${openDocument.page}쪽`;
  $('#viewer-original').href = `${url}#page=${openDocument.page}`;
  $('#viewer-body').scrollTop = 0;
}

function openViewer(url, title, imageMode = false) {
  const viewer = $('#viewer');
  const body = $('#viewer-body');
  const pdf = /\.pdf(?:#|$)/i.test(url) && !imageMode;
  $('#viewer-title').textContent = title || (pdf ? '원문 PDF' : '연구 자료');
  const original = $('#viewer-original');
  original.href = url;
  original.textContent = pdf ? '원본 PDF 다운로드 ↓' : '원본 이미지 ↗';
  if (pdf) original.setAttribute('download',url.split('/').pop().split('#')[0]);
  else original.removeAttribute('download');
  $('#zoom-toggle').hidden = false;
  $('#zoom-toggle').textContent = '원본 크기';
  body.className = 'image-view';
  body.replaceChildren();
  $('#page-controls').hidden = true;
  openDocument = null;
  const documentUrl = url.split('#')[0];
  if (pdf && documentManifest[documentUrl]) {
    const img = document.createElement('img');
    body.append(img);
    openDocument = {document:documentManifest[documentUrl],url:documentUrl,page:1};
    $('#page-controls').hidden = false;
    showDocumentPage(url.match(/#page=(\d+)/)?.[1] || 1);
  } else if (pdf) {
    body.className = 'pdf-view';
    $('#zoom-toggle').hidden = true;
    const frame = document.createElement('iframe');
    frame.title = title || '원문 PDF';
    frame.src = url;
    body.append(frame);
  } else {
    const img = document.createElement('img');
    img.src = url;
    img.alt = title || '확대한 연구 자료';
    body.append(img);
  }
  viewer.showModal();
}

function roundScore(item) {
  const score = item.score;
  const label = score.total != null ? `참고 점수 ${evaluationNumber(score.total)} / 100` : score.knownMax > 0 ? `확인한 항목 ${evaluationNumber(score.subtotal)} / ${evaluationNumber(score.knownMax)} · 잠정` : '점수 미평가';
  const {citations = {},journal = {}} = item.metrics;
  return `<div class="round-score"><strong>${escape(label)}</strong>${score.total == null ? '<span>미확인 항목 제외 · 총점 미확정</span>' : ''}<span>인용 ${citations.count == null ? '미확인' : `${evaluationNumber(citations.count)}회`} · ${journal.year ? `${escape(journal.year)} ` : ''}IF ${journal.jif == null ? '미확인' : evaluationNumber(journal.jif)}</span></div>`;
}

function renderRoundItem(item) {
  const candidate = item.candidate;
  const starting = roundsStartingIds.includes(item.candidateId);
  const busy = roundsLoading || roundsStartingIds.length > 0 || preparationBusy();
  const canPrepare = ['selected','materials_partial','materials_failed'].includes(item.workflow.status);
  const note = preparationReason(item.preparation);
  const localError = roundsError && roundsActionIds.includes(item.candidateId) ? roundsError : '';
  return `<article class="round-item" data-round-candidate="${escape(item.candidateId)}"><div class="round-item-top"><h2>${escape(item.area)}</h2><span class="round-status" role="status">${escape(starting ? '자료 준비 요청 중…' : item.workflow.label)}</span></div><h3>${escape(candidate.title)}</h3><p class="candidate-meta">${escape(candidate.journal || '저널 미확인')} · ${escape(candidate.date || '발행일 미확인')}</p><p class="round-reason">${escape(item.reason)}</p>${roundScore(item)}<p class="round-basis">${item.reviewBasis === 'abstract' ? '초록 기준 잠정 선정' : '본문 확인 기준 선정'} · ${escape(item.evaluatedAt.slice(0,10))}</p>${item.workflow.stage ? `<p class="preparation-card-detail">${escape(item.workflow.stage)}</p>` : ''}${note && ['materials_partial','materials_failed'].includes(item.workflow.status) ? `<p class="round-source-note">${escape(note)}</p>` : ''}${localError ? `<p class="round-source-note" role="alert">${escape(localError)}</p>` : ''}<div class="round-actions">${item.paperId ? `<a class="button primary" href="#/card/${escape(item.paperId)}">카드 보기</a>` : ''}${canPrepare ? `<button type="button" class="button primary" data-round-prepare="${escape(item.candidateId)}"${busy ? ' disabled' : ''}>${starting ? '요청 중…' : item.preparation ? '자료 준비 다시 시도' : '브리핑 자료 준비'}</button>` : ''}${item.preparation ? `<button type="button" class="button" data-preparation-open="${escape(item.candidateId)}">준비 자료 보기</button>` : ''}${evaluationLink(candidate.doiUrl || candidate.sourceUrl,'출처')}</div></article>`;
}

function renderRoundResults() {
  const container = $('#round-results');
  if (!container) return;
  $('#round-errors').hidden = !roundsError;
  $('#round-errors').innerHTML = roundsError ? `<p>${escape(roundsError)}</p><button class="button" data-round-refresh>다시 확인</button>` : '';
  const round = roundsData?.rounds?.[0];
  if (!round) {
    container.innerHTML = roundsLoading ? '<p class="loading" role="status">선정 회차를 불러오는 중…</p>' : '<div class="empty-state"><p>아직 선정한 회차가 없습니다.</p></div>';
    return;
  }
  const items = round.items;
  const bodyCount = items.filter(item => hasPreparedBody(item.preparation)).length;
  const ready = items.filter(item => item.preparation?.status === 'ready').length;
  const partial = items.filter(item => item.preparation?.status === 'partial').length;
  const missingBody = items.filter(item => ['partial','failed'].includes(item.preparation?.status) && !hasPreparedBody(item.preparation)).length;
  const registered = items.filter(item => item.workflow.status === 'brief_registered').length;
  const unprepared = items.filter(item => item.workflow.status === 'selected').map(item => item.candidateId);
  const retry = items.filter(item => ['materials_partial','materials_failed'].includes(item.workflow.status)).map(item => item.candidateId);
  const run = preparationData?.run;
  const active = run?.status === 'running' && run.candidateIds?.some(id => items.some(item => item.candidateId === id));
  const busy = roundsLoading || roundsStartingIds.length > 0 || preparationBusy();
  const html = `<section class="round-summary"><div><h2>${escape(round.title)}</h2><p>${escape(round.createdAt.slice(0,10))} · 6개 분야 · 원저 6편</p><p class="round-body-count">본문 확보 ${bodyCount} / ${items.length}편</p><p>자료 준비 완료 ${ready}편 · 일부 자료 ${partial}편 · 본문 미확보 ${missingBody}편</p><p>브리핑 등록 ${registered}편</p></div><div class="round-summary-actions">${unprepared.length ? `<button type="button" class="button primary" data-round-prepare="all"${busy ? ' disabled' : ''}>${unprepared.length}편 자료 준비</button>` : ''}${retry.length ? `<button type="button" class="button" data-round-prepare="retry"${busy ? ' disabled' : ''}>미확보 자료 ${retry.length}편 다시 시도</button>` : ''}</div></section><p class="round-policy">내용 60 · 인용 20 · 최근 증가 10 · 저널 10. 미확인 값은 0점으로 처리하지 않습니다.</p><details class="round-selection"><summary>선정 범위</summary><p>${escape(round.selection.from)} ~ ${escape(round.selection.to)} · ${escape(round.selection.source)}</p><p>${escape(round.selection.note)}</p><p>원저 중심 · Review 별도 · Preprint 보류. 자료 준비 후 브리핑은 현재 Codex에서 작성·검토합니다.</p></details>${active ? `<p class="round-progress" role="status">자료 준비 ${countText(run.processed)} / ${countText(run.total)}편 · ${escape(run.stage || '진행 중')}</p>` : ''}<div class="round-items">${items.map(renderRoundItem).join('')}</div>`;
  if (container.innerHTML !== html) container.innerHTML = html;
}

async function refreshRounds() {
  if (roundsLoading) return;
  roundsLoading = true;
  clearTimeout(roundsTimer);
  renderRoundResults();
  try {
    const [data, preparation] = await Promise.all([discoveryRequest('/api/rounds'),discoveryRequest('/api/preparation')]);
    roundsData = data;
    preparationData = preparation;
    roundsError = '';
    for (const item of data.rounds?.[0]?.items || []) {
      const candidate = {...item.candidate,preparation:item.preparation};
      if (item.paperId) candidate.generatedCard = {paperId:item.paperId,reviewStatus:papers.find(paper => paper.id === item.paperId)?.briefOrigin?.review?.status || 'unverified'};
      const existing = candidates.findIndex(value => value.id === item.candidateId);
      if (existing === -1) candidates.push(candidate);
      else candidates[existing] = {...candidates[existing],...candidate};
    }
    if (preparationOpenId && $('#preparation-reader').open) await openPreparation(preparationOpenId,true);
  } catch (error) {
    roundsError = `회차 상태를 불러오지 못했습니다. ${error.message}`;
  } finally {
    roundsLoading = false;
    renderRoundResults();
  }
  if (location.hash === '#/rounds' && preparationData?.run?.status === 'running' && !roundsError) roundsTimer = setTimeout(refreshRounds,2000);
}

async function startRoundPreparation(value) {
  if (roundsLoading || roundsStartingIds.length || preparationBusy()) return;
  const items = roundsData?.rounds?.[0]?.items || [];
  const chosen = items.filter(item => value === 'all' ? item.workflow.status === 'selected' : value === 'retry' ? ['materials_partial','materials_failed'].includes(item.workflow.status) : item.candidateId === value && ['selected','materials_partial','materials_failed'].includes(item.workflow.status)).slice(0,6);
  if (!chosen.length) return;
  roundsStartingIds = chosen.map(item => item.candidateId);
  roundsActionIds = [...roundsStartingIds];
  roundsError = '';
  clearTimeout(roundsTimer);
  renderRoundResults();
  try {
    preparationData = await discoveryRequest('/api/preparation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({candidateIds:roundsStartingIds})});
    roundsStartingIds = [];
    await refreshRounds();
    if (roundsError) roundsError = `자료 준비 요청은 접수됐습니다. ${roundsError}`;
  } catch (error) {
    roundsStartingIds = [];
    if (error.status === 409) await refreshRounds();
    roundsError = `자료 준비를 시작하지 못했습니다. ${error.message}`;
  }
  renderRoundResults();
}

function renderRounds() {
  currentId = null;
  document.title = '이번 회차 · Paper Radar';
  main.innerHTML = `${backButton()}<div class="library-intro"><h1>이번 회차</h1><button class="button" data-round-refresh>상태 새로고침</button></div><div id="round-errors" class="collection-error" role="alert" hidden></div><div id="round-results"></div>`;
  renderSidebar();
  renderRoundResults();
  refreshRounds();
}

function renderFocusedCard(paper) {
  currentId = null;
  document.title = `${paper.metadata.title} · 논문 카드 · Paper Radar`;
  main.innerHTML = `${backButton()}<div class="library-intro feed-intro"><h1>논문 카드</h1><a class="button" href="#/discover">전체 카드 →</a></div><div id="paper-results"></div>`;
  renderSidebar();
  renderResults();
}

function route() {
  if (location.hash !== '#/rounds') clearTimeout(roundsTimer);
  if (!history.state?.paperRadar) rememberView();
  const view = history.state.paperRadar;
  Object.assign(filters,view.filters);
  Object.assign(feed,view.feed || {});
  Object.assign(discovery,view.discovery || {});
  Object.assign(evaluation,view.evaluation || {});
  Object.assign(generationPilotView,view.generationPilot || {});
  if (location.hash === '#/rounds') {
    renderRounds();
    window.scrollTo({top:view.scrollY,behavior:'instant'});
    return;
  }
  if (location.hash === '#/generation-pilot') {
    renderGenerationPilot();
    window.scrollTo({top:view.scrollY,behavior:'instant'});
    return;
  }
  if (location.hash === '#/evaluation') {
    renderEvaluation();
    window.scrollTo({top:view.scrollY,behavior:'instant'});
    return;
  }
  if (isCardFeed()) {
    renderDiscover();
    window.scrollTo({top:view.scrollY,behavior:'instant'});
    return;
  }
  if (location.hash === '#/collection') {
    renderCollection();
    window.scrollTo({top:view.scrollY,behavior:'instant'});
    return;
  }
  const match = location.hash.match(/^#\/(paper|card)\/([^/]+)(?:\/([^/]+))?$/);
  if (match) {
    const paper = papers.find(p => p.id === match[2]);
    if (paper) {
      if (match[1] === 'card') renderFocusedCard(paper);
      else renderPaper(paper,match[3] || 'summary');
      window.scrollTo({top:view.scrollY,behavior:'instant'});
      return;
    }
    main.innerHTML = '<div class="empty-state"><h1>논문을 찾을 수 없습니다</h1><a href="#/">목록으로 돌아가기</a></div>';
  } else {
    renderLibrary();
    window.scrollTo({top:view.scrollY,behavior:'instant'});
  }
}

document.addEventListener('click', e => {
  if (e.target.closest('[data-round-refresh]')) {refreshRounds();return;}
  const roundPreparation = e.target.closest('[data-round-prepare]');
  if (roundPreparation) {startRoundPreparation(roundPreparation.dataset.roundPrepare);return;}
  if (e.target.closest('[data-preparation-retry]')) {refreshPreparation();return;}
  const preparationStart = e.target.closest('[data-preparation-start]');
  if (preparationStart) {startPreparation(preparationStart.dataset.preparationStart);return;}
  const preparationOpen = e.target.closest('[data-preparation-open]');
  if (preparationOpen) {openPreparation(preparationOpen.dataset.preparationOpen);return;}
  if (e.target.closest('[data-generation-retry]')) {refreshGenerationPilot();return;}
  const generationVersion = e.target.closest('[data-generation-version]');
  if (generationVersion) {generationPilotView.version = generationVersion.dataset.generationVersion;renderGenerationPilotPanel();rememberView();return;}
  const generationTab = e.target.closest('[data-generation-tab]');
  if (generationTab) {generationPilotView.tab = generationTab.dataset.generationTab;renderGenerationPilotPanel();rememberView();return;}
  if (e.target.closest('[data-acquisition-retry]')) {refreshAcquisition();return;}
  if (e.target.closest('[data-source-batch]')) {startAcquisition(acquisitionPageCandidates().map(candidate => candidate.id));return;}
  const sourceFetch = e.target.closest('[data-source-fetch]');
  if (sourceFetch) {startAcquisition([sourceFetch.dataset.sourceFetch]);return;}
  const sourceOpen = e.target.closest('[data-source-open]');
  if (sourceOpen) {openSource(sourceOpen.dataset.sourceOpen);return;}
  const kind = e.target.closest('[data-candidate-kind]');
  if (kind) {discovery.kind = kind.dataset.candidateKind;discovery.page = 1;renderCandidateResults();$(`[data-candidate-kind="${discovery.kind}"]`).focus({preventScroll:true});rememberView();return;}
  if (e.target.closest('[data-evaluation-retry]')) {refreshEvaluation();return;}
  if (e.target.closest('[data-collection-retry]')) {startCollection(e,true);return;}
  if (e.target.closest('[data-back]')) {goBack();return;}
  if (e.target.closest('[data-discovery-retry]')) {collectionStartError = '';refreshDiscovery();return;}
  const candidatePage = e.target.closest('[data-candidate-page]');
  if (candidatePage) {discovery.page = Number(candidatePage.dataset.candidatePage);renderCandidateResults();$('#candidate-heading').scrollIntoView({block:'start',behavior:'instant'});$('#candidate-heading').focus({preventScroll:true});rememberView();return;}
  const areaHelp = e.target.closest('[data-area-help]');
  if (areaHelp) {openAreaGuide(areaHelp.dataset.areaHelp);return;}
  if (e.target.closest('.brand')) {e.preventDefault();navigate('#/discover',{collection:'all',area:'',search:'',sort:'balanced'});return;}
  const collection = e.target.closest('[data-collection]');
  if (collection) {navigate('#/library',{collection:collection.dataset.collection,area:''});return;}
  const area = e.target.closest('[data-area]');
  if (area) {if ($('#area-guide').open) $('#area-guide').close();navigate(isCardFeed() ? '#/discover' : '#/library',{area:area.dataset.area});return;}
  if (e.target.closest('[data-reset]')) {navigate(isCardFeed() ? '#/discover' : '#/library',isCardFeed() ? {collection:'all',search:'',area:''} : {search:'',area:'',from:'',to:''});return;}
  const state = e.target.closest('[data-state]');
  if (state) {toggleState(state);return;}
  const tab = e.target.closest('[data-tab]');
  if (tab) {activateTab(tab.dataset.tab);return;}
  const image = e.target.closest('[data-image]');
  if (image) {openViewer(image.dataset.image,image.dataset.title,true);return;}
  const link = e.target.closest('a[href]');
  if (!link || e.ctrlKey || e.metaKey || e.shiftKey || link.hasAttribute('download')) return;
  const href = link.getAttribute('href');
  if (href.startsWith('#/')) {e.preventDefault();navigate(href);return;}
  if (/^\/(reference|assets)\/.*\.(png|svg|jpg|jpeg|pdf)(#.*)?$/i.test(href)) {
    e.preventDefault();
    const page = href.match(/#page=(\d+)/)?.[1];
    openViewer(href,/\.pdf/.test(href) ? `${href.includes('supplement') ? 'Supplementary Information' : '원문 PDF'}${page ? ` · p.${page}` : ''}` : link.textContent.trim());
  } else if (href.startsWith('#') && !href.startsWith('#/') && currentId) {
    const target = document.getElementById(href.slice(1));
    if (target) {e.preventDefault();const panel=target.closest('[role="tabpanel"]');if(panel)activateTab(panel.id.replace('panel-',''));let ancestor=target.parentElement;while(ancestor){if(ancestor.tagName==='DETAILS')ancestor.open=true;ancestor=ancestor.parentElement;}target.scrollIntoView({behavior:'smooth',block:'start'});}
  }
});
$('#viewer-close').onclick = () => $('#viewer').close();
$('#area-guide-close').onclick = () => $('#area-guide').close();
$('#source-reader-close').onclick = () => $('#source-reader').close();
$('#source-reader').addEventListener('close',() => {sourceRequestId++;$('#source-reader-body').replaceChildren();});
$('#preparation-reader-close').onclick = () => $('#preparation-reader').close();
$('#preparation-reader').addEventListener('close',() => {preparationRequestId++;preparationOpenId = null;$('#preparation-reader-body').replaceChildren();});
$('#viewer').addEventListener('close', () => {$('#viewer-body').replaceChildren();openDocument=null;});
$('#page-previous').onclick = () => showDocumentPage(openDocument.page-1);
$('#page-next').onclick = () => showDocumentPage(openDocument.page+1);
$('#page-number').onchange = e => showDocumentPage(e.target.value);
$('#page-number').onkeydown = e => {if(e.key==='Enter'){e.preventDefault();showDocumentPage(e.target.value);}};
$('#viewer').addEventListener('click', e => {if(e.target === $('#viewer')) {const r=$('#viewer').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('#viewer').close();}});
$('#zoom-toggle').onclick = () => {const actual=$('#viewer-body').classList.toggle('actual-size');$('#zoom-toggle').textContent=actual?'화면 맞춤':'원본 크기';};
window.addEventListener('hashchange',route);
window.addEventListener('popstate',route);
document.addEventListener('keydown',e=>{if(e.key==='/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName) && $('#search')) {e.preventDefault();$('#search').focus();}});
window.addEventListener('beforeunload',e=>{if(noteDrafts.size || pending.size) {e.preventDefault();e.returnValue='';}});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden') for(const id of noteDrafts.keys()) saveNote(id);});

async function init() {
  try {
    const [response, documents] = await Promise.all([fetch('/api/papers'),fetch('/assets/documents/manifest.json')]);
    if (!response.ok) throw new Error('서버 응답 오류');
    if (documents.ok) documentManifest = await documents.json();
    ({papers} = await response.json());
    route();
  } catch {
    main.innerHTML = '<div class="empty-state"><h1>라이브러리를 불러오지 못했습니다</h1><p>서버 실행 상태를 확인하고 다시 시도해 주세요.</p><button class="button" id="retry">다시 시도</button></div>';
    $('#retry').onclick=init;
  }
}
init();
