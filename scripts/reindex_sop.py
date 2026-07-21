#!/usr/bin/env python3
"""
SOP 문서 재인덱싱 스크립트 (서버 없이 직접 실행).
ChromaDB를 초기화하고 data/sop_docs/ 의 마크다운 파일을 재인덱싱한다.

사용법:
    uv run python scripts/reindex_sop.py
    uv run python scripts/reindex_sop.py --sop-dir data/sop_docs --chroma-dir data/chroma
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def main(sop_dir: Path, chroma_dir: Path) -> None:
    # 지연 import — 환경 설정 후 로드
    from rag.ingestion import ingest_document

    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)
        print(f"[1/3] ChromaDB 초기화 완료: {chroma_dir}")
    else:
        print(f"[1/3] ChromaDB 디렉터리 없음 — 신규 생성")

    sop_files = sorted(sop_dir.glob("*.md")) + sorted(sop_dir.glob("*.pdf"))
    print(f"[2/3] SOP 문서 발견: {len(sop_files)}건")
    if not sop_files:
        print(f"[오류] {sop_dir} 에 문서가 없습니다.")
        sys.exit(1)

    print("[3/3] 인덱싱 시작...")
    total, success = 0, 0
    for fpath in sop_files:
        total += 1
        content_type = "text/markdown" if fpath.suffix == ".md" else "application/pdf"
        try:
            result = await ingest_document(
                file_bytes=fpath.read_bytes(),
                filename=fpath.name,
                content_type=content_type,
            )
            print(f"  ✓ {fpath.name}  ({result.chunk_count} chunks, total={result.collection_total})")
            success += 1
        except Exception as exc:
            print(f"  ✗ {fpath.name}  오류: {exc}")

    print(f"\n완료: {success}/{total} 문서 인덱싱 성공")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SOP 문서 재인덱싱")
    parser.add_argument("--sop-dir",    type=str, default="data/sop_docs", help="SOP 문서 디렉터리")
    parser.add_argument("--chroma-dir", type=str, default="data/chroma",   help="ChromaDB 저장 경로")
    args = parser.parse_args()

    asyncio.run(main(
        sop_dir=Path(args.sop_dir),
        chroma_dir=Path(args.chroma_dir),
    ))
