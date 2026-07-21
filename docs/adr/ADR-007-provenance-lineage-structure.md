# ADR-007: Provenance / Lineage 기록 구조

**상태:** 검토중 (부분 구현)

---

## 맥락

제조 AI 시스템에서 "이 경보는 왜 발생했는가"에 답하려면 결과에서 근거까지 역추적이 가능해야 한다.  
이 역추적 체계 없이는 다음 문제가 생긴다:

1. **신뢰 문제:** 운전자가 조치계획 단계가 어느 SOP에서 왔는지 확인할 수 없음
2. **감사 문제:** "왜 이 설비에 CRITICAL 경보를 냈는가"를 사후에 재현할 수 없음
3. **데이터 자산화 불가:** SOP 문서의 어느 절차가 실제로 사용됐는지 통계를 낼 수 없음
4. **모델 개선 장벽:** 어떤 센서 조합 + 어떤 임계값이 어떤 경보로 이어졌는지 추적 없이는 피드백 루프 구성 불가

---

## 고려한 대안

### 대안 A: Langfuse 트레이스만 사용

- **방법:** 각 에이전트 호출에 correlation_id + Langfuse 스팬 기록. 결과 DB 없음
- **장점:** 이미 구현됨, 에이전트 호출 순서·지연 확인 가능
- **단점:**
  - Langfuse는 LLM 호출 트레이스 도구. "어느 SOP 청크가 이 조치계획의 근거인가"를 쿼리하기 어려움
  - Langfuse가 없는 오프라인 환경에서는 추적 불가
  - 장기 보존·감사 목적의 데이터 모델이 아님

### 대안 B: 결과 DB (PostgreSQL) + lineage 테이블

- **방법:** `pipeline_result` 테이블 + `action_step_provenance` 테이블 (step → chunk_id → 문서 경로)
- **장점:** 완전한 감사 쿼리 가능. "SOP-MNT-001이 몇 번 인용됐는가" 통계 가능
- **단점:** 별도 DB 인프라 필요. 현재 포트폴리오 범위와 운영 부담 불균형

### 대안 C: PipelineResult JSON에 provenance 필드 포함 + 로컬 append-only 로그

- **방법:** API 응답 JSON에 이미 `sop_reference` (chunk_id) 포함. 이를 로컬 JSONL 파일에 append
- **장점:** 인프라 추가 없음, 포트폴리오 범위 내, 로컬 grep/jq로 감사 가능
- **단점:** 쿼리 인터페이스 없음. 파일 크기 증가. 동시성 미고려

---

## 결정

**현재:** 대안 A (Langfuse) + PipelineResult에 sop_reference chunk_id 포함 (부분 구현).  
**목표:** 대안 C로 확장 (로컬 append-only lineage 로그 + 간단한 감사 스크립트).

---

## 현재 구현된 lineage 구조

```
EquipmentLog
  equipment_id, timestamp, sensor readings, tags
        │
        ▼ rule_engine
RiskAssessment
  risk_level, failure_type, risk_factors (sensor_id + value + threshold)
        │
        ▼ SOPRAGAgent
SOPContext
  chunks[]: chunk_id, document_name, page_number, content, failure_type
        │
        ▼ ActionPlanAgent
ActionPlan
  steps[]: step_number, action, sop_reference (= chunk_id)
        │
        ▼ HallucinationValidator
ValidationResult
  step_validations[]: grounding_score, best_matching_chunk_id
  overall_grounding_score, recommendation
        │
        ▼ (모든 단계에 전파)
correlation_id → Langfuse 스팬
```

**추적 가능한 것:**
- `action_plan.steps[N].sop_reference` → `SOP-MNT-001.md::chunk::2` (어느 SOP 청크)
- `validation_result.step_validations[N].grounding_score` (각 단계의 근거 강도)
- `risk_assessment.risk_factors` (어느 센서가 임계값을 얼마나 초과했는지)
- Langfuse 스팬 (에이전트 호출 시각, 지연, 모델 버전)

**추적 불가능한 것 (미구현):**
- "이 조치계획이 나온 시점의 임베딩 모델 버전은 무엇인가"
- "이 고장에서 SOP-MNT-001의 chunk::2가 몇 번이나 인용됐는가"
- correlation_id → 전체 lineage를 단일 쿼리로 재현

---

## 이유 (인과)

chunk_id(`{filename}::chunk::{index}`) 구조는 파싱만으로 원본 문서와 위치를 특정할 수 있다.  
완전한 DB lineage 테이블 없이도 `sop_reference` 필드로 "이 조치 단계의 출처"는 추적 가능하다.  
로컬 JSONL 로그 추가는 인프라 없이 감사 쿼리 가능성을 제공하는 최소 구현이다.

---

## 포기한 것 / 트레이드오프

완전한 데이터 lineage 플랫폼(DataHub, OpenLineage 등)은 이 포트폴리오 범위를 벗어난다.  
대신 "결과에서 원인까지 수동으로 역추적할 수 있는 구조"를 만들고,  
설계 의도를 ADR에 기록하는 것으로 대체한다.

---

## 결과 / 검증

`[___]` 빈칸 — 다음 구현 후 채운다:

1. PipelineResult를 JSONL로 append하는 로거 추가
2. `scripts/audit_query.py` — correlation_id로 전체 lineage 재현 스크립트
3. "SOP 청크별 인용 횟수 Top-5" 집계 쿼리 검증
