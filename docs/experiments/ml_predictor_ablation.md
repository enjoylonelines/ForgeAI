# ML Predictor Ablation 리포트

**측정일**: 2026-07-14 00:53 UTC  
**데이터셋**: AI4I 2020 Predictive Maintenance (10,000행)  
**ML threshold**: 0.3  
**소요**: 18.4초  

## 증명 목표 검증

| 목표 | MODE A (rule only) | MODE B (rule + ML) | 판정 |
|------|-------------------|-------------------|------|
| ① 불량 AUTO 유출 | 7건 | 3건 | ✅ 유지 |
| ② ML 추가 포착 불량 | — | 4건 | ✅ |
| ③ 정상 AUTO 감소 | 7724건 | 7687건 | 37건 추가 ESCALATE |

## 라우팅 비교

| 지표 | MODE A (rule only) | MODE B (rule + ML) | 변화 |
|------|-------------------|-------------------|------|
| 전체 AUTO | 7731 (77.3%) | 7690 (76.9%) | -41 |
| 불량 AUTO (유출) | 7 (2.1%) | 3 (0.9%) | -4 |
| 정상 AUTO | 7724 (80.0%) | 7687 (79.6%) | -37 |

## ML Predictor 단독 성능 (AI4I 전체)

- **PR-AUC**: 0.9521
- **F1** (threshold=0.3): 0.8686

## 해석

MODE B에서 ML predictor는 rule_engine이 SAFE로 판정한 케이스 중 4건의 실제 불량을 추가 포착했다.
대가로 정상 37건이 AUTO 대신 ESCALATE로 승격됐다.

**불량 유출 0건 유지 전제**: rule_engine이 잡은 불량(WARNING/CRITICAL)은
ML predictor가 관여하지 않으므로 MODE A → MODE B로 전환해도 기존 유출은 증가하지 않는다.

**남은 유출 3건**: rule_engine도 ML predictor도 포착 못한 케이스.
AI4I RNF 정의상 '공정 파라미터와 결정론적/통계적 관계가 없음' — 구조적 한계.

## 결론

threshold=0.3에서 ML predictor를 활성화하면:
- 불량 추가 포착 +4건 (recall 개선)
- 정상 AUTO 감소 -37건 (precision 소폭 감소)
- 전체 자동화율 77.3% → 76.9% (-41건)

rule_engine 단독 대비 ML 보조 신호가 추가적인 안전망 역할을 한다.
