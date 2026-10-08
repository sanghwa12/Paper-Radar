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
  history.replaceState({paperRadar:{index,filters:{...filters},feed:{...feed},scrollY:window.scrollY}},'');
}

function navigate(hash, changes = {}) {
  rememberView();
  const index = history.state.paperRadar.index + 1;
  Object.assign(['#/','#/discover'].includes(hash) ? feed : filters,changes);
  history.pushState({paperRadar:{index,filters:{...filters},feed:{...feed},scrollY:0}},'',hash);
  route();
}

function backButton() {
  const canGoBack = history.state?.paperRadar?.index > 0 || /^#\/(paper|card)(\/|$)/.test(location.hash) || ['#/library','#/workflow'].includes(location.hash);
  return `<nav class="page-navigation" aria-label="페이지 이동"><button type="button" class="button" data-back${canGoBack ? '' : ' disabled'}>← 뒤로가기</button></nav>`;
}

function goBack() {
  rememberView();
  if (history.state.paperRadar.index > 0) history.back();
  else {
    history.replaceState({paperRadar:{index:0,filters:{...filters},feed:{...feed},scrollY:0}},'','#/discover');
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
  const originNames = {fulltext:'핵심 요약 · 본문 기반 초안',prior_fulltext_review:'핵심 요약 · 기존 본문 검토 기반 초안',abstract:'핵심 요약 · 초록 기반 초안'};
  const label = paper.cardOrigin ? originNames[paper.cardOrigin.basis] || '핵심 요약 초안' : paper.metadata.reviewStatus || '수동 검토';
  return `<div class="tags">${(paper.metadata.tags || []).map(tag => `<span>${escape(tag)}</span>`).join('')}<span class="review-badge${paper.cardOrigin?.basis === 'abstract' ? ' abstract-basis' : ''}"${paper.cardOrigin?.evidenceNote ? ` title="${escape(paper.cardOrigin.evidenceNote)}"` : ''}>${escape(label)}</span>${paper.briefOrigin?.review ? `<span class="review-badge ${paper.briefOrigin.review.status !== 'reviewed' ? 'abstract-basis' : ''}">심층 분석 · ${escape(paper.metadata.reviewStatus)}</span>` : ''}</div>`;
}

function renderReviewScope(paper) {
  const review = paper.briefOrigin?.review;
  if (!review) return '';
  const scopes = {abstract:'초록',body:'본문',figures:'그림',supplement:'보충자료'};
  const states = {reviewed:'검토함',partial:'일부 검토',unverified:'미검증',unavailable:'미확인'};
  return `<aside class="brief-review" aria-label="심층 분석 검증 상태"><p><strong>${escape(paper.metadata.reviewStatus)}</strong>${paper.generationOrigin ? '' : ` · ${escape(review.note)}`}</p><details><summary>자료 확보·검토 범위</summary>${paper.generationOrigin ? `<p>${escape(review.note)}</p>` : ''}<div class="table-scroll"><table><thead><tr><th scope="col">자료</th><th scope="col">확보</th><th scope="col">내용 검토</th></tr></thead><tbody>${Object.entries(scopes).map(([key,label]) => `<tr><th scope="row">${label}</th><td>${review.acquired[key] == null ? '미확인' : review.acquired[key] ? '확보함' : '미확보'}</td><td>${states[review.checked[key]] || '미검증'}</td></tr>`).join('')}</tbody></table></div>${review.holds.length ? `<ul>${review.holds.map(hold => `<li><strong>${hold.reason === 'safety' ? '안전상 범위 제한' : '자료 미확인'} · ${escape(hold.scope)}</strong>: ${escape(hold.note)}</li>`).join('')}</ul>` : ''}<small>자료 확보는 다운로드·접근 상태이며, 내용 검토는 이번에 실제 대조한 범위입니다.</small></details></aside>`;
}

function stateButtons(paper) {
  return `<button type="button" class="state-button${paper.state.read ? ' active' : ''}" data-state="read" data-id="${paper.id}" aria-pressed="${paper.state.read}">${icon('check')}<span>${paper.state.read ? '읽음' : '읽음 표시'}</span></button><button type="button" class="state-button${paper.state.saved ? ' active' : ''}" data-state="saved" data-id="${paper.id}" aria-pressed="${paper.state.saved}">${icon('bookmark')}<span>${paper.state.saved ? '저장됨' : '저장'}</span></button>`;
}

function resourceLinks(paper) {
  const m = paper.metadata;
  return `${safeUrl(m.sourceUrl) ? `<a href="${escape(safeUrl(m.sourceUrl))}" target="_blank" rel="noopener">원문 ↗</a>` : ''}${safeUrl(m.pdfUrl) ? `<a href="${escape(safeUrl(m.pdfUrl))}">PDF ↗</a>` : ''}${safeUrl(m.siUrl) ? `<a href="${escape(safeUrl(m.siUrl))}"${/^https?:/.test(m.siUrl) ? ' target="_blank" rel="noopener"' : ''}>SI ↗</a>` : paper.kind === 'discovery' ? '' : '<span class="unavailable" title="제공 자료에 Supplementary Information이 없습니다.">SI 미확보</span>'}`;
}

function renderResearchFlow(paper) {
  if (!paper.card.flow?.length) return '';
  return `<figure class="research-flow"><figcaption>연구 흐름 요약</figcaption><ol>${paper.card.flow.map(step => `<li>${escape(step)}</li>`).join('')}</ol></figure>`;
}

// Diagram shown first on a summary card; the prose sections stay folded below it.
function renderGlance(g) {
  const step = (label, text, className = '') => `<li${className ? ` class="${className}"` : ''}><b>${rich(label)}</b><span>${rich(text)}</span></li>`;
  return `<section class="glance" aria-label="한눈에 보기"><div class="glance-head"><span class="glance-type">${rich(g.type)}</span><p>${rich(g.oneLiner)}</p></div><ol class="glance-flow">${step('문제', g.problem, 'glance-problem')}${(g.steps || []).map(s => step(s.label, s.text)).join('')}${step('결론', g.conclusion, 'glance-conclusion')}</ol><div class="glance-results">${(g.keyResults || []).map(r => `<div><strong>${rich(r.value)}</strong><span>${rich(r.label)}</span><small>${rich(r.context)}</small>${r.source ? `<small class="glance-source">${source(r.source)}</small>` : ''}</div>`).join('')}</div></section>`;
}

function renderCard(paper) {
  const {card, metadata:m, id} = paper;
  const representative = card.image || card.representative;
  const analysis = paper.generatedKind === 'summary' && m.doi ? papers.find(p=>p.generatedKind==='analysis' && p.metadata.doi?.toLowerCase()===m.doi.toLowerCase()) : null;
  return `<article class="paper-card" data-paper="${id}"><header class="card-heading"><div class="card-status"><span>${paper.state.read ? '<span class="read-dot"></span> 읽은 논문' : '<span class="new-dot"></span> 읽지 않음'}</span><div data-state-buttons="${id}">${stateButtons(paper)}</div></div><a class="title-link" href="#/card/${id}"><h2>${escape(m.title)}</h2></a><p class="translation">${escape(m.translation)}</p>${metadata(paper,true,true)}${badges(paper)}</header><div class="card-body">${paper.abstract ? renderAbstract(paper, true) : ''}${card.glance ? `${renderGlance(card.glance)}<div class="callout">${rich(card.limits || card.caution)}</div><details class="card-detail"><summary>자세한 설명 펼치기</summary>` : ''}<section class="card-purpose"><h3>연구 목적</h3><p>${rich(card.purpose)}</p></section><div class="card-evidence${representative ? '' : ' no-image'}"><section><h3>방법 <span class="arrow">→</span> 결과</h3><dl class="card-pairs">${(card.pairs || []).map(pair => `<div><dt>${rich(pair.label)}</dt><dd>${pair.text ? rich(pair.text) : `${rich(pair.method)} <span class="arrow">→</span> ${rich(pair.result)}`}${pair.source ? `<small>${source(pair.source)}</small>` : ''}</dd></div>`).join('')}</dl></section>${representative ? `<figure class="representative">${zoomImage(representative.src || representative.image, representative.alt || representative.title || '대표 구조식', 'ligand-image')}<figcaption>${representative.title ? `<strong>${rich(representative.title)}</strong>` : ''}${rich(representative.caption || representative.description || '')}<small>${source(representative.source)}</small></figcaption></figure>` : ''}</div>${renderResearchFlow(paper)}<div class="card-interpretation"><div><h3>동향상 의미</h3><p>${rich(card.significance || card.meaning)}</p></div><div><h3>연구 적용</h3><p>${rich(card.application)}</p></div></div>${card.glance ? '</details>' : `<div class="callout">${rich(card.limits || card.caution)}</div>`}<div class="card-actions">${analysis ? `<a class="button primary" href="#/paper/${analysis.id}/summary">심층 분석 보기 →</a>` : paper.generatedKind === 'summary' ? `<a class="button primary" href="#/generate-analysis?paper=${encodeURIComponent(id)}">심층 분석 생성 →</a><span class="muted">심층 분석 미작성</span>` : `<a class="button primary" href="#/paper/${id}/summary">심층 분석 ${icon('arrow')}</a>`}<div class="resource-links">${resourceLinks(paper)}</div></div>${card.selectionReason ? `<p class="selection-reason">선정 이유 · ${rich(card.selectionReason)}</p>` : ''}</div></article>`;
}

function renderSidebar() {
  const discovering = isCardFeed() || location.hash.startsWith('#/card/') || papers.find(p=>p.id===currentId)?.generatedKind==='summary';
  const inTools = ['#/workflow','#/generate-summary','#/generate-analysis'].includes(location.hash.split('?')[0]);
  const inLibrary = !discovering && !inTools;
  for (const link of $$('#discovery-nav a')) {
    const selected = link.getAttribute('href') === location.hash.split('?')[0];
    link.classList.toggle('selected',selected);
    if (selected) link.setAttribute('aria-current','page');
    else link.removeAttribute('aria-current');
  }
  const discoverLink = $('#discover-link');
  discoverLink.classList.toggle('selected',discovering);
  if (discovering) discoverLink.setAttribute('aria-current','page');
  else discoverLink.removeAttribute('aria-current');
  const analysisLink = $('#analysis-library-link');
  analysisLink.classList.toggle('selected',inLibrary);
  if (inLibrary) analysisLink.setAttribute('aria-current','page');
  else analysisLink.removeAttribute('aria-current');
  const libraryPapers = papers.filter(p=>!p.generatedKind || p.generatedKind===(discovering || inTools ? 'summary' : 'analysis'));
  const collections = [{id:'all',label:'전체 논문',icon:'library',count:libraryPapers.length},{id:'saved',label:'저장한 논문',icon:'bookmark',count:libraryPapers.filter(p => p.state.saved).length},{id:'unread',label:'읽지 않은 논문',icon:'unread',count:libraryPapers.filter(p => !p.state.read).length}];
  $('#collection-nav').innerHTML = collections.map(c => `<button class="nav-item${(discovering || inLibrary) && (discovering ? feed : filters).collection === c.id && !(discovering ? feed : filters).area ? ' selected' : ''}" data-collection="${c.id}"${(discovering || inLibrary) && (discovering ? feed : filters).collection === c.id && !(discovering ? feed : filters).area ? ' aria-current="page"' : ''}>${icon(c.icon)}<span>${c.label}</span><b>${c.count}</b></button>`).join('');
  const areas = [...new Set([...areaNames, ...papers.flatMap(p => p.metadata.categories || [])])];
  $('#area-nav').innerHTML = areas.map(area => `<div class="area-row"><button class="area-item${(discovering ? feed.area : inLibrary ? filters.area : '') === area ? ' selected' : ''}" data-area="${escape(area)}"${areaDescriptions[area] ? ` title="${escape(areaDescriptions[area].scope)}"` : ''}><span class="area-dot"></span>${escape(area)}</button>${areaDescriptions[area] ? `<button type="button" class="area-info" data-area-help="${escape(area)}" aria-label="${escape(area)} 분야 설명" aria-haspopup="dialog"><span aria-hidden="true">ⓘ</span></button>` : ''}</div>`).join('');
}

function openAreaGuide(area) {
  const names = areaDescriptions[area] ? [area] : areaNames;
  $('#area-guide-title').textContent = names.length === 1 ? area : '연구 분야 안내';
  $('#area-guide-content').innerHTML = `<p class="area-guide-note">분야는 논문을 읽는 관점입니다. 한 논문에 여러 분야가 함께 적용될 수 있습니다.</p>${names.map(name => `<section class="area-guide-section">${names.length > 1 ? `<h3>${escape(name)}</h3>` : ''}<p>${escape(areaDescriptions[name].scope)}</p><div class="area-checkpoints"><strong>확인할 점</strong><p>${escape(areaDescriptions[name].checkpoints)}</p></div><button type="button" class="button" data-area="${escape(name)}">이 분야 논문 보기 →</button></section>`).join('')}`;
  $('#area-guide').showModal();
}

function feedMatches() {
  const term = feed.search.trim().toLocaleLowerCase();
  const ordered = papers.filter(p => (!p.generatedKind || p.generatedKind === 'summary') &&
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
  document.title = '핵심 요약 라이브러리 · Paper Radar';
  const count = papers.filter(p=>!p.generatedKind || p.generatedKind==='summary').length;
  main.innerHTML = `${backButton()}<div class="library-intro feed-intro"><div><h1>핵심 요약 라이브러리</h1><p>핵심 요약 ${count}편</p></div><a class="button" href="#/generate-summary">핵심 요약 생성기</a></div><section class="filter-panel" aria-label="핵심 요약 필터"><label class="search-box">${icon('search')}<input id="search" type="search" placeholder="제목, 키워드, 저자 또는 DOI 검색" aria-label="핵심 요약 검색" value="${escape(feed.search)}"><kbd aria-hidden="true">/</kbd></label><div class="filter-row"><label class="field-select"><span>분야</span><select id="feed-area" aria-label="핵심 요약 분야"><option value="">모든 분야</option>${areaNames.map(area => `<option value="${escape(area)}"${feed.area === area ? ' selected' : ''}>${escape(area)}</option>`).join('')}</select></label><button type="button" class="text-button area-filter-help" data-area-help="${escape(feed.area)}" aria-haspopup="dialog">ⓘ 분야 설명</button><label class="field-select feed-state-filter"><span>보기</span><select id="feed-state" aria-label="핵심 요약 읽기 상태"><option value="all"${feed.collection === 'all' ? ' selected' : ''}>전체</option><option value="unread"${feed.collection === 'unread' ? ' selected' : ''}>읽지 않음</option><option value="read"${feed.collection === 'read' ? ' selected' : ''}>읽음</option><option value="saved"${feed.collection === 'saved' ? ' selected' : ''}>저장한 논문</option></select></label><button type="button" class="text-button" id="filter-reset" data-reset>초기화</button></div></section>${areaDescriptions[feed.area] ? `<section class="area-context" aria-label="선택한 연구 분야 설명"><h2>${escape(feed.area)}</h2><p>${escape(areaDescriptions[feed.area].scope)}</p></section>` : ''}<div class="results-bar"><p>${feed.area ? escape(feed.area) : '모든 분야'} <strong id="result-count"></strong></p><select id="feed-sort" aria-label="핵심 요약 정렬"><option value="balanced"${feed.sort === 'balanced' ? ' selected' : ''}>분야 균형순</option><option value="newest"${feed.sort === 'newest' ? ' selected' : ''}>최근 발행순</option></select></div><div id="paper-results" aria-live="polite"></div>`;
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
    return (!p.generatedKind || p.generatedKind === 'analysis') && (filters.collection !== 'saved' || p.state.saved) &&
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
  $('#paper-results').innerHTML = isInvalid ? '<div class="empty-state"><h2>날짜 범위를 확인해 주세요</h2><p>시작일은 종료일보다 이전이어야 합니다.</p></div>' : results.length ? results.map(p => p.generatedReport ? generatedCard(p) : renderCard(p)).join('') : `<div class="empty-state">${icon(active.collection === 'saved' ? 'bookmark' : 'search')}<h2>${active.collection === 'saved' ? '조건에 맞는 저장한 논문이 없습니다' : '조건에 맞는 논문이 없습니다'}</h2><p>검색어나 필터를 변경해 보세요.</p><button data-reset class="button">필터 초기화</button></div>`;
  $$('.paper-card .abstract').forEach(item => {if (openAbstracts.has(item.closest('[data-paper]').dataset.paper)) item.open = true;});
  if ($('#filter-reset')) $('#filter-reset').hidden = !Object.entries(active).some(([key,value]) => key === 'collection' ? isCardFeed() && value !== 'all' : key !== 'sort' && value);
}

function renderLibrary() {
  currentId = null;
  document.title = '심층 분석 라이브러리 · Paper Radar';
  const title = filters.collection === 'saved' ? '심층 분석 · 저장한 논문' : filters.collection === 'unread' ? '심층 분석 · 읽지 않은 논문' : '심층 분석 라이브러리';
  main.innerHTML = `${backButton()}<div class="library-intro"><div><h1>${title}</h1></div><div class="library-stamp"><b>${String(papers.filter(p=>!p.generatedKind || p.generatedKind==='analysis').length).padStart(2,'0')}</b><span>논문과 심층 분석</span></div></div><section class="filter-panel" aria-label="논문 필터"><label class="search-box">${icon('search')}<input id="search" type="search" placeholder="제목, 키워드, 저자 또는 DOI 검색" aria-label="논문 검색" value="${escape(filters.search)}"><kbd aria-hidden="true">/</kbd></label><div class="filter-row"><label class="field-select"><span>분야</span><select id="area-filter" aria-label="분야 필터"><option value="">모든 분야</option>${[...new Set([...areaNames,...papers.flatMap(p=>p.metadata.categories || [])])].map(a=>`<option value="${escape(a)}"${filters.area===a?' selected':''}>${escape(a)}</option>`).join('')}</select></label><div class="date-range"><span>발행일</span><input id="date-from" type="date" aria-label="발행일 시작" value="${filters.from}"><span>–</span><input id="date-to" type="date" aria-label="발행일 종료" value="${filters.to}"></div><button class="text-button" id="filter-reset" data-reset>초기화</button></div></section><div class="results-bar"><p>${filters.area ? escape(filters.area) : '모든 분야'} <strong id="result-count"></strong></p><select id="sort" aria-label="논문 정렬"><option value="newest"${filters.sort==='newest'?' selected':''}>최근 발행순</option><option value="oldest"${filters.sort==='oldest'?' selected':''}>과거 발행순</option></select></div><div id="paper-results" aria-live="polite"></div>`;
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
  if (paper.generatedReport) {renderGeneratedPaper(paper, tab);return;}
  currentId = paper.id;
  currentTab = tab in tabNames ? tab : 'summary';
  document.title = `${paper.metadata.title} · Paper Radar`;
  const m = paper.metadata;
  main.innerHTML = `${backButton()}<article class="brief"><header class="brief-header"><div class="brief-topline"><div data-state-buttons="${paper.id}">${stateButtons(paper)}</div></div><h1>${escape(m.title)}</h1><p class="translation">${escape(m.translation)}</p>${metadata(paper,true)}${badges(paper)}<div class="brief-resources resource-links">${resourceLinks(paper)}<span class="review-date">${paper.briefOrigin ? '검증 기록' : '검토'} ${escape((paper.generationOrigin ? m.reviewedAt?.split('T')[0] : m.reviewedAt) || (paper.briefOrigin ? '없음' : '원본 시안 기준'))}</span></div></header>${renderReviewScope(paper)}<div class="tabs" role="tablist" aria-label="심층 분석">${Object.entries(tabNames).map(([id,name])=>`<button role="tab" id="tab-${id}" aria-controls="panel-${id}" data-tab="${id}" aria-selected="${id === currentTab}" tabindex="${id === currentTab ? 0 : -1}">${name}</button>`).join('')}</div>${Object.keys(tabNames).map(id => `<div role="tabpanel" id="panel-${id}" aria-labelledby="tab-${id}"${id === currentTab ? '' : ' hidden'}>${id === 'summary' && paper.abstract ? renderAbstract(paper) : ''}${renderSections(paper.tabs?.[id])}${id === 'memo' ? `<section class="content-section memo-section"><div class="memo-heading"><div><h2><label for="notes">내 메모</label></h2></div><span id="note-status" role="status"></span></div><textarea id="notes" maxlength="100000" placeholder="메모 입력">${escape(noteDrafts.get(paper.id) ?? paper.state.notes)}</textarea><div class="memo-footer"><span>자동 저장</span><button class="button" id="save-note">메모 저장</button></div></section>` : ''}</div>`).join('')}<div class="brief-provenance"><p>${rich(m.availability || '제공된 원문과 수동 검토 심층 분석 기반')}</p><p>${source(m.license)}</p></div></article>`;
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
  const pageUrl = doc.pages[openDocument.page-1];
  img.src = pageUrl;
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

function renderFocusedCard(paper) {
  currentId = null;
  document.title = `${paper.metadata.title} · 핵심 요약 · Paper Radar`;
  main.innerHTML = `${backButton()}<div class="library-intro feed-intro"><h1>핵심 요약</h1><a class="button" href="#/discover">전체 핵심 요약 →</a></div><div id="paper-results"></div>`;
  renderSidebar();
  renderResults();
}

function route() {
  clearInterval(generationPoll);
  if (['#/collection','#/evaluation','#/generation-pilot','#/rounds','#/fulltext'].includes(location.hash)) history.replaceState(null,'','#/discover');
  if (!history.state?.paperRadar) rememberView();
  const view = history.state.paperRadar;
  Object.assign(filters,view.filters);
  Object.assign(feed,view.feed || {});
  if (location.hash === '#/workflow') {renderWorkflow();return;}
  if (['#/generate-summary','#/generate-analysis'].includes(location.hash.split('?')[0])) {renderGenerator();return;}
  if (isCardFeed()) {
    renderDiscover();
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
  if (e.target.closest('[data-back]')) {goBack();return;}
  const areaHelp = e.target.closest('[data-area-help]');
  if (areaHelp) {openAreaGuide(areaHelp.dataset.areaHelp);return;}
  if (e.target.closest('.brand')) {e.preventDefault();navigate('#/discover',{collection:'all',area:'',search:'',sort:'balanced'});return;}
  const collection = e.target.closest('[data-collection]');
  if (collection) {navigate(isCardFeed() || location.hash.startsWith('#/card/') ? '#/discover' : '#/library',{collection:collection.dataset.collection,area:''});return;}
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
