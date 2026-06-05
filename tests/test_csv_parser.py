from __future__ import annotations

import io

import pandas as pd
import pytest

from utils.csv_parser import parse_csv_logs


def _make_csv(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


def test_parse_csv_basic():
    csv_bytes = _make_csv([
        {
            "equipment_id": "M-001",
            "timestamp": "2026-06-03 08:00:00",
            "log_level": "ERROR",
            "message": "Test failure",
            "air_temperature_k": 298.5,
            "process_temperature_k": 308.2,
            "rotational_speed_rpm": 1500.0,
            "torque_nm": 42.0,
            "tool_wear_min": 210.0,
        }
    ])
    logs = parse_csv_logs(csv_bytes)
    assert len(logs) == 1
    assert logs[0].equipment_id == "M-001"
    assert logs[0].log_level == "ERROR"
    assert len(logs[0].readings) == 5


def test_parse_csv_ai4i_column_names():
    csv_bytes = _make_csv([
        {
            "Product ID": "L-12345",
            "Type": "L",
            "Air temperature [K]": 298.1,
            "Process temperature [K]": 308.6,
            "Rotational speed [rpm]": 1500.0,
            "Torque [Nm]": 40.0,
            "Tool wear [min]": 50.0,
            "Machine failure": 0,
            "TWF": 0,
            "HDF": 0,
            "PWF": 0,
            "OSF": 0,
            "RNF": 0,
        }
    ])
    logs = parse_csv_logs(csv_bytes)
    assert len(logs) == 1
    assert logs[0].log_level == "INFO"
    assert any(r.sensor_id == "air_temperature_k" for r in logs[0].readings)


def test_parse_csv_failure_flags():
    csv_bytes = _make_csv([
        {
            "Product ID": "H-99999",
            "Type": "H",
            "Air temperature [K]": 310.0,
            "Process temperature [K]": 315.0,
            "Rotational speed [rpm]": 1200.0,
            "Torque [Nm]": 68.0,
            "Tool wear [min]": 220.0,
            "Machine failure": 1,
            "TWF": 1,
            "HDF": 0,
            "PWF": 0,
            "OSF": 0,
            "RNF": 0,
        }
    ])
    logs = parse_csv_logs(csv_bytes)
    assert logs[0].log_level == "ERROR"
    assert "TWF" in logs[0].message
    assert logs[0].tags.get("failure_types") == "TWF"


def test_parse_csv_skips_bad_rows():
    csv_bytes = _make_csv([
        {"equipment_id": "M-001", "air_temperature_k": 298.0},
        {"equipment_id": "", "air_temperature_k": "not_a_number_that_breaks_things"},
        {"equipment_id": "M-003", "air_temperature_k": 300.0},
    ])
    logs = parse_csv_logs(csv_bytes)
    assert len(logs) >= 1
