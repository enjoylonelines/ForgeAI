# Troubleshooting & 개선 기록

## stream_simulator.py e2e 검증 과정 (2026-06-07)

---

### 발견 1 — AI 할루시네이션 (설계 의도 단정)

**상황:** RiskAssessmentAgent가 LLM으로 임계값 비교를 수행하는 구조에 대해 "포트폴리오에서 LLM을 많이 쓸수록 좋아 보이려 했기 때문"이라고 단정했다.

**실제:** 설계 의도를 모르면서 이유를 추론해 사실처럼 말한 것. 근거 없는 단정이었다.

**교훈:** AI가 근거 없이 설계 의도를 단정할 때 틀릴 수 있다. 이유를 모르면 "모른다"고 해야 한다.

---

### 발견 2 — RiskAssessmentAgent가 rule engine 역할을 LLM으로 수행

**문제:** 센서 임계값 비교(torque > 76.6, tool_wear > 200 등)는 산술 연산인데, 이를 LLM이 수행하고 있다.

**실측 성능:**
- qwen2.5:7b: RiskAssessmentAgent 1회 호출에 400s+
- qwen3:4b: early_exit 기준 178s

**왜 문제인가:**
- LLM은 임계값 경계(76.5 vs 76.6 Nm)에서 틀릴 수 있음 (비결정적)
- 산수를 위해 수백 초 소요
- rule engine으로 구현하면 수ms, 100% 결정적

**개선 방향:**
```python
# rule_engine.py
THRESHOLDS = {
    "tool_wear_min":        200,
    "rotational_speed_rpm": 2800,
    "torque_nm":            70,
    "air_temperature_k":    310,
}

def rule_engine(log: EquipmentLog) -> str:
    for r in log.readings:
        limit = THRESHOLDS.get(r.sensor_id)
        if limit and r.value >= limit:
            return "WARNING"
    return "SAFE"
```

RiskAssessmentAgent를 이 함수로 교체하면:
- SAFE early_exit: 수백 초 → 수ms
- 신뢰성: 비결정적 LLM → 100% 결정적

---

### 발견 3 — LLM 추론도 라우팅으로 단축 가능

**현재 구조:** LLM이 프롬프트 안에서 "어떤 고장 유형인지 파악 → 해당 유형 기준으로 판단"을 혼자 수행.

**문제:** 추론 범위가 넓어 프롬프트가 길고, 토큰 소비가 많으며 응답이 느림.

**개선 방향 — 패턴 기반 라우팅:**

```
rule_engine → 이상 센서 조합 분류 (TWF? HDF? PWF?)
                    ↓
        failure_type별 전용 프롬프트로 라우팅
        ├── TWF: "공구 마모 패턴 맥락에서 판단" (짧은 프롬프트)
        ├── HDF: "열 방산 맥락에서 판단"
        └── PWF: "출력 초과 맥락에서 판단"
```

효과:
- LLM은 타입이 이미 결정된 상태에서 판단만 → 입력 토큰 감소 → 응답 단축
- SOPRAGAgent도 전체 SOP 대신 해당 타입 SOP만 검색 → 정확도 향상
- 각 타입 프롬프트가 독립적이라 병렬 처리 가능

---

### 발견 4 — e2e 테스트 환경 한계

**문제:** CPU 환경에서 LLM 호출이 수백 초 소요, stream_simulator e2e full run 불가.

**확인된 것:**
- row 0: `early_exit=True`, `risk=SAFE` 정상 출력 (qwen3:4b, 178s)
- `_compute_metrics` 로직: unit test 6/6 pass
- 서버 로그: RiskAssessmentAgent 실행 → WARNING 판정 → PerceptionAgent 진입 확인

**결론:** 코드 로직은 정상. 속도는 GPU 없는 로컬 CPU 환경의 하드웨어 한계.

**메모:** GPU 환경에서는 row당 수초 수준으로 단축 가능.

---

## 우선순위 개선 목록

| 우선순위 | 항목 | 기대 효과 |
|---------|------|---------|
| 1 | RiskAssessmentAgent → rule engine 교체 | early_exit 수백s → 수ms |
| 2 | failure_type 라우팅 + 전용 프롬프트 분기 | LLM 추론 범위 축소, 속도·정확도 향상 |
| 3 | SOPRAGAgent failure_type 필터링 | 검색 범위 축소, 관련성 향상 |
