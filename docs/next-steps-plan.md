# 다음 작업 계획

## Task 1 — 테스트 업데이트

### 배경
이번 세션에서 다음 코드 변경이 있었고 기존 테스트에 영향을 줌:
- `models/anomaly_report.py`: `tags: dict[str, str] = {}` 필드 추가
- `agents/perception_agent.py`: `log.tags` → `AnomalyReport.tags` 전달
- `agents/sop_rag_agent.py`: failure_type where 필터 추가
- `rag/ingestion.py`: failure_type 메타데이터 저장

### 수정 필요 항목

#### `tests/conftest.py`

1. `sample_anomaly_report` fixture에 `tags` 추가:
```python
# 현재 (tags 없음)
AnomalyReport(equipment_id="M-12345", ..., correlation_id=_CID)

# 수정
AnomalyReport(equipment_id="M-12345", ..., tags={"machine_type": "M", "failure_types": "TWF"}, correlation_id=_CID)
```

2. `mock_chroma_collection`의 메타데이터에 `failure_type` 추가:
```python
# 현재
"metadatas": [[{"document_name": "SOP-MNT-001.md", "chunk_index": 2, "page_number": 0, "equipment_tags": ""}]]

# 수정
"metadatas": [[{"document_name": "SOP-MNT-001.md", "chunk_index": 2, "page_number": 0, "equipment_tags": "", "failure_type": "TWF"}]]
```

#### `tests/test_perception_agent.py`

tags가 EquipmentLog에서 AnomalyReport로 전달되는지 검증하는 테스트 추가:
```python
async def test_perception_agent_tags_propagated(mock_ollama_chat, sample_equipment_log, correlation_id):
    mock_ollama_chat.return_value = _VALID_RESPONSE
    agent = PerceptionAgent()
    report = await agent.run(sample_equipment_log, correlation_id)
    assert report.tags == sample_equipment_log.tags
```

#### `tests/test_sop_rag_agent.py`

failure_type where 필터가 적용되는지 검증하는 테스트 추가:
```python
async def test_sop_rag_agent_uses_failure_type_filter(mock_ollama_chat, mock_ollama_embed, mock_chroma_collection, sample_anomaly_report, correlation_id):
    # sample_anomaly_report.tags = {"failure_types": "TWF"} 인 경우
    mock_ollama_chat.return_value = json.dumps({"query": "tool wear failure procedure"})
    agent = SOPRAGAgent()
    await agent.run(sample_anomaly_report, correlation_id)

    call_kwargs = mock_chroma_collection.query.call_args.kwargs
    assert call_kwargs.get("where") == {"failure_type": {"$in": ["TWF"]}}


async def test_sop_rag_agent_no_filter_without_tags(mock_ollama_chat, mock_ollama_embed, mock_chroma_collection, correlation_id):
    # tags 없는 anomaly_report는 where 필터 없이 검색
    from models.anomaly_report import AnomalyReport, AnomalyDetail
    from datetime import datetime, timezone
    report_no_tags = AnomalyReport(
        equipment_id="M-00001",
        timestamp=datetime(2026, 6, 3, tzinfo=timezone.utc),
        has_anomaly=True,
        anomalies=[],
        summary="anomaly",
        raw_log_snippet="{}",
        tags={},
    )
    mock_ollama_chat.return_value = json.dumps({"query": "failure procedure"})
    agent = SOPRAGAgent()
    await agent.run(report_no_tags, correlation_id)

    call_kwargs = mock_chroma_collection.query.call_args.kwargs
    assert call_kwargs.get("where") is None
```

### 실행 확인
```bash
cd /Users/hb/Documents/code/ForgeAI
python -m pytest tests/ -v
```

---

## Task 2 — README 작성

### 포함할 섹션

1. **프로젝트 개요** — 제조 설비 로그 멀티에이전트 RAG 시스템, 포트폴리오 목적
2. **아키텍처** — 4개 에이전트 파이프라인 흐름 다이어그램 (텍스트 기반)
3. **기술 스택** — FastAPI, Ollama qwen2.5:7b, ChromaDB, nomic-embed-text, AI4I 2020
4. **빠른 시작** — 환경 설정, Ollama 모델 다운로드, SOP 인덱싱, 서버 실행
5. **API 사용법** — `/api/v1/analyze`, `/api/v1/analyze/csv`, `/api/v1/ingest` curl 예시
6. **RAG 개선 기록** — `docs/rag-improvement.md` 링크

### 아키텍처 다이어그램 (텍스트)
```
EquipmentLog (센서 데이터)
     │
     ▼
[1] PerceptionAgent ──── 이상 탐지 → AnomalyReport
     │
     ▼
[2] SOPRAGAgent ──────── ChromaDB 벡터 검색 → SOPContext
     │                   (failure_type 메타데이터 필터)
     ▼
[3] ActionPlanAgent ──── SOP 기반 조치 생성 → ActionPlan
     │
     ▼
[4] HallucinationValidatorAgent ── 임베딩 유사도 검증 → ValidationResult
     │
     ▼
PipelineResult (correlation_id로 전 단계 추적)
```

---

## Task 3 — AI4I 데이터셋 end-to-end 검증

### 목적
`utils/data_loader.py`의 `load_ai4i_anomaly_samples(n)`을 사용해 실제 데이터셋으로 CSV 배치 분석이 동작하는지 확인.

### 확인 항목
1. `load_ai4i_anomaly_samples(10)`으로 샘플 10개 추출 → CSV 저장
2. `/api/v1/analyze/csv`로 업로드
3. `anomaly_count`, `processed_rows` 확인
4. 고장 유형별(TWF/HDF/PWF/OSF) 탐지율 확인

### 스크립트 위치
`scripts/test_batch.sh` 또는 `scripts/test_batch.py` 신규 작성
