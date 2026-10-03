let generationPoll;
async function renderGenerator() {
  const hash = location.hash;
  const kind = hash.split('?')[0] === '#/generate-analysis' ? 'analysis' : 'summary';
  const paperId = new URLSearchParams(hash.split('?')[1] || '').get('paper');
  const name = kind === 'analysis' ? '심층 분석 생성기' : '핵심 요약 생성기';
  currentId = null;
  document.title = `${name} · Paper Radar`;
  renderSidebar();
  main.innerHTML = `${backButton()}<h1>${name}</h1><p role="status">논문을 불러오는 중…</p>`;
  try {
    const response = await fetch('/api/generation-requests');
    if (!response.ok) throw new Error('논문과 요청 목록을 불러오지 못했습니다.');
    const data = await response.json();
    if (location.hash !== hash) return;
    const groups = [...new Map(data.targets.map(t=>[t.groupId,{id:t.groupId,name:t.groupName}])).values()];
    const requestId = paperId?.match(/^generated-(\d+)$/)?.[1];
    const targetKey = requestId ? data.requests.find(r=>String(r.id)===requestId)?.key : paperId ? `library:${paperId}` : null;
    const selectedTarget = data.targets.find(t=>t.key===targetKey);
    let groupId = selectedTarget?.groupId || groups[0]?.id;
    main.innerHTML = `${backButton()}<div class="library-intro"><h1>${name}</h1></div><form id="generator-form" class="content-section"><fieldset id="generator-selection"><legend>논문 묶음</legend><input id="generator-group-search" type="search" aria-label="논문 묶음 검색" placeholder="묶음 이름으로 검색"><div id="generator-groups" role="radiogroup" aria-label="논문 묶음"></div><p id="generator-current-group"></p><div class="generator-selection-toolbar"><button type="button" class="button" id="generator-select-all">전체 선택</button><button type="button" class="button" id="generator-clear">선택 해제</button><span id="generator-selected-count" role="status"></span></div><div id="generator-targets"></div></fieldset><div class="generator-actions"><button class="button primary" type="submit" ${data.targets.length ? '' : 'disabled'}>생성</button><p class="muted">생성을 누르면 기존 Codex 로그인으로 원문 검토와 작성을 시작합니다. 검증을 통과한 결과만 라이브러리에 등록됩니다.</p></div><p id="generator-message" role="status"></p></form><section class="content-section"><h2>요청 내역</h2><div id="generator-history"></div></section>`;
    const paintGroups = () => {
      const term = $('#generator-group-search').value.trim().toLocaleLowerCase();
      const matched = groups.filter(g=>g.name.toLocaleLowerCase().includes(term));
      $('#generator-groups').innerHTML = matched.map(g=>`<label><input type="radio" name="group" value="${escape(g.id)}" ${g.id===groupId ? 'checked' : ''}><span>${escape(g.name)}</span><small>${data.targets.filter(t=>t.groupId===g.id).length}편</small></label>`).join('') || '<p class="muted">일치하는 묶음이 없습니다.</p>';
    };
    const updateSelection = () => {
      const inputs = $$('input[name="target"]');
      const count = inputs.filter(input=>input.checked).length;
      $('#generator-selected-count').textContent=`${count} / ${inputs.length}편 선택`;
      for (const section of $$('.generator-section')) {
        const items = [...section.querySelectorAll('input[name="target"]')];
        const checked = items.filter(input=>input.checked).length;
        const toggle = section.querySelector('[data-section-select]');
        toggle.checked = checked === items.length;
        toggle.indeterminate = checked > 0 && checked < items.length;
      }
    };
    const paintTargets = () => {
      const targets = data.targets.map((target,index)=>({...target,index})).filter(t=>t.groupId===groupId);
      const sections = [...new Set(targets.map(t=>t.section))];
      $('#generator-current-group').textContent=groupId ? `선택한 묶음 · ${groups.find(g=>g.id===groupId).name}` : '';
      $('#generator-targets').innerHTML = sections.map(section=>`<section class="generator-section"><h2><label><input type="checkbox" data-section-select aria-label="${escape(section)} 전체 선택">${escape(section)} <small>${targets.filter(t=>t.section===section).length}편</small></label></h2><div class="generator-choices">${targets.filter(t=>t.section===section).map(t=>`<label><input type="checkbox" name="target" value="${t.index}"><span>${escape(t.title)}</span></label>`).join('')}</div></section>`).join('') || '<p>PDF가 연결된 논문이 없습니다.</p>';
      $('#generator-message').textContent='';
      updateSelection();
    };
    $('#generator-group-search').oninput=paintGroups;
    $('#generator-group-search').onkeydown=event=>{if(event.key==='Enter') event.preventDefault();};
    $('#generator-groups').onchange=event=>{groupId=event.target.value;paintTargets();};
    $('#generator-targets').onchange=event=>{
      if(event.target.hasAttribute('data-section-select')) {
        for(const input of event.target.closest('.generator-section').querySelectorAll('input[name="target"]')) input.checked=event.target.checked;
      }
      updateSelection();
    };
    const selectAll = checked=>{for(const input of $$('input[name="target"]')) input.checked=checked;updateSelection();};
    $('#generator-select-all').onclick=()=>selectAll(true);
    $('#generator-clear').onclick=()=>selectAll(false);
    paintGroups();
    paintTargets();
    if (selectedTarget) {
      const index = data.targets.indexOf(selectedTarget);
      $(`input[name="target"][value="${index}"]`).checked = true;
      updateSelection();
      $('#generator-message').textContent='핵심 요약에서 선택한 논문입니다. 생성을 누르면 심층 분석을 시작합니다.';
    } else if (paperId) {
      $('#generator-message').textContent='이 논문의 연결된 PDF를 찾지 못했습니다. PDF 연결을 확인한 뒤 논문을 선택하세요.';
    }
    const paint = requests => {
      const entries = requests.filter(r=>r.kind===kind);
      const labels={requested:'이전 저장 요청 · 생성 버튼으로 시작',queued:'차례 대기',reading:'원문·그림 준비 중',generating:'Codex 작성 중',validating:'출처·필수 항목 검사 중',reviewing:'Codex 근거 검토 중',layout:'표·그림 배치 중',layout_review:'표·그림 근거·발췌 검토 중',held:'보류 · 검증 미통과',failed:'실행 실패',complete:'완료 · Codex 검토 통과 · 사람 미검토'};
      $('#generator-history').innerHTML = entries.length ? `<ul class="workflow-papers">${entries.map(r=>`<li><h4>${escape(r.title)}</h4><p>${escape(new Date(r.requestedAt).toLocaleString())} · ${escape(labels[r.status] || r.status)}</p>${r.error ? `<p role="alert">${escape(r.error)}</p>` : ''}${r.issues?.length ? `<ul>${r.issues.map(issue=>`<li>${escape(issue)}</li>`).join('')}</ul>` : ''}${r.status==='complete'?`<a class="button" href="#/paper/generated-${r.id}/summary">결과 보기 →</a>`:''}${['failed','held'].includes(r.status)?'<p>원인을 확인한 뒤 위 목록에서 해당 논문을 선택해 다시 생성할 수 있습니다.</p>':''}</li>`).join('')}</ul>` : '<p class="muted">저장된 요청이 없습니다.</p>';
    };
    paint(data.requests);
    clearInterval(generationPoll);
    generationPoll=setInterval(async()=>{
      if(location.hash!==hash) {clearInterval(generationPoll);return;}
      try {
        const response=await fetch('/api/generation-requests');
        if(!response.ok) throw new Error();
        const refreshed=await response.json();
        const paperResponse=await fetch('/api/papers');
        const paperData=await paperResponse.json();
        if(location.hash!==hash) return;
        papers=paperData.papers;
        paint(refreshed.requests);
        renderSidebar();
      } catch {if(location.hash===hash) $('#generator-message').textContent='진행 상태를 갱신하지 못했습니다. 서버 연결을 확인하세요.';}
    },3000);
    $('#generator-form').onsubmit = async event => {
      event.preventDefault();
      const keys = $$('input[name="target"]:checked').map(input=>data.targets[Number(input.value)].key);
      if (!keys.length) {$('#generator-message').textContent='논문을 선택하세요.';return;}
      if (keys.length>30) {$('#generator-message').textContent='한 번에 최대 30편까지 생성 요청할 수 있습니다. 선택을 줄여 주세요.';return;}
      const button = $('#generator-form button[type="submit"]');
      button.disabled = true;
      $('#generator-selection').disabled = true;
      try {
        const result = await fetch('/api/generation-requests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,keys})});
        const saved = await result.json();
        if (!result.ok) throw new Error(saved.error || '요청 저장에 실패했습니다.');
        if (location.hash !== hash) return;
        $('#generator-message').textContent='Codex 생성 요청을 접수했습니다. 아래에서 진행 상태를 확인하세요.';
        paint(saved.requests);
      } catch(error) {
        if (location.hash===hash) $('#generator-message').textContent=error.message;
      } finally {
        button.disabled=false;
        if (location.hash===hash) $('#generator-selection').disabled=false;
      }
    };
  } catch(error) {
    if (location.hash===hash) main.innerHTML=`${backButton()}<h1>${name}</h1><p role="alert">${escape(error.message)}</p><button class="button" id="generator-retry">다시 시도</button>`;
    if ($('#generator-retry')) $('#generator-retry').onclick=renderGenerator;
  }
}
