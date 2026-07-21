# TWF 층 일관성 분기 원인 분석

**현상**: 30-run 일관성 프로토콜에서 TWF 층만 route/recommendation 일관성 80% (나머지 100%)  
**grounding_score σ**: TWF=0.1258 vs HDF=0.0216, PWF=0.0011, OSF=0.0000

## 원인 분리 실험

고정된 action plan 텍스트로 validator를 5회 반복 실행:

```
σ = 0.0000  → 임베딩 계산은 완전 결정론적
```

**결론: TWF grounding_score 분산의 원인은 임베딩이 아닌 action plan 생성(LLM) 단계.**

## 근본 원인

`prompts/action_plan_v1.py`의 TWF addendum이 SOP에 없는 표현을 사용:

| addendum 단어 | SOP 실제 표현 (chunk::5) |
|--------------|------------------------|
| "post-replacement run test" | "Trial Machining: Perform one trial cut on scrap material" |
| "verification of cutting parameters" | "Reset Tool Length Offset" (chunk::4) |

LLM이 SOP 언어 없이 addendum을 paraphrase → 실행마다 다른 action 텍스트 → grounding_score 분산 → 임계값(0.85) 근처에서 REVIEW/APPROVE 분기.

qwen2.5:7b는 temperature=0, seed=42에서도 복잡한 TWF 프롬프트에 대해 완전한 결정론을 보장하지 못함.

## 수정 내용

TWF addendum 4단계 설명을 SOP chunk 원문 표현에 맞게 수정:

```
변경 전: (4) post-replacement run test
변경 후: (4) trial machining on scrap material and quality check
```

```
변경 전: (3) verification of cutting parameters
변경 후: (3) install new tool and reset tool length offset and tool life counter
```

"Use VERBATIM wording from the cited SOP chunk" 지시 추가.

## 기대 효과

LLM이 addendum의 단계 설명을 SOP 원문과 동일한 표현으로 생성 → grounding_score 분산 감소 → TWF 일관성 향상.

→ 수정 파일: `prompts/action_plan_v1.py`  
→ 재측정 방법: `uv run python scripts/consistency_protocol.py --runs 5 --samples 6`
