# ForgeAI 현행 파악 (Current State Analysis) — rev.3 (쉬운 문장 버전)

> **무엇을 기준으로 분석했나:** GitHub의 `docs/update` 브랜치, 마지막 커밋 `f8b4bf9` (2026-06-16)
> **왜 이 브랜치인가:** 원격 브랜치는 3개다 (main, docs/update, task/1-rule-engine). task/1은 main에 이미 합쳐진 과거 상태다. main보다 앞선 브랜치는 docs/update 하나뿐이고, 여기에 SECOM 추가와 데이터 폴더 개편(refactor) 커밋이 들어 있다. 그래서 이것을 "리팩토링 브랜치"로 판단했다.
> **원칙:** 코드가 진실이다. 코드에서 확인 못 한 것은 "확인 불가"라고 적는다.

**먼저 알아야 할 사실 하나:** 이 브랜치와 main의 **실행 코드는 완전히 똑같다.** git diff로 확인했다 (pipeline, agents, core, api 등 코드 폴더 전부 → 변경 0건). 이 브랜치가 새로 더한 것은 세 가지뿐이다: ① SECOM 데이터 파일, ② 오프라인 분석 스크립트, ③ 문서 (ADR 11개 + README 전면 개정). 그래서 아래 파이프라인 분석은 main에도 그대로 적용된다.

---

## ⚠️ 잠깐 멈춤 (HARD STOP): 기억과 코드가 다르다

작업 명령서에는 "SECOM 데이터셋 기반, XGBoost가 예측을 담당"이라고 적혀 있다. 실제 코드는 다르다.

| 명령서의 기억 | 실제 |
|---|---|
| SECOM 기반 FDC | SECOM 데이터는 **있다.** 하지만 **파이프라인 밖에** 있다. 데이터 파일(`data/raw/secom/`)과 오프라인 실험 스크립트(`scripts/secom_baseline_classifier.py`)만 존재한다. 게다가 이 리포의 문서 **ADR-001이 직접 이렇게 결정해 놓았다: "파이프라인은 AI4I 데이터로 유지하고, SECOM은 별도의 ML 실험용으로만 쓴다."** 즉 "SECOM 기반"이라는 기억은 리포 자신의 기록과도 어긋난다 |
| XGBoost가 예측 | 실시간 파이프라인에 **ML 모델이 하나도 없다.** 입구에서 판단하는 것은 if문 기반의 rule engine이다 (`core/rule_engine.py`). XGBoost는 오프라인 스크립트에서만 돌아간다. 다만 이 브랜치에서 xgboost가 정식 의존성으로 올라갔고, ADR-013에 "나중에 이렇게 연결하겠다"는 설계(`core/ml_predictor.py`, 아직 미구현)가 적혀 있다. 요약하면 XGBoost 예측은 **과거가 아니라 계획된 미래**다 |
| LLM triage | "LLM이 triage한다"는 단계는 없다. 분류(triage)에 해당하는 일은 rule engine이 결정론적으로 한다. LLM은 그 다음 단계(이상 해석)부터 등장한다 |

**Task 2에 아주 중요한 발견:** 새 README의 8장("에이전트 운영 안정성")이 **ADR-008(비결정성 제어)과 ADR-009(에스컬레이션 정책)라는 문서를 링크하고 있는데, 이 두 파일이 실제로는 없다.** ADR 폴더에는 11개 파일이 있고 008과 009만 빠져 있다. 신뢰성 지표 자리도 빈칸이다 (`일관성 [___]%`, `자동화율 [___]%`). **이번 Task 2가 하려는 일이 정확히 이 빈자리를 채우는 일이다.** 리포가 이미 자리를 예약해 둔 셈이다.

Task 2로 가기 전에 사용자가 정해야 할 갈림길 2개:

- **G1. 확신도 신호를 무엇으로 할 것인가의 전제.** 선택지는 3개다. (a) 지금 코드에 있는 신호만 쓴다 / (b) XGBoost를 실시간 파이프라인에 먼저 연결한다고 전제하고 설계한다 / (c) 둘 다 되도록 설계한다. 참고: 확률 보정(calibration)은 ADR-004에서 "실험 후 결정"으로 미뤄져 있고, SECOM에서 XGBoost 성적은 불량 Recall 0.000이라(하나도 못 잡음) 지금은 신호로 쓸 수 없다.
- **G2. 검증을 어떤 데이터로 할 것인가.** 명령서는 "SECOM 테스트셋"으로 검증하라고 했다. 그런데 LLM 파이프라인은 AI4I에서만 돌아간다. SECOM은 센서 이름도, rule engine 임계값도, SOP 문서와의 연결(failure_type)도 전부 없어서 지금 구조로는 검증 자체가 불가능하다. AI4I 기준으로 바꿀지, SECOM 연결을 별도 선행 작업으로 뺄지 결정이 필요하다.

---

## 1. 파이프라인 매핑 — 알람 1건이 지나가는 길

전체 입구: `POST /api/v1/analyze` (`api/routes.py:35`) → `ForgePipeline.run()` (`pipeline/forge_pipeline.py:340`) → LangGraph 그래프 실행.

그래프 모양 (`forge_pipeline.py:303-330`):

```
START → rule engine 판단 ─(SAFE면)→ 끝 [조기 종료, LLM 호출 0회]
              │(WARNING/CRITICAL이면)
              ▼
      perception (LLM 이상탐지) ─(이상 없다고 하면)→ 끝
              │(이상 있다고 하면)
              ▼
   진단(diagnostic) + SOP 검색 ← 두 개를 동시에(병렬) 실행
              ▼
      조치계획 생성 (LLM) ◄──┐
              ▼             │(REJECT이고 재시도 남았으면 다시)
      검증 (validator) ──────┘
              │(APPROVE/REVIEW이거나 재시도 소진)
              ▼
             끝 → PipelineResult 반환
```

### 단계 0. 센서 데이터가 들어온다

- **어떻게:** 입구가 3개다.
  - 단건: `/api/v1/analyze`에 `EquipmentLog` JSON을 직접 보냄 (`api/routes.py:35`)
  - 배치: `/api/v1/analyze/csv`에 AI4I CSV를 올리면 행마다 EquipmentLog로 바꿔서 처리 (`utils/csv_parser.py`)
  - 리플레이: `stream_simulator.py`가 CSV를 한 줄씩 재생하면서 "고장 며칠 전에 경보가 떴나(lead time)"와 오경보 수를 잰다
- **들어가고 나오는 것:** `EquipmentLog` (`models/equipment_log.py`) = 설비ID, 시각, 센서값 목록(sensor_id, 단위, 값), 메시지, 태그.
- **판단:** 없다. 파싱만 한다.
- **기록:** correlation_id(추적용 ID)가 여기서 만들어져 끝까지 따라간다 (`routes.py:36`).
- **참고:** SECOM 데이터는 이 입구로 못 들어온다. SECOM은 이름 없는 590개 숫자 컬럼이라 센서ID 체계, rule engine 임계값, SOP 연결이 전부 맞지 않는다. 로더 코드도 없다.

### 단계 1. 전처리/피처

- **실시간 경로에는 이 단계가 없다.** 센서 원본 값이 그대로 rule engine과 LLM 프롬프트에 들어간다. 파생값(전력 = 토크×회전수 등)은 판단하는 그 자리에서 즉석 계산한다 (`rule_engine.py:54, 58`).
- **오프라인에는 있다:** SECOM 스크립트가 결측 많은 컬럼 제거 → 상수 컬럼 제거 → 중앙값 채우기 → 시간순 8:2 분할을 한다. ADR-013은 "이 전처리를 나중에 서빙과 똑같이 맞추자"는 계획을 적어 놨지만 아직 코드는 없다.

### 단계 2. 입구 판단 — rule engine (명령서가 "XGBoost 예측"이라고 기억한 자리)

- **누가:** `core/rule_engine.py:assess_risk()` (101행). LLM도 ML도 없다. 순수 산수다. 수 ms 안에 끝난다.
- **나오는 것:** `RiskAssessment` = risk_level(SAFE/WARNING/CRITICAL), failure_type(TWF/HDF/PWF/OSF/NONE), **triggered_failure_types(동시에 걸린 고장 모드 전부)**, 센서별 위험도(utilization_pct), 요약문, 권고 조치.
- **판단 규칙 (전부 코드에 박힌 고정 숫자):**
  - 센서마다 "정상 범위의 몇 %까지 찼나"를 계산. 95% 이상이면 CRITICAL, 85% 이상이면 WARNING (`rule_engine.py:24-25`)
  - 공구 마모 200분 초과 → 따로 WARNING (`21행`)
  - WARNING이 2개 이상 겹치면 CRITICAL로 승격 (`141행`)
  - 고장 모드는 위험한 순서대로 하나만 고른다: PWF(전력 이상) > OSF(과부하) > HDF(방열 불량) > TWF(마모). 여러 개가 동시에 걸리면 제일 위험한 것만 표시하고, 가려진 것들은 triggered_failure_types에 남기고 경고 로그를 찍는다 (`70-97행, 156-164행`)
  - 개별 센서는 다 정상인데 조합 조건(고장 모드)만 걸린 경우, SAFE를 WARNING으로 올린다 (`152-154행`) — 과거 버그 수정의 흔적 (docs/decisions.md 버그 ①)
- **기록:** `pipeline_stage: 01_분류` 로그는 남는다. **그런데 Langfuse 추적(trace)에는 이 단계가 안 남는다** — LLM 호출만 계측하기 때문.
- **분기:** SAFE면 여기서 끝 (`forge_pipeline.py:275`). LLM 호출 4번을 아낀다.
- **문서 근거:** ADR-005(채택됨)가 이 역할 분담을 명문화했다 — "숫자 비교와 분류는 rule engine, 언어 이해가 필요한 것만 LLM."

### 단계 3. 알람 생성

- **독립된 "알람 생성" 단계는 없다.** 알람 비슷한 것이 세 군데에 흩어져 있다:
  - RiskAssessment 자체 (권고 조치 문구 포함)
  - 진단 에이전트가 부르는 `alert_maintenance_team` 도구 — **가짜(mock)다.** alert_id를 만들어 돌려줄 뿐 실제로 아무데도 발송하지 않는다 (`tools/sensor_tools.py:88`)
  - 조치계획의 escalation_required 플래그 (LLM이 정함)

### 단계 4. PerceptionAgent — LLM이 처음 등장하는 곳 (명령서의 "LLM triage" 자리)

- **누가:** `agents/perception_agent.py`. 기본 모델 qwen2.5:7b에게 로그 JSON을 주고 "이상이 있는지" JSON으로 답하게 한다.
- **나오는 것:** `AnomalyReport` = has_anomaly(이상 유무), 이상 목록(센서, 관측값, 심각도 LOW~CRITICAL, 설명), 요약.
- **중요한 점 1:** rule engine이 판단한 failure_type과 risk_level을 **이 에이전트에게 알려주지 않는다.** 독립적으로 다시 판단한다.
- **중요한 점 2 (가장 큰 판단 구멍):** LLM이 "이상 없음"이라고 하면 파이프라인이 그냥 끝난다 (`forge_pipeline.py:281`). **즉 rule engine이 CRITICAL이라고 해도 LLM 한 마디로 뒤집힌다. LLM이 결정론 판단에 거부권을 가진 유일한 지점이다.**
- **에러 대비:** LLM 호출이 실패하면 "이상 있음"으로 간주하고 계속 진행한다 (보수적 폴백, `forge_pipeline.py:107-122`).

### 단계 5. RCA (원인 진단) — DiagnosticAgent

- **누가:** `agents/diagnostic_agent.py`. LLM에게 도구 3개를 쥐여주고(임계값 조회, 위험지수 계산, 정비팀 알림) 최대 5번까지 도구를 부르게 하는 ReAct 루프.
- **나오는 것:** `DiagnosticResult` = risk_index(0~100), 해석, 도구 호출 기록 전체, 요약문.
- **주의 (코드 결함):** LLM에게 주는 입력에서 "원본 센서 값"이라고 적힌 자리에 실제로는 이상 목록을 한 번 더 복사해 넣는다 (`diagnostic_agent.py:70-71`). **그래서 원본 로그의 전체 센서 값은 진단 에이전트가 볼 수 없다.** perception이 이상으로 안 잡은 센서 값이 필요하면 LLM이 추측해야 한다.
- **더 중요한 사실:** **진단 결과를 그 다음 단계 누구도 안 쓴다.** 조치계획은 이상 리포트와 SOP 검색 결과만 받는다. 진단 결과는 최종 응답에 첨부만 된다.

### 단계 6. SOP 검색 — SOPRAGAgent

- **누가:** `agents/sop_rag_agent.py`. 두 단계로 움직인다: ① LLM이 검색어를 만든다 → ② ChromaDB에서 벡터 검색을 한다 (유사도 점수 포함, `62-64행`).
- **나오는 것:** `SOPContext` = 사용한 검색어, 찾은 조각들(chunk_id, 문서명, 본문, **relevance_score 유사도 점수**).
- **판단:** failure_type이 있으면 그 고장 모드의 SOP만 걸러서 검색한다. 결과가 모자라면 필터 없이 다시 검색한다 (폴백, `67-71행`). 상위 5개(top-k)를 가져온다.
- **중요한 점:** **유사도 점수가 낮아도 거른다는 판단이 없다.** 점수가 몇 점이든 상위 5개가 그대로 다음 단계로 간다. 점수는 기록만 된다.
- SOP 원본은 `data/sop_docs/`의 md 파일 5개 (고장 모드별 1개). "원본 파일과 벡터DB를 분리해서 임베딩 모델을 갈아끼울 수 있게 한다"는 원칙은 ADR-006(채택)에 있고, 재인덱싱 스크립트 `scripts/reindex.sh`도 실제로 있다.

### 단계 7. 조치계획 생성 — ActionPlanAgent

- **누가:** `agents/action_plan_agent.py`. 이상 리포트 + SOP 조각들 + 고장 모드별 추가 지침을 주고 계획을 JSON으로 받는다.
- **나오는 것:** `ActionPlan` = 단계 목록(할 일, 담당 역할, 우선순위 P1~P3, 예상 시간, 근거 SOP chunk_id) + **escalation_required(사람 개입 필요 여부) + 이유**.
- **중요한 점:** escalation_required를 **LLM이 스스로 정한다.** 프롬프트에 규칙이 적혀 있을 뿐("CRITICAL이거나 전원/안전 관련이면 true", `prompts/action_plan_v1.py:35`), 코드가 검증하지 않는다.
- **에러 대비:** 생성 실패 시 빈 계획 + escalation_required=True로 처리.

### 단계 8. 검증 — HallucinationValidator

- **누가:** `agents/hallucination_validator.py`. 계획의 각 단계 문장을 임베딩해서, 검색된 SOP 조각 임베딩과 코사인 유사도를 잰다. 즉 "이 조치가 SOP에 근거하는가"를 숫자로 확인한다. LLM은 REJECT일 때 이유 설명을 쓸 때만 쓴다.
- **나오는 것:** `ValidationResult` = 전체 근거 점수(overall_grounding_score), 단계별 점수, 근거 없는 단계 목록, **판정(APPROVE/REVIEW/REJECT)**.
- **판단 기준이 세 겹이다:**
  - 단계별 "근거 있음" 기준: 점수 ≥ 0.75 (환경변수로 조정 가능, `core/config.py:24`)
  - 판정 기준: 전체 점수 ≥0.85 → APPROVE, ≥0.60 → REVIEW, 그 밑 → REJECT (`90-95행`, **이건 코드에 박혀 있어 조정 불가**)
  - 계획이 비어 있으면 무조건 APPROVE에 점수 1.0 (`39-49행`) — **빈 계획이 검증을 그냥 통과하는 구멍**
- **분기:** REJECT이고 재시도가 남았으면(기본 최대 2회, `config.py:36`) 계획 생성으로 돌아간다. 재시도를 다 쓰면 **REJECT 상태 그대로 끝난다. 그 이후의 처리는 없다.**

### 단계 9. 최종 출력

- **무엇이:** `PipelineResult` — 지금까지의 모든 중간 산출물 + 지표(risk_level, 조기종료 여부, 재시도 횟수). 판정이 REJECT/REVIEW면 HTTP 헤더 `X-Plan-Status`를 붙인다 (`routes.py:46-50`).
- **누가 받나:** ① Streamlit 대시보드 (사람이 화면으로 봄), ② 원하면 별도 API를 한 번 더 불러서 C++ 제어 어댑터로 보냄 — 단 **dry-run만 허용**(실제 제어 쓰기는 코드가 예외를 던지며 막음, `control/bridge.py:66-67`). escalation_required가 켜져 있으면 NOTIFY_SUPERVISOR 명령이 추가된다.

### 참고: 두 번째 파이프라인

`POST /api/v1/diagnose`는 자연어 질문("3번 설비가 이상해요")을 받아 의도 추출 → SOP 검색 → 진단 답변을 만드는 별도의 직선 파이프라인이다 (`pipeline/nl_diagnosis_pipeline.py`). 알람 처리 경로와는 별개다.

---

## 2. Q1~Q4 답변

### Q1. "확신도"로 쓸 수 있는 신호가 지금 어디에 있나?

실시간 경로에 이미 있는 신호들 (전부 결과 모델에 저장됨):

| 신호 | 어디에 | 성격 |
|---|---|---|
| risk_level (SAFE/WARNING/CRITICAL) | rule engine 결과 | 결정론. 3단계 |
| utilization_pct (센서별, 연속값) | rule engine 결과의 risk_factors | 결정론. **가장 세밀한 결정론 신호** |
| triggered_failure_types (동시 고장 모드 수) | rule engine 결과 | 결정론. 많을수록 복합 상황 |
| relevance_score (SOP 조각별 유사도) | SOP 검색 결과 | 연속값. **지금은 아무 판단에도 안 쓰임** |
| risk_index (0~100) | 진단 결과 | 계산식은 결정론이지만 입력값을 LLM이 넣어서 반쯤 비결정 |
| grounding_score (전체+단계별) | 검증 결과 | 연속값. **유일하게 이미 라우팅(APPROVE/REVIEW/REJECT)에 쓰이는 신호** |
| anomaly severity | perception LLM 출력 | LLM이 스스로 매김 |
| escalation_required | 조치계획 LLM 출력 | LLM이 스스로 정함, 검증 없음 |

**없는 것:**
- 보정된(calibrated) ML 예측 확률 — 실시간 경로에 없다. XGBoost의 predict_proba는 오프라인 스크립트 2개에만 있다.
- 보정 코드 자체가 없다. ADR-004가 방법 4가지(무보정/Platt/Isotonic/Temperature)를 비교해 놨지만 결론은 "실험 후 결정"이고 측정값은 빈칸이다.
- SECOM 쪽 확률은 지금 못 쓴다: ADR-001 실측에서 XGBoost가 불량을 하나도 못 잡았다 (Recall 0.000).
- 다만 ADR-013이 확률 신호가 들어올 자리(`core/ml_predictor.py::predict_failure_probability(log) -> float`)를 스펙 수준으로 그려 놨다. 코드는 아직 없다.

### Q2. 최종 출력은 누구에게 어떤 형태로 가나? 에스컬레이션 개념이 이미 있나?

- **전달:** HTTP JSON → 대시보드에서 사람이 보거나, 별도 호출로 C++ 어댑터(dry-run 전용). **자동으로 사람에게 알려주는 채널은 없다** — 알림 도구는 mock이다.
- **에스컬레이션 비슷한 것이 코드에 4군데 흩어져 있다** (서로 연결 안 됨):
  1. escalation_required (LLM 판단) → 브릿지에서 NOTIFY_SUPERVISOR로 변환
  2. REVIEW/REJECT 판정 → X-Plan-Status 헤더 — 받는 쪽 처리 로직은 없음
  3. 각 단계 실패 시 폴백 (보수적으로 진행하거나 escalation 플래그를 켬)
  4. rule engine의 권고 문구 ("즉시 정지하세요" 등) — 글자일 뿐 라우팅이 아님
- **문서에는 3분기 이야기가 이미 있다:** 새 README 8장이 "APPROVE = 자동 전달 가능 / REVIEW = 사람 확인 / 재시도 소진 REJECT = 운영자 에스컬레이션 + 자동 조치 차단"이라고 써 놨다. **하지만 코드는 판정 라벨과 헤더까지만 구현했다.** "운영자 에스컬레이션"과 "자동 조치 차단"에 해당하는 코드는 없다. 이 정책의 주인이어야 할 ADR-009는 링크만 있고 파일이 없다. → **Task 2의 에스컬레이션 정책은 백지에서 만드는 게 아니라, README의 이야기를 코드 사실과 맞는 진짜 정책으로 승격시키는 작업이다.**

### Q3. 같은 입력을 두 번 넣으면 같은 결과가 나오나?

**안 나온다.** 비결정성이 들어오는 지점:

1. **LLM temperature가 0.1이고 seed가 없다** (`core/langchain_client.py:16`). 모든 LLM 호출이 매번 조금씩 다르다. **주의: README는 "temperature=0으로 고정했다"고 주장하는데 코드는 0.1이다. 문서-코드 불일치** (§3의 B-1).
2. **흔들림이 단계를 타고 커진다:** LLM이 만든 검색어가 달라지면 → 검색된 SOP 조각이 달라지고 → 조치계획이 달라지고 → 근거 점수가 달라지고 → 최종 판정(APPROVE/REVIEW/REJECT)까지 달라질 수 있다.
3. **진단 ReAct 루프:** 도구를 부를지, 몇 번 부를지, 어떤 값을 넣을지를 LLM이 정한다.
4. JSON 파싱 실패 시 최대 3번 재시도 — 재시도 자체가 새로운 샘플링이다 (`agents/base.py:44-45`).

**변하지 않는 부분:** rule engine 전체(같은 입력 → 항상 같은 판정), 임베딩(같은 문장 → 같은 벡터), 코사인 계산, 브릿지의 키워드 매핑. 한 줄 요약: **입구(rule engine)와 검증 계산은 결정론, 그 사이의 언어 처리 전부가 비결정론.**

문서 상태: 비결정성 통제 방침을 담아야 할 **ADR-008이 링크만 있고 파일이 없다.** README의 "일관성 [___]%" 빈칸이 측정 자리만 잡아 놨다. 그리고 README는 "재시도 최대 3회"라고 썼는데 설정 기본값은 2다 — "최초 1회 + 재시도 2회 = 총 3회"로 읽으면 맞긴 하지만 표현이 헷갈린다 (B-2).

### Q4. Langfuse(계측)를 붙인다면 어디가 자연스러운가?

**Langfuse는 이미 절반쯤 붙어 있다.** 이걸 모르고 설계하면 안 된다:
- 클라이언트: `core/langfuse_client.py`. 환경변수 `LANGFUSE_ENABLED`로 켜고 끄는데 **기본값이 꺼짐(false)**이다.
- trace(요청 1건의 전체 기록): 파이프라인 시작 시 correlation_id를 ID로 해서 만든다 (`forge_pipeline.py:346-353`).
- generation(LLM 호출 1건의 기록): 모든 프롬프트 기반 에이전트가 공통 부모 클래스에서 자동으로 남긴다 (`agents/base.py:57-69`). 프롬프트 이름/버전 메타데이터 포함.

**지금 안 남는 것 = 자연스러운 확장 지점:**
1. **rule engine 판단** — trace만 보면 파이프라인이 perception부터 시작한 것처럼 보인다
2. **벡터 검색** — 검색어를 만든 LLM 호출만 남고, 무엇이 몇 점으로 검색됐는지는 안 남는다
3. **검증의 코사인 계산** — 단계별 점수가 trace에 없다
4. **그래프의 분기 결정** — "왜 이 길로 갔나"를 어디에도 안 남긴다. `_route_after_*` 함수 3개가 그 자리다. 참고로 이 함수들이 에스컬레이션 레이어가 끼어들 자연스러운 위치이기도 하다
5. **로그 버그 하나:** `core/logging.py:14-17`에 dict를 JSON으로 예쁘게 남기려는 코드가 있는데, **절대 실행되지 않는 죽은 코드다.** 파이썬 로깅의 getMessage()가 항상 문자열을 돌려주기 때문이다. 그 결과 구조화 로그가 `{"message": "{'event': ...}"}` 같은 **통문자열로 뭉개져서 기계가 파싱할 수 없다** (직접 실행해서 확인함). 로그로 지표를 내려면 이것부터 고쳐야 한다.

문서 상태: **ADR-007(추적/계보 기록, 검토중)이 D3의 선택지를 이미 펼쳐 놨다** — "Langfuse만 쓰기 vs 결과 DB + 계보 테이블"을 비교하고, Langfuse만으로는 안 되는 것(SOP 근거를 나중에 쿼리하기, 오프라인 환경, 장기 감사)을 적어 놨다. 그리고 README 8장의 추적 사슬(센서값 → 판정 → SOP 조각 → 조치의 근거 → 검증 점수 → correlation_id)은 §1에서 확인한 데이터 모델 필드와 정확히 맞아떨어진다. **즉 추적에 필요한 데이터 고리는 이미 모델 안에 있고, 그것을 저장하고 조회하는 층만 없다.**

---

## 3. 의도와 코드가 어긋난 지점 (3개 층으로 정리)

### A층. 작업 명령서의 기억 vs 리포

- **A-1. "SECOM 기반 FDC"** — SECOM은 있지만 파이프라인 밖. 리포의 ADR-001이 "AI4I 파이프라인 유지 + SECOM은 별도 실험"을 명시적으로 결정해 놨다.
- **A-2. "XGBoost 예측"** — 실시간 경로에 여전히 없음. 다만 의존성 추가 + ADR-013 설계로 "계획된 미래"로는 문서화됨.

### B층. 리포 문서(README/ADR) vs 코드 — 이 브랜치에서 새로 생긴 어긋남

- **B-1.** README "temperature=0 고정" vs 코드 0.1 (`langchain_client.py:16`). 문서가 코드보다 앞서갔다.
- **B-2.** README "재시도 최대 3회" vs 설정 기본 2회. 총 시도 3회로 읽으면 맞지만 표현이 모호하다.
- **B-3.** README "재시도 소진 REJECT → 운영자 에스컬레이션, 자동 조치 차단" — 코드에 그런 메커니즘이 없다. REJECT 상태로 끝나고 헤더가 붙을 뿐이다.
- **B-4.** README가 링크한 **ADR-008, ADR-009 파일이 없다** (11개 중 결번). 신뢰성 지표도 빈칸. Task 2 산출물이 사실상 이 자리를 채운다.
- **B-5.** ADR-013이 언급하는 `core/preprocessor.py`, `core/ml_predictor.py` 등은 전부 "미구현 예정"으로 정직하게 표기돼 있음. 설계할 때 이미 있는 코드로 착각하면 안 된다.
- **B-6.** 탐색 스크립트 `test.py`가 `secom.data` 파일을 찾는데 실제 파일명은 `secom.csv` — 지금은 실행이 안 된다 (사소).

### C층. 코드 내부 결함 (브랜치와 무관하게 존재)

- **C-1.** `agents/risk_assessment_agent.py`는 아무도 import하지 않는 죽은 코드 (rule engine으로 대체된 흔적, ADR-005에 기록).
- **C-2.** README 그림과 달리 진단과 SOP 검색은 한 노드 안에서 병렬이고, **진단 결과는 아무도 안 쓴다.**
- **C-3.** 진단 에이전트 입력에서 "원본 센서값" 자리에 이상 목록이 중복으로 들어간다 (`diagnostic_agent.py:70-71`).
- **C-4.** 로깅의 죽은 분기 — 구조화 로그가 통문자열로 손실 (Q4-5).
- **C-5.** 검증 임계값이 이원화 — "근거 있음" 기준(0.75)은 설정으로 바꿀 수 있는데 판정 경계(0.85/0.60)는 코드에 박혀 있다. 0.60~0.75 사이는 "근거 부족인데 REVIEW로 통과"하는 어정쩡한 구간이다.
- **C-6.** 계획이 비어 있으면 검증을 만점으로 통과한다 (`hallucination_validator.py:39-49`).

## 4. 확인 못 한 것

- **실행해봐야 아는 숫자 전부**: LLM의 실제 일관성, 근거 점수 분포, 조기종료 비율, 처리 시간 — Ollama 실행 환경이 없어 측정 불가. ADR에 적힌 수치(AI4I XGBoost PR-AUC 0.830 등)는 문서에 적힌 값이고 이번에 재현하지 않았다.
- **ChromaDB에 SOP가 실제로 들어가 있는지**: 벡터 저장 폴더가 리포에 없어서 배포 환경에 달려 있다.
- **Langfuse를 실제로 켜서 쓰는지**: 코드는 있지만 기본 꺼짐이고 .env가 리포에 없다.
- **C++ 어댑터 빌드 여부**: 바이너리 경로만 있고 빌드됐는지는 환경에 달려 있다.
- **ADR-008/009가 다른 곳에 있을 가능성**: 아직 push 안 한 로컬 커밋에 있을 수도 있다. 원격 3개 브랜치 기준으로는 없다.

---

## 5. 완료 조건 체크

- [x] 파이프라인 전 단계를 파일 경로 수준으로 매핑 (이 브랜치의 실행 코드 = main과 동일함도 확인)
- [x] Q1~Q4에 코드 근거(경로:행) + 이 브랜치의 새 문서(ADR) 근거를 붙여 답변
- [x] 확인 불가 항목을 이유와 함께 명시
- [x] 어긋난 지점 목록 (3개 층, 14건)

**다음 단계:** 여기서 멈춘다 (HARD STOP). 위의 **G1**(확신도 신호의 전제: 현존 신호만 / XGBoost 통합 전제 / 겸용)과 **G2**(검증 데이터: 명령서의 SECOM vs 실제로 파이프라인이 도는 AI4I)를 결정해 주시면 Task 2를 시작한다.
