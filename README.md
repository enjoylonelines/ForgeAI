# ForgeAI

> **현재 포트폴리오 범위:** AI4I 고장 모드별 정보 한계를 분석하고,
> HDF/PWF/OSF 물리 규칙과 TWF 예방정비를 결합해 현장 엔지니어에게
> 필요한 정비 알림만 남기는
> 하이브리드 설비 모니터링 시스템

## 프로젝트 한눈에 보기

| 구분 | 내용 |
| --- | --- |
| 해결할 문제 | 고장 미탐을 늘리지 않으면서 현장 엔지니어가 확인해야 할 불필요한 정비 판정을 줄입니다. |
| 핵심 해결 | 고장 유형별 ML, 물리 규칙, 검증 게이트를 결합하고 에이전트의 도구 호출 실패가 자동 조치로 이어지지 않게 차단합니다. |
| 결과 확인 | [`하이브리드 정책 실험`](docs/experiments/hybrid_policy_results.md) · [`에이전트 신뢰성 검증`](docs/agent-reliability-result.md) |
| 로컬 화면 | [Streamlit 대시보드](http://localhost:8501) — `streamlit run dashboard/app.py` 실행 후 접근 |
| 로컬 API | [FastAPI](http://localhost:8000) · [Swagger 문서](http://localhost:8000/docs) · [Health](http://localhost:8000/api/v1/health) |
| 공개 배포 | 확인된 공개 배포 URL 없음 — 현재 README는 재현 가능한 로컬 실행과 검증 산출물을 기준으로 설명합니다. |

> 로컬 주소는 서버를 직접 실행했을 때만 열립니다. 테스트·로컬 API 확인 결과를 운영 배포나 SLA 근거로 확대하지 않습니다.

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

### 에이전트 신뢰성 검증

에이전트가 도구를 잘못 호출하거나, 잘못된 인자를 넘기거나, 반복 한도를 초과하거나,
근거가 충돌하는 상황을 포함해 총 24개의 신뢰성 검증 사례를 정의했다.
이 중 외부 모델 호출 없이 재현 가능한 23개 사례에서 기대한 라우팅 결과와 실제 결과가
모두 일치했고, 필요한 도구 호출 누락은 없었으며, 사람이 검토해야 할 상황이 자동 처리로
넘어간 경우는 0건이었다.

이 수치는 실제 LLM 성능 벤치마크가 아니라, 실패 상황이 자동 처리로 이어지지 않도록
막는 안전 계약 검증이다. Ollama를 쓰지 않는 노트북 확인 경로도 분리해
`LLM_MODE=api`에서 단일 API 요청이 통과하고 지연 시간과 토큰 사용량이 기록되는 것을
확인했다. 다만 이는 1회 선택 실행 확인이며, p50/p95 지연 시간이나 운영 SLA,
전체 ForgePipeline 실시간 벤치마크, 비용 검증으로 주장하지 않는다. 비용은 버전이 고정된
가격표가 없어 `unavailable`로 남긴다.

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
| `docs/agent-reliability-result.md` | 에이전트 도구 호출·라우팅 안전성 검증 결과 |
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
