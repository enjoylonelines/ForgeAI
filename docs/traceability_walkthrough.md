# 근거 추적 완주 예시 — TWF 케이스 (이슈 #31)

> **한 줄 요약:** 공구 마모 센서 215 min → TWF 판정 → SOP-MNT-001 §4.1·§4.2 인용 → 3단계 조치 계획

---

## 0. 입력 (센서 로그)

| 센서 | 값 | 정상 범위 |
|------|----|-----------|
| `tool_wear_min` | **215 min** | 0 – 250 min (교체 권고 임계값: 200 min) |
| `torque_nm` | 42.0 Nm | 3.8 – 76.6 Nm |
| `rotational_speed_rpm` | 1800 rpm | 1168 – 2886 rpm |
| `air_temperature_k` | 298.0 K | 295 – 304 K |
| `process_temperature_k` | 308.5 K | 305 – 313 K |

```
correlation_id: twf-demo-20260721
equipment_id:   CNC-42
```

---

## 1단계: Rule Engine (결정론적 분류)

**파일:** `core/rule_engine.py` → `assess_risk()`

```
tool_wear_min = 215  ≥  _TWF_TOOL_WEAR_MIN (200)
  → classify_failure_type() = "TWF"
  → _classify(): util_pct = (215-0)/(250-0)*100 = 86.0%  ≥  _WARNING_UTILIZATION (85%)
  → risk_level = "WARNING"
```

**RiskAssessment 출력:**
```json
{
  "risk_level": "WARNING",
  "failure_type": "TWF",
  "triggered_failure_types": ["TWF"],
  "risk_factors": [
    {
      "sensor_id": "tool_wear_min",
      "current_value": 215.0,
      "safe_max": 250.0,
      "utilization_pct": 86.0,
      "description": "tool_wear_min 215.0 min — exceeds 200 min replacement threshold"
    }
  ],
  "summary": "Risk warning: tool_wear_min approaching operating limits. Preventive inspection recommended within the shift."
}
```

**DecisionEvent 기록:**
```json
{"stage": "rule_engine", "decision": "WARNING", "reason": "failure_type=TWF, factors=1"}
```

---

## 1b단계: ML Predictor (보조 신호)

**파일:** `core/ml_predictor.py`, `core/forge_pipeline.py`

```
ml_proba = 0.18  <  ML_THRESHOLD (0.30)
risk_level = "WARNING" (≠ SAFE) → 개입 조건 불충족 → NO_CHANGE
```

**DecisionEvent 기록:**
```json
{"stage": "ml_predictor", "decision": "NO_CHANGE", "signals": {"ml_proba": 0.18, "upgraded": false}}
```

---

## 2단계: Perception Agent (이상 탐지)

**파일:** `agents/perception_agent.py`

rule_engine이 WARNING을 반환했으므로 early-exit 없이 Perception 단계로 진입.  
LLM이 센서 로그를 해석하여 이상 여부를 판정한다.

**AnomalyReport 출력 (요약):**
```json
{
  "has_anomaly": true,
  "anomalies": [
    {
      "sensor_id": "tool_wear_min",
      "description": "Tool wear at 215 min exceeds the 200 min replacement threshold. Immediate inspection warranted."
    }
  ],
  "summary": "Tool wear sensor indicates imminent TWF risk. Sensor value 215 min is 7.5% above replacement threshold."
}
```

**DecisionEvent 기록:**
```json
{"stage": "perception", "decision": "ANOMALY_DETECTED", "signals": {"has_anomaly": true, "anomaly_count": 1}}
```

---

## 3단계: SOP RAG (문서 검색)

**파일:** `agents/sop_rag_agent.py`, `rag/chroma_client.py`

Perception 이상 감지 → `failure_type="TWF"` 필터로 ChromaDB 벡터 검색.

```
query: "tool wear failure replacement procedure inspection"
filter: {"failure_type": {"$in": ["TWF"]}}
k: 4
```

**검색된 SOP 청크:**

| chunk_id | 문서 | 페이지 | relevance_score | 내용 요약 |
|----------|------|--------|-----------------|----------|
| `SOP-MNT-001-tool-wear-failure.md::chunk::3` | SOP-MNT-001 | — | 0.91 | §4.1 즉각 조치: 설비 정지, 구역 격리, 기술자 호출 |
| `SOP-MNT-001-tool-wear-failure.md::chunk::4` | SOP-MNT-001 | — | 0.88 | §4.2 공구 상태 점검: 육안 검사, 측정, 스핀들 검사 |
| `SOP-MNT-001-tool-wear-failure.md::chunk::5` | SOP-MNT-001 | — | 0.82 | §4.3 공구 교체: 신규 공구 장착, 옵셋 재설정 |
| `SOP-MNT-001-tool-wear-failure.md::chunk::6` | SOP-MNT-001 | — | 0.74 | §6 에스컬레이션 기준: 주 3회 이상 TWF 시 보고 |

**DecisionEvent 기록:**
```json
{
  "stage": "sop_search",
  "decision": "CHUNKS_FOUND",
  "signals": {"chunk_count": 4, "query_used": "tool wear failure replacement procedure inspection"},
  "reason": "top_chunk=SOP-MNT-001-tool-wear-failure.md::chunk::3"
}
```

---

## 4단계: Action Plan (조치 계획 생성)

**파일:** `agents/action_plan_agent.py`

SOP 청크 4개를 컨텍스트로 LLM이 조치 계획을 생성한다.

**ActionPlan 출력:**

| # | 조치 | 근거 (chunk_id) |
|---|------|----------------|
| 1 | 현재 가공 사이클 완료 후 CNC 설비 정지. 비상 정지 버튼 사용 금지. | `SOP-MNT-001::chunk::3` (§4.1) |
| 2 | 설비 주변 2m 안전 테이프 격리 및 작업 중 표지판 부착. 유지보수 기술자·교대 감독자 즉시 통보. | `SOP-MNT-001::chunk::3` (§4.1) |
| 3 | 스핀들에서 공구 탈착 → 육안 검사(마모·파손·치핑) → 공구 측정기로 마모량 측정. ISO 3685 VB=0.3mm 초과 시 즉시 폐기. | `SOP-MNT-001::chunk::4` (§4.2) |

```json
{
  "escalation_required": false,
  "steps": [
    {"action": "Stop CNC after current cycle. Do not use emergency stop.", "source_chunk_id": "SOP-MNT-001-tool-wear-failure.md::chunk::3"},
    {"action": "Isolate area 2m around equipment. Notify maintenance tech and shift supervisor.", "source_chunk_id": "SOP-MNT-001-tool-wear-failure.md::chunk::3"},
    {"action": "Remove tool, visual inspect, measure wear. Discard if VB > 0.3mm (ISO 3685).", "source_chunk_id": "SOP-MNT-001-tool-wear-failure.md::chunk::4"}
  ]
}
```

**DecisionEvent 기록:**
```json
{"stage": "action_plan", "decision": "PLAN_GENERATED", "signals": {"step_count": 3, "escalation_required": false}}
```

---

## 5단계: Hallucination Validator (근거 검증)

**파일:** `agents/hallucination_validator.py`

조치 계획의 각 step이 실제로 SOP 청크에 근거하는지 검증한다.

**ValidationResult 출력:**

```json
{
  "overall_grounding_score": 0.93,
  "is_valid": true,
  "ungrounded_steps": [],
  "recommendation": "APPROVE",
  "explanation": "All 3 steps are directly grounded in SOP-MNT-001 §4.1 and §4.2."
}
```

**DecisionEvent 기록:**
```json
{
  "stage": "validator",
  "decision": "APPROVE",
  "signals": {"grounding_score": 0.93, "ungrounded_steps": []}
}
```

---

## 6단계: Routing Gate (최종 라우팅)

**파일:** `core/routing_rules.py`, `pipeline/forge_pipeline.py`

```
risk_level = "WARNING"
has_anomaly = true
plan_step_count = 3
recommendation = "APPROVE"
verdict_conflict = false
→ matched_rule: "STANDARD_APPROVE"
→ route: "AUTO"
```

**DecisionEvent 기록:**
```json
{
  "stage": "routing_gate",
  "decision": "AUTO",
  "reason": "[STANDARD_APPROVE] Plan approved, anomaly confirmed, route to auto execution."
}
```

---

## 전체 추적 체인 (한눈에 보기)

```
[입력]
  tool_wear_min = 215 min
        │
        ▼
[1. Rule Engine]  rule_engine.py:classify_failure_type()
  failure_type = TWF  │  risk_level = WARNING
        │
        ▼
[2. Perception]   perception_agent.py
  has_anomaly = True  │  "tool wear 7.5% above threshold"
        │
        ▼
[3. SOP RAG]      sop_rag_agent.py → ChromaDB
  query: "tool wear failure replacement procedure"
  → SOP-MNT-001::chunk::3  (§4.1 즉각 조치)   score=0.91
  → SOP-MNT-001::chunk::4  (§4.2 공구 점검)   score=0.88
        │
        ▼
[4. Action Plan]  action_plan_agent.py
  Step 1: 설비 정지          → SOP-MNT-001 §4.1
  Step 2: 기술자 호출        → SOP-MNT-001 §4.1
  Step 3: 공구 탈착·측정    → SOP-MNT-001 §4.2
        │
        ▼
[5. Validator]    hallucination_validator.py
  grounding_score = 0.93  │  APPROVE
        │
        ▼
[6. Routing Gate] routing_rules.py
  route = AUTO
```

---

## 추적 가능 판정 요건 충족 여부 (ADR-014 기준)

| 요건 | 확인 |
|------|------|
| `failure_type` ≠ NONE | ✅ TWF |
| `SOPContext.chunks` ≥ 1 | ✅ 4개 |
| ActionPlan step 중 chunk_id 포함 | ✅ 3/3 step |
| decisions.jsonl에 4개 스테이지 기록 | ✅ rule_engine / sop_search / action_plan / validator |

→ **이 판정은 추적 가능 판정으로 계산된다.**

---

## 관련 파일

| 역할 | 경로 |
|------|------|
| 분류 로직 | `core/rule_engine.py` |
| SOP 원문 | `data/sop_docs/SOP-MNT-001-tool-wear-failure.md` |
| 벡터 검색 | `rag/chroma_client.py` |
| 결정 로그 | `logs/decisions.jsonl` |
| 추적 % ADR | `docs/adr/ADR-014-traceability-coverage-metric.md` |
