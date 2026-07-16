# 승격 기준 게이트 실동작 보고서

**측정일**: 2026-07-15 07:51 UTC
**게이트 기준**: F1 ≥ 0.65 AND Recall ≥ 0.7 (고정값, 수정 금지)

## 요약

| 후보 | F1 | Precision | Recall | 게이트 결과 |
|------|----|-----------|--------|------------|
| 정상 모델 (n_est=300, depth=4) | 0.761 | 0.730 | 0.794 | ✅ 승격 허용 |
| 언더핏 모델 (n_est=3, depth=1) | 0.314 | 0.471 | 0.235 | 🚫 승격 차단 |

## 증거

언더핏 XGBoost (n_estimators=3, max_depth=1, scale_pos_weight=1.0) 는
성능이 기준 미달이어서 게이트에서 차단됨:

```
F1=0.314 < 기준 0.65 — 승격 차단
```

정상 모델 (n_estimators=300, max_depth=4, Platt 보정) 은 기준을 통과하여 승격 허용됨:

```
F1, Recall 기준 통과 — 승격 허용
```

## 의미

- **'성능 저하 자동 차단'은 코드로 구현되어 있음** (`validate_for_promotion` in `scripts/promotion_gate_demo.py`)
- 게이트는 F1·Recall 두 지표를 모두 검사하여 과신뢰(high precision / low recall) 모델도 차단
- 운영 모델 교체 시 이 게이트를 통과해야만 `ml_predictor._get_model()` 캐시를 교체할 수 있음
