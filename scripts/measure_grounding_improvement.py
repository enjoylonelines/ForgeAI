"""grounding_score 개선 전후 비교 측정 스크립트.

개선 전: action step 임베딩 vs 청크 전체 임베딩 (max)
개선 후: 위 + 인용 청크 문장 단위 임베딩 (max)

사용법:
    uv run python scripts/measure_grounding_improvement.py
"""
from __future__ import annotations

import asyncio
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.langchain_client import get_embeddings
from rag.chroma_client import get_sop_collection


# TWF 케이스 action steps (실제 ActionPlanAgent 출력과 유사한 지시문)
TEST_STEPS = [
    ("Stop the CNC equipment after the current machining cycle completes.",
     "SOP-MNT-001-tool-wear-failure.md::chunk::2"),
    ("Cordon off the work area and post warning signs to prevent entry.",
     "SOP-MNT-001-tool-wear-failure.md::chunk::2"),
    ("Notify the maintenance team immediately with equipment ID and tool wear value.",
     "SOP-MNT-001-tool-wear-failure.md::chunk::3"),
    ("Remove the worn tool using proper handling procedures and inspect for damage.",
     "SOP-MNT-001-tool-wear-failure.md::chunk::3"),
    ("Install a new tool according to manufacturer specifications and verify torque settings.",
     "SOP-MNT-001-tool-wear-failure.md::chunk::4"),
]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _split_sentences(text: str, min_len: int = 15) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if len(p.strip()) >= min_len]


async def main() -> None:
    col = get_sop_collection()
    emb = get_embeddings()

    # 필요한 청크 ID 수집
    cited_ids = list({sop_ref for _, sop_ref in TEST_STEPS})

    # ChromaDB에서 청크 임베딩 + 텍스트 가져오기
    result = col.get(ids=cited_ids, include=["embeddings", "documents"])
    chunk_embs: dict[str, list[float]] = {}
    chunk_texts: dict[str, str] = {}
    for cid, emb_vec, doc in zip(result["ids"], result["embeddings"], result["documents"]):
        chunk_embs[cid] = emb_vec
        chunk_texts[cid] = doc

    # 인용 청크별 문장 임베딩 계산
    sentence_embs: dict[str, list[list[float]]] = {}
    for cid, text in chunk_texts.items():
        sentences = _split_sentences(text)
        if sentences:
            vecs = await emb.aembed_documents(sentences)
            sentence_embs[cid] = vecs
            print(f"[{cid}] 문장 {len(sentences)}개 임베딩 완료")

    print()
    print(f"{'Step':<5} {'청크 단위(기존)':>14} {'문장 단위(신규)':>14} {'최종(max)':>10} {'개선':>8}")
    print("-" * 62)

    chunk_scores, sentence_scores, combined_scores = [], [], []

    for i, (action, sop_ref) in enumerate(TEST_STEPS, 1):
        step_vec = await emb.aembed_query(action)

        # 기존: 청크 전체 임베딩과 비교
        chunk_score = _cosine(step_vec, chunk_embs[sop_ref]) if sop_ref in chunk_embs else 0.0

        # 신규: 문장 단위 비교
        sent_score = 0.0
        if sop_ref in sentence_embs:
            for sv in sentence_embs[sop_ref]:
                s = _cosine(step_vec, sv)
                if s > sent_score:
                    sent_score = s

        combined = max(chunk_score, sent_score)
        delta = combined - chunk_score

        chunk_scores.append(chunk_score)
        sentence_scores.append(sent_score)
        combined_scores.append(combined)

        print(f"  {i:<3}  {chunk_score:>13.4f}  {sent_score:>13.4f}  {combined:>9.4f}  {delta:>+7.4f}")

    print("-" * 62)
    avg_chunk    = sum(chunk_scores) / len(chunk_scores)
    avg_sentence = sum(sentence_scores) / len(sentence_scores)
    avg_combined = sum(combined_scores) / len(combined_scores)
    delta_avg    = avg_combined - avg_chunk

    print(f"{'평균':<5}  {avg_chunk:>13.4f}  {avg_sentence:>13.4f}  {avg_combined:>9.4f}  {delta_avg:>+7.4f}")
    print()
    print(f"APPROVE 기준 (0.85): 기존 {'✅' if avg_chunk >= 0.85 else '❌'}  →  개선 후 {'✅' if avg_combined >= 0.85 else '❌'}")
    print(f"REVIEW  기준 (0.60): 기존 {'✅' if avg_chunk >= 0.60 else '❌'}  →  개선 후 {'✅' if avg_combined >= 0.60 else '❌'}")


if __name__ == "__main__":
    asyncio.run(main())
