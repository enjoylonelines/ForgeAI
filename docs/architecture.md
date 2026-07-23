# ForgeAI Architecture

## 시스템 개요

AI4I 2020 제조 설비 데이터를 기반으로 한 멀티에이전트 RAG 파이프라인.  
온프레미스 LLM(Ollama)과 벡터 DB(ChromaDB)로 구성된 폐쇄망 환경을 상정.

**설계 원칙:** "이 판단에 언어 이해가 필요한가"를 기준으로 컴포넌트를 선택한다.  
산술 비교는 rule engine, 언어 추론이 필요한 부분만 LLM을 사용한다.

---

## 정형 ML 베이스라인 — 하이브리드 설계의 정량적 근거

**스크립트:** `scripts/baseline_classifier.py` | **데이터:** AI4I 2020 (10,000행, test_size=0.2, random_state=42)

### 클래스 불균형

고장 339/10,000 = 3.39%, 정상:고장 ≈ 28.5:1.  
Accuracy를 헤드라인 지표로 쓰면 "항상 정상"을 찍는 Dummy 모델도 96.6%가 나오지만 고장 recall은 0이다.

### 결과 (헤드라인 지표: PR-AUC + 고장 클래스 recall/precision/F1)

| 모델 | PR-AUC | 고장 Recall | 고장 Precision | 고장 F1 |
|------|--------|------------|---------------|---------|
| Dummy (항상 정상) | 0.034 | 0.000 | 0.000 | 0.000 |
| Random Forest (`class_weight='balanced'`) | 0.783 | 0.721 | 0.766 | 0.742 |
| **XGBoost** (`scale_pos_weight=28.52`) | **0.830** | **0.779** | **0.747** | **0.763** |

**피처(6개):** Type(L/M/H), Air temp, Process temp, Rotational speed, Torque, Tool wear  
**제외:** UDI, Product ID (식별자), TWF/HDF/PWF/OSF/RNF (타깃 파생 → 데이터 누수)  
**피처 엔지니어링·하이퍼파라미터 튜닝 없음** — raw 베이스라인 수치

### 정형 분류의 한계와 LLM 층의 필요성

이 분류기의 baseline 성능은 Random Forest 기준 PR-AUC 0.78, 고장 recall 0.72, precision 0.77이었고, XGBoost는 PR-AUC 0.83, recall 0.78, precision 0.75로 비슷한 수준이었다.  
RNF(랜덤 고장)는 정의상 센서 패턴과 무관하게 발생하므로 정형 분류로는 예측이 불가능하며, 라벨 자체에도 'Machine failure=1인데 모드 플래그가 모두 0인' 불일치가 일부 존재해 정형 분류만으로는 여기까지가 한계였다.  
그래서 센서 이상을 탐지하는 정형 모델 위에 고장 원인 추론·운전자 설명을 담당하는 LLM 에이전트 층을 얹는 하이브리드 아키텍처를 채택했다.

---

## 에이전트 파이프라인 (LangGraph StateGraph)

```
START
  └─ rule_engine.assess_risk()            # 결정론적 위험도 판단 (LLM 미사용, 수ms)
     + classify_failure_type()            # TWF | HDF | PWF | OSF | NONE 분류
     (core/rule_engine.py)
       ├─ SAFE → END                      # early_exit: 이후 LLM 호출 4회 절약
       └─ WARNING / CRITICAL + failure_type
            └─ PerceptionAgent            # 이상 감지 및 원인 분류
                 ├─ 이상 없음 → END
                 └─ 이상 있음
                      └─ SOPRAGAgent(failure_type)   # ChromaDB where 필터 직결 + 폴백
                           └─ ActionPlanAgent(failure_type)  # failure_type별 addendum 주입
                                └─ HallucinationValidatorAgent  # 근거 검증
                                     ├─ APPROVE / REVIEW → END
                                     └─ REJECT → ActionPlanAgent (재시도, 최대 2회)
```

### 각 에이전트 역할

| 에이전트 / 컴포넌트 | 역할 | 모델 호출 |
|---------|------|---------|
| rule_engine (assess_risk + classify_failure_type) | 센서 임계값 기반 결정론적 위험도 분류 + failure_type 분류, SAFE면 즉시 종료 | **0회** (결정적) |
| PerceptionAgent | 이상 패턴 분석, 고장 유형 추론 | 1회 |
| SOPRAGAgent | ChromaDB 벡터 검색, failure_type where 필터 직결 + 결과 부족 시 폴백 | 0회 (임베딩만) |
| ActionPlanAgent | SOP 기반 조치 계획 생성, failure_type별 전용 컨텍스트 addendum 주입 | 1회 (재시도 시 추가) |
| HallucinationValidatorAgent | 코사인 유사도로 근거 검증 | 1회 |

---

## 2-Tier 처리 구조

### 이 프로젝트에서의 구현

```
센서 row
  └─ rule_engine.assess_risk() + classify_failure_type() (~1ms, LLM 미사용)
       ├─ SAFE (96.6%) → early_exit              ← 1단계: 결정론적 필터
       └─ WARNING/CRITICAL + failure_type (3.4%)
            └─ 풀 LLM 파이프라인 (~4s)           ← 2단계: 심층 분석
```

`core/rule_engine.py`의 `assess_risk()` + `classify_failure_type()`이 1단계 필터 역할을 수행한다.
AI4I 데이터 기준 96.6%의 row가 SAFE로 early_exit되어 나머지 에이전트 호출을 생략한다.
`failure_type`(TWF/HDF/PWF/OSF/NONE)은 이 단계에서 결정되어 SOPRAGAgent와 ActionPlanAgent로 전달된다.

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

**Rule engine 구현 (`core/rule_engine.py`):**

```python
# assess_risk(): 센서 utilization % 기반 SAFE / WARNING / CRITICAL 결정 (LLM 미사용)
# classify_failure_type(): AI4I 2020 조건식으로 TWF/HDF/PWF/OSF/NONE 결정론적 분류
#   - TWF: tool_wear_min > 200
#   - HDF: (process_temp - air_temp) < 8.6 K AND rpm < 1380
#   - PWF: spindle_power < 3500 W OR > 9000 W
#   - OSF: tool_wear_min × torque_nm > 11000
#   - NONE: 위 조건 미해당

risk = assess_risk(log)              # RiskAssessment (risk_level + failure_type + risk_factors)
# failure_type은 assess_risk() 내부에서 classify_failure_type()을 호출해 함께 반환
```

Kafka 없이 간소화하면 rule_engine → SAFE: 스킵, WARNING/CRITICAL: `/analyze` 호출로 동일한 구조를 재현할 수 있다.

**이 프로젝트와 프로덕션의 차이:**

| 항목 | 이 프로젝트 | 프로덕션 |
|------|------------|---------|
| 1단계 필터 | rule_engine.assess_risk() (~1ms, 결정적) | Rule Engine / Flink Streaming (수ms) |
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
| `GET /health` | Ollama · ChromaDB 상태 확인, `mode` 필드 포함 |

---

## 배포 — Docker Compose & k3s

### Docker Compose (로컬 개발 / 단일 노드)

```bash
docker compose up
```

`docker-compose.yml` 서비스 3개: `ollama` → `ollama-init`(모델 pull) → `app`.  
healthcheck 기반 의존성 순서로 기동한다.

### k3s 경량 쿠버네티스

프로덕션 수준 운영 고려를 위한 k3s 매니페스트를 `k8s/` 디렉토리에 포함한다.

```bash
kubectl apply -k k8s/          # 전체 배포
kubectl get pods -n forgeai    # 상태 확인
```

**구성 파일:**

| 파일 | 역할 |
|------|------|
| `namespace.yaml` | `forgeai` 네임스페이스 |
| `configmap.yaml` | 환경변수 (`OLLAMA_BASE_URL` 등) |
| `pvc.yaml` | ChromaDB(5Gi) + Ollama 모델(20Gi) 퍼시스턴스 |
| `ollama-deployment.yaml` | Ollama Deployment + 모델 초기 pull initContainer |
| `deployment.yaml` | ForgeAI 앱 + readiness/liveness/startup probe |
| `service.yaml` | ClusterIP (내부 통신), NodePort 주석 포함 |
| `kustomization.yaml` | 위 파일 일괄 적용 진입점 |

**Probe 설계:**

- `startupProbe`: 최대 120초 대기 (Ollama 모델 로드 시간 확보)
- `readinessProbe`: `GET /api/v1/health` → 200일 때만 트래픽 수신
- `livenessProbe`: exec 방식으로 HTTP 응답 여부만 확인 (503도 통과 — 앱이 살아있으면 재시작 안 함)

---

## LLM 장애 시 Fail-safe (rule-only 모드)

Ollama가 불능 상태일 때도 Rule Engine 단독으로 분석 요청을 처리한다.

```
POST /api/v1/analyze
        │
        ▼
 ollama_health() 체크
        │
   ┌────┴─────────────────┐
   │ UP                   │ DOWN (또는 MaxRetriesExceededError)
   ▼                      ▼
ForgePipeline          run_rule_only()
 .run()                    │
   │                  Rule Engine + ML predictor
   │                  라우팅 규칙 적용
   └──────┬────────────────┘
          ▼
   PipelineResult
   metrics.mode = "full" | "rule-only"
   X-Mode 응답 헤더
```

**rule-only 모드 동작:**

- LLM 에이전트(Perception, Diagnostic, ActionPlan, Validator) 전체 생략
- Rule Engine(결정론적 FDC) + ML predictor(보조 신호)만 실행
- 라우팅 규칙(R-1~R-F) 적용 후 결과 반환

**`/health` 응답의 `mode` 필드:**

| 상태 | HTTP | `mode` | readiness probe |
|------|------|--------|----------------|
| Ollama + ChromaDB 정상 | 200 | `"full"` | ✅ 통과 |
| Ollama 불능 (ChromaDB 정상) | 200 | `"rule-only"` | ✅ 통과 (폴백 서빙 가능) |
| ChromaDB 불능 | 503 | — | ❌ 차단 |

**관련 파일:** `pipeline/forge_pipeline.py:run_rule_only()`, `api/routes.py:/analyze`, `tests/test_failsafe.py`
