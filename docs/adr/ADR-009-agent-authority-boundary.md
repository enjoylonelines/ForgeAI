# ADR-009: 에이전트 권한 경계 및 에스컬레이션 정책

**상태:** 채택 — 2026-07-09 사용자 확정: P-A(출구 게이트), D1-B(전 신호 dict + 우선순위 규칙), D5-C(불일치 = 신호). D2·D6은 잠정 채택 유지

> 입력: `docs/analysis/current-state.md` Q1·Q2, `docs/experiments/secom-standard-remedies.md`, 사용자 결정 G1(c)·G2(a-1). 구현 코드 없음.

## 맥락

판정 라벨(APPROVE/REVIEW/REJECT)과 escalation 플래그는 있지만 "이 알람을 누가 처리하는가"를 정하는 곳이 없다. 에스컬레이션 조각 4곳이 미연결이고, README 8장의 3분기 서사는 코드에 없으며(B-3), 빈 계획이 검증을 만점 통과하고(C-6), rule engine CRITICAL이 LLM 한 마디로 소멸한다(D5). 이 ADR은 그 조각들을 **하나의 라우팅 레이어**로 묶는다: 신호를 받아 `AUTO / HUMAN_REVIEW / ESCALATE`로 보내고 이유를 기록한다.

**권한 경계 원칙 (G1(c)를 설계 원칙으로 승격):**
1. 레이어는 신호의 의미를 모른다 — 이름 붙은 숫자 dict를 결정론 규칙으로 3분기할 뿐
2. LLM은 라우팅을 직접 정하지 못한다 — LLM 출력은 신호의 하나일 뿐
3. AUTO는 덜 위험한 방향으로만 — 애매하면 사람 쪽 (ADR-003의 비용 비대칭: FN ≫ FP)

---

## ★ P — 아키텍처 위치 (핵심 결정 1)

END로 가는 출구가 3개다(`forge_pipeline.py` 275·281·287행의 분기). 어느 출구든 라우팅 없이 나가면 그 알람은 3분기 밖이다.

- **P-A. 출구 게이트 (추천):** `routing` 노드를 신설하고 END행 엣지 3개를 전부 통과시킴. "라우팅 안 된 결과는 구조적으로 존재 불가"를 그래프가 보장, trace에도 노드로 남음. 비용: 배선 변경 3곳.
- **P-B. 분기 함수 3곳에 분산:** 새 노드 없음이 장점이나, 정책이 3곳에 흩어져 임계값 변경 시 3곳 수정 + 전체 정책을 한 곳에서 읽을 수 없음.
- **P-C. 그래프 밖 후처리:** 그래프 무변경이 장점이나, 이미 종료된 뒤라 그래프 내부 행동에 개입 불가 — **D5에서 어떤 옵션을 골라도 수용 가능한 위치는 P-A뿐**이라는 제약이 결정적.

**결정: P-A 채택 (2026-07-09).** 이유: 빠져나갈 구멍이 구조적으로 없어야 한다는 레이어의 존재 이유와 일치하고, D5의 어떤 선택과도 호환되는 유일한 위치.

## ★ D1 — 확신도 신호 구성 (핵심 결정 2)

- **D1-A. 최소 조합:** risk_level + grounding_overall 2신호 + escalation_required 오버라이드. 읽기 쉬우나, 검색 품질(relevance)이 낮은 케이스를 못 거른다 — 나쁜 검색을 닮은 계획은 grounding이 높게 나와 AUTO가 뚫릴 수 있음.
- **D1-B. 전 신호 dict + 우선순위 규칙 (추천):**
  ```
  signals = { risk_level, triggered_count, utilization_max,
              top_relevance, mean_relevance, grounding_overall, grounding_min,
              recommendation, escalation_required, empty_plan,
              retry_exhausted, stage_failures }
  ```
  규칙(위에서부터, 전부 결정론): ① retry_exhausted/stage_failures/empty_plan → **ESCALATE** (B-3·C-6을 여기서 닫음) ② escalation_required → 최소 HUMAN_REVIEW ③ CRITICAL → 최소 HUMAN_REVIEW ④ REJECT→ESCALATE, REVIEW→HUMAN_REVIEW ⑤ APPROVE라도 top_relevance 또는 grounding_min이 하한 미달 → HUMAN_REVIEW ⑥ 나머지 → **AUTO**.
  미사용이던 relevance_score가 처음 일을 하고, AUTO는 "모든 신호가 좋을 때"만 — 원칙 3과 정합. SECOM 스트레스에서는 `{model_proba}` 하나만 실어도 같은 골격이 작동. 비용: 임계값 3~4개 관리(D2).
- **D1-C. 가중합 스칼라:** 코드는 짧지만 "왜 에스컬레이션됐나"에 답 못 하고, 가중치 튜닝은 제외 항목이며, 척도가 다른 신호의 합산이 자의적.

**결정: D1-B 채택 (2026-07-09).** 이유: 걸린 규칙이 곧 이유가 되는 감사 가능성, 미사용 신호(relevance)의 편입, G1(c)의 "숫자 dict를 받는 함수" 요구를 동시에 충족.

## D2 — 임계값 구조 (잠정 채택: 전역 + CRITICAL 2단)

**채택안:** 임계값은 전역 1세트, 위험 차등은 "CRITICAL이면 AUTO 금지" 규칙 하나로 표현. 모드별 라우팅 분포는 지표로 기록해 차등 필요성을 데이터로 판단.

탈락 한 줄씩: ⓐ 전역 고정만 — 모드별 비용 차이(TWF 완만 vs PWF 정지 비용)를 전혀 못 담음. ⓑ 모드별 차등표 — AI4I 고장 339건을 모드로 쪼개면 모드당 수십 건이라 임계값 효과를 통계적으로 말할 수 없음 (SECOM 검정력 교훈 그대로: 표본 부족 상태의 세분화는 과적합).

## ★ D5 — perception 거부권 (핵심 결정 3)

현행: rule engine CRITICAL이어도 perception "이상 없음"이면 END(`forge_pipeline.py:281`) — 알람이 기록 없이 소멸.

**독립성 확인 (D5 성립 전제):** rule engine 판정은 LLM 프롬프트에 노출되지 않는다 — perception은 `state.log`만 받고(`forge_pipeline.py:104`) 프롬프트가 역할 분리를 명시(`prompts/perception_v1.py` SYSTEM 말미), RCA도 판정 미노출, SOP의 failure_type은 검색 필터 전용(`sop_rag_agent.py:56-60`). **성립.** 유보 2개: ① 프롬프트에 정상 범위 참조표가 있어 rule engine과 자(尺)를 공유 — "일치"의 증거 가치는 할인되나 "불일치"는 같은 자로도 갈렸다는 뜻이라 정보량이 오히려 큼(D5-C에 유리). ② D6 차단 전까지 독립성은 라이브 단건 입력에서만 성립 — CSV 기반 일치율은 신뢰 불가.

- **D5-A. 현행 유지:** LLM이 rule의 오탐을 걸러주는 필터. 그러나 결정론 판정이 확률론 출력 한 번에 무기록 소멸 — ADR-005 원칙과 정면 충돌.
- **D5-B. CRITICAL은 강제 진행:** 소멸은 막지만, "이상 없음"이라 답한 입력으로 후속 LLM들이 억지 계획을 만들다 REJECT→소진→ESCALATE로 끝날 공산 — LLM 4콜을 태우는 비싼 우회.
- **D5-C. 불일치 = 신호 (추천):** 진행은 종료하되 불일치를 `verdict_conflict=true`로 승격해 라우팅 dict에 싣는다. CRITICAL+불일치→ESCALATE, WARNING+불일치→HUMAN_REVIEW. 두 판단 체계의 불일치는 버릴 정보가 아니라 가장 값진 불확실성 신호다 — 이기는 쪽을 정하는 게 아니라 불일치를 위로 올린다. LLM 콜 추가 없음. 비용: rule의 FP만큼 HUMAN_REVIEW 증가 — 검증에서 빈도 실측 필요.

**결정: D5-C 채택 (2026-07-09).** 이유: 결정론과 LLM 중 승자를 정하는 대신 불일치를 불확실성 신호로 승격 — 추가 LLM 비용 없이 무기록 소멸을 제거. Sacrifice: rule engine FP만큼 HUMAN_REVIEW 증가 (검증에서 실측).

## D6 — 정답 라벨 누수 차단 (설계 중 발견, 잠정 채택: 프롬프트 화이트리스트)

CSV 파서가 정답을 `message`("Machine failure detected: TWF", `utils/csv_parser.py:100-101`)와 `tags["failure_types"]`(`130-131행`)에 심고, perception이 `model_dump()` 전체를 직렬화해 **배치 경로에서 LLM이 답안지를 본다** (tags는 AnomalyReport로 복사돼 SOP 쿼리 LLM까지 전파). 차단 전의 모든 배치 측정치는 오염 표본이다 — stream_simulator의 기존 lead time·오경보 수치 포함.

**채택안:** 에이전트 입력 조립을 화이트리스트 직렬화로(관측 필드만 명시적으로 포함) — 라벨은 파이프라인 안에 남아 검증·표시용으로 쓰되 LLM 눈에만 안 보임. "LLM에게는 원시 관측만"이라는 D5 개선 원칙과 한 몸.

탈락 한 줄씩: ⓐ 파서에서 제거 — 검증 하네스가 정답을 잃어 사이드 채널 구조를 새로 만들어야 함. ⓑ 평가 하네스만 정화 — 운영 경로 누수는 그대로, 측정과 운영이 다른 입력을 받아 대표성 붕괴.

## 인터페이스 초안 (스펙)

```
RoutingInput:    correlation_id, signals: dict[str, float|int|str|bool], policy_version
RoutingDecision: correlation_id, route(AUTO|HUMAN_REVIEW|ESCALATE), matched_rule,
                 reason, signal_snapshot, policy_version, ts
```

PipelineResult에 routing_decision 추가. 브릿지는 AUTO만 dry-run 명령 생성, ESCALATE는 NOTIFY_SUPERVISOR 고정. 기록은 ADR-008 DecisionEvent(stage="routing") 공유.

## 검증 계획

**선행 전제: D6 차단 적용 후에만 유효** (차단 전 수치는 "오염 표본" 표기).

**주 검증 — AI4I** (`data/raw/ai4i2020.csv` 10,000행, 고장 339건 전량):
1. 3분기 분포 (README 빈칸을 채우는 값) + 고장 모드별 분포 (D2 차등 필요성 판단 데이터)
2. **불량 유출 0건**: 고장 339건 중 사람 눈에 안 닿는 경로(SAFE 조기종료 AUTO, 무라벨 종료)로 끝난 건수 = 0
3. 자동화율 하한: 정상 9,661건 중 AUTO > 0% (0%면 레이어 무의미 — 목표치는 실측 후 재설정)
4. 라우팅 결정 일관성 ≥ 99% + 전 실행 routing DecisionEvent 존재 (ADR-008 연동)

**스트레스 검증 — SECOM** (test 314건, 불량 17건, XGBoost 확률을 오프라인 dict 주입 — 파이프라인 통합 아님):
- 합격 기준 (G2(a-1) 확정 조건, 현재는 주장이며 실측으로 채워야 통과): ① 자동화율 0% 수렴 ② AUTO로 라우팅된 실제 불량 0건

## 알려진 한계 (설계자가 스스로 찾은 경계)

**알람 피로의 재생산 위험.** "애매하면 사람으로"는 사람의 검토 용량이 유한하다는 현실과 긴장한다. 에스컬레이션이 과다하면 엔지니어는 형식 승인(rubber stamp)으로 흐르고 안전장치는 서류상으로만 남는다. SECOM의 "자동화율 0% 수렴"도 시스템 관점에선 안전한 실패지만 인간 관점에선 314건의 알람 폭주다 — 본 설계는 "불량 유출을 막는다"를 증명할 뿐 "사람이 감당할 수 있다"는 증명하지 않는다. 완화 방향은 에스컬레이션 총량 관리(검토 예산, 우선순위 큐)이며 본 설계 범위 밖 — **현장의 실제 관리 방식은 멘토링에서 확인 예정.** 검증 계획의 3분기 분포가 이 한계의 크기를 재는 첫 숫자다 (HUMAN_REVIEW 비율 = 요구되는 인간 용량).

## 명시적 제외 (알고 뺐다)

| 제외 | 이유 |
|---|---|
| ml_predictor 실시간 연결, 전처리 서빙 정합, 확률 보정 파이프라인 | G1(c) 확정 조건 — 필요해 보이는 순간이 (b)로의 미끄러짐, 멈추고 보고 |
| 신호 플러그인 레지스트리, 가중치 프레임워크 | 필요한 것은 "숫자 dict를 받는 함수"다 (G1(c)) |
| 임계값 자동 튜닝 | 표본 부족 상태의 튜닝은 과적합 (SECOM 교훈). 수동 + 실측 보고 |
| **피드백 루프** — 사람의 판정이 임계값·신호로 되돌아오는 경로 없음 | drift를 실측으로 확인해 필요성은 인지하나, 온라인 학습/재보정은 별도 신뢰성 문제(사람 라벨은 누가 검증하나)를 동반 — 알고 뺐다 |
| **탐지 자체의 FN** — rule이 안 울린 불량은 레이어가 완벽해도 도달 불가 | 문제정의를 "알람 이후 워크플로우"로 한정한 의도적 선택. 탐지 개선은 별도 트랙(ML/rule 보강) |
| **SOP 자체의 정확성** — grounding은 "문서와 정합"까지만, 낡은/틀린 문서는 못 잡음 (틀린 SOP에 충실한 계획이 만점 AUTO 통과 가능) | 지식 원천 품질은 조직 프로세스 영역. 시스템 책임은 "무엇을 근거로 답했는지 추적 가능"까지 — 그 추적성이 사후 역추적의 최소 조건 |
| 알림 채널 실구현, 대시보드 UI, 인프라, SECOM LLM 통합(컬럼 의미 원천 부재) | 범위 밖 / 원천 불가 — sacrifice |

## 결정 현황

- [x] **P = A** 출구 게이트 (2026-07-09 확정)
- [x] **D1 = B** 전 신호 dict + 우선순위 규칙 (2026-07-09 확정)
- [x] **D5 = C** 불일치 = 사람 확인 신호 (2026-07-09 확정)
- [x] D2 잠정 채택 (전역 + CRITICAL 2단), D6 잠정 채택 (화이트리스트) — 이견 시 재검토
- ADR-008의 D3(계측 이원화)·D4(seed 절충 + 99% 합격선)도 잠정 채택

※ 설계 중 발견된 새 갈림길은 D6 1건 (임의 결정 없이 추가 후 잠정 채택 처리).
