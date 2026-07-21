# grounding_score 개선 실측 결과

**측정일**: 2026-07-21  
**모델**: nomic-embed-text (Ollama)  
**대상**: TWF 케이스 5개 action step  
**인용 청크**: SOP-MNT-001 chunk::2, ::3, ::4

## 방법 비교

| step | 청크 단위(기존) | 문장 단위(신규) | 최종(max) | 개선 |
|------|---------------|---------------|---------|------|
| 1. Stop equipment after cycle | 0.7535 | **0.8854** | 0.8854 | +0.1320 |
| 2. Cordon off work area | 0.5850 | 0.7585 | 0.7585 | +0.1735 |
| 3. Notify maintenance team | 0.6878 | 0.7079 | 0.7079 | +0.0201 |
| 4. Remove and inspect worn tool | 0.7400 | 0.7996 | 0.7996 | +0.0597 |
| 5. Install new tool | 0.7796 | 0.8072 | 0.8072 | +0.0275 |
| **평균** | **0.7092** | **0.7917** | **0.7917** | **+0.0825** |

## 해석

- **+8.25p 향상**: 1024자 청크 전체 임베딩 vs 짧은 지시문 비교의 구조적 한계를 문장 단위 분할로 완화
- **Step 1이 APPROVE(≥0.85) 돌파(0.8854)**: SOP 문장 "Stop the CNC equipment immediately after completing the current machining cycle"과 step 텍스트가 직접 매칭
- **평균은 0.7917로 REVIEW 유지**: 일반적인 지시문(작업구역 통제, 팀 통보 등)은 특정 SOP 문장과의 직접 매칭이 약해 개선 폭이 작음

## 결론

문장 단위 비교는 SOP 내 절차 문장과 action step이 의미적으로 일치할 때 큰 효과(+0.13~0.17)를 보임.  
평균이 APPROVE 기준에 미달하는 것은 nomic-embed-text의 paraphrase 유사도 범위 특성과,  
일부 step이 여러 SOP 문장의 조합을 지시하는 복합 지시문이기 때문.

→ 개선 스크립트: `scripts/measure_grounding_improvement.py`  
→ 구현 변경: `agents/hallucination_validator.py`  
→ 관련 ADR: ADR-008 (비결정성 제어)
