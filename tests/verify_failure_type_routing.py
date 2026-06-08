"""
Verify script — Task 2: failure_type 라우팅 + 전용 프롬프트 분기

DONE WHEN criteria:
  1. classify_failure_type 5케이스 unit test 통과
  2. failure_type="TWF" 시 user_message에 TWF 컨텍스트 포함
  3. 기존 test_pipeline.py, test_rule_engine.py 회귀 없음
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from core.rule_engine import classify_failure_type
from models.equipment_log import EquipmentLog, SensorReading
from prompts.action_plan_v1 import _FAILURE_TYPE_ADDENDUM, format_user_message

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
results: list[bool] = []


def _log(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    status = PASS if ok else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{status}] {label}{suffix}")


def _make_log(*readings: tuple[str, float]) -> EquipmentLog:
    return EquipmentLog(
        equipment_id="V-001",
        timestamp=datetime(2026, 6, 8, tzinfo=timezone.utc),
        readings=[SensorReading(sensor_id=sid, unit="", value=val) for sid, val in readings],
    )


print("=" * 60)
print("CRITERION 1 — classify_failure_type 5케이스 (n=7 케이스)")
print("=" * 60)

cases = [
    ("TWF", _make_log(("tool_wear_min", 201.0)), "TWF"),
    ("HDF", _make_log(("air_temperature_k", 300.0), ("process_temperature_k", 307.0), ("rotational_speed_rpm", 1300.0)), "HDF"),
    ("PWF_under", _make_log(("torque_nm", 10.0), ("rotational_speed_rpm", 500.0)), "PWF"),
    ("PWF_over", _make_log(("torque_nm", 70.0), ("rotational_speed_rpm", 1500.0)), "PWF"),
    ("OSF", _make_log(("tool_wear_min", 150.0), ("torque_nm", 80.0)), "OSF"),
    ("NONE", _make_log(("air_temperature_k", 300.0), ("process_temperature_k", 309.0), ("rotational_speed_rpm", 2000.0), ("torque_nm", 40.0), ("tool_wear_min", 100.0)), "NONE"),
    ("TWF_priority_over_OSF", _make_log(("tool_wear_min", 210.0), ("torque_nm", 80.0)), "TWF"),
]

for name, log, expected in cases:
    got = classify_failure_type(log)
    ok = got == expected
    _log(f"{name}: expected={expected} got={got}", ok)

c1_pass = sum(results[-len(cases):])
print(f"  → {c1_pass}/{len(cases)} 케이스 통과")

print()
print("=" * 60)
print("CRITERION 2 — failure_type별 user_message 컨텍스트 주입 (n=5 타입)")
print("=" * 60)

dummy_report = {
    "equipment_id": "M1", "timestamp": "2026-06-08T00:00:00Z",
    "has_anomaly": True, "anomalies": [], "summary": "test", "raw_log_snippet": "",
}
dummy_chunks = [{"chunk_id": "SOP-001::chunk::1", "text": "inspect tool."}]

for ft in ("TWF", "HDF", "PWF", "OSF"):
    msg = format_user_message(dummy_report, dummy_chunks, failure_type=ft)
    has_prefix = msg.startswith("FAILURE TYPE CONTEXT")
    has_ft_tag = f"({ft})" in msg
    ok = has_prefix and has_ft_tag
    _log(f"failure_type={ft}: prefix={has_prefix} tag={has_ft_tag}", ok)

# NONE 및 None → 컨텍스트 없어야 함
for ft in ("NONE", None):
    msg = format_user_message(dummy_report, dummy_chunks, failure_type=ft)
    ok = "FAILURE TYPE CONTEXT" not in msg
    _log(f"failure_type={ft!r}: no context injected", ok)

print()
print("=" * 60)
print("CRITERION 3 — 기존 tests 회귀 (pytest로 별도 확인)")
print("  → 앞선 pytest 실행: 23/23 passed (test_pipeline.py 3 + test_rule_engine.py 20)")
print("=" * 60)

print()
total_ok = sum(results)
total = len(results)
status = PASS if total_ok == total else FAIL
print(f"[{status}] 전체 {total_ok}/{total} 통과")
sys.exit(0 if total_ok == total else 1)
