#!/usr/bin/env bash
# AI4I 2020 데이터셋 배치 분석 end-to-end 테스트.
#
# AI4I 고장 샘플을 CSV로 내보낸 뒤 /api/v1/analyze/csv 엔드포인트에 업로드하고
# 결과 요약을 출력한다.
#
# 사용법:
#   ./scripts/test_batch.sh            # 기본 10개 샘플
#   ./scripts/test_batch.sh 20         # 20개 샘플
#   FORGE_URL=http://... ./scripts/test_batch.sh 5

set -euo pipefail

BASE_URL="${FORGE_URL:-http://localhost:8000}"
N="${1:-10}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TMP_CSV="$(mktemp /tmp/ai4i_batch_XXXXXX.csv)"
trap 'rm -f "$TMP_CSV"' EXIT

echo "=== ForgeAI AI4I 배치 검증 (샘플 ${N}개) ==="
echo "서버: ${BASE_URL}"
echo ""

# 1. 헬스 체크
echo "[1/3] 헬스 체크..."
HEALTH=$(curl -sf "${BASE_URL}/api/v1/health" || echo '{"status":"error"}')
STATUS=$(echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))")
if [ "$STATUS" != "ok" ]; then
    echo "  경고: 서버 상태 = ${STATUS}"
    echo "  $HEALTH" | python3 -m json.tool
    echo ""
    echo "  서버가 실행 중인지 확인하세요: uvicorn main:app --reload"
    exit 1
fi
DOCS=$(echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('collection_doc_count','?'))")
echo "  상태: ok  (ChromaDB 문서 수: ${DOCS})"
echo ""

# 2. AI4I CSV 생성
echo "[2/3] AI4I 고장 샘플 CSV 생성 중 (${N}개)..."
python3 - <<PYEOF
import sys, csv
sys.path.insert(0, "$PROJECT_ROOT")
from utils.data_loader import load_ai4i_anomaly_samples

logs = load_ai4i_anomaly_samples(n=$N)

sensor_order = [
    "air_temperature_k",
    "process_temperature_k",
    "rotational_speed_rpm",
    "torque_nm",
    "tool_wear_min",
]

fieldnames = ["equipment_id", "timestamp", "machine_type", "machine_failure",
              "twf", "hdf", "pwf", "osf", "rnf"] + sensor_order

with open("$TMP_CSV", "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for log in logs:
        failure_types = log.tags.get("failure_types", "").split(",")
        sensor_vals = {r.sensor_id: r.value for r in log.readings}
        row = {
            "equipment_id": log.equipment_id,
            "timestamp": log.timestamp.isoformat(),
            "machine_type": log.tags.get("machine_type", ""),
            "machine_failure": 1 if log.log_level in ("ERROR", "CRITICAL") else 0,
            "twf": 1 if "TWF" in failure_types else 0,
            "hdf": 1 if "HDF" in failure_types else 0,
            "pwf": 1 if "PWF" in failure_types else 0,
            "osf": 1 if "OSF" in failure_types else 0,
            "rnf": 1 if "RNF" in failure_types else 0,
        }
        for s in sensor_order:
            row[s] = sensor_vals.get(s, "")
        writer.writerow(row)

print(f"  CSV 생성 완료: {len(logs)}행  →  $TMP_CSV")
PYEOF
echo ""

# 3. 배치 분석 POST
echo "[3/3] /api/v1/analyze/csv 업로드 중..."
RESPONSE=$(curl -s -X POST "${BASE_URL}/api/v1/analyze/csv" \
    -F "file=@${TMP_CSV};type=text/csv" \
    -H "X-Correlation-ID: ai4i-batch-test")

echo ""
echo "=== 결과 ==="
echo "$RESPONSE" | python3 - <<PYEOF
import sys, json

raw = sys.stdin.read().strip()
if not raw:
    print("  오류: 서버 응답이 비어 있습니다.")
    print("  서버 로그를 확인하세요.")
    sys.exit(1)

try:
    data = json.loads(raw)
except json.JSONDecodeError:
    print("  오류: JSON 파싱 실패. 원본 응답:")
    print(raw[:500])
    sys.exit(1)
total     = data.get("total_rows", 0)
processed = data.get("processed_rows", 0)
anomalies = data.get("anomaly_count", 0)
results   = data.get("results", [])

print(f"  전체 행       : {total}")
print(f"  처리 성공     : {processed}")
print(f"  이상 감지     : {anomalies} ({anomalies/processed*100:.0f}%)" if processed else "  이상 감지: 0")
print("")

scores = [r["grounding_score"] for r in results if "grounding_score" in r]
if scores:
    avg = sum(scores) / len(scores)
    print(f"  평균 grounding score: {avg:.3f}")

rec_counts = {}
for r in results:
    rec = r.get("recommendation", "N/A")
    rec_counts[rec] = rec_counts.get(rec, 0) + 1
if rec_counts:
    print("  판정 분포:")
    for rec, cnt in sorted(rec_counts.items()):
        print(f"    {rec:<8} : {cnt}")

print("")
print(f"{'#':<4} {'Equipment ID':<14} {'Anomaly':<8} {'Score':<7} {'Result'}")
print("-" * 50)
for r in results:
    if "error" in r:
        print(f"{r.get('row_index','?'):<4} {'ERROR':<14} {'':8} {'':7} {r['error'][:30]}")
    else:
        a = "YES" if r.get("has_anomaly") else "NO "
        sc = f"{r.get('grounding_score', 0):.3f}"
        print(f"{r.get('row_index',''):<4} {r.get('equipment_id',''):<14} {a:<8} {sc:<7} {r.get('recommendation','')}")
PYEOF
