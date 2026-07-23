# ADR-015: 할루시네이션 검증 전략 — 코사인 유사도 → NLI 하이브리드

**날짜:** 2026-07-23  
**상태:** Accepted  
**이슈:** #46

---

## 배경

`HallucinationValidatorAgent`는 조치계획 단계(action step)와 SOP 청크를 **코사인 유사도**로 비교해 grounding score를 산출한다. 이 방식은 "주제 유사성"만 측정하므로, SOP와 **의미적으로 모순되는 조치**도 높은 점수로 통과시킬 수 있다.

예시:
- SOP: "점검 전 반드시 전원을 차단하라"
- 조치계획: "가동 중 감속 상태에서 베어링을 점검하라"

두 텍스트는 'inspect', 'machine', 'bearing' 등의 어휘를 공유하므로 코사인 유사도가 높다. 그러나 의미는 정반대다. 합성 케이스(`data/conflict_case_nli.json`) 기준으로 3/5 contradiction 케이스가 코사인 방식에서 APPROVE로 오판되었다.

---

## 결정

**NLI(Natural Language Inference) cross-encoder를 병행 검증 층으로 도입하는 하이브리드 전략을 채택한다.**

- 기본 모드(`NLI_ENABLED=false`): 기존 코사인 전략 유지 — 하위 호환
- NLI 모드(`NLI_ENABLED=true`): 코사인으로 최적 청크 선정 → NLI로 의미 관계 판정

### NLI 판정 우선순위

| NLI 판정 | contradiction_score | grounding_score | 최종 recommendation |
|----------|--------------------|-----------------|--------------------|
| contradiction | ≥ 0.5 (설정 가능) | 0.0 (강제) | REJECT (즉시) |
| neutral | - | min(cosine, 0.5) | 기존 임계값 적용 (REVIEW 유도) |
| entailment | - | cosine 그대로 | 기존 임계값 적용 |

contradiction이 하나라도 검출되면 전체 recommendation이 REJECT로 결정된다.

---

## 모델 선정

### 선택: `cross-encoder/nli-deberta-v3-small`

| 항목 | 내용 |
|------|------|
| 크기 | ~184MB |
| 언어 | 영어 |
| 추론 | CPU 가능 (~50-200ms/쌍) |
| 레이블 순서 | [contradiction, entailment, neutral] |
| 의존성 | `sentence-transformers>=3.0.0` |

### 한국어 SOP 환경 권장 모델

현재 SOP 문서에 한국어가 포함된 경우 `cross-encoder/nli-deberta-v3-small`의 성능이 저하될 수 있다.

| 모델 | 크기 | 다국어 | 비고 |
|------|------|--------|------|
| `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` | ~580MB | ✅ (한국어 포함) | NLI_MODEL 환경변수로 교체 가능 |
| `cross-encoder/nli-deberta-v3-small` | ~184MB | ❌ 영어 전용 | 기본값 |

운영 환경에서 한국어 SOP가 주를 이루는 경우:
```bash
NLI_MODEL=MoritzLaurer/mDeBERTa-v3-base-mnli-xnli
```

---

## 아키텍처

```
HallucinationValidatorAgent.run()
  │
  ├─ get_strategy(nli_enabled)
  │     ├─ NLI_ENABLED=false → CosineStrategy      (기존 동작)
  │     └─ NLI_ENABLED=true  → NLIHybridStrategy
  │
  └─ strategy.score_step(action, step_vec, sop_embeddings, ...)
        │
        ├─ [공통] 코사인 유사도로 best_chunk 선정
        └─ [NLI only] NLIValidator.predict(hypothesis=action, premise=best_chunk_text)
              ├─ contradiction → grounding_score = 0.0, contradiction_detected = True
              ├─ neutral       → grounding_score = min(cosine, 0.5)
              └─ entailment    → grounding_score = cosine (변경 없음)
```

**관련 파일:**
- `agents/validation_strategy.py` — 전략 인터페이스 + 구현체
- `core/nli_validator.py` — NLI cross-encoder lazy-load 래퍼
- `models/validation_result.py` — `nli_label`, `contradiction_detected`, `validation_strategy`, `contradiction_count` 추가

---

## 설정

```bash
# NLI 활성화 (기본: false)
NLI_ENABLED=true

# 모델 (기본: cross-encoder/nli-deberta-v3-small)
NLI_MODEL=cross-encoder/nli-deberta-v3-small

# contradiction 판정 임계값 (기본: 0.5)
NLI_CONTRADICTION_THRESHOLD=0.5
```

---

## 성능 영향

| 모드 | 추가 지연 | 추가 메모리 |
|------|---------|----------|
| cosine (기본) | 0 | 0 |
| nli-hybrid | ~50-200ms/step × step 수 | ~500MB (모델 최초 로드) |

NLI 모델은 첫 호출 시 lazy-load되며 이후 메모리에 캐시된다.

---

## 검증 결과 (합성 케이스, `data/conflict_case_nli.json`)

| 방식 | contradiction 3건 판정 | entailment 1건 | neutral 1건 |
|------|----------------------|---------------|------------|
| 코사인 | ❌ 3건 APPROVE 오판 | ✅ APPROVE | ✅ REVIEW |
| NLI 하이브리드 | ✅ 3건 REJECT | ✅ APPROVE | ✅ REVIEW |

→ **contradiction 검출률: 0% → 100% (합성 케이스 기준)**

---

## ADR-014와의 정합성

ADR-014 "근거 추적 %" 정의에서 `validator` 단계의 `DecisionEvent`를 추적 요건으로 포함한다.  
NLI 모드에서도 동일한 DecisionEvent 로그 구조를 유지하므로 근거 추적 % 측정에 영향 없다.
