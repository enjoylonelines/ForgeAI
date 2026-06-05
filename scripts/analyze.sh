#!/usr/bin/env bash
# /api/v1/analyze 테스트 스크립트
#
# 사용법:
#   ./scripts/analyze.sh               # 기본 (TWF 고장 샘플)
#   ./scripts/analyze.sh normal        # 정상 샘플
#   ./scripts/analyze.sh hdf           # 열 방출 고장
#   ./scripts/analyze.sh pwf           # 전력 고장
#   ./scripts/analyze.sh osf           # 과부하 고장

set -euo pipefail

BASE_URL="${FORGE_URL:-http://localhost:8000}"
ENDPOINT="/api/v1/analyze"
PRESET="${1:-twf}"

case "$PRESET" in
  normal)
    PAYLOAD='{
      "equipment_id": "M-00001",
      "timestamp": "2026-06-03T08:00:00+00:00",
      "log_level": "INFO",
      "readings": [
        {"sensor_id": "air_temperature_k",    "unit": "K",   "value": 298.1},
        {"sensor_id": "process_temperature_k","unit": "K",   "value": 309.5},
        {"sensor_id": "rotational_speed_rpm", "unit": "rpm", "value": 1500.0},
        {"sensor_id": "torque_nm",            "unit": "Nm",  "value": 40.0},
        {"sensor_id": "tool_wear_min",        "unit": "min", "value": 80.0}
      ],
      "message": "Routine sensor check — no anomaly",
      "tags": {"machine_type": "L"}
    }'
    ;;
  twf)
    PAYLOAD='{
      "equipment_id": "M-12345",
      "timestamp": "2026-06-03T08:00:00+00:00",
      "log_level": "ERROR",
      "readings": [
        {"sensor_id": "air_temperature_k",    "unit": "K",   "value": 298.1},
        {"sensor_id": "process_temperature_k","unit": "K",   "value": 308.6},
        {"sensor_id": "rotational_speed_rpm", "unit": "rpm", "value": 1251.0},
        {"sensor_id": "torque_nm",            "unit": "Nm",  "value": 42.8},
        {"sensor_id": "tool_wear_min",        "unit": "min", "value": 216.0}
      ],
      "message": "Machine failure detected: TWF",
      "tags": {"machine_type": "M", "failure_types": "TWF"}
    }'
    ;;
  hdf)
    PAYLOAD='{
      "equipment_id": "M-22222",
      "timestamp": "2026-06-03T08:00:00+00:00",
      "log_level": "ERROR",
      "readings": [
        {"sensor_id": "air_temperature_k",    "unit": "K",   "value": 296.0},
        {"sensor_id": "process_temperature_k","unit": "K",   "value": 319.8},
        {"sensor_id": "rotational_speed_rpm", "unit": "rpm", "value": 1200.0},
        {"sensor_id": "torque_nm",            "unit": "Nm",  "value": 29.0},
        {"sensor_id": "tool_wear_min",        "unit": "min", "value": 105.0}
      ],
      "message": "Machine failure detected: HDF",
      "tags": {"machine_type": "H", "failure_types": "HDF"}
    }'
    ;;
  pwf)
    PAYLOAD='{
      "equipment_id": "M-33333",
      "timestamp": "2026-06-03T08:00:00+00:00",
      "log_level": "CRITICAL",
      "readings": [
        {"sensor_id": "air_temperature_k",    "unit": "K",   "value": 301.3},
        {"sensor_id": "process_temperature_k","unit": "K",   "value": 314.0},
        {"sensor_id": "rotational_speed_rpm", "unit": "rpm", "value": 1168.0},
        {"sensor_id": "torque_nm",            "unit": "Nm",  "value": 76.0},
        {"sensor_id": "tool_wear_min",        "unit": "min", "value": 130.0}
      ],
      "message": "Machine failure detected: PWF",
      "tags": {"machine_type": "L", "failure_types": "PWF"}
    }'
    ;;
  osf)
    PAYLOAD='{
      "equipment_id": "M-44444",
      "timestamp": "2026-06-03T08:00:00+00:00",
      "log_level": "ERROR",
      "readings": [
        {"sensor_id": "air_temperature_k",    "unit": "K",   "value": 299.7},
        {"sensor_id": "process_temperature_k","unit": "K",   "value": 311.5},
        {"sensor_id": "rotational_speed_rpm", "unit": "rpm", "value": 2860.0},
        {"sensor_id": "torque_nm",            "unit": "Nm",  "value": 73.5},
        {"sensor_id": "tool_wear_min",        "unit": "min", "value": 200.0}
      ],
      "message": "Machine failure detected: OSF",
      "tags": {"machine_type": "M", "failure_types": "OSF"}
    }'
    ;;
  *)
    echo "알 수 없는 프리셋: $PRESET"
    echo "사용 가능: normal | twf | hdf | pwf | osf"
    exit 1
    ;;
esac

echo "POST ${BASE_URL}${ENDPOINT}  [preset=${PRESET}]"
echo "---"

curl -s -X POST "${BASE_URL}${ENDPOINT}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  | python3 -m json.tool
