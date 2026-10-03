# 개발 인수인계

현재 범위·실행 방법은 README.md를 기준으로 합니다.

## 다음 논문 작성 시 필수 기준 (2026-10-02)

- `BRIEFING_GUIDELINES.md`의 **작성 순서와 기준 사례** 및 **완료 전 체크리스트**를 먼저 읽고 적용한다. 핵심 요약은 읽기 쉬운 문장형, 심층 분석은 AdaptiveFlow처럼 단계별 표·그림 중심이다. 탭만 맞춘 줄글 결과는 완료가 아니다.
- 기준 사례는 AdaptiveFlow의 `tabs` 전체, Sung, 생성 요청 8번의 `result.presentationTabs`이다. 검토용 원본 `sections`/`figures`는 보존한다.
- `codex_generation.py`는 매 작업에서 지침 전체를 읽어 초안 작성·독립 검토에 전달한다. 심층 분석은 근거 검토 후 `visual_generation.py`의 표·그림 배치 및 별도 검토를 거쳐 `presentationTabs`를 만든다. `layout` / `layout_review` 진행 상태를 표시하며, 편집 검증 실패는 보류한다. 브라우저 화면 확인은 별도로 수행한다.
- 화면은 `public/generated-results.js`에서 `presentationTabs`가 있으면 사용하고, 기존 `renderPaper`로 표시한다. 논문 8번 그림 발췌는 `public/assets/generated-8/`에 있다. 이 논문 전용 편집 스크립트를 다른 논문에 그대로 실행하지 않는다.

다음 개발: 사용자 제공 리뷰/원저와 RIS 목록을 작업 단위로 관리하고 Zotero PDF의 DOI·제목을 확인해 원본 경로를 연결합니다. PDF 복사는 기본으로 하지 않습니다. 요약·심층 분석 작성 기준은 BRIEFING_GUIDELINES.md를 유지합니다. 미구현 기능을 완료로 표시하지 않습니다.

이전 자동 수집·평가·회차·직접 다운로드 기능은 사용자 승인으로 삭제했습니다. 복원은 별도 요청이 있을 때만 진행합니다.

작업 관리 1단계 구현: workflow.py / public/workflow.js / data/workflows. Choi 제공 PDF 원본 경로·해시 확인, 관련 문헌 14편·RIS 2종·작성 상태를 한 화면에 표시. 현재 새 작업/요약 등록은 Codex의 로컬 JSON 편집을 통해 진행. Zotero 원저 PDF 폴더 매칭은 2026-10-02 구현했습니다.

PDF 연결 구현: pdf_links.py, server.py의 작업 scan/confirm/PDF 제공 API, workflow_pdf_links SQLite 테이블, public/workflow.js의 검사·후보 확인 UI. 현재 실제 검사 35개, Choi 14편 중 자동 연결 6·확인 필요 1·없음 7. 확인 필요 파일은 제목 일치/첫 페이지 DOI 없음으로 사용자 확인 대기. 다음은 연결한 원문 검토와 핵심 요약 작성이며 과학적 검토 완료로 표시하지 않습니다.

2026-10-02 생성 도구 분리: README의 “생성 도구와 요청 저장” 참조. 사용자가 앱에서 대상을 선택해 요청하고 Codex 채팅에서 처리를 시작하는 방식으로 확정. AI API 자동 실행 없음. 요청 테이블은 생성 종류와 원본 해시별 중복을 방지하며 서버 재시작 후 유지됨. 실제 작성·검토·결과 등록은 다음 처리 작업에서 수행해야 하며, 요청만으로 완료 표시하지 않음. 원본 PDF를 재확인하고 기존 작성 지침을 적용할 것.

2026-10-02 자동 생성 연결: 이전 채팅 수동 처리 방식 대신 명시적인 생성 버튼이 Codex ChatGPT 로그인 실행을 시작함. BRIEFING_GUIDELINES의 두 결과물 구분과 완료 기준, README의 Codex 버튼 생성 절을 따른다. 원문 텍스트/전체 페이지 이미지를 전달하고 별도 근거 검토를 수행한다. 생성본은 사람 미검토 표시. `.runtime/generation`의 그림은 완료 결과가 참조하므로 보존한다.
