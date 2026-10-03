let pdfLinkBusy = false;
let workflowRecords = null;

async function renderWorkflow() {
  currentId = null;
  document.title = 'Review 추출기 · Paper Radar';
  renderSidebar();
  main.innerHTML = '<p role="status">작업을 불러오는 중…</p>';
  try {
    const response = await fetch('/api/workflows');
    if (!response.ok) throw new Error('작업 목록을 불러오지 못했습니다.');
    const data = await response.json();
    if (location.hash !== '#/workflow') return;
    workflowRecords = data.workflows;
    if (!workflowRecords.length) {main.innerHTML = '<h1>Review 추출기</h1><p>등록된 작업이 없습니다.</p>';return;}
    main.innerHTML = `${backButton()}<div class="library-intro"><h1>Review 추출기</h1></div><label for="workflow-choice">Review</label> <select id="workflow-choice">${workflowRecords.map(w => `<option value="${escape(w.id)}">${escape(w.name)}</option>`).join('')}</select><div id="workflow-detail"></div>`;
    $('#workflow-choice').onchange = event => renderWorkflowDetail(event.target.value);
    renderWorkflowDetail(workflowRecords[0].id);
  } catch (error) {
    if (location.hash !== '#/workflow') return;
    main.innerHTML = `<h1>Review 추출기</h1><p role="alert">${escape(error.message)}</p><button class="button" id="workflow-retry">다시 시도</button>`;
    $('#workflow-retry').onclick = renderWorkflow;
  }
}

function renderWorkflowDetail(id) {
  const w = workflowRecords.find(item => item.id === id);
  const review = w.papers.filter(p => w.pdfLinks?.papers[p.doi]?.status === 'review');
  $('#workflow-detail').innerHTML = `
    ${review.length ? `<section class="content-section workflow-attention" aria-label="확인 필요한 PDF"><h2>먼저 확인해 주세요 · ${review.length}편</h2><ul class="workflow-papers">${review.map(p=>renderWorkflowPaper(w,p,true)).join('')}</ul></section>` : ''}
    ${renderPdfLinkControls(w)}
    <details class="content-section workflow-source"><summary>제공 논문 · ${escape(w.name)}</summary><h3>${escape(w.source.title)}</h3><p>${escape(w.source.year)} · ${escape(w.source.type)}</p><div class="workflow-source-actions">${w.source.available ? `<a class="button" href="${escape(w.source.url)}" target="_blank" rel="noopener">제공 PDF 열기</a>` : '<span>원본 파일 확인 필요</span>'}<a href="https://doi.org/${encodeURIComponent(w.source.doi)}" target="_blank" rel="noopener">DOI ↗</a></div><section class="workflow-source-summary" aria-label="제공 논문 핵심 요약"><h4>핵심 요약</h4><p${w.summary ? '' : ' class="muted"'}>${w.summary ? escape(w.summary) : '작성 대기'}</p></section></details>
    <section class="content-section"><h2>관련 논문</h2><details class="workflow-context"><summary>목록 출처·분류 기준</summary><p>${escape(w.relationNote)}</p><a href="${escape(safeUrl(w.provenance))}" target="_blank" rel="noopener">출처 ↗</a><p>PDF 연결과 내용 검토·요약 작성 상태는 별도입니다.</p></details>
    ${w.groups.map((group, index) => {
      const all = w.papers.filter(p=>p.risFile===group.file);
      const items = all.filter(p=>!review.includes(p));
      const content = `<div class="workflow-group-title"><span>${all.length-items.length ? `확인 필요 ${all.length-items.length}편은 맨 위에 표시` : ''}</span><a class="button" download href="${escape(safeUrl(group.url))}">RIS 다운로드 · ${all.length}편</a></div><ul class="workflow-papers">${items.map(p=>renderWorkflowPaper(w,p)).join('')}</ul>`;
      return index === 0 ? `<div class="workflow-group"><h3>${escape(group.name)} · ${all.length}편</h3>${content}</div>` : `<details class="workflow-group"><summary>${escape(group.name)} · ${all.length}편</summary>${content}</details>`;
    }).join('')}</section>`;
}

function renderWorkflowPaper(w,p,attention=false) {
  const entry=w.pdfLinks?.papers[p.doi];
  const labels={linked:'PDF 연결됨',missing:'PDF 없음',review:'확인 필요'};
  const index=w.papers.indexOf(p);
  const candidates=entry?.candidates || [];
  return `<li class="workflow-row"><div class="workflow-row-title"><h4>${escape(p.title)}</h4><span class="workflow-badge ${escape(entry?.status || '')}">${labels[entry?.status] || '검사 전'}</span></div>
    ${attention ? `<p class="workflow-review-reason">${escape(entry.reason)}</p>` : ''}
    <div class="workflow-row-actions">${entry?.status==='linked' ? `<a class="button" href="/api/workflows/${encodeURIComponent(w.id)}/pdf/${index}/${entry.selected || 0}" target="_blank" rel="noopener">PDF 열기</a>` : ''}${p.summaryPaperId ? `<a class="button" href="#/card/${encodeURIComponent(p.summaryPaperId)}">핵심 요약</a>` : ''}${p.analysisPaperId ? `<a class="button" href="#/paper/${encodeURIComponent(p.analysisPaperId)}/summary">심층 분석</a>` : ''}</div>
    ${attention ? candidates.map((c,i)=>`<div class="workflow-candidate">${candidates.length>1 ? `<p>${escape(c.name)}</p>` : ''}<a class="button" href="/api/workflows/${encodeURIComponent(w.id)}/pdf/${index}/${i}" target="_blank" rel="noopener">후보 PDF 열기</a> <button class="button" data-pdf-confirm="${i}" data-pdf-paper="${index}" data-pdf-work="${escape(w.id)}"${pdfLinkBusy ? ' disabled' : ''}>이 PDF로 연결</button></div>`).join('') : ''}
    <details class="workflow-row-details"><summary>상세 정보</summary><p>${escape(p.journal)} · ${escape(p.year)} · ${escape(p.type)}</p><a href="https://doi.org/${encodeURIComponent(p.doi)}" target="_blank" rel="noopener">${escape(p.doi)} ↗</a><p>핵심 요약 · ${p.summaryPaperId ? '등록됨':'작성 대기'} / 심층 분석 · ${p.analysisPaperId ? '등록됨':'미작성'}</p>${entry ? `<p>${escape(entry.reason)}</p>` : ''}${candidates.map(c=>`<p>${escape(c.name)} · ${c.pages}쪽</p><code class="workflow-path">${escape(c.path)}</code><p>${escape(c.basis)} · 내용 미검토</p>`).join('')}</details></li>`;
}

function renderPdfLinkControls(w) {
  const report=w.pdfLinks || {papers:{},errors:[]};
  const entries=Object.values(report.papers);
  return `<section class="content-section workflow-scan"><div class="workflow-group-title"><h2>PDF 연결</h2><button class="button primary" data-pdf-scan="${escape(w.id)}"${pdfLinkBusy ? ' disabled' : ''}>${pdfLinkBusy ? 'PDF 검사 중…' : 'PDF 연결 확인'}</button></div><p id="pdf-link-message" role="status">${report.scannedAt ? `연결 ${entries.filter(e=>e.status==='linked').length} · 확인 필요 ${entries.filter(e=>e.status==='review').length} · 없음 ${entries.filter(e=>e.status==='missing').length}` : '아직 검사하지 않았습니다.'}</p><details><summary>검사 정보</summary><code class="workflow-path">${escape(report.folder || '')}</code><p>${report.scannedAt ? `${escape(new Date(report.scannedAt).toLocaleString())} · PDF ${report.fileCount}개 검사` : ''}</p><p>원본을 복사·이동하지 않습니다. 온라인 전용 파일은 검사 중 PC로 내려받아질 수 있습니다.</p></details>${report.errors.length ? `<details><summary>읽지 못한 파일·폴더 ${report.errors.length}개</summary><ul>${report.errors.map(e=>`<li>${escape(e.name)} · ${escape(e.reason)}</li>`).join('')}</ul></details>` : ''}</section>`;
}
document.addEventListener('click',async event=>{
  const button = event.target.closest('[data-pdf-scan],[data-pdf-confirm]');
  if (!button || pdfLinkBusy) return;
  const id = button.dataset.pdfScan || button.dataset.pdfWork;
  const w = workflowRecords.find(item=>item.id===id);
  const action = button.dataset.pdfScan ? 'scan' : 'confirm';
  const payload = action==='scan' ? {} : {doi:w.papers[Number(button.dataset.pdfPaper)].doi,index:Number(button.dataset.pdfConfirm)};
  pdfLinkBusy = true;
  renderWorkflowDetail(id);
  $('#workflow-choice').disabled = true;
  try {
    const response = await fetch(`/api/workflows/${encodeURIComponent(id)}/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'PDF 연결에 실패했습니다.');
    w.pdfLinks = data;
    if (location.hash==='#/workflow') renderWorkflowDetail(id);
  } catch(error) {
    if (location.hash==='#/workflow') $('#pdf-link-message').textContent = error.message;
  } finally {
    pdfLinkBusy = false;
    if (location.hash==='#/workflow') {
      $('#workflow-choice').disabled = false;
      for (const element of $$('[data-pdf-scan],[data-pdf-confirm]')) element.disabled = false;
      const scanButton = $('[data-pdf-scan]');
      if (scanButton) scanButton.textContent = 'PDF 연결 확인';
    }
  }
});
