# 시범 12편 상세 브리핑 검증

2026-09-23 기준. [BRIEFING_GUIDELINES.md](BRIEFING_GUIDELINES.md)에 따라 기존 브리핑의 근거·출처·그림 연결과 표시 상태를 검증했다. 현재 12편은 모두 **`partial` — 일부 검증 · 초안**이다. 관련 본문·그림을 확인한 논문도 전체 원문·SI와 모든 수치를 검증 완료한 것은 아니다.

상태의 기준은 [data/brief-reviews.json](data/brief-reviews.json)이다. `acquired`는 이번 로컬 검증에 사용 가능한 자료의 확보 여부, `checked`는 실제 대조한 범위다. 과거 브라우저 열람·검토 메모와 현재 로컬 원문 재대조를 구분한다. 특히 기존 `evidenceStatus: fulltext`는 현재 검토 완료를 보장하지 않는다.

## 논문별 확인 범위

아래의 ‘본문 확인’은 브리핑 관련 절·표의 확인을 뜻한다. SI 파일 확보, 그림 표시 성공, 원문을 여는 동작만으로 검토 완료로 올리지 않는다.

| 논문 | 확보 자료 | 실제 확인 범위 | 미확인·보류 | 주요 교정·감사 결과 |
| --- | --- | --- | --- | --- |
| [Dockformer](data/briefs/dd6010ad6b2843cd956439aeb5e43554.json) | 초록, 저자 연구실 도식 | 초록, 도식 일부 | 출판본 본문·그림·SI | 초록에서 직접 확인한 값과 과거 검토 메모의 수치를 구분. 연구실 도식을 출판본 Figure로 간주하지 않음. |
| [FEP·ML 입력 구조 비교](data/briefs/196c61d3c3ed44c6baa4e201eda0799d.json) | 초록, Figures 1·2·3·5 | 초록, 확보 그림의 주요 비교 | 본문·SI의 세부 조건, 원문 표기 차이의 원인 | AUC의 표준편차와 곡선 신뢰구간을 구분하고 대표 baseline의 비교 묶음을 명시. 확보한 원본 그림을 연결. |
| [GSK3227634](data/briefs/0f6663d4752b4459855dfd8b133db44f.json) | 본문, 그림, SI | 관련 본문·표, Figures 2–7, SI Fig. S2·Tables S12·S13 | 나머지 SI, 원자료 독립 재분석 | 직접 상호작용 표적과 하위 효소 readout을 구분. SI에서 실제 읽은 범위를 명시하고 원문 단위 불일치를 보존. |
| [KRAS macrocycle](data/briefs/62c2bdb4c9d4412f9b9685cb2d7ba408.json) | 초록, Figures 2–6, Tables 1·3 | 초록, 확보 도판의 비교·표기 | 로컬 본문·SI, PK·MetID 전체 표, PDB 원자료 매핑 | 세포 활성 비교 대상을 명시하고 그림의 화합물 번호를 구분. 과거 본문 메모에서 온 수치는 이번 원문 미대조로 표시. |
| [MetaVision-SPR](data/briefs/39a312b9f37c4602bbd4c5c00953e02a.json) | 초록 | 초록의 주요 수치·주장 범위 | 본문·원본 그림·SI | 초록 기반 설명을 유지. 작성한 흐름 SVG를 원문 Figure나 본문 확인의 근거로 사용하지 않음. |
| [MTS 전기화학 판독](data/briefs/f73c383248d54b4e8c4b0f76337ffc96.json) | 본문, 그림, SI | 관련 본문·그림 | SI 미검토, 원문 내부 상충의 확정 해소 | 파일 순번 때문에 잘못 연결된 Figure 3·7·8을 수정. 실제 패널·축과 본문/caption의 차이, 표시된 유의차와 단위 불일치를 구분. |
| [Population PK](data/briefs/6f209faaaaf1425198eac5375fd141ba.json) | 본문, 그림 | 주요 표·수치, Figures 1–4 | SI 미확보, 추가 모델 분석·재실행 | 집계 단위 차이를 표시. Figures 3·4의 남색 사전 예측과 청록색 관측 후 갱신 예측 범례를 설명. |
| [Zavegepant PBPK](data/briefs/b6585588759e4eee883f24d82603f2b1.json) | 본문, 그림, SI | 주요 표·수치, Figures 1·3·4 | SI 입력·결과 표 미검토 | 모델 조정과 검증을 구분. 원문 caption을 보존하면서 Cmax 약어 설명의 오류를 한국어 설명에 명시. |
| [NCS-1](data/briefs/3303517f651d4cd5b59a8b62c3f4ffb6.json) | 본문, 그림, SI | 주요 결과 일부, Figures 5·7·8 | 전체 Methods·세부 수치·SI | 이번 감사의 새 오류 지적은 없음. 확인한 주요 결과와 미검토 범위를 분리해 표시. |
| [LysRS](data/briefs/c3a5f89a860d4488b09a0a3630f51617.json) | 본문, 그림, SI | 주요 결과 일부, Figures 1–3 | 전체 Methods·세부 수치·SI | 독성이 관찰된 농도를 CC50로 잘못 표현한 부분을 수정. |
| [Protea-Tac](data/briefs/f575f73dd8934f93bc61c574e7fdd5a5.json) | 본문, 그림, SI | 주요 결과 일부, Figures 1·3·6 | 전체 Methods·SI, 모든 통계의 독립 재계산 | Figure 6A의 종양 사진을 평가 흐름도로 잘못 설명한 부분을 수정하고 다른 패널과 구분. |
| [CRB-701](data/briefs/18561cf87e6e4e7e8d09f713d34b13c3.json) | 본문, 그림, SI | 주요 결과 일부, Figures 1·3·4 | 전체 Methods·세부 수치·SI | Figure 4C의 축 단위와 표의 단위를 구분하고 Figure 3D의 일정 표기 차이를 명시. |

## 감사 기록과 남은 항목

감사 기록은 29건이며 26건에 교정·해결 내역이 있다. ‘해결’은 확인된 표현·연결 오류를 바로잡았다는 의미다. 원문의 상충을 임의로 하나의 정답으로 통일하거나, 미확보 자료를 추가 검증했다는 뜻은 아니다. 표에 남긴 미확인 범위는 후속 확인 대상으로 유지한다.

검토 기록에는 범위별 보류 13건이 있으며 모두 `source` — 자료 미확보 또는 미검토 — 사유다. `safety`와는 별도 필드로 구분한다. 실제로 제공받지 않은 안전 차단의 내부 판정 원인은 추정하지 않았다.

상세 화면에는 간략한 상태와 기본적으로 접힌 **자료 확보·검토 범위**가 표시된다. 전체 `held` 상태일 때에는 상세 본문을 보류 안내로 대체하며 카드와 읽음·저장·메모는 유지한다. 현재 12편을 전체 `held`로 분류한 것은 아니다.

## 구현 검증

- 최종 unittest **82개 통과**. ID·탭·출처, 그림 번호와 파일 연결, 이미지/PDF 형식·HTTP 응답, 확보와 검토의 구분, 보류 처리, 재시작 후 개인 기록 보존을 검증했다. JavaScript·Python 구문 검사와 diff 공백 검사도 통과했다.
- 실제 화면에서 14개 카드와 신규 12편×4개 본문 탭을 확인했다. 빈 패널·그림 로드 오류가 없었으며 검토 범위 펼치기, 그림 확대, 뒤로가기와 검색 복원, 390px 화면을 확인했다.
- 신규 본문 8개·SI 7개를 포함해 총 18문서·458페이지가 이미지 뷰어에 등록됐다. 신규 15문서의 뷰어 연결, MTS 본문·SI 첫 페이지 표시와 본문 페이지 이동을 확인했다. 전체 페이지의 시각 검토나 과학적 내용 검토를 수행한 것은 아니다.
- 별도 DB 복사본으로 저장·재시작을 검증했고 실제 사용자 DB의 7개 테이블 내용은 작업 전과 동일했다. 자세한 실행 범위는 [VALIDATION.md](VALIDATION.md)에 기록했다.

근거 파일: `.runtime/verification-audit.json`, `verification-chemistry.json`, `verification-mechanisms.json`, `verification-translation.json`, `verification-tests-final.log`, `verification-ui-results.json`, `verification-db-preservation.json`. 이 실행 로그는 로컬 기록이며 Git에서 제외된다. 지속적으로 사용하는 논문별 상태는 `data/brief-reviews.json`에 보존한다.

다음 검토에서는 미확보 원문·SI와 이미 확보했으나 읽지 않은 SI를 구분해 확인하고, 실제 대조한 항목만 상태에 반영한다. 새 후보의 상시 생성·정기 수집·기간별 동향 비교는 이번 검증의 완료 항목이 아니다.
