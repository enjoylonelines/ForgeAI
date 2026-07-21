# ADR-006: RAG 원본 문서와 벡터 분리로 임베딩 모델 교체 흡수

**상태:** 채택

---

## 맥락

RAG 시스템에서 임베딩 모델은 교체될 수 있다 (성능 개선, 모델 deprecated, 언어 대응 변경 등).  
만약 원본 문서와 벡터 DB가 혼재되거나, 재인덱싱 절차가 복잡하면 모델 교체가 대형 작업이 된다.  
이 프로젝트에서는 실제로 SOP 문서를 한국어에서 영어로 전환하는 과정에서  
"원본을 어디서 관리하고, 벡터는 어떻게 재생성하는가"라는 설계 결정이 필요했다.

또한 `nomic-embed-text`가 한국어/영어 크로스 임베딩에서 낮은 판별력을 보여  
SOP 언어를 영어로 전환하는 과정에서 원본 문서 관리 방식을 정해야 했다.

---

## 고려한 대안

### 대안 A: 원본과 벡터를 ChromaDB에만 저장

- **방법:** 문서 텍스트를 ChromaDB `documents` 필드에 저장. 별도 원본 파일 없음
- **장점:** 인제스트 한 번으로 끝
- **단점:**
  - ChromaDB는 파생물(벡터 캐시)인데 원본 진실(truth source) 역할까지 맡게 됨
  - 임베딩 모델 교체 시 ChromaDB를 지우면 원본도 사라짐
  - 문서 내용을 수정하려면 ChromaDB API를 통해야 함 (git diff 불가)

### 대안 B: 원본 문서를 파일시스템에, 벡터만 ChromaDB에 — 채택

- **방법:** `data/sop_docs/*.md`가 원본 (git 관리), ChromaDB는 재생성 가능한 파생물
- **장점:**
  - 임베딩 모델 교체 = `rm -rf data/chroma && ./scripts/reindex.sh` (배치 작업)
  - 원본 문서는 git 히스토리로 변경 추적 가능
  - SOP 내용 수정은 `.md` 파일 편집 → reindex
- **단점:** 인제스트 스크립트를 별도로 실행해야 함 (자동화 필요)

### 대안 C: 원본 DB (PostgreSQL/S3) + 벡터 DB 분리

- **방법:** 문서 관리는 별도 DB, 벡터만 ChromaDB
- **장점:** 프로덕션 수준 문서 관리, 접근 제어, 버전 관리
- **단점:** 온프레미스 소규모 SOP(5개 문서)에 과도한 인프라. 포트폴리오 범위 초과

---

## 결정

대안 B — 원본 문서는 `data/sop_docs/*.md` (git 관리), ChromaDB는 파생물.

```
data/sop_docs/                ← 원본 (truth source)
  SOP-MNT-001-tool-wear-failure.md
  SOP-MNT-002-heat-dissipation-failure.md
  SOP-MNT-003-power-failure.md
  SOP-MNT-004-overstrain-failure.md
  SOP-MNT-005-random-failure.md
        │
        │  ./scripts/reindex.sh
        ▼
data/chroma/                  ← 파생물 (재생성 가능한 캐시)
  chroma.sqlite3
  {collection_uuid}/
```

**SOP 문서 형식:** 영어 본문 + `<!-- 한국어 -->` HTML 주석  
**인덱싱 전처리:** `re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)` — 임베딩에는 영어만 사용, 파일에는 한국어 보존

---

## 이유 (인과)

SOP 문서는 설비 도메인 지식의 명시적 자산이다. 이 자산의 진실은 임베딩 벡터가 아니라 원본 텍스트다.  
임베딩 모델이 바뀌어도 원본 텍스트는 바뀌지 않는다. 따라서 재생성은 항상 가능하다.  
ChromaDB를 "캐시"로 취급하면 모델 교체, 버그 수정, 컬렉션 초기화가 재앙이 아닌 운영 절차가 된다.

이 결정은 실제로 한국어→영어 SOP 전환 과정에서 검증됐다:  
원본 `.md` 파일을 수정하고 `reindex.sh`를 실행한 것이 전부였다.

---

## 포기한 것 / 트레이드오프

파일시스템 원본은 접근 제어(IAM), 버전 관리(non-git), 동시 편집에 약하다.  
SOP 문서가 수백 개로 늘어나거나 여러 사람이 편집하면 별도 문서 관리 시스템이 필요하다.  
현재 규모(5개 문서, 1인 운영)에서는 파일시스템 + git으로 충분하다.

---

## 결과 / 검증

**RAG 개선 4회 결과 (docs/rag-improvement.md 상세):**

| 지표 | 개선 전 | 최종 |
|------|---------|------|
| TWF 요청 시 1위 SOP | HDF (0.417) | TWF (0.730) |
| grounding_score | 0.615 | 0.731 |

개선 내역:
1. SOP 영어 전환 (한국어/영어 크로스 임베딩 유사도 저하 해소)
2. chunk_size 512 → 1024 (영어 동일 내용 2~3배 문자 사용)
3. failure_type 메타데이터 필터 (`where={"failure_type": {"$in": [...]}}`)
4. chunk_overlap 64 → 200 (청크 경계 문장 grounding score 개선)

이 4회 개선 모두 원본 `.md` 수정 + reindex로 처리됐다. ChromaDB 내부를 직접 건드리지 않았다.
