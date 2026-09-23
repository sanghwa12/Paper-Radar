/* Review discovery is separate from the original-paper collection and reading state. */
const reviewRadar = (() => {
  let catalog = null;
  let loading = false;
  let loadError = '';
  let searching = false;
  let searchError = '';
  let result = null;
  const fields = {area:'', keywords:'', sort:'relevance'};
  const briefingTabs = [['overview','요약'],['methods','방법 비교'],['evidence','근거와 원저'],['limits','그림·한계'],['application','연구 적용']];
  const selectedTabs = new Map();

  const onPage = () => /^#\/review-radar(?:\/[^/]+)?$/.test(location.hash);
  const text = value => escape(value == null ? '' : value);
  const count = value => Number.isFinite(value) ? value.toLocaleString('ko-KR') : '미확인';
  function link(url, label) {
    return /^https?:\/\//i.test(url || '')
      ? `<a href="${text(url)}" target="_blank" rel="noopener">${text(label)} ↗</a>`
      : `<span>${text(label)}</span>`;
  }
  function detailId() {
    const value = location.hash.match(/^#\/review-radar\/([^/]+)$/)?.[1];
    try { return value ? decodeURIComponent(value) : ''; }
    catch { return 'invalid-review-id'; }
  }
  function meta(paper) {
    return `<p class="review-meta">${text(paper.journal)}${paper.date ? ` · ${text(paper.date)}` : ''}</p>`;
  }
  function scopeLabel(review) {
    return review.readingScope?.fullText === 'checked' ? '본문 검토 · 원저 별도 확인 필요'
      : review.readingScope?.fullText === 'partial' ? '본문 일부 검토 · 원저 별도 확인 필요'
      : '초록 검토 · 본문 확인 필요';
  }
  function registeredCard(review) {
    return `<article class="review-card"><div class="review-card-top"><span>${text((review.areas || []).join(' · '))}</span><span class="review-status">${text(scopeLabel(review))}</span></div><h3><a href="#/review-radar/${encodeURIComponent(review.id)}">${text(review.title)}</a></h3>${review.titleKo ? `<p class="translation">${text(review.titleKo)}</p>` : ''}${meta(review)}<p class="review-scope">${text(review.summary?.scope)}</p><p class="review-selection"><strong>선정 이유</strong> ${text(review.selectionReason)}</p><a class="button primary" href="#/review-radar/${encodeURIComponent(review.id)}">상세 브리핑 →</a></article>`;
  }
  function searchForm() {
    const policy = catalog?.policy;
    return `<section class="review-search" aria-labelledby="review-search-heading"><h2 id="review-search-heading">리뷰 검색</h2><p class="review-policy">${policy ? `${text(policy.from)} – ${text(policy.to)} · 최근 ${text(policy.windowYears)}년 · 분야·방법의 흐름을 정리하는 리뷰 중심` : '검색 기준을 불러오는 중입니다.'}</p><form id="review-search-form"><label>분야<select id="review-search-area" name="area" required>${(policy?.areas || []).map(area => `<option value="${text(area)}"${fields.area === area ? ' selected' : ''}>${text(area)}</option>`).join('')}</select></label><label class="review-keywords">검색어 <span>선택</span><input id="review-search-keywords" name="keywords" type="search" maxlength="120" placeholder="관심 주제 또는 방법" value="${text(fields.keywords)}"></label><label>정렬<select id="review-search-sort" name="sort"><option value="relevance"${fields.sort === 'relevance' ? ' selected' : ''}>검색 관련도순</option><option value="newest"${fields.sort === 'newest' ? ' selected' : ''}>최근 발행순</option></select></label><button id="review-search-submit" class="button primary" type="submit"${searching || !policy ? ' disabled' : ''}>${searching ? '검색 중…' : '리뷰 검색'}</button></form><p class="review-search-note">검색 후보는 최대 30편이며, 검토·선정된 목록이 아닙니다.</p><div id="review-search-error" role="alert"${searchError ? '' : ' hidden'}>${text(searchError)}${result ? '<p>아래에는 이전에 성공한 검색 결과가 남아 있습니다.</p>' : ''}</div><div id="review-search-results" aria-live="polite">${searchResults()}</div></section>`;
  }
  function candidateCard(paper) {
    const classification = paper.classification;
    return `<article class="review-candidate"><div class="review-card-top"><span>${text(classification?.label || '유형 확인 필요')}</span><span>메타데이터 후보 · 미검토</span></div><h3>${link(paper.doiUrl || paper.sourceUrl, paper.title)}</h3>${meta(paper)}${paper.authors ? `<p class="review-authors">${text(paper.authors)}</p>` : ''}${paper.abstract ? `<details class="review-abstract"><summary>Abstract · 원문</summary><p>${text(paper.abstract)}</p></details>` : '<p class="review-search-note">초록 미확보</p>'}<div class="review-source-links">${link(paper.sourceUrl, '서지정보 출처')}${paper.doi ? `<span>DOI ${text(paper.doi)}</span>` : ''}</div></article>`;
  }
  function searchResults() {
    if (!result) return searching ? '<p class="review-search-note" role="status">리뷰 메타데이터를 검색하는 중입니다.</p>' : '';
    const data = result.data;
    const candidates = (data.candidates || []).slice(0, 30);
    const excluded = Object.entries(data.excludedCounts || {}).filter(([,number]) => number > 0);
    const excludedLabels = {invalidMetadata:'서지정보 확인 필요',outsideWindow:'기간 밖',notReview:'리뷰 유형 불일치',systematicOrMetaAnalysis:'체계적 고찰·메타분석',duplicate:'중복'};
    return `${searching ? '<p class="review-search-note" role="status">새 검색 중 · 아래는 이전 검색 결과입니다.</p>' : ''}<div class="review-results-heading"><h3>검색 후보 <span>${candidates.length}편</span></h3><p>${text(result.fields.area)}${result.fields.keywords ? ` · ${text(result.fields.keywords)}` : ''} · ${result.fields.sort === 'newest' ? '최근 발행순' : '검색 관련도순'}</p><p>${text(data.from)} – ${text(data.to)} · 조회 ${text((data.observedAt || '').slice(0, 10))}</p><p>검색 응답 ${count(data.hitCount)}건 · 확인한 메타데이터 ${count(data.fetched)}편 · 표시 ${candidates.length}편${data.truncated ? ' · 일부 결과만 표시' : ''}</p></div><details class="review-query"><summary>검색 출처와 조건</summary><p>${link(data.sourceUrl, 'Europe PMC 검색')}</p><p class="review-query-text">${text(data.query)}</p>${excluded.length ? `<p>표시 제외: ${excluded.map(([kind,number]) => `${text(excludedLabels[kind] || '기타 제외')} ${count(number)}편`).join(' · ')}</p>` : ''}</details>${candidates.length ? candidates.map(candidateCard).join('') : '<div class="empty-state"><p>표시할 리뷰 후보가 없습니다. 검색어 또는 분야를 변경해 주세요.</p></div>'}`;
  }
  function readingScope(review) {
    const names = {abstract:'초록',fullText:'본문',figures:'그림',supplements:'보충자료',originalPapers:'연결된 원저'};
    const labels = {checked:'검토함',partial:'일부 검토',unverified:'미검토',metadata_only:'본문 미검토 · 확인 범위는 출처 참고'};
    const detailed = review.briefing?.version === 1;
    const note = `<p>${text(review.readingScope?.note)}</p>`;
    return `<aside class="review-reading-scope"><strong>${text(scopeLabel(review))}</strong>${detailed ? '' : note}<details><summary>검토 범위</summary>${detailed ? note : ''}<dl>${Object.entries(names).map(([key,label]) => `<div><dt>${label}</dt><dd>${text(labels[review.readingScope?.[key]] || '미확인')}</dd></div>`).join('')}</dl></details></aside>`;
  }
  function originalCard(paper) {
    return `<article class="review-original"><div class="review-card-top"><span>${text(paper.referenceLabel || '인용 원저')}${paper.year ? ` · ${text(paper.year)}` : ''}</span><span class="review-status">인용 서지 확인 · 원저 본문 미검토</span></div><h3>${link(paper.sourceUrl, paper.title)}</h3><p>${text(paper.role)}</p><p class="review-original-location">리뷰 내 위치 · ${text(paper.referenceLocation || '미확인')}</p>${paper.note ? `<p class="review-search-note">${text(paper.note)}</p>` : ''}${paper.doi ? `<small>DOI ${text(paper.doi)}</small>` : ''}</article>`;
  }
  function originalsSection(review) {
    return `<section class="review-originals" aria-labelledby="review-originals-heading"><h2 id="review-originals-heading">핵심 원저 <span>${(review.originals || []).length}편</span></h2><p class="review-search-note">연결 원저의 본문은 아직 검토하지 않았습니다. 확인한 자료의 범위는 각 근거와 원저 설명에 표시했습니다.</p>${(review.originals || []).map(originalCard).join('')}</section>`;
  }
  function blockSources(ids, sources, interpretation = false) {
    if (!ids?.length) return interpretation ? '' : '<p class="review-evidence-note">근거 미확인 · 연결된 출처가 없습니다.</p>';
    return `<details class="review-block-sources"><summary>근거 ${ids.length}개 · 위치와 확인 범위</summary><ul>${ids.map(id => {
      const source = sources.get(id);
      return source ? `<li>${link(source.url, source.label)}<dl><div><dt>위치</dt><dd>${text(source.location || '미확인')}</dd></div><div><dt>확인 범위</dt><dd>${text(source.scope || '미확인')}</dd></div></dl></li>` : '<li><strong>출처 미확인</strong><p>연결된 자료를 확인하지 못했습니다.</p></li>';
    }).join('')}</ul></details>`;
  }
  function briefingBlock(block, sources) {
    const labels = {review_claim:'리뷰 저자 주장',evidence:'보고된 근거',interpretation:'분석자 해석',background:'배경 설명',limitation:'한계'};
    return `<section class="content-section review-brief-block"><div class="review-brief-block-heading"><h3>${text(block.heading)}</h3><span>${text(labels[block.kind] || '설명')}</span></div>${(block.paragraphs || []).map(paragraph => `<p>${text(paragraph)}</p>`).join('')}${blockSources(block.sourceIds, sources, block.kind === 'interpretation')}</section>`;
  }
  function briefingTable(table, sources) {
    return `<div class="review-table-scroll" role="region" tabindex="0" aria-label="${text(table.caption || '방법 비교 표')}"><table class="review-method-table"><caption>${text(table.caption)}</caption><thead><tr>${(table.columns || []).map(column => `<th scope="col">${text(column)}</th>`).join('')}<th scope="col">근거</th></tr></thead><tbody>${(table.rows || []).map(row => `<tr>${(row.cells || []).map((cell,index) => index === 0 ? `<th scope="row">${text(cell)}</th>` : `<td>${text(cell)}</td>`).join('')}<td>${blockSources(row.sourceIds, sources)}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function briefingFlow(flow) {
    return `<figure class="review-brief-flow"><figcaption>분석자가 재구성한 개념 흐름</figcaption><ol>${flow.map(step => `<li><h3>${text(step.title)}</h3><p>${text(step.text)}</p></li>`).join('')}</ol></figure>`;
  }
  function briefingFigure(figure, sources) {
    const safe = /^\/assets\/review-radar\/[A-Za-z0-9_-]+\/[A-Za-z0-9_-]+\.(?:svg|png|jpe?g|webp)$/i.test(figure.src || '');
    return `<figure class="review-brief-figure">${safe ? `<button type="button" class="image-zoom" data-image="${text(figure.src)}" data-title="${text(figure.alt)}" aria-label="${text(figure.alt || '해설 그림')} 확대"><img src="${text(figure.src)}" alt="${text(figure.alt)}" loading="lazy"><span>그림 확대</span></button>` : '<p class="review-evidence-note">그림 자료 미확인 · 표시할 파일을 확인하지 못했습니다.</p>'}<figcaption><p>${text(figure.caption)}</p>${blockSources(figure.sourceIds, sources)}</figcaption></figure>`;
  }
  function detailedBriefing(review) {
    const selected = selectedTabs.get(review.id) || 'overview';
    const sections = new Map((review.briefing.sections || []).map(section => [section.id,section]));
    const sources = new Map((review.briefing.sources || []).map(source => [source.id,source]));
    return `<div class="tabs review-brief-tabs" id="review-brief-tabs" role="tablist" aria-label="리뷰 상세 브리핑">${briefingTabs.map(([id,title]) => `<button type="button" role="tab" id="review-brief-tab-${id}" data-review-brief-tab="${id}" aria-controls="review-brief-panel-${id}" aria-selected="${id === selected}" tabindex="${id === selected ? 0 : -1}">${title}</button>`).join('')}</div>${briefingTabs.map(([id,title]) => {
      const section = sections.get(id);
      return `<div class="review-brief-panel" role="tabpanel" id="review-brief-panel-${id}" aria-labelledby="review-brief-tab-${id}" tabindex="0"${id === selected ? '' : ' hidden'}><header class="review-brief-section-heading"><h2>${title}</h2>${section?.lead ? `<p>${text(section.lead)}</p>` : ''}</header>${section ? `${section.flow?.length ? briefingFlow(section.flow) : ''}${section.figure ? briefingFigure(section.figure, sources) : ''}${section.table ? briefingTable(section.table, sources) : ''}${(section.blocks || []).map(block => briefingBlock(block, sources)).join('')}` : '<p class="review-evidence-note">이 탭의 브리핑 자료는 아직 없습니다.</p>'}${id === 'evidence' ? originalsSection(review) : ''}</div>`;
    }).join('')}`;
  }
  function activateBriefingTab(reviewId, selected, focus = false) {
    selectedTabs.set(reviewId, selected);
    for (const [id] of briefingTabs) {
      const button = $(`#review-brief-tab-${id}`);
      const panel = $(`#review-brief-panel-${id}`);
      if (!button || !panel) continue;
      button.setAttribute('aria-selected', String(id === selected));
      button.tabIndex = id === selected ? 0 : -1;
      panel.hidden = id !== selected;
    }
    if (focus) $(`#review-brief-tab-${selected}`)?.focus();
  }
  function bindBriefing(review) {
    const tablist = $('#review-brief-tabs');
    if (!tablist) return;
    for (const [id] of briefingTabs) $(`#review-brief-tab-${id}`).onclick = () => activateBriefingTab(review.id, id);
    tablist.onkeydown = event => {
      const index = briefingTabs.findIndex(([id]) => id === event.target.getAttribute('data-review-brief-tab'));
      if (index < 0 || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? briefingTabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + briefingTabs.length) % briefingTabs.length;
      activateBriefingTab(review.id, briefingTabs[next][0], true);
    };
  }
  function legacyDetail(review) {
    return `<section class="content-section"><h2>이 리뷰를 고른 이유</h2><p>${text(review.selectionReason)}</p></section><section class="content-section"><h2>다루는 범위</h2><p>${text(review.summary?.scope)}</p><h3>핵심 정리</h3><ul class="content-list">${(review.summary?.takeaways || []).map(item => `<li>${text(item)}</li>`).join('')}</ul></section><section class="content-section"><h2>범위와 한계</h2><ul class="content-list">${(review.summary?.limitations || []).map(item => `<li>${text(item)}</li>`).join('')}</ul></section>${originalsSection(review)}`;
  }
  function detail(review) {
    const citations = review.citations || {};
    const journal = review.journalMetric || {};
    return `<article class="review-detail"><header><p class="review-detail-area">${text((review.areas || []).join(' · '))}</p><h1>${text(review.title)}</h1>${review.titleKo ? `<p class="translation">${text(review.titleKo)}</p>` : ''}${meta(review)}<p class="review-authors">${text(review.authors)}</p><div class="review-source-links">${link(review.sourceUrl, '리뷰 원문')}${review.doi ? `<span>DOI ${text(review.doi)}</span>` : ''}</div></header>${readingScope(review)}${review.briefing?.version === 1 ? detailedBriefing(review) : legacyDetail(review)}<details class="review-provenance"><summary>출처와 지표</summary><p>인용 ${count(citations.count)}${citations.count == null ? '' : '회'}${citations.observedAt ? ` · 조회 ${text(citations.observedAt.slice(0, 10))}` : ''}${citations.sourceUrl ? ` · ${link(citations.sourceUrl, '인용 출처')}` : ''}</p><p>Journal Impact Factor ${journal.status === 'verified' && Number.isFinite(journal.jif) ? `${text(journal.jif)} (${text(journal.year)})` : '미확인'}</p><ul>${(review.provenance || []).map(item => `<li>${link(item.url, item.label)}<span>${text(item.scope)}${item.checkedAt ? ` · ${text(item.checkedAt.slice(0, 10))}` : ''}</span></li>`).join('')}</ul></details></article>`;
  }
  function paint() {
    if (!onPage()) return;
    const id = detailId();
    const review = catalog?.reviews?.find(item => item.id === id);
    document.title = `${review ? review.title + ' · ' : ''}리뷰 Radar · Paper Radar`;
    const error = loadError ? `<div class="review-load-error" role="alert"><p>${text(loadError)}</p>${catalog ? '<p>이전에 불러온 등록 자료를 표시합니다.</p>' : ''}<button class="button" id="review-load-retry"${loading ? ' disabled' : ''}>다시 확인</button></div>` : '';
    const body = id ? (review ? detail(review) : `<div class="empty-state"><p>${loading ? '리뷰를 불러오는 중입니다.' : loadError ? '등록 리뷰를 확인하지 못했습니다.' : '등록된 리뷰를 찾을 수 없습니다.'}</p><a class="button" href="#/review-radar">리뷰 목록으로</a></div>`) : `<div class="library-intro review-intro"><h1>리뷰 Radar</h1>${catalog ? `<span>최근 ${text(catalog.policy.windowYears)}년 · ${catalog.policy.areas.length}개 분야</span>` : ''}</div><section class="review-registered" aria-labelledby="review-registered-heading"><div class="review-section-heading"><h2 id="review-registered-heading">등록 리뷰</h2><span>${catalog?.reviews?.length || 0}편</span></div>${catalog?.reviews?.length ? catalog.reviews.map(registeredCard).join('') : `<div class="empty-state"><p>${loading ? '등록 리뷰를 불러오는 중입니다.' : loadError ? '등록 목록을 확인하지 못했습니다.' : '아직 등록된 리뷰가 없습니다.'}</p></div>`}</section>${searchForm()}`;
    main.innerHTML = `${backButton()}${id ? '<a class="review-list-link" href="#/review-radar">← 리뷰 목록</a>' : ''}${error}${body}`;
    renderSidebar();
    if (review?.briefing?.version === 1) bindBriefing(review);
    const retry = $('#review-load-retry');
    if (retry) retry.onclick = refresh;
    const form = $('#review-search-form');
    if (form) {
      form.onsubmit = search;
      for (const [selector,key] of [['#review-search-area','area'],['#review-search-keywords','keywords'],['#review-search-sort','sort']]) {
        $(selector).oninput = event => {fields[key] = event.target.value;};
        $(selector).onchange = event => {fields[key] = event.target.value;};
      }
    }
  }
  async function request(url, options) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '요청을 처리하지 못했습니다.');
    return payload;
  }
  async function refresh() {
    if (loading) return;
    loading = true;
    loadError = '';
    paint();
    try {
      const data = await request('/api/review-radar');
      if (!Array.isArray(data.reviews) || !Array.isArray(data.policy?.areas)) throw new Error('리뷰 목록의 형식을 확인해 주세요.');
      catalog = data;
      if (!catalog.policy.areas.includes(fields.area)) fields.area = catalog.policy.areas[0] || '';
    } catch (error) {
      loadError = `등록 리뷰를 불러오지 못했습니다. ${error.message}`;
    } finally {
      loading = false;
      paint();
    }
  }
  async function search(event) {
    event?.preventDefault();
    if (searching || !catalog) return;
    for (const [selector,key] of [['#review-search-area','area'],['#review-search-keywords','keywords'],['#review-search-sort','sort']]) {
      const input = $(selector);
      if (input) fields[key] = input.value;
    }
    const submitted = {...fields,keywords:fields.keywords.trim()};
    searching = true;
    searchError = '';
    paint();
    try {
      const data = await request('/api/review-radar/search', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(submitted)});
      if (!Array.isArray(data.candidates)) throw new Error('검색 결과의 형식을 확인해 주세요.');
      result = {data,fields:submitted};
    } catch (error) {
      searchError = `검색하지 못했습니다. ${error.message}`;
    } finally {
      searching = false;
      paint();
    }
  }
  function open() {
    currentId = null;
    if (loading) paint();
    return refresh();
  }
  return {open};
})();
