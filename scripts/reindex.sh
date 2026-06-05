#!/usr/bin/env bash
# ChromaDB 초기화 후 SOP 문서 전체 재인덱싱
#
# 사용법:
#   ./scripts/reindex.sh

set -euo pipefail

BASE_URL="${FORGE_URL:-http://localhost:8000}"
CHROMA_DIR="$(dirname "$0")/../data/chroma"
SOP_DIR="$(dirname "$0")/../data/sop_docs"

# ── 1. ChromaDB 데이터 삭제 ──────────────────────────────────────────────────
echo "[1/3] ChromaDB 데이터 삭제 중..."
if [ -d "$CHROMA_DIR" ]; then
    rm -rf "$CHROMA_DIR"
    echo "      삭제 완료: $CHROMA_DIR"
else
    echo "      이미 비어 있음"
fi

# ── 2. 서버 재시작 대기 ──────────────────────────────────────────────────────
echo ""
echo "[2/3] 서버를 재시작한 후 Enter를 누르세요."
echo "      (다른 터미널에서 uvicorn main:app --reload)"
read -r

echo "      서버 응답 확인 중..."
MAX_WAIT=30
WAITED=0
until curl -sf "${BASE_URL}/api/v1/health" > /dev/null 2>&1; do
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        echo "      [오류] ${MAX_WAIT}초 내에 서버가 응답하지 않습니다."
        exit 1
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done
echo "      서버 준비 완료"

# ── 3. SOP 문서 재인덱싱 ─────────────────────────────────────────────────────
echo ""
echo "[3/3] SOP 문서 인덱싱 시작..."

TOTAL=0
SUCCESS=0

for filepath in "$SOP_DIR"/*.md; do
    filename="$(basename "$filepath")"
    TOTAL=$((TOTAL + 1))

    response=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST "${BASE_URL}/api/v1/ingest" \
        -F "file=@${filepath};type=text/markdown")

    if [ "$response" = "200" ]; then
        SUCCESS=$((SUCCESS + 1))
        echo "      ✓ $filename"
    else
        echo "      ✗ $filename (HTTP $response)"
    fi
done

echo ""
echo "완료: ${SUCCESS}/${TOTAL} 문서 인덱싱 성공"

# ── 헬스 체크로 최종 확인 ────────────────────────────────────────────────────
echo ""
echo "컬렉션 상태:"
curl -s "${BASE_URL}/api/v1/health" | python3 -m json.tool
