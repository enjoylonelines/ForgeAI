# ForgeAI

제조 설비 로그를 분석하는 **온프레미스 멀티에이전트 RAG 시스템**.  
외부 API 없이 Ollama 로컬 LLM만으로 위험 사전 평가 → 이상 감지 → Tool Use 진단 → SOP 조회 → 조치 계획 생성 → 할루시네이션 검증까지 **LangGraph StateGraph** 기반으로 완결합니다.

---

## 아키텍처

### 메인 파이프라인 (`POST /api/v1/analyze`)

```
EquipmentLog (센서 데이터)
        │
        ▼
┌──────────────────────────┐
│   RiskAssessmentAgent    │  AI4I 센서 범위 기반 위험 등급 사전 평가
│   (Prevention Layer)     │  SAFE → 조기 종료 (LLM 4콜 절약)
└──────────────────────────┘
        │  WARNING / CRITICAL
        ▼
┌──────────────────────────┐
│    PerceptionAgent       │  센서 값 분석, 이상 감지, AnomalyReport 생성
└──────────────────────────┘
        │  anomaly detected
        ▼
┌──────────────────────────┐
│   DiagnosticAgent        │  LangChain bind_tools() + 수동 ReAct 루프 (최대 5회)
│   (Tool Use / ReAct)     │  도구: get_sensor_thresholds, calculate_risk_index,
│                          │        alert_maintenance_team
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│     SOPRAGAgent          │  ChromaDB 벡터 검색, failure_type 메타데이터 필터 + 폴백
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│    ActionPlanAgent       │  SOP 기반 단계별 조치 계획 생성, 실패 시 피드백 반영 재시도
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│ HallucinationValidator   │  임베딩 코사인 유사도로 SOP 근거 정량 검증
└──────────────────────────┘
        │  REJECT + retry < MAX
        └──────────────────────▶  ActionPlanAgent (재시도)
        │  APPROVE / REVIEW
        ▼
  PipelineResult (risk_assessment, anomaly_report, action_plan, metrics)
```

**LangGraph 그래프 조건 분기:**

```
START → risk_assessment
  ├── SAFE ──────────────────────────────────────────────────────▶ END (early exit)
  └── WARNING/CRITICAL → perception
        ├── no anomaly ───────────────────────────────────────────▶ END
        └── anomaly → diagnostic → sop_rag → action_plan → validator
              ├── APPROVE/REVIEW ────────────────────────────────▶ END
              └── REJECT & retry < MAX ──────────────────────────▶ action_plan
```

### 자연어 진단 파이프라인 (`POST /api/v1/diagnose`)

```
UserQuery (자연어)
        │
        ▼
┌──────────────────────────┐
│  IntentExtractionAgent   │  자연어 → failure_type, equipment_id, sensor 키워드 추출
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│     SOPRAGAgent          │  추출된 의도 기반 SOP 검색
└──────────────────────────┘
        │
        ▼
┌──────────────────────────┐
│  DiagnosisResponseAgent  │  한국어 진단 응답 생성
└──────────────────────────┘
        ▼
  NLDiagnosisResult
```

---

## 기술 스택

| 구성 요소 | 선택 | 비고 |
|-----------|------|------|
| LLM | `qwen2.5:7b` (Ollama) | M2 Air 8GB 온프레미스, 외부 API 미사용 |
| 에이전트 오케스트레이션 | LangGraph `StateGraph` | 조건 분기 + 재시도 루프 |
| Tool Use | LangChain `bind_tools()` + 수동 ReAct | DiagnosticAgent, 최대 5회 루프 |
| 임베딩 | `nomic-embed-text` (Ollama) | 768-dim, cosine space |
| 벡터 DB | ChromaDB (로컬 영구 저장) | `./data/chroma`, failure_type 메타데이터 필터 |
| 데이터셋 | UCI AI4I 2020 Predictive Maintenance | `ucimlrepo` 패키지, id=601 |
| API | FastAPI + uvicorn | REST 4개 엔드포인트 |
| 관찰 가능성 | Langfuse | 에이전트별 트레이스, correlation_id 전파 |
| 테스트 | pytest + pytest-asyncio | 26개 단위 테스트 |

---

## 빠른 시작

### 사전 요구사항

- Python 3.11+
- [Ollama](https://ollama.com) 설치 및 실행 중

```bash
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

### 설치

```bash
git clone https://github.com/enjoylonelines/ForgeAI.git
cd ForgeAI

python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

cp .env.example .env
```

### 서버 실행

```bash
uvicorn main:app --reload
# http://localhost:8000
```

### SOP 문서 초기 인덱싱

```bash
./scripts/reindex.sh
```

---

## API 사용법

### 단건 센서 분석 — `POST /api/v1/analyze`

```bash
# 프리셋 스크립트 (normal | twf | hdf | pwf | osf)
./scripts/analyze.sh twf
```

직접 호출:

```bash
curl -s -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "equipment_id": "M-12345",
    "timestamp": "2026-06-05T08:00:00+00:00",
    "log_level": "ERROR",
    "readings": [
      {"sensor_id": "air_temperature_k",     "unit": "K",   "value": 298.1},
      {"sensor_id": "process_temperature_k", "unit": "K",   "value": 308.6},
      {"sensor_id": "rotational_speed_rpm",  "unit": "rpm", "value": 1251.0},
      {"sensor_id": "torque_nm",             "unit": "Nm",  "value": 42.8},
      {"sensor_id": "tool_wear_min",         "unit": "min", "value": 216.0}
    ],
    "message": "Machine failure detected: TWF",
    "tags": {"machine_type": "M", "failure_types": "TWF"}
  }' | python3 -m json.tool
```

응답 예시:

```json
{
  "correlation_id": "abc123",
  "risk_assessment": {
    "risk_level": "CRITICAL",
    "risk_factors": [{"sensor": "tool_wear_min", "value": 216.0, "threshold": 220.0}]
  },
  "anomaly_report": {
    "has_anomaly": true,
    "summary": "Tool wear (216 min) approaching failure threshold. Type: TWF."
  },
  "diagnostic_result": {
    "tool_calls": [
      {"tool": "get_sensor_thresholds", "args": {"equipment_type": "M"}},
      {"tool": "calculate_risk_index",  "args": {"tool_wear_min": 216.0, "torque_nm": 42.8, "rotational_speed_rpm": 1251.0}},
      {"tool": "alert_maintenance_team","args": {"equipment_id": "M-12345", "severity": "CRITICAL", "message": "..."}}
    ]
  },
  "action_plan": {
    "steps": ["Stop machine immediately", "Inspect tool wear", "..."]
  },
  "validation_result": {
    "overall_grounding_score": 0.731,
    "recommendation": "REVIEW",
    "is_valid": false
  },
  "metrics": {
    "risk_level": "CRITICAL",
    "early_exit": false,
    "retry_count": 0,
    "stages_completed": ["risk_assessment", "perception", "diagnostic", "sop_rag", "action_plan", "validator"]
  }
}
```

응답 헤더:
- `X-Plan-Status: APPROVED` — grounding_score ≥ 0.75
- `X-Plan-Status: REVIEW` — grounding_score < 0.75, 사람 검토 권고
- `X-Plan-Status: REJECTED` — 최대 재시도 후에도 검증 실패

### 자연어 진단 — `POST /api/v1/diagnose`

사용자가 체감한 이상 증상을 자연어로 입력하면 에이전트가 관련 SOP를 검색해 진단 응답을 생성합니다.

```bash
curl -s -X POST http://localhost:8000/api/v1/diagnose \
  -H "Content-Type: application/json" \
  -d '{"query": "장비 M-12345에서 진동이 심하고 온도가 올라가는데 무슨 문제인가요?"}' \
  | python3 -m json.tool
```

### CSV 배치 분석 — `POST /api/v1/analyze/csv`

```bash
curl -s -X POST http://localhost:8000/api/v1/analyze/csv \
  -F "file=@your_logs.csv" | python3 -m json.tool
```

배치 결과 `improvement_metrics` 포함:

| 지표 | 설명 |
|------|------|
| `early_exit_rate_pct` | SAFE 판정으로 조기 종료된 비율 (LLM 호출 절감) |
| `warning_prevented_count` | WARNING 감지로 예방 조치된 건수 |
| `llm_calls_saved` | early_exit 건수 × 4 (절약된 LLM 호출 수) |
| `avg_retries_per_row` | 평균 재시도 횟수 |

### SOP 문서 인제스트 — `POST /api/v1/ingest`

```bash
curl -s -X POST http://localhost:8000/api/v1/ingest \
  -F "file=@data/sop_docs/SOP-MNT-001-tool-wear-failure.md;type=text/markdown"
```

PDF, Markdown, TXT 지원.

### 헬스 체크 — `GET /api/v1/health`

```bash
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool
```

---

## 환경 변수

`.env.example`을 복사해 `.env`로 사용:

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `OLLAMA_CHAT_MODEL` | `qwen2.5:7b` | 대화용 LLM |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | 임베딩 모델 |
| `CHROMA_PERSIST_DIR` | `./data/chroma` | ChromaDB 저장 경로 |
| `GROUNDING_SCORE_THRESHOLD` | `0.75` | APPROVE/REVIEW 분기 기준 |
| `CHUNK_SIZE` | `1024` | RAG 청크 크기 (characters) |
| `CHUNK_OVERLAP` | `200` | 청크 간 겹침 크기 |
| `TOP_K_RETRIEVAL` | `5` | ChromaDB 상위 k 검색 수 |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse 트레이스 (선택) |
| `LANGFUSE_SECRET_KEY` | — | Langfuse 트레이스 (선택) |

---

## 테스트

```bash
python -m pytest tests/ -v
```

26개 테스트 (단위 테스트, mock 기반):

```
tests/test_pipeline.py              # 메인 파이프라인 + 조기 종료 + 재시도
tests/test_nl_diagnosis_pipeline.py # 자연어 진단 파이프라인 3케이스
tests/test_*.py                     # 에이전트별 단위 테스트
```

---

## 프로젝트 구조

```
ForgeAI/
├── agents/
│   ├── risk_assessment_agent.py   # 예방 레이어: AI4I 센서 범위 기반 위험 평가
│   ├── perception_agent.py        # 이상 감지, AnomalyReport 생성
│   ├── diagnostic_agent.py        # Tool Use / ReAct (bind_tools + 수동 루프)
│   ├── sop_rag_agent.py           # ChromaDB 검색 + failure_type 필터
│   ├── action_plan_agent.py       # SOP 기반 조치 계획, 재시도 피드백 반영
│   ├── hallucination_validator.py # 임베딩 코사인 유사도 검증
│   └── intent_extraction_agent.py # 자연어 → 구조화 의도 추출
├── pipeline/
│   ├── forge_pipeline.py          # LangGraph StateGraph 메인 파이프라인
│   └── nl_diagnosis_pipeline.py   # 자연어 진단 3-노드 파이프라인
├── tools/
│   └── sensor_tools.py            # LangChain @tool 3종: 임계값/위험지수/알림
├── api/
│   └── routes.py                  # FastAPI 엔드포인트 4종
├── core/                          # 설정, 로깅, Ollama/Langfuse 클라이언트
├── data/
│   ├── chroma/                    # ChromaDB 영구 저장소
│   └── sop_docs/                  # SOP 문서 5종 (TWF/HDF/PWF/OSF/RNF)
├── docs/
│   └── rag-improvement.md         # RAG 개선 4회 트러블슈팅 기록
├── models/                        # Pydantic 데이터 모델
├── prompts/                       # 에이전트별 프롬프트 템플릿
├── rag/                           # ChromaDB 클라이언트, 임베더, 인제스트
├── scripts/
│   ├── analyze.sh                 # 단건 분석 테스트 스크립트
│   └── reindex.sh                 # ChromaDB 초기화 및 재인덱싱
├── tests/                         # pytest 단위 테스트 (26개)
└── utils/                         # CSV 파서, AI4I 데이터 로더
```

---

## RAG 개선 기록

초기 구현에서 TWF 요청 시 HDF SOP가 1위로 검색되는 문제를 4회 반복 개선으로 해결했습니다.

| 지표 | 개선 전 | 최종 |
|------|---------|------|
| SOP 검색 1위 | HDF (0.417) | TWF (0.730) |
| grounding_score | 0.615 | 0.731 |

**적용한 개선:**

1. **SOP 영어 전환** — `nomic-embed-text` 크로스 언어 한계 해소 (한국어 원문은 HTML 주석으로 보존)
2. **chunk_size 512 → 1024** — 영어는 동일 내용에 2~3배 문자 사용, 문맥 보존
3. **failure_type 메타데이터 필터** — ChromaDB `where={"failure_type": {"$in": [...]}}` 적용, 결과 부족 시 폴백
4. **chunk_overlap 64 → 200** — 청크 경계에 위치한 절차 문장의 grounding score 개선

상세 분석 및 트레이드오프: [`docs/rag-improvement.md`](docs/rag-improvement.md)

---

## 설계 의도

이 프로젝트는 **제조 도메인 온프레미스 LLM 멀티에이전트 파이프라인** 구현 능력을 보여주기 위해 설계되었습니다.

- **LangGraph StateGraph**: 조건 분기 + 재시도 루프를 선언적으로 표현. 단순 순차 파이프라인 대비 SAFE 조기 종료로 LLM 호출 절감
- **예방 레이어 (RiskAssessmentAgent)**: 감지·대응보다 앞선 Prevention 단계. 실시간 스트리밍 시나리오 시뮬레이션 (AI4I 2020은 사후 라벨 데이터)
- **Tool Use / ReAct**: `bind_tools()` 기반 도구 호출 루프로 에이전트가 센서 임계값 조회, 위험지수 계산, 알림 발송을 자율 수행
- **보수적 임계값 (0.75)**: REVIEW 판정은 버그가 아닌 의도된 안전 설계. 제조 도메인에서 false negative보다 false positive가 낫다는 판단
- **온프레미스**: Ollama만 사용, OpenAI API 등 외부 의존성 없음
- **트레이스 로깅**: 모든 에이전트 호출에 `correlation_id` + Langfuse 스팬 전파
