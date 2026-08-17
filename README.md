# ForgeAI

> **현재 포트폴리오 범위:** AI4I 고장 모드별 정보 한계를 분석하고,
> HDF/PWF/OSF 물리 규칙과 TWF 예방정비를 결합해 현장 엔지니어에게
> 필요한 정비 알림만 남기는
> 하이브리드 설비 모니터링 시스템

## 현재 문제 정의

**고장 미탐을 늘리지 않으면서 불필요한 정비 판정 알림을 제거해,
현장 엔지니어에게 필요한 알림만 남긴다.**

AI4I에는 실제 알림 이력이 없으므로, 모델과 운영정책이 생성한
`정비 필요 판정 건수`를 알림 피로의 대리지표로 사용한다.

## 현재 검증 결과

- 평가 프로토콜: train 60% / validation 20% / test 20%, 10개 반복 시드
- 임계값 선택: validation에서만 결정하고 test에는 고정 적용
- 통합 4모드 ML: test 정비 필요 판정 중앙값 732건, 관측 FN=0 4/10회
- 최종 하이브리드 정책: test 정비 필요 판정 중앙값 213건, 관측 FN=0 10/10회
- 통합 ML 대비 정비 필요 판정 건수 중앙값 **70.9% 감소**
- 라벨 책임 범위: RNF-only 18건과 원인 플래그 없는 고장 9건은 별도 감사

재현 가능한 실험은
[`docs/experiments/hybrid_policy_results.md`](docs/experiments/hybrid_policy_results.md)에 정리했다.

### Agent reliability 검증

에이전트 도구 호출과 라우팅 안전성은 별도 mock 계약으로 검증한다.
현재 `agent-reliability-v1` 결과는 24개 case 중 23개를 deterministic mock으로 평가하고
1개 live opt-in case를 제외했다. 결과는 route accuracy 100.0%,
required-tool recall 100.0%, unsafe AUTO 0건이다.

Ollama를 쓰지 않는 노트북 smoke 경로도 분리했다. `LLM_MODE=api`에서 단일
OpenAI-compatible API 요청은 통과했고 latency와 token usage를 관측했다. 다만 이는
1회 opt-in smoke이며, p50/p95 latency나 운영 SLA, full ForgePipeline live benchmark,
monetary cost 검증으로 주장하지 않는다. cost는 versioned pricing table이 없어
`unavailable`로 남긴다.

세부 조건과 한계는
[`docs/agent-reliability-result.md`](docs/agent-reliability-result.md)에 정리했다.

이력서용 표현과 산출물은 별도 저장소 `portfolio`로 분리했다 (2026-08-11).
어필 포인트는 `portfolio/notes/portfolio-resume-highlights.md`에 있다.

---

## 재현 방법

```bash
git clone https://github.com/enjoylonelines/ForgeAI.git
cd ForgeAI
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 하이브리드 정책 실험 재실행

```bash
python scripts/hybrid_policy_evaluation.py
# → docs/experiments/hybrid_policy_results.json  (원본 결과)
# → docs/experiments/hybrid_policy_results.md    (검증 리포트)
```

10개 시드로 train/validation/test를 분리하고, validation에서 고른 임계값을
test에 고정 적용해 재실행합니다. 위 "현재 검증 결과"의 모든 수치가 이 스크립트에서 나옵니다.

### 결과 대시보드

```bash
streamlit run dashboard/app.py
```

---

## 저장소 구조

| 경로 | 내용 |
|------|------|
| `scripts/` | 실험·검증 스크립트 20개 (하이브리드 정책 평가, 운영점 분석, 모드별 frontier, 승격 게이트 등) |
| `docs/experiments/` | 실험 원본 결과(JSON)와 검증 리포트 |
| `docs/agent-reliability-result.md` | Agent 도구 선택·라우팅 안전성 mock 평가 결과 |
| `docs/adr/` | 설계 결정 기록 15건 — 무엇을 왜 그렇게 정했는지 |
| `dashboard/` | Streamlit 결과 대시보드 |
| `core/`, `agents/` | 규칙 엔진·ML 예측기·에이전트 구현 |
| `docs/legacy-multiagent-rca.md` | 초기 범위였던 멀티에이전트 RAG·RCA 구현 이력 |

---

## 설계 결정 기록 (ADR)

주요 판단만 추립니다. 전체 목록은 [`docs/adr/`](docs/adr/)에 있습니다.

| ADR | 결정 |
|-----|------|
| [003](docs/adr/ADR-003-eval-metric-operating-point.md) | 평가지표를 PR-AUC + 재현율로 두고 정확도를 배제 |
| [005](docs/adr/ADR-005-classical-ml-vs-llm-separation.md) | 예측 레이어와 설명 레이어를 분리 |
| [010](docs/adr/ADR-010-model-comparison-protocol.md) | 모델 비교 프로토콜 — 단일 점수가 아닌 반복 분할 분산으로 판단 |
| [011](docs/adr/ADR-011-deployment-gate.md) | 승격 게이트 — 기준 미달 모델의 배포 차단 |
| [014](docs/adr/ADR-014-traceability-coverage-metric.md) | 근거 추적 가능 여부의 측정 정의 |

---

## 한계

- AI4I는 합성 데이터이며 행 단위 스냅샷이라, 시간 기반 조기 예측이나 잔여수명(RUL) 추정은 다루지 않습니다.
- 정비 필요 판정 건수는 실제 알림 이력이 없어 **알림 피로의 대리지표**로 사용했습니다.
- 반복 test 분할에서 관측한 미탐 0건이 미래 미탐률 0%를 보장하지는 않습니다.
- TWF 198분 교체 기준은 AI4I에 맞춘 보수적 정책이며, 실제 공장에 그대로 적용되는 값이 아닙니다.
