# ForgeAI

> **제조 설비 센서 로그 기반 FDC·RCA 멀티에이전트 시스템**  
> 이상 탐지(rule engine) → 근본원인분석(LLM ReAct) → SOP 검색(RAG) → 조치계획 생성 → 할루시네이션 검증까지  
> 외부 API 없이 온프레미스 LLM(Ollama)만으로 완결하는 폐쇄망 대응 설계.

---

## 1. 이 시스템이 푸는 제조 문제

**핵심:** "센서 이상을 탐지하는 것"과 "왜 이상인지, 어떻게 대응할지 설명하는 것"은 서로 다른 문제다.

FDC(Fault Detection & Classification) 단계에서는 임계값 기반 rule engine이 수ms 안에 고장 여부와 고장 모드(TWF/HDF/PWF/OSF)를 결정한다.  
RCA(Root Cause Analysis) 단계에서는 LLM 에이전트가 복수 센서 조합을 해석하고, SOP 문서에 근거한 조치 계획을 생성한다.  
두 레이어를 분리해 "예측 정확도"와 "운영 설명 가능성"을 함께 확보하는 것이 이 프로젝트의 핵심 설계 목표다.

---

## 2. 문제 정의 — 왜 어려운가

| 문제 | 구체 증거 (AI4I 2020 기준) |
|------|--------------------------|
| **클래스 불균형** | 고장 339 / 정상 9,661 = 3.39%. "항상 정상" dummy가 Accuracy 96.6%지만 고장 Recall 0.000 |
| **비용 비대칭 (FN ≫ FP)** | 미탐(FN) → 설비 파손·부상·라인 정지. 과탐(FP) → 점검 비용. 임계값은 Recall 우선 |
| **다중 센서 조합 고장** | HDF는 개별 센서가 정상 범위 내에도 (ΔT < 8.6K AND rpm < 1380) 동시 충족 시 발생 |
| **RNF 예측 불가** | Random Failure는 정의상 센서 패턴과 무관 → 정형 분류기의 구조적 한계 |
| **라벨 불일치** | Machine failure=1 이지만 5개 고장 모드 플래그가 전부 0인 행이 일부 존재 |
| **LLM 신뢰성** | LLM 조치계획이 SOP에 근거하지 않으면 현장에서 위험. 할루시네이션 정량 검증 필요 |
| **폐쇄망 제약** | 데이터가 외부로 나갈 수 없는 공장 환경 → 외부 API 불가, 온프레미스 전제 |

---

## 3. 아키텍처 개요

```
[DIAGRAM: 데이터 흐름 + 에이전트 파이프라인]

EquipmentLog (센서 5종 + 태그)
        │
        ▼
┌──────────────────────────────────────────────┐
│  rule_engine.assess_risk()                   │  ← 구현 완료
│  + classify_failure_type()                   │  AI4I 2020 조건식 기반 결정론적 FDC
│  (core/rule_engine.py)                       │  TWF/HDF/PWF/OSF/NONE, 수ms, LLM 0회
│                                              │  우선순위: PWF > OSF > HDF > TWF (안전 트리아지)
└──────────────────────────────────────────────┘
        │
        ├── SAFE (AI4I 기준 ~96.6%) ──────────────────────────────────▶ END (early exit)
        │
        └── WARNING / CRITICAL + failure_type
                │
                ▼
        ┌──────────────────────────┐
        │  PerceptionAgent         │  ← 구현 완료
        │  (agents/perception_agent│  센서 값 분석, AnomalyReport 생성, LLM 1회
        └──────────────────────────┘
                │
                ├── 이상 없음 ────────────────────────────────────────▶ END
                │
                └── 이상 있음
                        │
                        ▼
                ┌──────────────────────────┐
                │  DiagnosticAgent         │  ← 구현 완료
                │  (agents/diagnostic_agent│  LangChain bind_tools() + 수동 ReAct
                │                          │  도구: get_sensor_thresholds,
                │                          │        calculate_risk_index,
                │                          │        alert_maintenance_team (최대 5회 루프)
                └──────────────────────────┘
                        │
                        ▼
                ┌──────────────────────────────────────────────────────┐
                │  SOPRAGAgent (agents/sop_rag_agent.py)               │  ← 구현 완료
                │  ChromaDB where={"failure_type": ...} 필터 + 폴백    │  LLM 0회 (임베딩만)
                └──────────────────────────────────────────────────────┘
                        │
                        ▼
                ┌──────────────────────────────────────────────────────┐
                │  ActionPlanAgent (agents/action_plan_agent.py)       │  ← 구현 완료
                │  SOP 기반 조치계획 생성, failure_type별 addendum 주입 │  LLM 1회
                └──────────────────────────────────────────────────────┘
                        │
                        ▼
                ┌──────────────────────────┐
                │  HallucinationValidator  │  ← 구현 완료 (임계값 튜닝 중)
                │  (agents/hallucination_  │  단계별 코사인 유사도 vs SOP 청크
                │   validator.py)          │  APPROVE(≥0.85) / REVIEW(≥0.60) / REJECT
                └──────────────────────────┘
                        │
                        ├── APPROVE / REVIEW ─────────────────────────▶ PipelineResult
                        └── REJECT & retry < MAX ─────────────────────▶ ActionPlanAgent (재시도)

```

### 미구현 / 골격 상태

| 항목 | 현재 상태 |
|------|----------|
| SECOM 데이터셋 통합 | 탐색 스크립트 작성까지 완료, ML 파이프라인 미통합 |
| 확률 보정 (calibration) | 미구현 — ADR-004 참조 |
| 다중 레이블 failure_type | `get_all_triggered_failure_types()` 구현됨, 파이프라인 미연결 |
| 실시간 스트리밍 | CSV replay 평가 도구(stream_simulator.py)만 구현, Kafka 미연결 |
| Provenance lineage 체계 | ADR-014 측정 정의 완료, 감사 쿼리 인터페이스 미구현 |

---

## 4. 핵심 설계 결정 인덱스

| ADR | 결정 | 상태 |
|-----|------|------|
| [ADR-001](docs/adr/ADR-001-ai4i-to-secom-dataset.md) | 검증 데이터 AI4I → SECOM 이전 방향 | 검토중 |
| [ADR-002](docs/adr/ADR-002-time-based-split.md) | 훈련/검증 분할 방식 (stratify 현재 적용, 시간순 이전 논의) | 검토중 |
| [ADR-003](docs/adr/ADR-003-eval-metric-operating-point.md) | 평가지표 PR-AUC + Recall, accuracy 배제, 운영점 설정 | 채택 |
| [ADR-004](docs/adr/ADR-004-probability-calibration.md) | 확률 보정 도입 여부·방식 | 검토중 |
| [ADR-005](docs/adr/ADR-005-classical-ml-vs-llm-separation.md) | 예측은 고전 ML / LLM은 RCA·운영 레이어 분리 | 채택 |
| [ADR-006](docs/adr/ADR-006-rag-source-vector-separation.md) | RAG 원본 문서와 벡터 분리로 임베딩 모델 교체 흡수 | 채택 |
| [ADR-007](docs/adr/ADR-007-provenance-lineage-structure.md) | Provenance/lineage 기록 구조 | 검토중 |
| [ADR-008](docs/adr/ADR-008-agent-decision-stability.md) | 에이전트 결정 안정성 (비결정성 제어 방식) | 검토중 |
| [ADR-009](docs/adr/ADR-009-agent-authority-boundary.md) | 에이전트 권한 경계 및 에스컬레이션 정책 | 검토중 |
| [ADR-010](docs/adr/ADR-010-model-comparison-protocol.md) | 모델 비교·선택 프로토콜 (동일 조건 원칙) | 채택 |
| [ADR-011](docs/adr/ADR-011-deployment-gate.md) | 배포 게이트(승격 기준) 정의 | 채택 |
| [ADR-012](docs/adr/ADR-012-data-validation-gate.md) | 데이터 검증 단계 (서빙 전 품질 게이트) | 검토중 |
| [ADR-013](docs/adr/ADR-013-training-serving-skew.md) | training-serving skew 방지 (학습/서빙 전처리 일치) | 검토중 |
| [ADR-014](docs/adr/ADR-014-traceability-coverage-metric.md) | 근거 추적 % 측정 정의 (분모·분자·SAFE early-exit 처리) | 채택 |

---

## 5. 데이터 & 평가 설계

### 데이터셋

**현재 검증 데이터:** UCI AI4I 2020 Predictive Maintenance (`data/raw/ai4i2020.csv`)  
- 10,000행, 피처 6개 (Type, Air temp, Process temp, RPM, Torque, Tool wear)  
- 고장 339건 (3.39%), 정상:고장 ≈ 28.5:1  
- 고장 모드 5종 레이블 포함 (TWF/HDF/PWF/OSF/RNF)

**누수 방지 (A — 확정):**  
TWF/HDF/PWF/OSF/RNF 5개 컬럼은 타깃(`Machine failure`)에서 파생된 변수이므로 입력 피처에서 완전 제거. `baseline_classifier.py`에서 assert로 가드레일 추가.  
UDI/Product ID는 행 식별자이므로 제거.  
→ 포기한 것: 고장 모드별 분류기 훈련 불가. 보완: rule engine이 AI4I 2020 조건식으로 직접 분류.

### 훈련/검증 분할 (→ ADR-002)

현재: `stratify=y` 랜덤 분할 (test_size=0.2, random_state=42).  
시간순 분할이 배포 현실에 더 가깝지만 AI4I 2020에는 타임스탬프가 없어 적용 불가.  
ADR-002에 상세 트레이드오프 기록.

### 평가지표 선택 (A — 확정)

**헤드라인 지표: PR-AUC + 고장 클래스 Recall**

| 지표 | 이유 |
|------|------|
| PR-AUC | 불균형 클래스에서 ROC-AUC보다 민감. Dummy가 PR-AUC 0.034 vs ROC-AUC ~0.50 |
| 고장 Recall | FN(미탐) 비용이 FP(과탐) 비용보다 훨씬 크다 — 미탐 = 설비 파손 / 과탐 = 점검 비용 |
| Accuracy 배제 | "항상 정상" dummy가 96.6% — 클래스 불균형 환경에서 무의미 |

**운영점(operating point):** 임계값 **0.10**, Recall **0.809** / Precision **0.567**

| 임계값 | Recall | Precision | F1 | 가중비용(FN×10+FP) | 비고 |
|--------|--------|-----------|----|--------------------|------|
| 0.05 | 0.809 | 0.483 | 0.604 | 189 | |
| **0.10** | **0.809** | **0.567** | **0.667** | **172** | **← 선택 (Recall≥0.80 최저비용)** |
| 0.30 | 0.794 | 0.684 | 0.735 | 165 | 가중비용 절대 최소 |
| 0.50 | 0.779 | 0.726 | 0.752 | 170 | 기본값 |
| 0.75 | 0.735 | 0.848 | 0.787 | 189 | F1 최대 |

**선택 근거:** FN(미탐) 비용이 FP(과탐)의 10배인 제조 환경에서, 달성 가능한 최대 Recall(0.81)을 유지하면서 가중 비용을 최소화하는 지점. Recall 0.90 이상은 RNF(랜덤 고장)의 구조적 한계로 불가 — 상세: `scripts/operating_point_analysis.py`

### 확률 보정 (→ ADR-004)

트리 앙상블은 예측 확률이 실제 빈도와 어긋나는 경향이 있다.  
현재 미구현. ADR-004에 Platt scaling vs isotonic regression 선택 논의 기록.

---

## 6. ML 베이스라인 vs LLM 에이전트

### "왜 XGBoost로 충분하지 않은가"에 대한 정직한 답

| 레이어 | 담당 | 근거 |
|--------|------|------|
| **이상 탐지** (탐지: 고장 여부) | rule engine + 정형 ML | 수치 비교·패턴 인식 — 빠르고 감사 가능 |
| **FDC** (분류: 어떤 고장) | rule engine (AI4I 조건식) | 도메인 조건식이 명확히 존재 |
| **RCA** (추론: 왜 고장) | LLM (DiagnosticAgent) | 복수 센서 조합 해석, 자연어 표현 필요 |
| **SOP 검색** | RAG (벡터 유사도) | 문서-쿼리 매칭, LLM보다 빠르고 근거 추적 가능 |
| **조치계획 생성** | LLM (ActionPlanAgent) | SOP 이해 + 상황 맞춤 절차 생성 |
| **근거 검증** | 임베딩 코사인 유사도 | 수치 계산 — LLM 불필요 |

**XGBoost의 한계:**
1. **RNF 예측 불가** — Random Failure는 정의상 센서 패턴과 무관. baseline에서도 이 구조적 한계 확인됨.
2. **설명 불가** — "PWF 위험" 분류 후 "이 상황에서 구체적으로 무엇을 먼저 해야 하는가"는 SOP를 이해하고 상황에 맞게 절차를 생성해야 한다.
3. **문서 연결 불가** — 조치계획 각 단계를 SOP 특정 청크에 연결하는 것은 정형 분류기의 역할이 아니다.

**LLM을 쓰지 않는 곳:**
- 센서 임계값 초과 판단 (rule engine)
- 고장 모드 분류 (rule engine 조건식)
- 근거 검증 (코사인 유사도)
- SOP 검색 자체 (벡터 검색)

XGBoost PR-AUC 0.830은 "이상 가능성"을 수치로 잡는 데는 강력하지만, 이후 운영자가 필요한 것(왜, 무엇을, 어떤 순서로)은 LLM이 담당한다. 두 레이어는 경쟁이 아니라 분업이다.

### 실측 베이스라인 수치

**데이터:** AI4I 2020, 10,000행, test_size=0.2, stratify=y, random_state=42  
**피처 엔지니어링·하이퍼파라미터 튜닝 없음** (raw baseline)

| 모델 | PR-AUC | 고장 Recall | 고장 Precision | 고장 F1 |
|------|--------|------------|---------------|---------|
| Dummy (항상 정상) | 0.034 | 0.000 | 0.000 | 0.000 |
| Random Forest (`class_weight='balanced'`) | 0.783 | 0.721 | 0.766 | 0.742 |
| **XGBoost** (`scale_pos_weight=28.52`) | **0.830** | **0.779** | **0.747** | **0.763** |

`scripts/baseline_classifier.py`로 재현 가능.

### 모델 검증 & 선택 프로토콜

"더 좋은 모델"이라는 주장은 **동일 데이터 분할 · 동일 지표 · 동일 운영점**에서의 비교로만 성립한다.  
훈련셋, 임계값, 전처리 방식 중 하나라도 다른 조건 간 수치 비교는 무효이며 이를 명시적으로 문서화한다.

#### 후보 비교 (동일 조건: test_size=0.2, stratify=y, random_state=42, threshold=0.5)

| 모델 | PR-AUC | 고장 Recall | 고장 Precision | 고장 F1 | ECE | 추론시간(ms) |
|------|--------|------------|---------------|---------|-----|------------|
| Dummy (항상 정상) | 0.034 | 0.000 | 0.000 | 0.000 | [___] | < 1 |
| Random Forest (`class_weight='balanced'`) | 0.783 | 0.721 | 0.766 | 0.742 | [___] | [___] |
| **XGBoost** (`scale_pos_weight=28.52`) | **0.830** | **0.779** | **0.747** | **0.763** | [___] | [___] |

*ECE(Expected Calibration Error): 확률 보정 실험 후 채운다. → ADR-004*  
*추론시간: 서빙 통합 후 측정 예정.*

#### 최종 모델 선택 근거: XGBoost

| 기준 | XGBoost | Random Forest | 판정 |
|------|---------|--------------|------|
| 예측 정확도 (PR-AUC) | **0.830** | 0.783 | XGBoost +0.047 |
| 해석가능성 | feature importance, SHAP 호환 | 동일 | 동등 |
| 불균형 제어 | `scale_pos_weight = N_neg / N_pos` 공식 적용 | `class_weight='balanced'` | 동등 |
| 재학습 용이성 | 새 데이터셋에서 `scale_pos_weight` 재계산만으로 적응 | 동일 | 동등 |
| 폐쇄망 호환 | ✓ | ✓ | 동등 |

PR-AUC 우위(+0.047)가 결정적 근거다. 해석가능성·재학습 용이성은 두 모델이 동등하므로 정확도 차이로 선택한다.  
LightGBM 등 추가 후보를 비교할 경우 반드시 동일 분할·동일 조건에서 측정 후 이 표를 확장한다.

### 배포 게이트 (승격 기준)

"이 모델을 배포해도 되는가"를 사람의 감이 아닌 **사전 정의 기준**으로 판단한다.  
모델 교체·재학습 시 아래 게이트를 모두 통과해야 배포를 승인한다. 하나라도 실패하면 이전 버전을 유지한다.

```
배포 승인 조건 (AND 전부 충족):
  PR-AUC         ≥ 0.827    ← 현재 XGBoost 기준선 (scripts/operating_point_analysis.py)
  운영점 Recall  ≥ 0.800    ← 임계값 0.10 적용 시 달성, Precision 0.567
                               RNF 구조적 한계로 0.90 불가 — FN/FP 비용비 10:1 기준 최적 지점
  ECE            ≤ [___]    ← 확률 보정 실험 후 (ADR-004)
  재현성 확인               ← 동일 시드·동일 데이터에서 수치 일치 확인
  회귀 테스트 통과          ← 이전 버전 대비 핵심 지표 하락 없음 (scripts/regression_test.py)
  → 모두 충족 시 배포 승인
```

이 게이트는 **모델 변동성의 방어선**이다.  
게이트 없이 배포하면 "이전보다 나빠졌는가"를 사후에야 알 수 있다.  
운영 중 재학습이 반복될수록 이 기준이 회귀를 막는 유일한 자동 장치가 된다. → ADR-011

### 재현성 & 회귀 테스트

| 항목 | 상태 | 방법 |
|------|------|------|
| 동일 시드 → 동일 결과 | **(가) 확인됨** | `random_state=42` 고정. `scripts/baseline_classifier.py` 재실행 시 수치 일치 |
| 피처 누수 가드레일 | **(가) 확인됨** | `assert set(LEAK_COLS).isdisjoint(X.columns)` — 타깃 파생 컬럼 진입 차단 |
| 이전 버전 대비 지표 회귀 점검 | **(나) 계획됨** | `scripts/regression_test.py` — 신규 버전 PR-AUC가 기준선 미달 시 배포 차단 |
| SECOM 시간순 분할 재현성 | **(나) 계획됨** | 타임스탬프 기반 80/20, 시드 독립적으로 동일 결과 |

*(가) 구현·확인 완료 / (나) 계획됨 (스크립트 미작성) / (다) 미계획*

---

## 7. RAG & 모델 변동성 관리

### 임베딩 구성

| 항목 | 값 | 결정 이유 |
|------|----|----------|
| 임베딩 모델 | `nomic-embed-text` (Ollama) | 768-dim, cosine space, 온프레미스 |
| 청킹 단위 | paragraph-based, 1,024자 / overlap 200자 | 영어는 동일 내용에 2~3배 문자 사용 — 512는 문맥 파괴 |
| 청킹 방식 | `\n\n` 단락 분할 후 문자 초과 시 문장 분할 | 문단 경계 보존 우선 |
| 벡터 스토어 | ChromaDB (cosine, 로컬 영구 저장) | 폐쇄망, 소규모 SOP 문서, 외부 의존성 없음 |
| failure_type 필터 | `where={"failure_type": {"$in": [...]}}` + 폴백 | 관련 없는 SOP 간 유사도 오염 방지 |

### 원본 문서와 벡터의 분리 (임베딩 모델 교체 흡수 설계)

```
data/sop_docs/*.md          ← 원본 (truth source, git 관리)
        │  ingest_document() 호출
        ▼
HTML 주석 제거 전처리
        │
        ▼  nomic-embed-text로 임베딩
data/chroma/                ← 파생물 (ChromaDB 벡터)
  chroma.sqlite3
  {collection_uuid}/
```

원본 `.md` 파일은 영어 본문 + `<!-- 한국어 -->` 주석 구조로 보존된다.  
임베딩에는 HTML 주석 제거 후 영어 텍스트만 사용 (`re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)`).

**임베딩 모델 교체 시:** ChromaDB를 삭제하고 `./scripts/reindex.sh`를 실행하면  
원본 `.md` 파일로부터 새 모델로 재임베딩된다. 원본 문서를 재작성할 필요가 없다.  
→ 모델 교체가 재앙이 아닌 배치 작업이 되는 이유는 원본과 벡터의 분리 때문이다.

### Provenance 추적

각 청크에는 chunk_id(`{filename}::chunk::{index}`), 문서명, 페이지 번호, 인덱싱 시각이 메타데이터로 기록된다.  
조치계획 각 단계의 `sop_reference` 필드에 chunk_id가 저장되어 "이 조치 단계의 근거는 어느 SOP 문서의 몇 번째 청크인가"를 추적할 수 있다.  
감사 쿼리 인터페이스는 미구현 — ADR-007 참조.

---

## 8. 에이전트 운영 안정성 (Agent Operational Reliability)

> **핵심 주장:** LLM 에이전트는 비결정적이다. 그걸 제조 운영에 올릴 수 있게 만든 안정성 장치들.

제조 현업이 AI 에이전트를 불신하는 지점은 명확하다: "같은 이상이 들어와도 다른 판단이 나올 수 있다."  
이 시스템은 그 비결정성을 부정하지 않는다. 대신 네 층의 안정성 장치로 제어 가능한 범위 안에 묶는다.

---

### 기둥 1: 결정 안정성 (비결정성 대응)

**위협:** 동일한 센서 이상이 들어와도 에이전트가 다른 분기·조치를 출력할 수 있다.  
온도(temperature)가 높거나 시드가 없으면 LLM 출력이 호출마다 달라진다.

**대응:**
- **온도 고정 (`temperature=0`):** 샘플링 분산을 제거해 동일 입력 → 동일 출력을 최대화
- **구조화 출력:** ActionPlan을 Pydantic 스키마로 강제해 자유 텍스트 변동을 차단
- **분기 규칙화:** `risk_level` / `failure_type` 판정은 rule engine이 결정론적으로 수행 — LLM에 위임하지 않음 (ADR-005)
- **최대 루프 횟수 고정:** DiagnosticAgent tool use 최대 5회, ActionPlanAgent 재시도 최대 3회

**측정 (30-run 실측, 6 stratum × 5회):**

| 지표 | 값 | 판정 기준 |
|------|-----|----------|
| has_anomaly 일관성 | **100.0%** | ✅ |
| route 일관성 | **96.7%** | ❌ (≥99% 미달, TWF 층 분기) |
| recommendation 일관성 | **96.0%** | ❌ (≥99% 미달) |
| grounding_score σ 평균 | **0.0347** | — |

TWF 층에서 1건 분기 발생 (LLM 비결정성 잔존). 상세: [`docs/consistency_report.md`](docs/consistency_report.md) → ADR-008

---

### 기둥 2: 권한 경계 (Governance)

**위협:** 에이전트가 해선 안 될 자동 조치를 실행한다. 오탐으로 라인이 정지되거나,  
grounding_score가 낮은 조치계획이 그대로 현장에 내려간다.

**대응:**
- **신뢰도 임계 기반 자동 분기:**

  ```
  grounding_score ≥ 0.85  → APPROVE  (자동 전달 가능 범위)
  grounding_score ≥ 0.60  → REVIEW   (사람 확인 에스컬레이션)
  grounding_score < 0.60  → REJECT   → ActionPlanAgent 재시도 (최대 3회)
  재시도 소진 후 REJECT   → 운영자에게 에스컬레이션, 자동 조치 차단
  ```

- **C++ 어댑터 dry-run 강제:** 산업제어 명령 실행 레이어는 live write가 기본 차단
- **에스컬레이션 로그:** 모든 REVIEW/REJECT 케이스는 correlation_id와 함께 기록

**측정:** 자동화율(APPROVE) `[___]%` / 에스컬레이션(REVIEW+REJECT) `[___]%` → 레이어3 / ADR-009 참조

---

### 기둥 3: 추적·감사 (Provenance)

**위협:** "왜 그 판단을 했는가"를 사후에 재구성할 수 없으면 사고 조사·규제 감사가 불가능하다.  
운전자가 조치계획을 따르다 이상이 생겼을 때 책임 소재를 추적할 수 없다.

**대응:** 입력 센서값부터 최종 조치계획까지 전 단계를 연결하는 lineage 구조 (ADR-007):

```
EquipmentLog (센서값 + 타임스탬프)
  → RiskAssessment (risk_level, failure_type, 초과 임계값)
    → SOPContext (검색된 chunk_id, 문서명, 페이지)
      → ActionPlan.steps[N].sop_reference (= chunk_id)
        → ValidationResult.step_validations[N].grounding_score
          + correlation_id → Langfuse 스팬
```

**측정:** "결과에서 원본 SOP 청크까지 역추적 가능" 비율 → ADR-014 기준 정의 완료, `scripts/measure_traceability.py`로 측정 가능. 4개 요건(센서값·rule 판정·SOP chunk_id·grounding_score) 전부 충족 시 추적 가능으로 판정, 종료 코드로 ≥80% 기준 자동 판별. 상세: [`docs/traceability_walkthrough.md`](docs/traceability_walkthrough.md) → ADR-014

현재 추적 가능한 것과 불가능한 것의 상세는 → [9. DataOps & Provenance](#9-dataops--provenance)

---

### 기둥 4: 입력·모델 안정성 (서빙 전제)

**위협:** 오염된 센서 데이터 또는 조용히 교체된 모델이 에이전트 전체 출력을 망친다.  
에이전트 자체는 정상이어도 입력이 이미 쓰레기면 판단을 신뢰할 수 없다.

**대응 (세 겹의 방어선):**

| 방어선 | 역할 | ADR |
|--------|------|-----|
| 데이터 검증 게이트 | 스키마·범위·결측 — 오염 데이터의 파이프라인 진입 차단 | ADR-012 |
| 배포 승격 기준 | PR-AUC·Recall·ECE·재현성 — 열등한 모델의 서빙 진입 차단 | ADR-011 |
| training-serving skew 방지 | 학습/서빙 전처리 일치 — 조용한 성능 괴리 차단 | ADR-013 |

**측정:** 각 게이트의 통과 기준값 및 차단율 → 레이어3 참조  
상세 흐름 → [10. 데이터 수집·분석 파이프라인](#10-데이터-수집분석-파이프라인-서비스-관점)

---

## 9. DataOps & Provenance

### 현재 구현된 lineage 구조

```
원본 신호              파생물                    결과
SOP-MNT-001.md  →  chunk::2 (1024자)  →  ActionPlan.step[1].sop_reference
                    + 임베딩 벡터           "SOP-MNT-001.md::chunk::2"
                    + 메타데이터
                      {failure_type: TWF,
                       ingested_at: ...,
                       document_name: ...}
```

각 에이전트 호출에는 `correlation_id`가 전파되고 Langfuse에 스팬으로 기록된다.  
결과(`action_plan`, `grounding_score`)에서 근거(`sop_reference` chunk_id)까지는 추적 가능하나,  
chunk_id → 원본 문서 특정 위치 → 센서 값 → 어떤 임계값에 의해 해당 SOP가 검색됐는지를  
단일 조회로 확인하는 감사 인터페이스는 미구현이다.

### DataOps 관점에서 왜 원본-벡터 분리가 자산화인가

SOP 문서는 설비 도메인 지식의 명시적 자산이다.  
벡터는 특정 임베딩 모델로 만든 파생물이고, 모델이 바뀌면 재생성해야 한다.  
원본을 파생물과 섞어 관리하면 모델 교체 시 "무엇이 진짜 문서인가"를 알 수 없게 된다.  
원본을 git 관리 하에 두고, ChromaDB는 재생성 가능한 캐시로 취급하는 것이 자산화의 기초다.

---

## 10. 데이터 수집·분석 파이프라인 (서비스 관점)

DataOps/8번 섹션이 "데이터 자산화 및 lineage 추적"을 다룬다면,  
이 섹션은 **서비스로 데이터가 유입되어 예측기에 도달하기까지의 흐름**을 서술한다.

### 수집: 데이터 유입 경로

```
[실시간 경보]  →  FastAPI POST /analyze          ← 현재 구현 (EquipmentLog JSON)
[배치 replay]  →  scripts/stream_simulator.py    ← CSV row→row 재현 (Kafka 미연결)
[미래 확장]    →  Kafka topic / gRPC stream      ← 계획됨 (ADR에 연결 방식 미결정)
```

현재 구현 범위: FastAPI `/analyze` 엔드포인트가 `EquipmentLog` JSON을 수신하면  
rule engine → 에이전트 파이프라인 순으로 흐른다.  
실시간 스트리밍(Kafka)은 `stream_simulator.py`의 CSV 재현으로 대체하며 실제 브로커 연결은 미구현이다.

### 데이터 검증: 모델 진입 전 품질 게이트

"쓰레기가 들어가면 쓰레기가 나온다(GIGO)." 센서 데이터는 결측·범위 이탈·스키마 변화가 빈번하다.  
검증을 통과하지 못한 데이터는 예측기에 도달하지 않는다.

| 검증 항목 | 기준 | 현재 상태 |
|-----------|------|----------|
| 스키마 확인 | 필수 필드(air_temp, process_temp, rpm, torque, tool_wear) 존재 | (나) 계획됨 |
| 범위 검사 | 각 센서 정상 범위 내 (예: rpm 0–3500, tool_wear 0–300) | (나) 계획됨 |
| 결측 처리 | 단일 행 결측 → imputation or 거부; 모든 센서 결측 → 거부 | (나) 계획됨 |
| 이상치 탐지 | 3σ 이탈 시 경고 플래그 (예측은 계속, 로그 기록) | (다) 미계획 |

→ 구체적 구현 방침: ADR-012

### 분석 → 모델 연결: end-to-end 흐름

```
수집 (FastAPI)
    │
    ▼  [데이터 검증 게이트]  ← ADR-012
    │  스키마·범위·결측 체크
    │  실패 시 → 400 오류 + 로그 기록, 예측 파이프라인 진입 차단
    ▼
rule_engine.assess_risk()          ← 전처리 없음, raw 센서값 직접 사용
    │
    ▼ (WARNING/CRITICAL 시에만)
정형 ML (XGBoost)                  ← 학습 시 전처리와 동일한 피처 스펙 필요 (ADR-013)
    │
    ▼
에이전트 파이프라인 (PerceptionAgent → DiagnosticAgent → SOPRAGAgent → ActionPlanAgent)
    │
    ▼
PipelineResult (JSON 응답 + lineage 로그)
```

### 학습-서빙 일관성 (training-serving skew 방지)

학습 시와 서빙 시의 전처리가 달라지면 모델 성능이 학습 수치와 乖離된다.  
이를 **training-serving skew**라 하며, 제조 AI에서 가장 자주 발생하는 운영 오류 중 하나다.

| 항목 | 학습 시 | 서빙 시 (현재 설계) | 일치 여부 |
|------|---------|------------------|----------|
| 피처 목록 | air_temp, process_temp, rpm, torque, tool_wear, type_encoded | 동일 필드 수신 | (나) 스펙 문서화 필요 |
| 결측 처리 | median imputation (훈련셋 기준 median) | 동일 median 재사용 | (나) median 값 저장·로드 필요 |
| 스케일링 | 없음 (트리 계열) | 없음 | (가) 일치 |
| 누수 컬럼 제거 | LEAK_COLS assert | 서빙 시 수신 안 함 (FastAPI 스키마) | (나) 스키마 가드 명시 필요 |

현재 ML 모델은 파이프라인에 서빙 통합 전(오프라인 베이스라인 단계)이므로 skew 위험이 잠재적이다.  
통합 시점에 median 값과 피처 목록을 모델 아티팩트와 함께 저장해야 한다. → ADR-013

---

## 11. 한계 & 다음 단계

### 현재 한계 (솔직하게)

| 한계 | 설명 |
|------|------|
| **AI4I 단일 데이터셋 의존** | 10,000행, 실험실 시뮬레이션 데이터. 실공장 센서 드리프트·노이즈 미반영 |
| **시간순 분할 없음** | 타임스탬프 없어 stratify 랜덤 분할 — 배포 후 concept drift 탐지 불가 |
| **SECOM 미통합** | 고차원(590피처, 결측 다수) 반도체 공정 데이터 탐색까지만 진행 |
| **확률 보정 없음** | XGBoost 출력 확률이 실제 빈도와 어긋날 수 있음 — 임계값 설정 불신뢰 |
| **grounding_score 0.70~0.74 고착** | nomic-embed-text의 paraphrase 유사도 범위 특성. APPROVE 기준 0.85 미달로 전부 REVIEW |
| **C++ 어댑터 dry-run 전용** | live hardware write 차단 설계 — 실제 PLC 연동 없음 |
| **RNF 예측 불가** | 구조적 한계. 센서 패턴 없는 랜덤 고장은 어떤 분류기로도 불가 |

### 다음 단계

| # | 항목 | 상태 |
|---|------|------|
| 1 | **SECOM 베이스라인** — 590피처 결측 처리 + 수율 예측 PR-AUC 측정 → ADR-001 빈칸 채우기 | 탐색 완료, ML 통합 미완 |
| 2 | **운영점 설정** — recall/precision 트레이드오프 곡선 → 임계값 결정 | 미완 |
| 3 | **확률 보정** — Platt scaling or isotonic regression 실험 → ADR-004 | 미완 |
| 4 | **grounding_score 개선** — cited chunk 직접 비교 | 미완 |
| 5 | **감사 인터페이스** — correlation_id → 단일 조회 구현 | 미완 |
| 6 | **일관성 TWF 분기 원인 분석** — TWF 층 route 80% 분기 재현 및 온도 고정 보완 | 미완 |
| 7 | **근거 추적 % 실측** — `measure_traceability.py` 실행 후 ADR-014 ≥80% 달성 확인 | 미완 |

---

## 12. 실행 방법

### 사전 요구사항

```bash
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

### 설치

```bash
git clone https://github.com/enjoylonelines/ForgeAI.git
cd ForgeAI

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
```

### 서버 실행

```bash
uvicorn main:app --reload
# http://localhost:8000
```

### SOP 문서 초기 인덱싱

```bash
./scripts/reindex.sh
```

### ML 베이스라인 재현

```bash
python scripts/baseline_classifier.py
```

### C++ 산업제어 어댑터 빌드

```bash
./scripts/build_control_adapter.sh
```

응답 예시:

```json
{
  "correlation_id": "abc123",
  "risk_assessment": {
    "risk_level": "CRITICAL",
    "risk_factors": [{"sensor": "tool_wear_min", "value": 216.0, "threshold": 220.0}]
  },
  "anomaly_report": {
    "has_anomaly": true,
    "summary": "Tool wear (216 min) approaching failure threshold. Type: TWF."
  },
  "diagnostic_result": {
    "tool_calls": [
      {"tool": "get_sensor_thresholds", "args": {"equipment_type": "M"}},
      {"tool": "calculate_risk_index",  "args": {"tool_wear_min": 216.0, "torque_nm": 42.8, "rotational_speed_rpm": 1251.0}},
      {"tool": "alert_maintenance_team","args": {"equipment_id": "M-12345", "severity": "CRITICAL", "message": "..."}}
    ]
  },
  "action_plan": {
    "steps": ["Stop machine immediately", "Inspect tool wear", "..."]
  },
  "validation_result": {
    "overall_grounding_score": 0.731,
    "recommendation": "REVIEW",
    "is_valid": false
  },
  "metrics": {
    "risk_level": "CRITICAL",
    "early_exit": false,
    "retry_count": 0,
    "stages_completed": ["risk_assessment", "perception", "diagnostic", "sop_rag", "action_plan", "validator"]
  }
}
```

응답 헤더:
- `X-Plan-Status: APPROVED` — grounding_score ≥ 0.75
- `X-Plan-Status: REVIEW` — grounding_score < 0.75, 사람 검토 권고
- `X-Plan-Status: REJECTED` — 최대 재시도 후에도 검증 실패

### 자연어 진단 — `POST /api/v1/diagnose`

사용자가 체감한 이상 증상을 자연어로 입력하면 에이전트가 관련 SOP를 검색해 진단 응답을 생성합니다.

```bash
curl -s -X POST http://localhost:8000/api/v1/diagnose \
  -H "Content-Type: application/json" \
  -d '{"query": "장비 M-12345에서 진동이 심하고 온도가 올라가는데 무슨 문제인가요?"}' \
  | python3 -m json.tool
```

### C++ 산업제어 dry-run — `POST /api/v1/control/plan`

SOP 검증을 통과하거나 REVIEW로 분기된 `action_plan`을 C++ 제어 어댑터에 dry-run으로 전달합니다.

```bash
curl -s -X POST http://localhost:8000/api/v1/control/plan \
  -H "Content-Type: application/json" \
  -d '{
    "dry_run": true,
    "action_plan": {
      "equipment_id": "M-12345",
      "generated_at": "2026-06-06T00:00:00Z",
      "steps": [
        {
          "step_number": 1,
          "action": "Stop machine immediately after current cycle",
          "responsible_role": "maintenance_technician",
          "priority": "P1",
          "estimated_duration_minutes": 5,
          "sop_reference": "SOP-MNT-001.md::chunk::2"
        },
        {
          "step_number": 2,
          "action": "Remove and inspect tool for wear",
          "responsible_role": "maintenance_technician",
          "priority": "P1",
          "estimated_duration_minutes": 15,
          "sop_reference": "SOP-MNT-001.md::chunk::3"
        }
      ],
      "escalation_required": true,
      "escalation_reason": "Tool wear is above the safe operating threshold."
    }
  }' | python3 -m json.tool
```

응답 예시:

```json
{
  "correlation_id": "abc123",
  "dry_run": true,
  "command_count": 3,
  "results": [
    {
      "equipment_id": "M-12345",
      "command_type": "STOP_MACHINE",
      "status": "accepted",
      "dry_run": true,
      "adapter": "cpp-control-adapter-v1",
      "message": "Dry-run accepted STOP_MACHINE for M-12345..."
    }
  ],
  "safety_note": "C++ adapter is wired in dry-run mode only; no PLC or actuator is modified."
}
```

### CSV 배치 분석 — `POST /api/v1/analyze/csv`

```bash
curl -s -X POST http://localhost:8000/api/v1/analyze/csv \
  -F "file=@your_logs.csv" | python3 -m json.tool
```

배치 결과 `improvement_metrics` 포함:

| 지표 | 설명 |
|------|------|
| `early_exit_rate_pct` | SAFE 판정으로 조기 종료된 비율 (LLM 호출 절감) |
| `warning_prevented_count` | WARNING 감지로 예방 조치된 건수 |
| `llm_calls_saved` | early_exit 건수 × 4 (절약된 LLM 호출 수) |
| `avg_retries_per_row` | 평균 재시도 횟수 |

### SOP 문서 인제스트 — `POST /api/v1/ingest`

```bash
curl -s -X POST http://localhost:8000/api/v1/ingest \
  -F "file=@data/sop_docs/SOP-MNT-001-tool-wear-failure.md;type=text/markdown"
```

PDF, Markdown, TXT 지원.

### 헬스 체크 — `GET /api/v1/health`

```bash
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool
```

---

## 환경 변수

`.env.example`을 복사해 `.env`로 사용:

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `OLLAMA_CHAT_MODEL` | `qwen2.5:7b` | 대화용 LLM |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | 임베딩 모델 |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | ChromaDB 저장 경로 |
| `GROUNDING_SCORE_THRESHOLD` | `0.75` | 단계별 근거 있음 판정 기준 |
| `GROUNDING_APPROVE_THRESHOLD` | `0.85` | APPROVE 판정 기준 (전체 평균) |
| `GROUNDING_REVIEW_THRESHOLD` | `0.60` | REVIEW/REJECT 경계 |
| `CHUNK_SIZE` | `1024` | RAG 청크 크기 (characters) |
| `CHUNK_OVERLAP` | `200` | 청크 간 겹침 크기 |
| `TOP_K_RETRIEVAL` | `5` | ChromaDB 상위 k 검색 수 |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse 트레이스 (선택) |
| `LANGFUSE_SECRET_KEY` | — | Langfuse 트레이스 (선택) |
| `CONTROL_ADAPTER_PATH` | `./build/control_adapter` | C++ dry-run 제어 어댑터 경로 |

---

## SOP MCP 서버

ForgeAI는 Claude Desktop/Code에서 직접 SOP 문서를 검색하고 센서 컨텍스트를 조회할 수 있는 MCP 서버를 포함합니다. 파이프라인과 엔지니어가 동일한 도구 계층을 공유하는 것이 목적입니다.

### 제공 도구

| 도구 | 설명 |
|------|------|
| `search_sop` | SOP 문서 벡터 검색. `query`, `failure_type`(TWF\|HDF\|PWF\|OSF\|RNF, 선택), `top_k`(1–5, 기본 3) |
| `get_sensor_context` | 설비 등급별 센서 정상 범위 + 리스크 지수. `equipment_type`(H\|M\|L), `tool_wear_min`, `torque_nm`, `rotational_speed_rpm` |

### Claude Desktop 연결

`~/Library/Application Support/Claude/claude_desktop_config.json`에 추가:

```json
{
  "mcpServers": {
    "forgeai-sop": {
      "command": "uv",
      "args": ["run", "python", "mcp_server/server.py"],
      "cwd": "/path/to/ForgeAI"
    }
  }
}
```

### MCP Inspector로 테스트

```bash
uv run fastmcp dev inspector mcp_server/server.py
```

브라우저에서 `http://localhost:5173` 열어 도구 호출 확인.

### 설계 근거

- **STDIO 트랜스포트**: ForgeAI 본체(FastAPI :8000)와 런타임을 분리. 인증·원격 배포 없이 로컬 사용.
- **신뢰성 3종**: Pydantic 입력 검증 + 구조화 에러(LLM 재시도 가능), 출력 토큰 예산 truncation(청크당 600자/전체 2,400자), description 버전 관리(`[v1.0.0]`).
- 상세 결정 기록: [`docs/adr_001_mcp_tool_layer.md`](docs/adr_001_mcp_tool_layer.md)

---

## 테스트

```bash
python -m pytest tests/ -v
# 26개 단위 테스트
```

### 단건 분석 (프리셋)

```bash
./scripts/analyze.sh twf    # TWF 케이스
./scripts/analyze.sh hdf    # HDF 케이스
./scripts/analyze.sh normal # 정상 (early exit 확인)
```

---

## 기술 스택

| 구성 요소 | 선택 | 비고 |
|-----------|------|------|
| LLM | `qwen2.5:7b` (Ollama) | M2 Air 8GB, 외부 API 미사용 |
| 에이전트 오케스트레이션 | LangGraph `StateGraph` | 조건 분기 + 재시도 루프 선언적 표현 |
| Tool Use | LangChain `bind_tools()` + 수동 ReAct 루프 | DiagnosticAgent, 최대 5회 |
| 임베딩 | `nomic-embed-text` (Ollama, 768-dim) | cosine space |
| 벡터 DB | ChromaDB (로컬 영구 저장) | `./data/chroma`, failure_type 메타데이터 필터 |
| 훈련 데이터 | UCI AI4I 2020 Predictive Maintenance | 10,000행, `ucimlrepo` id=601 |
| API | FastAPI + uvicorn | REST 엔드포인트 4종 |
| 산업제어 어댑터 | C++17 + Python subprocess bridge | dry-run 전용 |
| 관찰 가능성 | Langfuse | 에이전트별 트레이스, correlation_id 전파 |
| 테스트 | pytest + pytest-asyncio | 26개 단위 테스트 |

---

## 프로젝트 구조

```
ForgeAI/
├── agents/
│   ├── perception_agent.py        # 이상 감지, AnomalyReport 생성
│   ├── diagnostic_agent.py        # Tool Use / ReAct (bind_tools + 수동 루프)
│   ├── sop_rag_agent.py           # ChromaDB 검색 + failure_type where 필터 + 폴백
│   ├── action_plan_agent.py       # SOP 기반 조치계획, failure_type addendum, 재시도 피드백
│   ├── hallucination_validator.py # 임베딩 코사인 유사도 검증
│   └── intent_extraction_agent.py # 자연어 → 구조화 의도 추출
├── pipeline/
│   ├── forge_pipeline.py          # LangGraph StateGraph 메인 파이프라인
│   └── nl_diagnosis_pipeline.py   # 자연어 진단 3-노드 파이프라인
├── core/
│   └── rule_engine.py             # 결정론적 FDC: assess_risk() + classify_failure_type()
├── rag/
│   ├── ingestion.py               # HTML 주석 제거 → 청킹 → ChromaDB 적재
│   ├── chroma_client.py           # ChromaDB 연결, failure_type 필터
│   └── embedder.py                # nomic-embed-text 래퍼
├── data/
│   ├── raw/
│   │   ├── ai4i2020.csv           # UCI AI4I 2020 (10,000행)
│   │   └── secom/                 # SECOM 반도체 공정 (탐색 단계, 미통합)
│   ├── sop_docs/                  # SOP 원본 5종 (git 관리, 영어 본문 + 한국어 주석)
│   └── chroma/                    # ChromaDB 벡터 (재생성 가능한 파생물)
├── scripts/
│   ├── baseline_classifier.py     # RF + XGBoost 베이스라인 (재현 가능)
│   ├── validate_ai4i.py           # AI4I 샘플로 파이프라인 E2E 검증
│   ├── consistency_protocol.py    # 30-run 층화 일관성 프로토콜
│   ├── escalation_demo.py         # SAFE→AUTO / CRITICAL→ESCALATE 분기 재현
│   ├── promotion_gate_demo.py     # 승격 게이트: 좋은 모델 승인 / 나쁜 모델 차단
│   ├── conflict_case_reproduce.py # 판단 충돌 → 에스컬레이션 케이스 재현
│   ├── eval_routing_accuracy.py   # 라우팅 정확도 평가 (20케이스, 9개 규칙 전체)
│   └── measure_traceability.py    # 근거 추적 % 측정 (ADR-014 기준)
├── docs/
│   ├── adr/                       # 설계 결정 기록 (ADR-001 ~ ADR-014)
│   ├── consistency_report.md      # 30-run 일관성 실측 결과
│   ├── traceability_walkthrough.md # 센서값→SOP까지 6단계 완주 예시
│   └── rag-improvement.md         # RAG 개선 4회 트러블슈팅 기록
└── tests/                         # pytest 단위 테스트 (26개)
```

---

<!-- ai4i-verification-results -->

### AI4I 2020 검증 결과

| 지표 | 값 |
|------|----|
| 고장 전수 검출 | 불량 유출 7건 ❌ |
| 정상 AUTO 비율 (rule engine early-exit) | 80.0% |
| SAFE / WARNING / CRITICAL | 7,731 / 1,362 / 907 |

상세: [`docs/ai4i_verification_report.md`](docs/ai4i_verification_report.md)

---

<!-- routing-accuracy-results -->

### 라우팅 정확도 평가 결과

| 지표 | 값 |
|------|----|
| 라우팅 정확도 | 20/20 = **100.0%** |
| 커버 규칙 | R-C1, R-C2, R-1, R-2, R-3, R-4, R-5, R-6, R-F (9개 전체) |
| 우선순위 경계 케이스 포함 | 2건 (c19, c20) |

평가 데이터: [`data/routing_eval_20cases.csv`](data/routing_eval_20cases.csv) · 스크립트: [`scripts/eval_routing_accuracy.py`](scripts/eval_routing_accuracy.py)

---

## RAG 개선 기록

초기 구현에서 TWF 요청 시 HDF SOP가 1위로 검색되는 문제를 4회 반복 개선으로 해결했습니다.

| 지표 | 개선 전 | 최종 |
|------|---------|------|
| SOP 검색 1위 | HDF (0.417) | TWF (0.730) |
| grounding_score | 0.615 | 0.731 |

**적용한 개선:**

1. **SOP 영어 전환** — `nomic-embed-text` 크로스 언어 한계 해소 (한국어 원문은 HTML 주석으로 보존)
2. **chunk_size 512 → 1024** — 영어는 동일 내용에 2~3배 문자 사용, 문맥 보존
3. **failure_type 메타데이터 필터** — ChromaDB `where={"failure_type": {"$in": [...]}}` 적용, 결과 부족 시 폴백
4. **chunk_overlap 64 → 200** — 청크 경계에 위치한 절차 문장의 grounding score 개선

상세 분석 및 트레이드오프: [`docs/rag-improvement.md`](docs/rag-improvement.md)

---

## 설계 의도

### LLM을 쓰는 기준

각 컴포넌트는 **"이 판단에 언어 이해가 필요한가"** 를 기준으로 LLM 사용 여부를 결정합니다.

| 판단 유형 | 담당 | 이유 |
|-----------|------|------|
| 센서 임계값 초과 여부 | rule engine | 산술 비교, 결정적 처리 |
| 이상 패턴 원인 추론 | LLM (PerceptionAgent) | 센서 조합 해석, 도메인 언어 필요 |
| SOP 기반 조치 계획 생성 | LLM (ActionPlanAgent) | 문서 이해 + 절차 생성 |
| 근거 검증 | 임베딩 코사인 유사도 | 수치 계산, LLM 불필요 |

### 주요 설계 결정

- **LangGraph StateGraph**: 조건 분기 + 재시도 루프를 선언적으로 표현. SAFE 조기 종료로 불필요한 LLM 호출 차단
- **2-tier 처리**: rule engine(수ms) → LLM pipeline(수초). 모든 row를 LLM에 보내지 않음
- **Tool Use / ReAct**: `bind_tools()` 기반 도구 호출 루프로 에이전트가 센서 임계값 조회, 위험지수 계산, 알림 발송을 자율 수행
- **C++ 산업제어 연동**: LLM 조치 계획을 Python bridge가 안전 명령 후보로 변환하고 C++17 어댑터가 dry-run 승인. live hardware write는 의도적으로 차단
- **보수적 grounding 임계값 (0.75)**: REVIEW 판정은 버그가 아닌 안전 설계. 제조 도메인에서 false negative보다 false positive가 낫다는 판단
- **온프레미스**: Ollama만 사용, 외부 API 의존성 없음
- **트레이스 로깅**: 모든 에이전트 호출에 `correlation_id` + Langfuse 스팬 전파

### 한계 및 개선 방향

실용적 설계를 지향하지만 현재 구조에서 개선 중인 부분이 있습니다. [`docs/troubleshooting.md`](docs/troubleshooting.md) 참고.

> 이 프로젝트는 제조 도메인 멀티에이전트 RAG 시스템 포트폴리오이기도 합니다.
