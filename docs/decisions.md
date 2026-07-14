# ForgeAI — 설계 결정 및 디버깅 로그

이 문서는 설계 과정에서 내린 결정, 발견한 버그, 트레이드오프를 기록한다.
"완성된 아키텍처"가 아니라 **실제 추론 과정의 증거**다.

---

## 역할 분리 원칙

```
Rule Engine  → 분류 (failure_type, risk_level) — 결정론적
LLM Agents   → 해석·검색·계획·설명 — 언어 이해가 필요한 영역
```

PerceptionAgent 프롬프트에 TWF/HDF/PWF/OSF 판별 기준이 있었다.
LLM이 분류를 시도하게 유도하는 구조였다.
→ 해당 섹션 제거. LLM은 "센서 값이 얼마나 벗어났는가"만 보고,
  failure_type 레이블은 rule engine이 단독으로 결정한다.

---

## 버그 ①: HDF/PWF/OSF early exit

**발견**: e2e 테스트에서 HDF·PWF·OSF 3개 케이스가 모두 SAFE로 early exit됨.

**원인** (`rule_engine.py:125`):
```python
# 버그
failure_type = classify_failure_type(log) if risk_level != "SAFE" else "NONE"
```
`risk_level`은 개별 센서 utilization(85% 임계치)으로 계산된다.
HDF/PWF/OSF는 센서 조합 조건이라 개별 센서가 모두 정상 범위 안에 있어도 발생한다.
→ `risk_level == "SAFE"`이면 `classify_failure_type` 자체를 호출하지 않았고,
  파이프라인은 SAFE를 보고 early exit 했다.

**수정**:
```python
failure_type = classify_failure_type(log)
if failure_type != "NONE" and risk_level == "SAFE":
    risk_level = "WARNING"
```

**교훈**: utilization 기반 risk_level과 조합 조건 기반 failure_type은
별개의 신호다. 하나가 정상이라도 다른 하나가 이상일 수 있다.

---

## 버그 ②: OSF 테스트 케이스가 PWF로 분류됨

**발견**: OSF 케이스 설정값 `torque=65Nm, rpm=1800rpm`에서
  OSF 대신 PWF가 반환됨.

**원인**:
```
power = 65 × (1800 × 2π/60) = 12,252W > PWF_POWER_MAX(9000W)
→ priority 순서상 PWF가 OSF보다 먼저 체크됨 → PWF 반환
```

**수정**: OSF만 단독으로 발생하는 값으로 교체.
```
rpm 1800→1000, torque 65→60, wear 180→190
power = 60 × (1000 × 2π/60) = 6,283W (정상 범위)
strain = 190 × 60 = 11,400 > 11,000 → OSF
```

**교훈**: 테스트 케이스는 물리 공식으로 검증해야 한다.
"OSF처럼 보이는 값"이 실제로는 다른 조건을 먼저 트리거할 수 있다.

---

## 설계 결정: 단일 레이블 우선순위 — 안전 트리아지 기준

AI4I 2020 데이터셋에서 여러 고장 조건이 동시에 참일 수 있다.
`classify_failure_type`은 우선순위 순서로 첫 번째 매칭만 반환한다.

**확정 우선순위: PWF > OSF > HDF > TWF**

| 순위 | 고장 | 근거 |
|------|------|------|
| 1 | PWF | 과전력(화재·소손) / 저전력(스톨·잼) — 전기/화재 즉각 위험 |
| 2 | OSF | 급파단·비산 — 물리적 부상 위험 |
| 3 | HDF | 열 누적 → 베어링 소손 — 진행 느리나 화재 전환 가능 |
| 4 | TWF | 점진적 마모 — 대응 시간 가장 여유 있음 |

**트레이드오프 (의도된 설계):**
이 순서는 "안전 트리아지 우선, 진단 정확도는 차선"이다.
복수 조건 동시 충족 시 낮은 순위 고장 모드가 숨겨진다.
숨겨진 모드는 `RiskAssessment.triggered_failure_types` 필드에 보존되고
`multiple_failure_types_triggered` 이벤트로 경고 로그를 남긴다.

이전 순서(TWF>HDF>PWF>OSF)는 근거 없이 구현 순서대로 배치된 것이었다.
안전 심각도 역순이어서 교정했다.

**다중 레이블 지원은 다음 단계.**
구현 방향: `get_all_triggered_failure_types()` 이미 구현됨.
파이프라인에서 primary/secondary를 구분해 SOP 검색을 복수 실행하는 방향.

---

## 버그 ③: citation 부스트가 순환 구조였음

**배경**: Validator의 cosine similarity가 0.70~0.74에 고착.
APPROVE 기준 0.85를 넘지 못하고 전부 REVIEW.

**시도한 수정**: `sop_reference` chunk_id가 유효하면 score를 0.90으로 올림.
→ 결과: 전부 APPROVE.

**문제점**: LLM은 프롬프트에서 chunk_id 목록을 이미 받는다.
따라서 action 텍스트가 SOP와 무관해도 chunk_id만 정확히 적으면 APPROVE된다.
**Validator가 LLM 자신의 출력을 신뢰하는 순환 구조**였다.

**결론**: 제거. cosine similarity는 LLM 출력과 독립적인 신호여야 한다.

---

## 현재 미해결: Validator 임계값 문제

정상적으로 생성된 action plan의 cosine similarity가 0.70~0.74.
APPROVE 기준 0.85 미달 → 전부 REVIEW.

근본 원인: `nomic-embed-text`는 의미적으로 관련된 paraphrase에
  자연스럽게 0.65~0.80 범위를 준다. 프롬프트로 올리기 어렵다.

**검토 중인 대안**:
- A: 임계값 재보정 (나쁜 플랜 점수 분포 없이 근거 부족)
- B: 키워드 오버랩 혼합 (결정론적, 추가 구현 필요)
- C: cited chunk 직접 비교 (sop_reference 텍스트와 action 1:1 비교)

**현재 상태**: REVIEW는 "사람 검토 필요" 의미로 운영상 허용 가능.
  데모 목적으로는 C 방식 구현 예정.

---

## 버그 ④: TWF 임계값 경계 포함 누락 (`> 200` → `>= 200`)

**발견**: AI4I 주검증(이슈 #9)에서 `machine_failure=1` + `TWF=1`인 행 중
  `tool_wear_min=200.0`(L56354)이 SAFE로 판정돼 AUTO 라우팅으로 유출.

**원인** (`rule_engine.py`):
```python
# 버그 — 200.0 정확히 일치 시 포착 안 됨
if tool_wear is not None and tool_wear > _TWF_TOOL_WEAR_MIN:  # _TWF_TOOL_WEAR_MIN = 200.0
```
AI4I 2020 논문 기준: TWF는 tool_wear **≥ 200** min에서 발생.
`>` 연산자가 경계값(200.0)을 제외해 false negative 발생.

**수정**: `>` → `>=` (2곳: TWF trigger, tool_wear WARNING 임계값)

**남은 TWF 유출 1건** (`M16856`, `tool_wear=198.0`):
- 논문 기준(200+) 미만이지만 데이터셋이 TWF 레이블 부여.
- 임계값을 198로 낮추면 다른 정상 행이 WARNING으로 상향될 위험.
- **판단**: 데이터셋 레이블 이상(수작업 레이블 오류 가능성)으로 보고, 현 임계값 유지.
  포트폴리오 문서에 "7건 중 1건은 데이터셋 경계 이상"으로 명시.

---

## 구조적 한계: NONE/RNF 유출 — 센서 기반 포착 불가

**발견**: AI4I 주검증에서 `machine_failure=1`이지만 `TWF=HDF=PWF=OSF=RNF=0`인 행 9건 중
  6건이 SAFE → AUTO 유출.

**원인**:
AI4I 2020 데이터셋에는 "어떤 고장 유형에도 해당하지 않지만 실패한" 행이 존재한다.
논문은 이를 **RNF(Random National Failure)**로 분류하며
"공정 파라미터와 결정론적 관계가 없다"고 명시한다.
실제 센서값을 보면 정상 범위 내(tool_wear 20~179, torque 27~48, rpm 1419~1710)로
단일 임계값 규칙으로는 구조적으로 포착 불가능하다.

**결론**:
- 이 유출은 rule_engine 버그가 아닌 **RNF의 정의에 의한 불가피한 한계**.
- 해결 방향: 다변량 이상 탐지(ML predictor, 이슈 #11) — 센서 조합 패턴 학습 필요.
- 포트폴리오 문서에 "NONE 6건은 RNF 구조적 한계, ML predictor 대상"으로 명시.

---

## ADR-008: 비결정성 통제 — temperature=0 + seed 고정 (D4 채택안)

**날짜**: 2026-07-12  
**상태**: 채택

**배경**:
동일 입력에 대해 LLM 출력이 매 호출마다 달라지면 파이프라인 재현성이 없고
디버깅·포트폴리오 지표 신뢰성이 떨어진다.

**결정**:
- `get_chat_llm(model, seed)` — `temperature=0.0`, `seed=42`(기본값) 고정
- `lru_cache`는 `(model, seed)` 쌍으로 인스턴스를 캐시함
- REJECT 재시도에서만 `seed = BASE_SEED + retry_attempt`로 혼합
  → 같은 재시도 횟수에서는 결정론적, 서로 다른 재시도에서는 탐색 다양성 확보

**검토한 대안**:
- D1: temperature=0만 (seed 없음) — GPU non-determinism 잔류 가능
- D2: per-call seed 무작위 — 재현 불가
- D3: temperature=0.1 유지 — 현 상태, 비결정성 제어 없음
- **D4(채택)**: temperature=0 + 고정 seed, REJECT retry만 seed 혼합

**검증 기준**:
동일 입력 5회 실행 → 결정 등급(APPROVE/REVIEW/REJECT) 출력 일치.
GPU 한계로 완전 일치 보장 불가 시 실측값을 이 ADR에 기록.

**영향 범위**:
- `core/langchain_client.py` — `get_chat_llm` 시그니처 변경
- `agents/base.py` — `_invoke_chain(seed=)` 파라미터 추가
- `agents/action_plan_agent.py` — retry 시 seed 혼합 적용
