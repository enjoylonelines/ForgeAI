# ADR-013: Training-Serving Skew 방지 (학습/서빙 전처리 일치)

**상태:** 검토중 (ML 서빙 통합 전)

---

## 맥락

학습(training) 시 전처리와 서빙(serving) 시 전처리가 달라지면  
모델이 학습 때 본 적 없는 입력 분포를 받게 되어 예측 성능이 오프라인 수치와 괴리된다.  
이를 **training-serving skew**라 한다.

현재 ML 베이스라인은 `scripts/baseline_classifier.py`에서 오프라인으로만 실행되며  
FastAPI 서빙 파이프라인과 연결되어 있지 않다.  
연결 시점에 전처리 일관성을 보장하지 않으면 "오프라인 PR-AUC 0.830"이 운영 환경에서 재현되지 않는다.

---

## 고려한 대안

### 대안 A: 서빙 시 전처리 코드를 별도로 재작성

- FastAPI 핸들러 안에서 `median` 값을 하드코딩하거나 재계산
- **배제 이유:** 학습 시 median과 서빙 시 median이 달라질 수 있다.  
  하드코딩이면 재학습 때 갱신을 빠뜨릴 위험이 있다.

### 대안 B: 학습·서빙 공통 전처리 함수 + 아티팩트 저장 — 채택

- 전처리 로직을 단일 모듈(`core/preprocessor.py`)에 정의
- 학습 시 fit된 imputer (median 값 등)를 모델과 함께 직렬화 저장
- 서빙 시 동일 객체를 불러와 transform만 실행

### 대안 C: 피처 스토어(Feature Store) 사용

- 학습과 서빙 모두 동일 피처 스토어에서 피처를 읽음
- **배제 이유:** 현재 포트폴리오 규모와 폐쇄망 제약에서 별도 인프라 도입 불필요.  
  아티팩트 직렬화로 동일 효과 달성 가능.

---

## 결정

ML 모델을 서빙 파이프라인에 통합할 때 다음을 강제한다:

### 전처리 아티팩트 저장

```python
# scripts/baseline_classifier.py (학습 완료 후 추가 예정)
import joblib

pipeline = Pipeline([
    ("imputer", SimpleImputer(strategy="median")),
    ("classifier", XGBClassifier(...))
])
pipeline.fit(X_train, y_train)

# 모델 + 전처리 파라미터 함께 저장
joblib.dump(pipeline, "models/xgb_pipeline.joblib")
```

```python
# core/ml_predictor.py (미구현 — 서빙 통합 시 생성)
import joblib

_pipeline = joblib.load("models/xgb_pipeline.joblib")

def predict_failure_probability(log: EquipmentLog) -> float:
    X = extract_features(log)   # raw 센서값 → 피처 DataFrame
    return float(_pipeline.predict_proba(X)[0, 1])
```

### 피처 추출 함수 공유

```python
# core/feature_extractor.py (단일 진실 소스)
FEATURE_COLS = ["air_temp", "process_temp", "rpm", "torque", "tool_wear", "type_encoded"]
LEAK_COLS    = ["TWF", "HDF", "PWF", "OSF", "RNF", "Machine failure"]

def extract_features(log: EquipmentLog) -> pd.DataFrame:
    """학습·서빙 공통. 피처 목록·순서·타입 보장."""
    ...
```

학습 스크립트와 서빙 코드 모두 이 함수를 import한다.  
피처 목록이 바뀌면 이 파일 한 곳만 수정하면 된다.

### 확인 체크리스트 (서빙 통합 시)

| 항목 | 확인 방법 |
|------|----------|
| 동일 피처 목록·순서 | `feature_extractor.py` 단일 소스 사용 |
| 동일 imputation 값 | 학습 시 fit한 `SimpleImputer` 객체 저장·재사용 |
| 동일 인코딩 (type) | `{"L":0, "M":1, "H":2}` 매핑 상수화 |
| 누수 컬럼 차단 | 서빙 시 `LEAK_COLS` 필드는 FastAPI 스키마에 없음 |
| 스케일링 없음 | 트리 계열 — 학습·서빙 모두 스케일링 생략 |

---

## 이유 (인과)

skew의 가장 흔한 발생 원인:

1. **median 재계산 오류:** 서빙 시 전체 데이터로 다시 median을 계산하면 학습 시 median과 다르다.  
   → `SimpleImputer`를 학습 데이터로 fit 후 serialized 상태로 서빙에 전달해야 한다.
2. **피처 순서 불일치:** DataFrame 컬럼 순서가 달라지면 XGBoost가 잘못된 피처에 가중치를 적용한다.  
   → `FEATURE_COLS` 리스트를 상수로 고정하고 `.reindex(columns=FEATURE_COLS)` 강제.
3. **인코딩 불일치:** 학습 시 `"L"→0`, 서빙 시 `"L"→1` 같은 오류.  
   → 인코딩 매핑을 단일 상수로 관리.

---

## 포기한 것 / 트레이드오프

Pipeline 객체 직렬화는 sklearn/XGBoost 버전 호환성에 의존한다.  
`joblib` 역직렬화 시 버전 불일치가 있으면 오류가 발생한다.  
이를 보완하기 위해 모델 파일과 함께 패키지 버전을 `models/versions.json`에 기록한다.

---

## 결과 / 검증

`[___]` — 서빙 통합 완료 후 다음을 기록한다:
- 오프라인 PR-AUC vs 서빙 환경 재현 PR-AUC 비교
- `core/feature_extractor.py` 단위 테스트 통과 여부
- `models/xgb_pipeline.joblib` 로드 → 예측 일관성 확인 테스트
