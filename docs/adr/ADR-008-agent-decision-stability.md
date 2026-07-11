# ADR-008: 에이전트 결정 안정성 (비결정성 제어)

**상태:** 잠정 채택 — 사용자 이견 시 재검토 (결정 대기 항목 없음)

> `docs/analysis/current-state.md` Q3·Q4가 입력. 구현 코드 없음 — 원칙·측정 절차·스키마만.

## 맥락

같은 알람을 두 번 넣으면 다른 답이 나온다. 원인: 전 LLM 호출이 temperature=0.1·seed 없음(`core/langchain_client.py:16`)이고, 흔들림이 연쇄 증폭된다(LLM 쿼리→검색→계획→점수→판정). 반면 rule engine·임베딩·코사인은 결정론이다. 문제는 "전부 흔들린다"가 아니라 **어디까지의 흔들림을 허용하고 어떻게 재는가**다.

## 원칙 — 비결정성의 3등급

| 등급 | 예 | 기준 |
|---|---|---|
| **결정** | 라우팅 3분기, recommendation, has_anomaly | 같은 입력 → 같은 값. 흔들리면 결함 |
| **수치** | grounding/relevance score, risk_index | 허용 오차 내 (오차는 실측 후 확정) |
| **서술** | summary, 설명문 | 표현 달라도 무방. 측정 안 함 |

"일관성 100%"를 글자 단위로 요구하면 불가능하고, 결정 단위로 요구하면 달성 가능하며 의미도 있다.

## D4 — 통제·측정 (잠정 채택: 절충안)

**채택안:** temperature=0 + seed 고정(ChatOllama에 seed 파라미터 실존 확인 — langchain-ollama 1.1.0 기준, 설치 버전 재확인 필요), 단 REJECT 재시도에는 retry_count를 seed에 섞어 의도된 다양성만 허용. 라우팅 판정은 LLM 출력이 아닌 결정론 규칙만 사용(ADR-009 원칙 2).

탈락 대안 한 줄씩: ⓐ seed 고정만 — 재시도가 같은 실패를 반복. ⓑ 비결정성 수용 + 구조로만 흡수 — 검색 쿼리 결정론화 등 손대는 곳이 과다. 채택안이 둘의 장점을 포함하며 상호 배타적이지 않음.

**측정 프로토콜 (일관성 비율):**
- 전제: **ADR-009 D6(정답 라벨 누수) 차단 후에만 유효** — 답을 보면 출력도 안정되므로(가짜 일관성) 차단 전 수치는 오염 표본
- 입력: AI4I 층화 30건(risk_level별 10, 고장 모드 4종 ≥2건씩) × 20회 반복 = 600회
- 지표: **결정 일관성**(최빈 결정 일치율, has_anomaly/recommendation/라우팅 각각 보고), 수치 산포(grounding std), 연쇄 추적(흔들린 케이스의 최초 분기 지점)
- 합격선(잠정): 통제 적용 후 결정 일관성 ≥ 99%. README 8장 `일관성 [___]%` 빈칸을 이 값으로 채움

## D3 — 계측 방식 (잠정 채택: 이원화)

**채택안:** 신뢰성 지표의 원장(源帳)은 JSONL 이벤트 로그(항상 기록, 오프라인 완결, 재계산 자유) — 단 `core/logging.py:14-17`의 dead branch(구조화 로그가 repr 문자열로 손실, 재현 확인) 수정이 선행 조건(구현 단계 1번). Langfuse는 기본 꺼짐 유지, 개발·시연 시에만 켜서 trace 시각화 — 기존 절반 구현(trace 생성 + generation 자동 기록) 위에 공백 4곳(rule engine, 벡터 검색, 코사인, 분기 이유) span만 추가.

탈락 대안 한 줄씩: ⓐ Langfuse 중심 — 지표가 외부 서버 가용성에 묶이고(꺼진 실행 누락) 1660/M2 Air에서 상시 구동 부담, ADR-007이 지적한 장기 감사 한계 그대로. ⓑ 로깅만 — 개별 케이스 디버깅 UI 부재. 채택안은 "지표는 반드시 남는 곳에서, 뷰는 편한 곳에서"로 둘을 상쇄하며 ADR-007과 정합.

## 공유 스키마 — DecisionEvent (판단 1건당 1레코드)

```
correlation_id, stage(rule_engine|perception|sop_search|action_plan|validator|routing),
signals: dict, decision, reason(규칙 ID 포함 한 줄), policy_version, duration_ms, ts
```

벡터 검색은 signals에 top_chunk/top_score/filter_used를, 분기 함수 3곳은 stage="routing"으로 남긴다 — "분기 이유가 어디에도 안 남는" 공백을 닫는 자리.

## 신뢰성 4축 — 산출 방법

| 축 | 산출 | 출처 |
|---|---|---|
| 일관성 비율 | D4 프로토콜의 결정 일치율 | 30건×20회 |
| 검색 정확도 | 고장 라벨 입력에서 top-k 내 해당 모드 SOP 문서 포함 비율 (라벨↔SOP 파일 1:1이라 구조적 정답 존재) | AI4I 라벨 |
| 자동화/에스컬레이션율 | 3분기 분포 (정의·합격선은 ADR-009) | routing DecisionEvent |
| 추적 가능률 | 통과한 전 stage의 DecisionEvent가 존재하는 실행 비율, 목표 100% | DecisionEvent 로그 |

## 제외

임계값·seed 자동 튜닝(수동 + 실측 보고까지), 프롬프트 버전 관리 시스템(기존 메타 재사용), Langfuse 운영 자동화·대시보드, 모델 교체/양자화.
