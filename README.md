# ForgeAI

제조 설비 로그를 분석하는 **온프레미스 멀티에이전트 RAG 시스템**.  
외부 API 없이 Ollama 로컬 LLM만으로 이상 감지 → SOP 조회 → 조치 계획 생성 → 할루시네이션 검증까지 순차 파이프라인을 완결합니다.

---

## 아키텍처

```
EquipmentLog (센서 데이터)
        │
        ▼
┌─────────────────────┐
│  PerceptionAgent    │  센서 값 분석, 이상 감지, AnomalyReport 생성
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│   SOPRAGAgent       │  ChromaDB 벡터 검색, failure_type 필터 + 폴백
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│  ActionPlanAgent    │  SOP 기반 단계별 조치 계획 생성
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│ HallucinationValidator │  임베딩 코사인 유사도로 SOP 근거 검증
└─────────────────────┘
        │
        ▼
  PipelineResult (grounding_score, is_valid, recommendation)
```

각 에이전트는 독립적인 Ollama LLM 호출로 동작하며, `correlation_id`로 전체 파이프라인 트레이스를 구성합니다.

---

## 기술 스택

| 구성 요소 | 선택 | 비고 |
|-----------|------|------|
| LLM | `qwen2.5:7b` (Ollama) | M2 Air 8GB 온프레미스, 외부 API 미사용 |
| 임베딩 | `nomic-embed-text` (Ollama) | 768-dim, cosine space |
| 벡터 DB | ChromaDB (로컬 영구 저장) | `./data/chroma` |
| 데이터셋 | UCI AI4I 2020 Predictive Maintenance | `ucimlrepo` 패키지, id=601 |
| API | FastAPI + uvicorn | `/api/v1/analyze`, `/api/v1/ingest`, `/api/v1/health` |
| 테스트 | pytest + pytest-asyncio | `unittest.mock` 기반 단위 테스트 |

---

## 빠른 시작

### 사전 요구사항

- Python 3.11+
- [Ollama](https://ollama.com) 설치 및 실행 중

```bash
# 필요 모델 풀
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

### 설치

```bash
git clone <repo-url>
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

서버가 처음 실행된 후 SOP 문서를 ChromaDB에 인덱싱합니다.

```bash
./scripts/reindex.sh
```

---

## API 사용법

### 단건 분석 — `POST /api/v1/analyze`

```bash
# TWF(Tool Wear Failure) 샘플
./scripts/analyze.sh twf

# 프리셋: normal | twf | hdf | pwf | osf
./scripts/analyze.sh hdf
```

직접 호출:

```bash
curl -s -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "equipment_id": "M-12345",
    "timestamp": "2026-06-03T08:00:00+00:00",
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
  "anomaly_report": {
    "has_anomaly": true,
    "summary": "Tool wear (216 min) exceeds threshold. Failure type: TWF.",
    "tags": {"machine_type": "M", "failure_types": "TWF"}
  },
  "sop_context": {
    "retrieved_chunks": [...]
  },
  "action_plan": {
    "steps": ["Stop machine immediately", "Inspect tool wear", "..."]
  },
  "validation_result": {
    "overall_grounding_score": 0.731,
    "recommendation": "REVIEW",
    "is_valid": false
  }
}
```

`recommendation` 값:
- `APPROVE` — grounding_score ≥ 0.75, SOP 근거 충분
- `REVIEW` — grounding_score < 0.75, 사람 검토 필요 (보수적 안전 설계)

### CSV 배치 분석 — `POST /api/v1/analyze/csv`

```bash
curl -s -X POST http://localhost:8000/api/v1/analyze/csv \
  -F "file=@your_logs.csv" | python3 -m json.tool
```

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

---

## 테스트

```bash
python -m pytest tests/ -v
```

---

## 프로젝트 구조

```
ForgeAI/
├── agents/               # 4개 에이전트 (perception, sop_rag, action_plan, hallucination_validator)
├── api/                  # FastAPI 라우터
├── core/                 # 설정, 로깅, Ollama 클라이언트
├── data/
│   ├── chroma/           # ChromaDB 영구 저장소
│   └── sop_docs/         # SOP 문서 5종 (TWF/HDF/PWF/OSF/RNF)
├── docs/
│   └── rag-improvement.md  # RAG 개선 트러블슈팅 기록
├── models/               # Pydantic 데이터 모델
├── pipeline/             # ForgePipeline 오케스트레이터
├── prompts/              # 에이전트별 프롬프트 템플릿
├── rag/                  # ChromaDB 클라이언트, 임베더, 인제스트
├── scripts/
│   ├── analyze.sh        # 단건 분석 테스트 스크립트
│   └── reindex.sh        # ChromaDB 초기화 및 재인덱싱
├── tests/                # pytest 단위 테스트
└── utils/                # CSV 파서, AI4I 데이터 로더
```

---

## RAG 개선 기록

초기 구현에서 TWF 요청 시 HDF SOP가 1위로 검색되는 문제를 4회 반복 개선으로 해결했습니다.

| 지표 | 개선 전 | 최종 |
|------|---------|------|
| SOP 검색 1위 | HDF (0.417) | TWF (0.730) |
| grounding_score | 0.615 | 0.731 |
| escalation_required 판정 | false (오판) | true (정확) |

**적용한 개선:**

1. **SOP 영어 전환** — 한/영 임베딩 유사도 불일치 해소 (`nomic-embed-text` 크로스 언어 한계)
2. **chunk_size 512 → 1024** — 영어는 동일 내용에 2~3배 문자 사용, 문맥 보존
3. **failure_type 메타데이터 필터** — `tags.failure_types`로 ChromaDB where 필터 적용, 결과 부족 시 폴백
4. **chunk_overlap 64 → 200** — 청크 경계에 위치한 절차 문장의 grounding score 개선

상세 분석 및 트레이드오프: [`docs/rag-improvement.md`](docs/rag-improvement.md)

---

## 설계 의도

이 프로젝트는 **제조 도메인 온프레미스 LLM 멀티에이전트 파이프라인** 구현 능력을 보여주기 위해 설계되었습니다.

- **순차 파이프라인**: 각 에이전트가 이전 에이전트 출력을 입력으로 받아 선형 실행
- **할루시네이션 검증**: 임베딩 코사인 유사도로 액션 플랜이 SOP에 근거하는지 정량 측정
- **보수적 임계값 (0.75)**: REVIEW 판정은 버그가 아닌 의도된 안전 설계. 제조 도메인에서 false negative보다 false positive가 낫다는 판단
- **온프레미스**: Ollama만 사용, OpenAI API 등 외부 의존성 없음
- **트레이스 로깅**: 모든 에이전트 호출에 `correlation_id` 전파
