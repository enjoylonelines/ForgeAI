# RAG 검색 품질 개선 트러블슈팅

## 증상

`/api/v1/analyze` TWF(Tool Wear Failure) 요청에서 다음 문제 발생:

- SOP 검색 1위가 TWF 전용 SOP가 아닌 HDF/OSF SOP
- 전체 relevance score가 0.40대로 낮고 SOP 간 점수 차이가 0.02 이하
- `overall_grounding_score: 0.615`, 5개 스텝 전부 `is_grounded: false`
- 최종 판정 `REVIEW` (임계값 0.75 미달)

---

## 원인 분석

### 원인 1 — 언어 불일치

SOP 문서는 한국어, 검색 쿼리는 영어로 생성됨.  
`nomic-embed-text`가 다국어를 지원하지만 한/영 크로스 언어 임베딩 유사도가 낮아 relevance score가 전체적으로 0.40대에 집중되고 SOP 간 판별력이 사라짐.

```
한국어 "공구 마모로 인한 가공 불량 예방 절차" (22자)
영어   "procedure to prevent machining defects caused by tool wear" (59자)
→ 동일 의미지만 임베딩 공간에서 유사도 낮음
```

### 원인 2 — failure_type 메타데이터 미활용

요청 tags에 `"failure_types": "TWF"`가 명시되어 있어도 ChromaDB가 전체 컬렉션을 대상으로 벡터 검색.  
SOP 문서에 failure_type 메타데이터가 없어 필터링 불가.

### 원인 3 — chunk_size 불균형

`chunk_size = 512` characters 기준은 한국어에 적합한 값.  
영어로 전환 시 동일 내용이 더 많은 문자를 차지해 chunk가 과도하게 분할됨.

---

## 적용한 개선

### 개선 1 — SOP 문서 영어 전환 + HTML 주석으로 한국어 보존

**파일:** `data/sop_docs/*.md`

5개 SOP 문서를 영어 본문으로 교체. 한국어는 `<!-- -->` HTML 주석으로 보존하여 가독성 유지.

**`rag/ingestion.py`** — 인덱싱 전 HTML 주석 제거 전처리 추가:

```python
text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
```

→ 임베딩에는 영어 텍스트만 사용, 파일에는 한국어 컨텍스트 보존.

### 개선 2 — chunk_size 조정

**파일:** `core/config.py`

```python
chunk_size: int = 512  →  1024
```

영어는 한국어 대비 동일 내용에 약 2~3배 문자 사용. 1024로 키워 chunk당 문맥 유지.

### 개선 3 — failure_type 메타데이터 필터링

**`rag/ingestion.py`** — SOP 파일명에서 failure_type 추출 후 메타데이터 저장:

```python
_FAILURE_TYPE_MAP = {
    "tool-wear": "TWF",
    "heat-dissipation": "HDF",
    "power-failure": "PWF",
    "overstrain": "OSF",
    "random": "RNF",
}
```

**`models/anomaly_report.py`** — tags 필드 추가:

```python
tags: dict[str, str] = {}
```

**`agents/perception_agent.py`** — EquipmentLog의 tags를 AnomalyReport에 전달:

```python
report = AnomalyReport.model_validate({**data, "correlation_id": correlation_id, "tags": log.tags})
```

**`agents/sop_rag_agent.py`** — ChromaDB where 필터 적용 + 결과 부족 시 폴백:

```python
where = {"failure_type": {"$in": failure_types}} if failure_types else None
results = collection.query(..., where=where)

# 필터 결과 부족 시 전체 재검색
if where and len(results["documents"][0]) < n_results:
    results = collection.query(...)  # 필터 없이 재검색
```

---

## 개선 결과

| 지표 | 개선 전 | 개선 1·2 후 | 개선 3 후 | 개선 4 후 |
|------|---------|------------|----------|----------|
| SOP 검색 1위 | HDF (0.417) | TWF (0.732) | TWF (0.732) | TWF (0.730) |
| relevance score (최고) | 0.417 | 0.732 | 0.732 | 0.730 |
| grounding_score | 0.615 | 0.711 | 0.7205 | **0.7309** |
| step 2 score (경계 케이스) | - | - | 0.599 | **0.7603** ✅ |
| 액션플랜 SOP 참조 | HDF·OSF 혼재 | TWF 위주 | TWF 전용 | TWF 전용 |
| escalation_required | false (오판) | false (오판) | true (정확) | true (정확) |
| is_valid | false | false | false | false (0.75 미달) |

### 잔여 과제 분석

grounding_score 0.7309로 임계값 0.75까지 0.02 차이. 대부분의 스텝이 0.72~0.76 구간에 분포해 LLM 비결정성(매 실행마다 액션 문장이 미묘하게 달라짐)으로 인해 개별 스텝이 임계값 근방에서 오르내림. 구조적 개선은 완료됐으나 임계값 특성상 is_valid=false가 유지됨.

**판단:** REVIEW 판정 자체가 "사람 검토가 필요한 경계 케이스를 보수적으로 잡아낸다"는 제조 도메인 안전 설계의 의도된 동작으로 해석 가능.

---

## 재인덱싱 절차

개선 적용 후 반드시 ChromaDB를 초기화하고 재인덱싱해야 함:

```bash
./scripts/reindex.sh
```

---

### 개선 4 — chunk_overlap 조정

**파일:** `core/config.py`

```python
chunk_overlap: int = 64  →  200
```

**선택 근거:**
grounding score 미달 step 2·4의 내용이 SOP에 실제로 존재함을 확인.  
해당 내용이 청크 경계(chunk::1 끝부분)에 위치해 청크 내 비중이 낮아 유사도가 분산되는 구조적 문제.  
overlap을 64 → 200으로 늘려 경계 문장이 다음 청크 앞부분에도 포함되도록 개선.

**트레이드오프:**

| | 내용 |
|--|------|
| 장점 | 청크 경계 케이스 grounding score 개선, 메트릭 조작 없이 구조적 원인 해결 |
| 단점 | 청크 간 중복 텍스트 증가 → 전체 doc_count 증가, 저장 공간 소폭 증가 |
| 기각한 대안 | 임계값 하향(0.70): 메트릭 후퇴 / ActionPlan 인용 강제: 검증기 목적 무력화 / multi-query: 검색 문제가 아닌 청크 경계 문제이므로 원인 불일치 |

적용 후 `reindex.sh` 재실행 필요.

---

### 실험 5 — Multi-query + Max Score Fusion (적용 후 롤백)

**시도한 내용:**
LLM이 각도가 다른 쿼리 3개를 한 번에 생성하고, 임베딩 병렬 처리 후 ChromaDB에 단일 호출로 검색. 청크별 max score fusion으로 결과 통합.

**실험 결과:**

| 지표 | 개선 4 후 | 멀티쿼리 적용 |
|------|----------|-------------|
| relevance score 1위 | 0.730 | 0.747 (+0.017) |
| grounding_score | 0.7309 | 0.7062 (-0.025) |
| grounded steps | 1/5 | 0/5 |

**롤백 근거:**

1. **문제 원인 불일치**: 멀티쿼리는 "검색이 틀린 경우"에 효과적인 기법. 하지만 현재 시스템에서 TWF SOP는 이미 상위 4개를 독점하고 있어 검색 자체는 정상. 미달 원인은 검증기(grounding) 방식의 한계였기 때문에 검색을 강화해도 근본 해결 불가.

2. **LLM 비결정성으로 인한 공정한 비교 불가**: grounding_score 하락(-0.025)은 멀티쿼리 자체의 부작용이 아니라 실행마다 다른 액션 문장이 생성되는 비결정성 때문. step 2가 "Isolate the equipment to prevent further use..." 로 바뀌며 score 0.644로 하락.

3. **효과 대비 복잡도**: relevance score 최고값이 0.017 상승에 그쳐 추가된 코드 복잡도를 정당화하기 어려움.

**향후 재시도 조건:**
- vLLM + RTX 환경에서 temperature=0 완전 고정 후 동일 액션 플랜으로 공정 비교
- 검증기를 LLM-as-judge 방식으로 교체한 후 검색 커버리지 확대 효과 측정

---

## 향후 과제

### LLM-as-judge 검증기 교체

**현재 방식의 한계:**
임베딩 코사인 유사도로 grounding을 판단하기 때문에 paraphrase에 취약. "Isolate work area with safety tape"와 "Cordon off the area within 2m" 같이 의미가 동일한 문장도 표현이 다르면 score가 낮게 나옴.

**개선 방향:**
HallucinationValidatorAgent가 임베딩 유사도 대신 LLM에게 직접 "이 액션이 이 SOP 청크에 근거가 있는가?"를 판단하게 함.

**트레이드오프:**
- 장점: paraphrase 문제 해결, 0.75 임계값 근방 불안정성 제거
- 단점: LLM 호출이 스텝 수(현재 5회)만큼 추가 → 응답 시간 대폭 증가
- 단점: ActionPlanAgent(LLM)의 출력을 동일 모델이 검증하는 구조 → 검증 독립성 약화, 할루시네이션을 못 잡을 가능성

**재시도 조건:** vLLM + RTX 환경, 모델 14B 이상에서 응답 시간과 검증 품질 동시 측정

---

### Multi-query + Score Fusion 재시도

**재시도 조건:** vLLM + RTX 환경에서 temperature=0 완전 고정 후 LLM 비결정성 제거. 동일 액션 플랜 기준으로 단일 쿼리 대비 공정 비교.

---

### 모델 업그레이드

**현재 환경 한계:** M2 Air 8GB — qwen2.5:7b가 실질적 상한. 14B부터 스왑 발생으로 응답 시간 분 단위로 증가.

**재시도 조건:** RTX GPU 환경에서 qwen2.5:14b 이상 또는 vLLM 서빙으로 처리량 개선 후 전체 파이프라인 재측정.

---

### grounding_score_threshold와 recommendation 구간의 불일치

**현재 상태:**

`core/config.py`의 `grounding_score_threshold` (기본값 0.75)는 **두 가지 역할을 동시에** 수행한다.

1. `StepValidation.is_grounded` 판정 기준 — 개별 스텝이 SOP에 근거했는지 여부
2. `ValidationResult.is_valid` 판정 기준 — 전체 액션 플랜의 유효성 여부

반면, recommendation 구간(`hallucination_validator.py` 90~95번째 줄)은 별도로 하드코딩되어 있다.

```python
if overall >= 0.85:
    recommendation = "APPROVE"
elif overall >= 0.60:
    recommendation = "REVIEW"
else:
    recommendation = "REJECT"
```

이로 인해 다음 불일치가 발생한다.

| overall_grounding_score | is_valid | recommendation |
|------------------------|----------|----------------|
| 0.85 이상              | True     | APPROVE        |
| 0.75 ~ 0.84            | True     | REVIEW         | ← is_valid=True지만 사람 검토 요청
| 0.60 ~ 0.74            | False    | REVIEW         | ← REVIEW/REJECT 경계가 threshold 기준과 다름
| 0.60 미만              | False    | REJECT         |

`is_valid=True`이면서 `recommendation=REVIEW`인 구간(0.75~0.84)에서 파이프라인이 재시도를 건너뛰고 종료한다. 이는 보수적 설계로 의도된 동작이지만, threshold 하나의 값이 is_grounded와 is_valid 두 판정에 모두 영향을 준다는 구조적 모호성이 있다.

**개선 방향:**

임계값을 역할별로 분리한다.

```python
# core/config.py 에 추가
grounding_score_threshold: float = 0.75       # StepValidation.is_grounded 기준 (기존)
approval_score_threshold: float = 0.85        # recommendation APPROVE 기준 (신규)
review_score_threshold: float = 0.60          # recommendation REVIEW 하한 (신규)
```

세 값을 config에서 관리하면 threshold 변경이 recommendation 구간에도 일관되게 반영되며, 환경 변수로 조정 가능해진다.

**트레이드오프:**
- 장점: 역할 명확화, 구간 변경 시 config 한 곳만 수정
- 단점: 파라미터 3개 → 조합 실수 가능성, 값 간 관계(review < threshold ≤ approval) 보장하는 검증 로직 필요
- 현재 REVIEW 구간(0.60~0.85)은 제조 도메인 보수적 설계의 의도된 넓이이므로, 변경 시 도메인 전문가 검토 필요

**적용 조건:** LLM-as-judge 검증기로 교체 후 grounding_score 분포가 안정화된 시점에 재검토.
