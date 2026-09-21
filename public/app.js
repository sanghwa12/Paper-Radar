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
const localDate = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
const discoveryToday = new Date();
const discoveryStart = new Date(discoveryToday);
discoveryStart.setDate(discoveryStart.getDate()-29);
const discovery = {search:'',area:'',sort:'balanced',page:1,from:localDate(discoveryStart),to:localDate(discoveryToday)};
const evaluation = {area:''};
let evaluationData = null;
let evaluationError = '';
let evaluationLoading = false;
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
  history.replaceState({paperRadar:{index,filters:{...filters},discovery:{...discovery},evaluation:{...evaluation},scrollY:window.scrollY}},'');
}

function navigate(hash, changes = {}) {
  rememberView();
  const index = history.state.paperRadar.index + 1;
  Object.assign(filters,changes);
  history.pushState({paperRadar:{index,filters:{...filters},discovery:{...discovery},evaluation:{...evaluation},scrollY:0}},'',hash);
  route();
}

function backButton() {
  const canGoBack = history.state?.paperRadar?.index > 0 || /^#\/paper\//.test(location.hash) || ['#/discover','#/evaluation'].includes(location.hash);
  return `<nav class="page-navigation" aria-label="페이지 이동"><button type="button" class="button" data-back${canGoBack ? '' : ' disabled'}>← 뒤로가기</button></nav>`;
}

function goBack() {
  rememberView();
  if (history.state.paperRadar.index > 0) history.back();
  else {
    history.replaceState({paperRadar:{index:0,filters:{...filters},discovery:{...discovery},evaluation:{...evaluation},scrollY:0}},'','#/');
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

function metadata(paper, full = true) {
  const m = paper.metadata;
  return `<p class="paper-meta"><b>${escape(m.journal)}</b><span>${escape(m.date)}</span><span>${escape(m.authors)}</span><span>${escape(m.peerReview || 'Peer-reviewed')}</span></p>${full ? `<p class="doi">DOI <a href="https://doi.org/${escape(m.doi)}" target="_blank" rel="noopener">${escape(m.doi)}</a></p>` : ''}`;
}

function badges(paper) {
  return `<div class="tags">${(paper.metadata.tags || []).map(tag => `<span>${escape(tag)}</span>`).join('')}<span class="review-badge">${escape(paper.metadata.reviewStatus || '수동 검토')}</span></div>`;
}

function stateButtons(paper) {
  return `<button type="button" class="state-button${paper.state.read ? ' active' : ''}" data-state="read" data-id="${paper.id}" aria-pressed="${paper.state.read}">${icon('check')}<span>${paper.state.read ? '읽음' : '읽음 표시'}</span></button><button type="button" class="state-button${paper.state.saved ? ' active' : ''}" data-state="saved" data-id="${paper.id}" aria-pressed="${paper.state.saved}">${icon('bookmark')}<span>${paper.state.saved ? '저장됨' : '저장'}</span></button>`;
}

function resourceLinks(paper) {
  const m = paper.metadata;
  return `<a href="${escape(safeUrl(m.sourceUrl))}" target="_blank" rel="noopener">원문 ↗</a><a href="${escape(safeUrl(m.pdfUrl))}">PDF ↗</a>${m.siUrl ? `<a href="${escape(safeUrl(m.siUrl))}"${/^https?:/.test(m.siUrl) ? ' target="_blank" rel="noopener"' : ''}>SI ↗</a>` : '<span class="unavailable" title="제공 자료에 Supplementary Information이 없습니다.">SI 미확보</span>'}`;
}

function renderCard(paper) {
  const {card, metadata:m, id} = paper;
  const representative = card.image || card.representative;
  return `<article class="paper-card" data-paper="${id}"><header class="card-heading"><div class="card-status"><span>${paper.state.read ? '<span class="read-dot"></span> 읽은 논문' : '<span class="new-dot"></span> 읽지 않음'}</span><div data-state-buttons="${id}">${stateButtons(paper)}</div></div><a class="title-link" href="#/paper/${id}/summary"><h2>${escape(m.title)}</h2></a><p class="translation">${escape(m.translation)}</p>${metadata(paper)}${badges(paper)}</header><div class="card-body">${renderAbstract(paper, true)}<section class="card-purpose"><h3>연구 목적</h3><p>${rich(card.purpose)}</p></section><div class="card-evidence"><section><h3>방법 <span class="arrow">→</span> 결과</h3><dl class="card-pairs">${(card.pairs || []).map(pair => `<div><dt>${rich(pair.label)}</dt><dd>${pair.text ? rich(pair.text) : `${rich(pair.method)} <span class="arrow">→</span> ${rich(pair.result)}`}${pair.source ? `<small>${source(pair.source)}</small>` : ''}</dd></div>`).join('')}</dl></section>${representative ? `<figure class="representative">${zoomImage(representative.src || representative.image, representative.alt || representative.title || '대표 구조식', 'ligand-image')}<figcaption>${representative.title ? `<strong>${rich(representative.title)}</strong>` : ''}${rich(representative.caption || representative.description || '')}<small>${source(representative.source)}</small></figcaption></figure>` : ''}</div><div class="card-interpretation"><div><h3>동향상 의미</h3><p>${rich(card.significance || card.meaning)}</p></div><div><h3>연구 적용</h3><p>${rich(card.application)}</p></div></div><div class="callout">${rich(card.limits || card.caution)}</div><div class="card-actions"><a class="button primary" href="#/paper/${id}/summary">상세 브리핑 ${icon('arrow')}</a><div class="resource-links">${resourceLinks(paper)}</div></div><p class="selection-reason">선정 이유 · ${rich(card.selectionReason)}</p></div></article>`;
}

function renderSidebar() {
  const discovering = location.hash === '#/discover';
  const evaluating = location.hash === '#/evaluation';
  const inLibrary = !discovering && !evaluating;
  const discoverLink = $('#discover-link');
  discoverLink.innerHTML = `${icon('search')}<span>새 논문 수집</span>`;
  discoverLink.classList.toggle('selected',discovering);
  if (discovering) discoverLink.setAttribute('aria-current','page');
  else discoverLink.removeAttribute('aria-current');
  const evaluationLink = $('#evaluation-link');
  evaluationLink.innerHTML = `${icon('check')}<span>시범 평가</span>`;
  evaluationLink.classList.toggle('selected',evaluating);
  if (evaluating) evaluationLink.setAttribute('aria-current','page');
  else evaluationLink.removeAttribute('aria-current');
  const collections = [{id:'all',label:'전체 논문',icon:'library',count:papers.length},{id:'saved',label:'저장한 논문',icon:'bookmark',count:papers.filter(p => p.state.saved).length},{id:'unread',label:'읽지 않은 논문',icon:'unread',count:papers.filter(p => !p.state.read).length}];
  $('#collection-nav').innerHTML = collections.map(c => `<button class="nav-item${inLibrary && filters.collection === c.id && !filters.area ? ' selected' : ''}" data-collection="${c.id}"${inLibrary && filters.collection === c.id && !filters.area ? ' aria-current="page"' : ''}>${icon(c.icon)}<span>${c.label}</span><b>${c.count}</b></button>`).join('');
  const areas = [...new Set([...areaNames, ...papers.flatMap(p => p.metadata.categories || [])])];
  $('#area-nav').innerHTML = areas.map(area => `<div class="area-row"><button class="area-item${inLibrary && filters.area === area ? ' selected' : ''}" data-area="${escape(area)}"${areaDescriptions[area] ? ` title="${escape(areaDescriptions[area].scope)}"` : ''}><span class="area-dot"></span>${escape(area)}</button>${areaDescriptions[area] ? `<button type="button" class="area-info" data-area-help="${escape(area)}" aria-label="${escape(area)} 분야 설명" aria-haspopup="dialog"><span aria-hidden="true">ⓘ</span></button>` : ''}</div>`).join('');
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
  $('#collection-submit').disabled = collectionStarting || discoveryLoading || !collectionData || Boolean(collectionError) || running;
  $('#collection-submit').textContent = collectionStarting ? '수집 요청 중…' : running ? '수집 중…' : '6개 분야 수집';
  for (const id of ['#collection-from','#collection-to']) $(id).disabled = collectionStarting || running;
  $('#collection-errors').innerHTML = [collectionStartError,collectionError].filter(Boolean).map(message => `<p>${escape(message)}</p>`).join('') + (collectionError ? '<button type="button" class="button" data-discovery-retry>다시 불러오기</button>' : '');
  $('#collection-errors').hidden = !collectionStartError && !collectionError;
  const configuredAreas = collectionData?.areas || [];
  $('#collection-queries').innerHTML = configuredAreas.length ? configuredAreas.map(area => `<section class="collection-query"><h3>${escape(area.name)}</h3><p>${escape(areaDescriptions[area.name]?.scope || '')}</p><code>${escape(`(${area.query}) AND FIRST_PDATE:[${discovery.from} TO ${discovery.to}]`)}</code></section>`).join('') : `<p>${collectionError ? '검색식을 불러오지 못했습니다.' : '검색식을 불러오는 중…'}</p>`;
  const summary = !collectionData ? (collectionError ? '수집 정보를 확인할 수 없습니다.' : '수집 정보를 불러오는 중…') : !run ? '아직 수집 기록이 없습니다.' : `${collectionStatusNames[run.status] || run.status} · ${run.from} ~ ${run.to}`;
  $('#collection-progress').innerHTML = `<p class="collection-run-summary" role="status">${escape(summary)}${collectionError && run ? ' · 최신 상태 확인 필요' : ''}</p><div class="collection-totals"><span>누적 후보 <strong>${collectionData ? countText(collectionData.counts?.total) : '—'}편</strong></span>${run ? `<span>이번 수집 신규 <strong>${countText(run.added)}편</strong></span><span>기존 갱신 <strong>${countText(run.updated)}편</strong></span>` : ''}</div>${run ? `<p class="collection-timing">시작 ${escape(collectionTime(run.startedAt))}${run.finishedAt ? ` · 종료 ${escape(collectionTime(run.finishedAt))}` : ''}</p>` : ''}<div class="collection-area-progress">${(configuredAreas.length ? configuredAreas : areaNames.map(name => ({name}))).map(area => {
    const progress = run?.areas?.find(item => item.name === area.name);
    return `<article><div><h3>${escape(area.name)}</h3><span>${escape(progress ? collectionStatusNames[progress.status] || progress.status : run?.retryOf ? '이전 수집 완료' : '수집 전')}</span></div>${!progress && run?.retryOf ? '<p>이번 재시도에서 제외</p>' : `<p>검색 결과 ${progress?.pages ? countText(progress.matched) : '—'} · 처리 ${countText(progress?.processed)} · ${countText(progress?.pages)}페이지</p>`}<small>누적 후보 ${countText(collectionData?.counts?.areas?.[area.name])}편</small>${progress?.error ? `<p class="collection-area-error">${escape(progress.error)}</p>` : ''}</article>`;
  }).join('')}</div><p class="collection-count-note">누적 후보는 중복을 합친 전체 편수입니다. 여러 분야에 일치하는 논문은 분야별 편수에 각각 포함됩니다.</p>`;
  if (run?.retryOf) $('#collection-progress').insertAdjacentHTML('afterbegin', `<p class="collection-date-note">같은 발행일 범위의 실패한 ${run.areas.length}개 분야 재시도</p>`);
  if (run && !running && run.areas.some(area => ['failed','pending'].includes(area.status))) {
    $('#collection-progress').insertAdjacentHTML('beforeend', `<button type="button" class="button" data-collection-retry${collectionStarting || discoveryLoading || collectionError ? ' disabled' : ''}>실패한 분야 재시도</button>`);
  }
}

function candidateMatches() {
  const term = discovery.search.trim().toLocaleLowerCase();
  const ordered = candidates.filter(candidate => (!discovery.area || (candidate.categories || []).includes(discovery.area)) && (!term || [candidate.title,candidate.authors,candidate.journal,candidate.doi,candidate.pmid,candidate.abstract].join(' ').toLocaleLowerCase().includes(term))).sort((a,b) => String(b.date || '').localeCompare(String(a.date || '')) || String(a.id).localeCompare(String(b.id)));
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
  const types = candidate.publicationTypes || [];
  const authors = Array.isArray(candidate.authors) ? candidate.authors.join(', ') : candidate.authors;
  const dateSource = ['firstPublicationDate','Europe PMC firstPublicationDate'].includes(candidate.dateSource) ? 'Europe PMC 최초 발행일' : candidate.dateSource;
  return `<article class="candidate-card"><div class="candidate-status"><span>미검토 후보</span>${candidate.inLibrary ? '<span>브리핑 등록됨</span>' : ''}</div><h3>${externalLink(candidate.sourceUrl,candidate.title || '제목 없음') || escape(candidate.title || '제목 없음')}</h3><p class="candidate-meta">${escape(candidate.journal || '저널 정보 없음')} · ${escape(candidate.date || '발행일 정보 없음')}</p>${authors ? `<p class="candidate-authors">${escape(authors)}</p>` : ''}<div class="tags">${types.map(type => `<span>${escape(type)}</span>`).join('')}<span>${candidate.openAccess ? 'Open access 표기' : 'Open access 표기 없음'}</span><span>원문 미확보</span></div><p class="candidate-categories">검색식 일치 · ${escape((candidate.categories || []).join(' · ') || '분야 정보 없음')}</p>${candidate.abstract ? `<details class="candidate-abstract"><summary>Abstract · 원문</summary><p>${escape(candidate.abstract)}</p></details>` : '<p class="candidate-missing">Abstract 미제공</p>'}<div class="candidate-source"><span>메타데이터 · Europe PMC${candidate.source ? ` (${escape(candidate.source)})` : ''}${candidate.pmid ? ` · PMID ${escape(candidate.pmid)}` : ''}${candidate.pmcid ? ` · PMCID ${escape(candidate.pmcid)}` : ''}</span>${dateSource ? `<span>날짜 기준 · ${escape(dateSource)}</span>` : ''}</div><div class="candidate-links">${externalLink(candidate.sourceUrl,'출처')}${externalLink(candidate.doiUrl,candidate.doi ? `DOI ${candidate.doi}` : 'DOI')}</div></article>`;
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
  $('#candidate-results').innerHTML = !candidatesLoaded ? (candidateError ? '' : '<div class="loading">후보 목록을 불러오는 중…</div>') : results.length ? results.slice(start,start+24).map(renderCandidate).join('') : `<div class="empty-state"><h3>${candidates.length ? '조건에 맞는 후보가 없습니다' : '수집한 후보가 없습니다'}</h3><p>${candidates.length ? '검색어나 분야를 변경해 주세요.' : '발행일 범위를 선택하고 수집을 실행해 주세요.'}</p></div>`;
  $('#candidate-pagination').innerHTML = results.length ? `<button type="button" class="button" data-candidate-page="${discovery.page-1}"${discovery.page === 1 ? ' disabled' : ''}>← 이전</button><span>${discovery.page} / ${pages}페이지 · ${start+1}–${Math.min(start+24,results.length)}편</span><button type="button" class="button" data-candidate-page="${discovery.page+1}"${discovery.page === pages ? ' disabled' : ''}>다음 →</button>` : '';
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

function renderDiscover() {
  currentId = null;
  document.title = '새 논문 수집 · Paper Radar';
  main.innerHTML = `${backButton()}<div class="library-intro"><h1>새 논문 수집</h1></div><section class="collection-panel"><form id="collection-form"><div class="collection-dates"><label for="collection-from">발행일 시작<input type="date" id="collection-from" required value="${escape(discovery.from)}"></label><label for="collection-to">발행일 종료<input type="date" id="collection-to" required value="${escape(discovery.to)}"></label><button type="submit" class="button primary" id="collection-submit">6개 분야 수집</button></div></form><p class="collection-scope">Europe PMC · 최초 발행일 기준 · 6개 분야 동일 기간 검색 · 편수 제한 없음</p><p class="collection-date-note">기본 입력은 최근 30일이며 변경할 수 있습니다. 자동 실행은 설정되어 있지 않습니다.</p><div class="collection-error" id="collection-errors" role="alert" hidden></div><div id="collection-progress"></div><details class="collection-settings"><summary>분야별 검색 범위·검색식</summary><p>선택한 최초 발행일 범위를 포함한 검색식입니다. 읽기 전용이며 날짜 입력에 맞춰 바뀝니다.</p><div id="collection-queries"></div></details></section><section aria-labelledby="candidate-heading"><div class="candidate-heading"><h2 id="candidate-heading" tabindex="-1">수집 후보</h2><strong id="candidate-count"></strong></div><p class="candidate-scope">누적 수집 목록 · 메타데이터와 Abstract 원문. 분야 태그는 검색식 일치이며 내용 검토 결과가 아닙니다.</p><p class="candidate-scope">Open access 표기는 출처 정보입니다. PDF·본문은 아직 확보하지 않았습니다.</p><div class="filter-panel"><label class="search-box">${icon('search')}<input id="candidate-search" type="search" aria-label="수집 후보 검색" placeholder="제목, 저자, DOI, Abstract 검색" value="${escape(discovery.search)}"></label><div class="filter-row"><label class="field-select"><span>분야</span><select id="candidate-area" aria-label="수집 후보 분야"><option value="">모든 분야</option>${areaNames.map(area => `<option value="${escape(area)}"${discovery.area === area ? ' selected' : ''}>${escape(area)}</option>`).join('')}</select></label><label class="candidate-sort-label"><span>정렬</span><select id="candidate-sort"><option value="balanced"${discovery.sort === 'balanced' ? ' selected' : ''}>분야 균형순</option><option value="newest"${discovery.sort === 'newest' ? ' selected' : ''}>최근 발행순</option></select></label></div></div><p class="candidate-order-note">분야 균형순은 각 분야의 최신 논문을 한 편씩 번갈아 보여줍니다. 중복 논문은 한 번만 표시합니다.</p><div class="collection-error" id="candidate-errors" role="alert" hidden></div><div id="candidate-results"></div><nav id="candidate-pagination" class="candidate-pagination" aria-label="수집 후보 페이지"></nav></section>`;
  $('.library-intro').insertAdjacentHTML('afterend','<a class="evaluation-entry" href="#/evaluation"><div><strong>시범 평가 보기</strong><span>6개 분야 · 논문별 점수와 평가 근거</span></div><span aria-hidden="true">→</span></a>');
  renderSidebar();
  renderCollectionState();
  renderCandidateResults();
  $('#collection-form').addEventListener('submit',startCollection);
  for (const [selector,key] of [['#collection-from','from'],['#collection-to','to']]) $(selector).addEventListener('change',event => {discovery[key] = event.target.value;renderCollectionState();rememberView();});
  for (const [selector,key,eventName] of [['#candidate-search','search','input'],['#candidate-area','area','change'],['#candidate-sort','sort','change']]) $(selector).addEventListener(eventName,event => {discovery[key] = event.target.value;discovery.page = 1;renderCandidateResults();rememberView();});
  refreshDiscovery();
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
  const results = matches();
  const isInvalid = filters.from && filters.to && filters.from > filters.to;
  $('#result-count').textContent = `${isInvalid ? 0 : results.length}편`;
  $('#paper-results').innerHTML = isInvalid ? '<div class="empty-state"><h2>날짜 범위를 확인해 주세요</h2><p>시작일은 종료일보다 이전이어야 합니다.</p></div>' : results.length ? results.map(renderCard).join('') : `<div class="empty-state">${icon(filters.collection === 'saved' ? 'bookmark' : 'search')}<h2>${filters.collection === 'saved' && !papers.some(p => p.state.saved) ? '저장한 논문이 없습니다' : '조건에 맞는 논문이 없습니다'}</h2><p>검색어나 분야, 발행일 조건을 변경해 보세요.</p><button data-reset class="button">필터 초기화</button></div>`;
  $('#filter-reset').hidden = !Object.entries(filters).some(([key,value]) => key !== 'collection' && key !== 'sort' && value);
}

function renderLibrary() {
  currentId = null;
  document.title = 'Paper Radar';
  const title = filters.collection === 'saved' ? '저장한 논문' : filters.collection === 'unread' ? '읽지 않은 논문' : '논문 라이브러리';
  main.innerHTML = `${backButton()}<div class="library-intro"><div><h1>${title}</h1></div><div class="library-stamp"><b>${String(papers.length).padStart(2,'0')}</b><span>검토된 브리핑</span></div></div><section class="filter-panel" aria-label="논문 필터"><label class="search-box">${icon('search')}<input id="search" type="search" placeholder="제목, 키워드, 저자 또는 DOI 검색" aria-label="논문 검색" value="${escape(filters.search)}"><kbd aria-hidden="true">/</kbd></label><div class="filter-row"><label class="field-select"><span>분야</span><select id="area-filter" aria-label="분야 필터"><option value="">모든 분야</option>${[...new Set([...areaNames,...papers.flatMap(p=>p.metadata.categories || [])])].map(a=>`<option value="${escape(a)}"${filters.area===a?' selected':''}>${escape(a)}</option>`).join('')}</select></label><div class="date-range"><span>발행일</span><input id="date-from" type="date" aria-label="발행일 시작" value="${filters.from}"><span>–</span><input id="date-to" type="date" aria-label="발행일 종료" value="${filters.to}"></div><button class="text-button" id="filter-reset" data-reset>초기화</button></div></section><div class="results-bar"><p>${filters.area ? escape(filters.area) : '모든 분야'} <strong id="result-count"></strong></p><select id="sort" aria-label="논문 정렬"><option value="newest"${filters.sort==='newest'?' selected':''}>최근 발행순</option><option value="oldest"${filters.sort==='oldest'?' selected':''}>과거 발행순</option></select></div><div id="paper-results" aria-live="polite"></div>`;
  renderSidebar();
  renderResults();
  $('.field-select').insertAdjacentHTML('afterend', `<button type="button" class="text-button area-filter-help" data-area-help="${escape(filters.area)}" aria-haspopup="dialog">ⓘ 분야 설명</button>`);
  if (areaDescriptions[filters.area]) {
    $('.filter-panel').insertAdjacentHTML('afterend', `<section class="area-context" aria-label="선택한 연구 분야 설명"><h2>${escape(filters.area)}</h2><p>${escape(areaDescriptions[filters.area].scope)}</p><p class="area-context-checkpoints"><strong>확인할 점</strong> ${escape(areaDescriptions[filters.area].checkpoints)}</p></section>`);
  }
  $('#search').addEventListener('input', e => {filters.search = e.target.value.trim(); renderResults(); rememberView();});
  for (const [selector,key] of [['#area-filter','area'],['#date-from','from'],['#date-to','to'],['#sort','sort']]) {
    $(selector).addEventListener('change', e => {if (key === 'area') {navigate('#/',{area:e.target.value});return;} filters[key] = e.target.value; renderResults(); renderSidebar(); rememberView();});
  }
}

function renderPaper(paper, tab) {
  currentId = paper.id;
  currentTab = tab in tabNames ? tab : 'summary';
  document.title = `${paper.metadata.title} · Paper Radar`;
  const m = paper.metadata;
  main.innerHTML = `${backButton()}<article class="brief"><header class="brief-header"><div class="brief-topline"><div data-state-buttons="${paper.id}">${stateButtons(paper)}</div></div><h1>${escape(m.title)}</h1><p class="translation">${escape(m.translation)}</p>${metadata(paper,true)}${badges(paper)}<div class="brief-resources resource-links">${resourceLinks(paper)}<span class="review-date">검토 ${escape(m.reviewedAt || '원본 시안 기준')}</span></div></header><div class="tabs" role="tablist" aria-label="상세 브리핑">${Object.entries(tabNames).map(([id,name])=>`<button role="tab" id="tab-${id}" aria-controls="panel-${id}" data-tab="${id}" aria-selected="${id === currentTab}" tabindex="${id === currentTab ? 0 : -1}">${name}</button>`).join('')}</div>${Object.keys(tabNames).map(id => `<div role="tabpanel" id="panel-${id}" aria-labelledby="tab-${id}"${id === currentTab ? '' : ' hidden'}>${id === 'summary' ? renderAbstract(paper) : ''}${renderSections(paper.tabs?.[id])}${id === 'memo' ? `<section class="content-section memo-section"><div class="memo-heading"><div><h2><label for="notes">내 메모</label></h2></div><span id="note-status" role="status"></span></div><textarea id="notes" maxlength="100000" placeholder="메모 입력">${escape(noteDrafts.get(paper.id) ?? paper.state.notes)}</textarea><div class="memo-footer"><span>자동 저장</span><button class="button" id="save-note">메모 저장</button></div></section>` : ''}</div>`).join('')}<div class="brief-provenance"><p>${rich(m.availability || '제공된 원문과 수동 검토 브리핑 기반')}</p><p>${source(m.license)}</p></div></article>`;
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

function route() {
  if (!history.state?.paperRadar) rememberView();
  const view = history.state.paperRadar;
  Object.assign(filters,view.filters);
  Object.assign(discovery,view.discovery || {});
  Object.assign(evaluation,view.evaluation || {});
  if (location.hash === '#/evaluation') {
    renderEvaluation();
    window.scrollTo({top:view.scrollY,behavior:'instant'});
    return;
  }
  if (location.hash === '#/discover') {
    renderDiscover();
    window.scrollTo({top:view.scrollY,behavior:'instant'});
    return;
  }
  const match = location.hash.match(/^#\/paper\/([^/]+)(?:\/([^/]+))?$/);
  if (match) {
    const paper = papers.find(p => p.id === match[1]);
    if (paper) {
      renderPaper(paper,match[2] || 'summary');
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
  if (e.target.closest('[data-evaluation-retry]')) {refreshEvaluation();return;}
  if (e.target.closest('[data-collection-retry]')) {startCollection(e,true);return;}
  if (e.target.closest('[data-back]')) {goBack();return;}
  if (e.target.closest('[data-discovery-retry]')) {collectionStartError = '';refreshDiscovery();return;}
  const candidatePage = e.target.closest('[data-candidate-page]');
  if (candidatePage) {discovery.page = Number(candidatePage.dataset.candidatePage);renderCandidateResults();$('#candidate-heading').scrollIntoView({block:'start',behavior:'instant'});$('#candidate-heading').focus({preventScroll:true});rememberView();return;}
  const areaHelp = e.target.closest('[data-area-help]');
  if (areaHelp) {openAreaGuide(areaHelp.dataset.areaHelp);return;}
  if (e.target.closest('.brand')) {e.preventDefault();navigate('#/',{collection:'all',area:'',search:'',from:'',to:''});return;}
  const collection = e.target.closest('[data-collection]');
  if (collection) {navigate('#/',{collection:collection.dataset.collection,area:''});return;}
  const area = e.target.closest('[data-area]');
  if (area) {if ($('#area-guide').open) $('#area-guide').close();navigate('#/',{area:area.dataset.area});return;}
  if (e.target.closest('[data-reset]')) {navigate('#/',{search:'',area:'',from:'',to:''});return;}
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
