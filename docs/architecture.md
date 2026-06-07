# ForgeAI Architecture

## 시스템 개요

AI4I 2020 제조 설비 데이터를 기반으로 한 멀티에이전트 RAG 파이프라인.  
온프레미스 LLM(Ollama)과 벡터 DB(ChromaDB)로 구성된 폐쇄망 환경을 상정.

---

## 에이전트 파이프라인 (LangGraph StateGraph)

```
START
  └─ RiskAssessmentAgent        # 센서값 기반 위험도 판단 (SAFE / WARNING / CRITICAL)
       ├─ SAFE → END            # early_exit: 이후 LLM 호출 4회 절약
       └─ WARNING / CRITICAL
            └─ PerceptionAgent  # 이상 감지 및 원인 분류
                 ├─ 이상 없음 → END
                 └─ 이상 있음
                      └─ SOPRAGAgent          # ChromaDB에서 관련 SOP 조회
                           └─ ActionPlanAgent  # 조치 계획 생성
                                └─ HallucinationValidatorAgent  # 근거 검증
                                     ├─ APPROVE / REVIEW → END
                                     └─ REJECT → ActionPlanAgent (재시도, 최대 2회)
```

### 각 에이전트 역할

| 에이전트 | 역할 | 모델 호출 |
|---------|------|---------|
| RiskAssessmentAgent | 센서 임계값 기반 위험도 분류, SAFE면 즉시 종료 | 1회 |
| PerceptionAgent | 이상 패턴 분석, 고장 유형 추론 | 1회 |
| SOPRAGAgent | ChromaDB 벡터 검색, 관련 SOP 청크 추출 | 0회 (임베딩만) |
| ActionPlanAgent | SOP 기반 조치 계획 생성 | 1회 (재시도 시 추가) |
| HallucinationValidatorAgent | 코사인 유사도로 근거 검증 | 1회 |

---

## 2-Tier 처리 구조

### 이 프로젝트에서의 구현

```
센서 row
  └─ RiskAssessmentAgent (LLM, ~0.3s)
       ├─ SAFE (96.6%) → early_exit        ← 1단계: 필터
       └─ WARNING/CRITICAL (3.4%) → 풀 파이프라인 (~4s)  ← 2단계: 심층 분석
```

RiskAssessmentAgent가 1단계 필터 역할을 수행한다. AI4I 데이터 기준 96.6%의 row가 SAFE로
early_exit되어 나머지 에이전트 호출을 생략한다.

### 프로덕션에서의 동등 구조

실제 IoT 스트리밍 환경에서는 LLM이 hot path에 들어갈 수 없다 (응답 수초 vs 센서 유입 수ms).
프로덕션 표준 패턴:

```
센서 스트림 (ms 단위)
  └─ [1단계] Rule Engine / Flink Streaming (~1ms, 모든 row)
       │  임계값 초과·통계적 이상 감지
       ├─ SAFE → 버림 (96% 이상)
       └─ 의심 row → Kafka alert topic
                        └─ [2단계] LLM Worker Pool (async, 플래그된 row만)
                             └─ 분석 결과 → DB / 대시보드
```

**Rule engine 구현 예시 (Python):**

```python
THRESHOLDS = {
    "tool_wear_min":        (">=", 200),
    "rotational_speed_rpm": (">=", 2800),
    "torque_nm":            (">=", 70),
    "air_temperature_k":    (">=", 310),
}

def rule_engine(log: EquipmentLog) -> str:
    for r in log.readings:
        op, limit = THRESHOLDS.get(r.sensor_id, (None, None))
        if op and r.value >= limit:
            return "WARNING"
    return "SAFE"
```

Kafka 없이 간소화하면 rule_engine → SAFE: 스킵, WARNING: `/analyze` 호출로 동일한 구조를 재현할 수 있다.

**이 프로젝트와 프로덕션의 차이:**

| 항목 | 이 프로젝트 | 프로덕션 |
|------|------------|---------|
| 1단계 필터 | RiskAssessmentAgent (LLM, ~0.3s) | Rule Engine (수ms) |
| 스트리밍 버퍼 | 없음 (순차 대기) | Kafka topic |
| LLM 처리 | 동기 (row 대기) | 비동기 Worker Pool |
| 데이터 | CSV replay | 실시간 센서 스트림 |

---

## 스트림 시뮬레이터 (stream_simulator.py)

CSV를 시간순으로 replay하며 에이전트의 조기 경고 성능을 측정하는 평가 도구.  
실시간 스트리밍이 아닌 **사후 배치 평가(replay evaluation)**임을 명시한다.

### 측정 지표

| 지표 | 정의 |
|------|------|
| `early_warning_count` | 고장 이벤트 중 직전에 WARNING/CRITICAL이 존재했던 건수 |
| `lead_time` | 고장 row 기준, 직전 WARNING/CRITICAL까지의 거리 (rows) |
| `false_alarm_count` | WARNING/CRITICAL 이후 `lookahead` rows 내에 고장이 없는 건수 |

```bash
python stream_simulator.py data/ai4i.csv --lookahead 10 --delay 0.5
```

---

## 추가 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `POST /analyze` | 단일 EquipmentLog 분석 |
| `POST /analyze/csv` | CSV 일괄 분석, improvement_metrics 포함 |
| `POST /diagnose` | 자연어 쿼리 → NL 진단 파이프라인 |
| `POST /control/plan` | 조치 계획 → 제어 명령 변환 |
| `POST /ingest` | SOP 문서 ChromaDB 적재 |
| `GET /health` | Ollama · ChromaDB 상태 확인 |
