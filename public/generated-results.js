function generatedCard(paper) {
  if (paper.generatedKind==='summary') {
    const r=paper.generatedReport;
    const sections=r.compactSections || r.sections;
    const figures=r.compactFigures || r.figures;
    const base=`/api/generated/${paper.requestId}`;
    const points=title=>sections.find(s=>s.title===title)?.points || [];
    const text=title=>points(title).map(p=>escape(p.text)).join('<br>');
    const figure=figures[0];
    const g=r.glance;
    const glance=g && {type:escape(g.type),oneLiner:escape(g.oneLiner),problem:escape(g.problem),conclusion:escape(g.conclusion),
      steps:g.steps.map(s=>({label:escape(s.label),text:escape(s.text)})),
      keyResults:g.keyResults.map(k=>({value:escape(k.value),label:escape(k.label),context:escape(k.context),source:{label:`PDF ${k.page}쪽 ↗`,url:`${base}/source.pdf#page=${k.page}`}}))};
    return renderCard({...paper,
      metadata:{...paper.metadata,pdfUrl:`${base}/source.pdf`,peerReview:'원문 기반'},
      card:{glance,purpose:text('연구 질문'),
        pairs:points('방법과 핵심 결과').map(p=>{
          const separator=p.text.indexOf(': ');
          const hasLabel=separator>0 && separator<45;
          return {label:hasLabel ? escape(p.text.slice(0,separator)) : '방법과 검증 결과',text:escape(hasLabel ? p.text.slice(separator+2) : p.text),source:{label:`${p.basis} · PDF ${p.page}쪽`,url:`${base}/source.pdf#page=${p.page}`}};
        }),
        significance:text('연구적 의미'),application:text('적용 관점'),limits:text('주요 한계'),
        image:figure ? {src:`${base}/page-${figure.page}.png`,alt:figure.label,title:figure.label,caption:escape(figure.interpretation),source:{label:`그림 포함 원문 페이지 · PDF ${figure.page}쪽`,url:`${base}/source.pdf#page=${figure.page}`}} : null}});
  }
  const name=paper.generatedKind==='summary'?'핵심 요약':'심층 분석';
  return `<article class="paper-card"><header class="card-heading"><div class="card-status"><span>${name} · Codex 근거 검토 통과 · 사람 미검토</span><div data-state-buttons="${paper.id}">${stateButtons(paper)}</div></div><a href="#/paper/${paper.id}/summary"><h2>${escape(paper.metadata.title)}</h2></a><p>${escape(paper.metadata.translation)}</p></header><div class="card-body"><p>${escape(paper.card.purpose)}</p><a class="button primary" href="#/paper/${paper.id}/summary">${name} 보기 →</a></div></article>`;
}

function generatedAnalysisLayout(paper) {
  const r=paper.generatedReport;
  const base=`/api/generated/${paper.requestId}`;
  const points=title=>r.sections.find(s=>s.title===title)?.points || [];
  const pointBlocks=p=>[
    {type:'paragraph',text:escape(p.text)},
    {type:'details',title:`근거 · ${escape(p.basis)} · PDF ${p.page}쪽`,blocks:[
      {type:'paragraph',text:escape(p.quote)},
      {type:'links',items:[{label:'원문 보기 ↗',url:`${base}/source.pdf#page=${p.page}`}]}]}
  ];
  const section=title=>({title,blocks:points(title).flatMap(pointBlocks)});
  const figureBlock=f=>({type:'figure',title:f.label,description:'그림이 포함된 원문 페이지',image:`${base}/page-${f.page}.png`,alt:f.label,
    explanation:[{label:'그림 읽기',text:escape(f.interpretation)}],source:{label:`PDF ${f.page}쪽 ↗`,url:`${base}/source.pdf#page=${f.page}`}});
  const summary= papers.find(p=>p.generatedKind==='summary' && p.metadata.doi && p.metadata.doi.toLowerCase()===paper.metadata.doi.toLowerCase())?.generatedReport;
  const summarySections=summary?.compactSections || summary?.sections;
  const briefPoints=title=>summarySections?.find(s=>s.title===title)?.points;
  const purpose=briefPoints('연구 질문') || points('연구 질문과 기존 연구').slice(0,1);
  const results=briefPoints('방법과 핵심 결과') || points('결과와 통계').slice(0,3);
  const pairs=results.map(p=>{
    const split=p.text.indexOf(': ');
    return {label:split>0 && split<50 ? escape(p.text.slice(0,split)) : '주요 결과',text:escape(split>0 && split<50 ? p.text.slice(split+2) : p.text)+` <a href="${base}/source.pdf#page=${p.page}">PDF ${p.page}쪽 ↗</a>`};
  });
  const flow=r.figures.find(f=>f.label==='Figure 1');
  return {...paper,generatedReport:null,
    metadata:{...paper.metadata,pdfUrl:`${base}/source.pdf`,availability:'제공 PDF 기반 · Codex 근거 검토 통과 · 사람 미검토',reviewedAt:'Codex 근거 검토 통과'},
    tabs:r.presentationTabs || {
      summary:[{title:'연구 목적',blocks:purpose.flatMap(pointBlocks)},
        ...(flow ? [{title:'연구 흐름',blocks:[figureBlock(flow)]}] : []),
        {title:'주요 결과',blocks:[{type:'pairs',items:pairs}]}],
      overview:['연구 질문과 기존 연구','실험 설계 논리','결과와 통계','주장과 근거'].map(section),
      methods:[section('방법·조건·대조군'),section('적용 범위')],
      evidence:[{title:'그림·표별 해석',blocks:r.figures.map(figureBlock)},section('한계와 미해결 질문'),
        {title:'자료 확인 범위',blocks:[{type:'details',title:'확인한 자료와 미확인 사항',blocks:[
          {type:'paragraph',text:`본문: PDF ${r.readPages.join(', ')}쪽 · 그림: PDF ${r.visualPages.join(', ')}쪽`},
          {type:'list',items:r.unverified.map(escape)}]}]}],
      memo:[section('적용 범위')]
    }};
}

function renderGeneratedPaper(paper, tab) {
  currentId=paper.id;
  if (paper.generatedKind==='summary') {
    document.title=`핵심 요약 · ${paper.metadata.title}`;
    main.innerHTML=`${backButton()}<div class="library-intro"><h1>핵심 요약</h1><a class="button" href="#/discover">핵심 요약 라이브러리 →</a></div>${generatedCard(paper)}`;
    renderSidebar();
    return;
  }
  renderPaper(generatedAnalysisLayout(paper),tab);
}
