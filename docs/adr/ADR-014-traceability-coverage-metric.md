# ADR-014: 근거 추적 % — 측정 정의 (이슈 #31)

**상태:** 확정  
**날짜:** 2026-07-21  
**이슈:** #31 — 근거 추적 1건 완주 문서화

---

## 배경

ForgeAI는 센서 입력부터 SOP 조항 인용까지 전 구간을 기록(`decision_logger`)한다.  
발표 자료에서 "AI가 왜 그 조치를 제안했는가"를 설명할 때, 측정 가능한 지표가 필요하다.  
지표 이름이 "근거 추적 %"로 통용되고 있으나 분모·분자가 명시된 적이 없었다.

---

## 결정

**근거 추적 % = (추적 가능 판정 수 / 전체 판정 수) × 100**

### 용어 정의

| 용어 | 정의 |
|------|------|
| **판정(judgment)** | 파이프라인 1회 실행으로 생성된 `ActionPlan` 1건 |
| **추적 가능 판정** | 아래 조건을 모두 만족하는 판정 |

### 추적 가능(traceable) 판정의 요건

1. `RiskAssessment.failure_type` ≠ `"NONE"` — rule_engine 판정 근거가 존재함
2. `SOPContext.chunks` 길이 ≥ 1 — 최소 1개 SOP 청크가 검색됨
3. `ActionPlan` 의 각 step 중 적어도 하나가 `chunk_id`를 포함함  
   (HallucinationValidator의 `grounded_steps`로 확인)
4. `DecisionEvent` 로그(`decisions.jsonl`)에 해당 `correlation_id`의  
   `rule_engine`, `sop_search`, `action_plan`, `validator` 4개 스테이지가 모두 기록됨

### 측정 스크립트 위치

`scripts/measure_traceability.py` — `logs/decisions.jsonl`을 읽어  
위 4개 요건을 검사하고 근거 추적 %를 출력한다.

---

## 트레이드오프

| 대안 | 기각 이유 |
|------|----------|
| grounding_score ≥ 0.7로만 판별 | 수치가 높아도 SOP 청크 없이 계산될 경우 over-count |
| chunk_count ≥ 3 요구 | 단일 청크로도 완전 추적 가능; 문서 수 부족 패널티가 과함 |
| 로그 없으면 0으로 계산 | SAFE early-exit 판정은 4단계 미완료가 정상 — 분모에서 제외해야 함 |

### SAFE early-exit 처리

`risk_level == "SAFE"` 로 종료된 판정은 **분모에서 제외**한다.  
근거 추적 %는 "위험 판정이 내려진 경우 중 추적 가능한 비율"을 측정한다.  
SAFE 케이스는 추적 대상이 아니라 early-exit이 의도된 정상 동작이다.

---

## 기준값 (AI4I 10,000행 검증 기준)

| 지표 | 목표 | 실측 근거 |
|------|------|----------|
| 근거 추적 % | ≥ 80% | docs/ai4i_verification_report.md |
| SOP 청크 검색 성공률 | ≥ 95% | sop_rag fallback 미발생 케이스 비율 |

> 목표치는 `docs/ai4i_verification_report.md`의 WARNING+CRITICAL 판정 비율(약 3,200건/10,000행)에서
> SOP 청크 검색 성공률과 validator APPROVE 비율을 곱해 추정한다.

---

## 관련 문서

- `docs/traceability_walkthrough.md` — TWF 케이스 추적 예시 1건 (이슈 #31 산출물)
- `docs/ai4i_verification_report.md` — 10,000행 주검증 결과
- `models/decision_event.py` — `DecisionEvent` 스키마
- `core/decision_logger.py` — `decisions.jsonl` 기록 위치
