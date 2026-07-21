# ADR-004: 확률 보정 도입 여부 및 방식

**상태:** 검토중

---

## 맥락

XGBoost와 Random Forest의 `predict_proba()` 출력은 모델의 예측 확률이지 실제 사건 발생 빈도(calibrated probability)가 아니다.  
트리 앙상블은 특히 다수 클래스 쪽으로 확률이 쏠리는 경향이 있다.  
이 프로젝트에서 예측 확률은 두 곳에서 쓰인다:

1. 운영점(operating point) 설정 — 특정 임계값에서 Recall/Precision 결정
2. (미래) 위험 점수를 숫자로 현장에 보고 — "이 설비의 고장 확률 X%" 신뢰 문제

보정되지 않은 확률로 임계값을 설정하면 "0.6 이상이면 경보"라는 규칙이 실제로 몇 %의 고장을 잡는지 알 수 없다.

---

## 고려한 대안

### 대안 A: 보정 없음 (현재)

- **장점:** 구현 불필요, PR-AUC 최대화 목표에서는 보정과 무관
- **단점:** 확률 수치 자체를 신뢰할 수 없음. "고장 확률 73%"를 현장에 보고하면 의미가 불분명

### 대안 B: Platt Scaling (sigmoid 보정)

- **방법:** 훈련된 모델의 확률 출력에 sigmoid 회귀 적합
- **장점:** 간단, scikit-learn `CalibratedClassifierCV(method='sigmoid')`로 즉시 적용
- **단점:** 선형 보정 가정 — 클래스 불균형이 심할 때 보정 효과가 약할 수 있음

### 대안 C: Isotonic Regression

- **방법:** 단조 증가 함수로 확률 보정 (비모수적)
- **장점:** Platt보다 유연, 비선형 보정 가능
- **단점:** 훈련 샘플이 적을 때 과적합 위험. 10,000행 / 고장 271개(train) 환경에서 실험 필요

### 대안 D: Temperature Scaling

- **방법:** 소프트맥스 출력을 단일 스칼라 T로 나눔 (LLM calibration에서 차용)
- **장점:** 매개변수 1개, ECE(Expected Calibration Error) 최소화
- **단점:** sklearn 직접 지원 없음. 이진 분류에서 장점 불명확

---

## 결정

미확정 — 실험 후 결정.  
**우선 시도:** Platt Scaling → calibration curve(reliability diagram) 확인 → 불충분하면 Isotonic으로 전환.

---

## 이유

PR-AUC 최대화가 목적이면 보정은 선택 사항이다.  
그러나 이 프로젝트의 운영 목표(현장 경보 임계값 설정, 위험 점수 보고)에서는 보정된 확률이 필요하다.  
실험 없이 "보정한다/안 한다"를 결정하는 것은 추측이다.

---

## 포기한 것 / 트레이드오프

보정은 모델의 순위 성능(PR-AUC)을 바꾸지 않는다. 순위가 같더라도 확률 값이 달라진다.  
보정 후 임계값 재설정이 필요하다 (보정 전 0.5 기준 임계값이 보정 후 다른 수치가 됨).

---

## 결과 / 검증

`[___]` 빈칸 — 다음 실험 후 채운다:

1. `CalibratedClassifierCV(method='sigmoid')` 적용 → calibration curve 생성
2. ECE(Expected Calibration Error) 보정 전/후 비교: `___` → `___`
3. "고장 예측 확률 X% 구간에서 실제 고장 비율은 Y%"인지 reliability diagram으로 확인
4. 보정 후 운영점 재결정 필요 여부 판단
