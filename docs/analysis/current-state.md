# ForgeAI 현행 파악 (Current State Analysis)

> 기준: `docs/update` 브랜치 (`f8b4bf9`, 2026-06-16). main보다 앞선 유일한 브랜치이며 **실행 코드는 main과 바이트 단위 동일** (git diff로 확인 — 이 브랜치가 더한 것은 SECOM 데이터, 오프라인 스크립트, 문서뿐).
> 원칙: 코드가 진실. 확인 못 한 것은 "확인 불가"로 표시.

## 요약 — 중대 발견 3건

**1. 명령서의 기억과 코드가 다르다 (해소됨).** "SECOM 기반 + XGBoost 예측"은 사실이 아니다. 실제 파이프라인은 AI4I 데이터 위의 결정론 rule engine이고, SECOM은 파이프라인 밖의 실험 데이터, XGBoost는 오프라인 스크립트뿐이다. 리포의 ADR-001이 이 구도("AI4I 유지 + SECOM은 별도 실험")를 이미 명시적으로 결정해 놓았다. → 사용자 결정 **G1(c)** 신호 출처 중립 설계, **G2(a-1)** SECOM은 약신호 스트레스 테스트로 역할 재정의 (근거: `docs/experiments/secom-standard-remedies.md`).

**2. README가 링크한 ADR-008/009 파일이 없다.** README 8장이 비결정성 통제(008)와 에스컬레이션 정책(009)을 링크하고 신뢰성 지표 빈칸(`일관성 [___]%` 등)까지 잡아놨는데 파일이 결번이다. 이번 Task 2 산출물이 정확히 그 자리를 채운다.

**3. 정답 라벨이 LLM 프롬프트로 샌다 (분석 중 발견, D6).** CSV 파서가 정답을 `message`("Machine failure detected: TWF", `utils/csv_parser.py:100-101`)와 `tags["failure_types"]`(`130-131행`)에 심고, perception이 `log.model_dump()` 전체를 프롬프트에 넣는다. **배치/스트림 경로에서 LLM이 답안지를 보며 채점받는 구조** — 차단(ADR-009 D6) 전의 모든 배치 기반 측정치는 오염 표본이다.

---

## 1. 파이프라인 — 알람 1건이 지나가는 길

입구: `POST /api/v1/analyze` (`api/routes.py:35`) → `ForgePipeline.run()` (`pipeline/forge_pipeline.py:340`) → LangGraph 실행.

```
START → rule engine ─(SAFE)→ 끝 [조기 종료]
           │(WARNING/CRITICAL)
           ▼
      perception(LLM) ─(이상 없음)→ 끝   ← LLM이 결정론 판정을 뒤집는 유일한 지점
           │(이상 있음)
           ▼
   진단 + SOP 검색 (병렬)
           ▼
      조치계획(LLM) ◄──┐(REJECT & 재시도 남음)
           ▼          │
      검증(임베딩) ─────┘
           │(APPROVE/REVIEW or 소진)
           ▼
          끝 → PipelineResult
```

| 단계 | 담당 (경로) | 핵심 판단과 특이점 |
|---|---|---|
| 0. 입수 | `api/routes.py:35,59`, `utils/csv_parser.py`, `stream_simulator.py` | 판단 없음. correlation_id 생성·전파. **CSV 경로는 정답 라벨 누수 (요약 3)**. SECOM은 스키마 불일치로 이 입구 사용 불가 |
| 1. 전처리 | 없음 (라이브 경로) | 파생값은 판단 시점 인라인 계산 (`rule_engine.py:54,58`). 오프라인 스크립트에만 전처리 존재 |
| 2. 입구 판단 | `core/rule_engine.py:assess_risk()` (101행) | 순수 산술. 센서별 utilization ≥95%→CRITICAL, ≥85%→WARNING (`24-25행`); WARNING 2개→CRITICAL 승격 (`141행`); failure_type은 PWF>OSF>HDF>TWF 우선순위 단일 라벨, 가려진 모드는 triggered_failure_types 보존 (`70-97,156-164행`). SAFE면 조기 종료 (`forge_pipeline.py:275`) |
| 3. 알람 생성 | 독립 단계 없음 | alert 도구는 **mock** (`tools/sensor_tools.py:88` — dict 반환뿐, 발송 없음) |
| 4. perception | `agents/perception_agent.py` | rule engine 판정을 **받지 않고** 독립 판단 (프롬프트가 역할 분리 명시). "이상 없음"이면 파이프라인 종료 (`forge_pipeline.py:281`) — **CRITICAL도 LLM 한 마디에 소멸, 기록 없음 (→ ADR-009 D5)**. 실패 시 보수 폴백(이상 있음 간주) |
| 5. RCA 진단 | `agents/diagnostic_agent.py` | ReAct 루프 최대 5회. 입력 결함: "원본 센서값" 자리에 이상 목록 중복 (`70-71행`) — 원본 로그 미전달. **결과(DiagnosticResult)를 이후 누구도 소비 안 함** |
| 6. SOP 검색 | `agents/sop_rag_agent.py` | LLM이 쿼리 생성 → Chroma 벡터 검색 (`62-64행`), failure_type 메타 필터 + 부족 시 무필터 폴백. **relevance_score는 기록만 되고 어떤 판단에도 미사용** |
| 7. 조치계획 | `agents/action_plan_agent.py` | escalation_required를 **LLM이 자율 판단** (프롬프트 규칙뿐, 코드 검증 없음). 실패 시 빈 계획 + escalation=True |
| 8. 검증 | `agents/hallucination_validator.py` | step↔SOP 임베딩 코사인. 판정 경계 0.85/0.60 **하드코딩** (`90-95행`), step 기준 0.75는 config — 이원화. **빈 계획은 만점 통과** (`39-49행`). REJECT 재시도 최대 2회 (`config.py:36`), 소진 시 REJECT 그대로 종료 — **후속 처리 없음 (→ ADR-009가 닫음)** |
| 9. 출력 | `forge_pipeline.py:37-46`, `routes.py:46-50` | PipelineResult JSON + REJECT/REVIEW 시 X-Plan-Status 헤더. 소비자: Streamlit 대시보드(사람), C++ 브릿지(별도 호출, dry-run 전용 `bridge.py:66-67`) |

부속: `POST /api/v1/diagnose` 자연어 진단 파이프라인 (직선, 분기 없음).

## 2. Q1~Q4 답변

**Q1. 확신도 신호는 어디에 있나.** 결정론: risk_level, 센서별 utilization_pct(`rule_engine.py:112`, 가장 세밀), triggered_failure_types. 반결정론: risk_index(산식 결정론/인자 LLM). 연속값: relevance_score(**미사용**), grounding_score(유일하게 이미 라우팅에 사용). LLM 자율: severity, escalation_required. **없는 것**: 라이브 ML 확률(오프라인 스크립트 2종뿐), 보정 코드(ADR-004 "실험 후 결정" 상태), SECOM 확률은 실측상 사용 불가(Recall 0.000 — 실험 기록 참조). ADR-013이 확률 진입 자리(`ml_predictor`, 미구현)를 스펙으로만 예약.

**Q2. 최종 출력은 누구에게, 에스컬레이션은 있나.** HTTP JSON → 대시보드(사람 열람) / 선택적 브릿지(dry-run). 자동 통지 채널 없음. 에스컬레이션 조각 4곳이 서로 미연결: LLM 플래그, X-Plan-Status 헤더(수신 처리 없음), 단계 실패 폴백, rule engine 권고 문구. README 8장은 3분기 서사(자동/사람/운영자)를 이미 서술했으나 코드는 라벨+헤더까지만 — **ADR-009는 백지 설계가 아니라 이 서사의 코드 승격**.

**Q3. 같은 입력 → 같은 출력인가.** 아니다. temperature=0.1 + seed 없음(`core/langchain_client.py:16` — README의 "temperature=0" 주장과 불일치). 흔들림이 연쇄 증폭: LLM 쿼리→검색 결과→계획→점수→판정. ReAct 루프는 도구 호출 자체가 비결정. 결정론인 것: rule engine, 임베딩, 코사인, 브릿지 매핑. 구조 요약: **입구와 검증 산식은 결정론, 중간 언어 처리 전체가 비결정론** (→ ADR-008).

**Q4. 계측은 어디에 붙이나.** Langfuse가 절반 구현(기본 꺼짐): trace 생성(`forge_pipeline.py:346-353`) + LLM generation 자동 기록(`agents/base.py:57-69`). 공백 = 훅 포인트: ① rule engine 판단 ② 벡터 검색 결과 ③ 검증 코사인 ④ 분기 이유(`_route_after_*` 3곳 — 에스컬레이션 레이어의 개입 지점이기도 함). 그리고 **로그 버그**: `core/logging.py:14-17`의 dict 분기는 도달 불가 dead code라 구조화 로그가 repr 통문자열로 뭉개짐 (재현 확인) — 지표 산출의 선행 수정 대상. ADR-007이 "Langfuse만으로는 부족"(장기 감사, 오프라인)을 이미 문서화.

## 3. 부록 — 기타 divergence·결함 (한 줄씩)

| # | 내용 (근거) |
|---|---|
| B-1 | README "temperature=0" vs 코드 0.1 (`langchain_client.py:16`) |
| B-2 | README "재시도 3회" vs config 2회 — 총 시도 3회로 읽으면 정합, 표현 모호 |
| B-5 | ADR-013 참조 코드(`ml_predictor` 등) 전부 미구현으로 정직 표기 — 실재로 착각 금지 |
| B-6 | ~~`test.py`가 `secom.data`를 찾으나 실제는 `secom.csv` — 실행 불가~~ → **해소됨**: test.py 삭제 (탐색 스니펫이 secom-standard-remedies.md §0 및 secom_baseline_classifier.py 도큐스트링에 완전 대체됨) |
| C-1 | `agents/risk_assessment_agent.py` dead code (rule engine 대체, ADR-005 기록) |
| C-2 | README 그림과 달리 진단·SOP는 병렬 + DiagnosticResult 미소비 |
| C-3 | 진단 입력의 이상 목록 중복 직렬화 (`diagnostic_agent.py:70-71`) |
| C-4 | 로깅 dead branch — 구조화 손실 (Q4 참조) |
| C-5 | 검증 임계값 이원화 (config 0.75 vs 하드코딩 0.85/0.60) |
| C-6 | 빈 계획 만점 통과 (`hallucination_validator.py:39-49`) |

## 4. 확인 불가

런타임 실측치 전부(Ollama 필요), ChromaDB 인제스트 상태, Langfuse 실사용 여부, C++ 빌드 산출물, ADR-008/009의 미푸시 로컬 존재 가능성.

## 5. 상태

- Task 1 완료. HARD STOP의 G1/G2는 사용자 결정으로 해소 (G1=c, G2=a-1).
- Task 2 산출물: `docs/adr/ADR-008`, `docs/adr/ADR-009` — 핵심 결정 3건(P·D1·D5) 대기, 나머지 잠정 채택.
