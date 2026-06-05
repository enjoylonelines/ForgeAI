from __future__ import annotations

import io
from datetime import datetime, timezone

import pandas as pd

from models.equipment_log import EquipmentLog, SensorReading

_META_COLUMNS = {"equipment_id", "timestamp", "log_level", "message", "type", "machine_failure",
                 "twf", "hdf", "pwf", "osf", "rnf"}

_LOG_LEVEL_MAP = {
    0: "INFO",
    1: "ERROR",
    "0": "INFO",
    "1": "ERROR",
    "INFO": "INFO",
    "WARN": "WARN",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}

_SENSOR_UNIT_MAP = {
    "air_temperature_k": "K",
    "process_temperature_k": "K",
    "rotational_speed_rpm": "rpm",
    "torque_nm": "Nm",
    "tool_wear_min": "min",
    "air temperature [k]": "K",
    "process temperature [k]": "K",
    "rotational speed [rpm]": "rpm",
    "torque [nm]": "Nm",
    "tool wear [min]": "min",
}


def parse_csv_logs(file_bytes: bytes, filename: str = "") -> list[EquipmentLog]:
    if filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls"):
        df = pd.read_excel(io.BytesIO(file_bytes))
    else:
        df = pd.read_csv(io.BytesIO(file_bytes))

    df.columns = [c.strip().lower() for c in df.columns]
    _normalize_ai4i_columns(df)

    logs: list[EquipmentLog] = []
    for _, row in df.iterrows():
        try:
            logs.append(_row_to_log(row, df.columns.tolist()))
        except Exception:
            continue
    return logs


def _normalize_ai4i_columns(df: pd.DataFrame) -> None:
    rename = {}
    for col in df.columns:
        col_lower = col.lower()
        if "air temp" in col_lower:
            rename[col] = "air_temperature_k"
        elif "process temp" in col_lower:
            rename[col] = "process_temperature_k"
        elif "rotational" in col_lower or "rotation" in col_lower:
            rename[col] = "rotational_speed_rpm"
        elif "torque" in col_lower:
            rename[col] = "torque_nm"
        elif "tool wear" in col_lower:
            rename[col] = "tool_wear_min"
        elif col_lower in ("udi", "product id"):
            rename[col] = "equipment_id"
        elif col_lower == "type":
            rename[col] = "machine_type"
        elif col_lower == "machine failure":
            rename[col] = "machine_failure"
    df.rename(columns=rename, inplace=True)


def _row_to_log(row: pd.Series, columns: list[str]) -> EquipmentLog:
    equipment_id = str(row.get("equipment_id", row.get("product id", f"EQ-{row.name}")))

    ts_raw = row.get("timestamp")
    if pd.isna(ts_raw) if isinstance(ts_raw, float) else ts_raw is None:
        timestamp = datetime.now(timezone.utc)
    else:
        try:
            timestamp = pd.to_datetime(ts_raw).to_pydatetime()
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        except Exception:
            timestamp = datetime.now(timezone.utc)

    machine_failure = row.get("machine_failure", 0)
    failure_flags = []
    for flag in ["twf", "hdf", "pwf", "osf", "rnf"]:
        if flag in row and row[flag]:
            failure_flags.append(flag.upper())

    if failure_flags:
        log_level = "ERROR"
        message = f"Machine failure detected: {', '.join(failure_flags)}"
    elif machine_failure and str(machine_failure) not in ("0", "False", "false"):
        log_level = "WARN"
        message = "Machine failure flag set"
    else:
        log_level_raw = row.get("log_level", "INFO")
        log_level = _LOG_LEVEL_MAP.get(log_level_raw, "INFO")
        message = str(row.get("message", ""))

    sensor_cols = [c for c in columns if c not in _META_COLUMNS and c not in
                   {"machine_type", "equipment_id", "timestamp", "log_level", "message"}]

    readings: list[SensorReading] = []
    for col in sensor_cols:
        val = row.get(col)
        if val is not None and not (isinstance(val, float) and pd.isna(val)):
            try:
                unit = _SENSOR_UNIT_MAP.get(col, "unit")
                readings.append(SensorReading(
                    sensor_id=col,
                    unit=unit,
                    value=float(val),
                ))
            except (ValueError, TypeError):
                continue

    tags: dict[str, str] = {}
    if "machine_type" in row and row["machine_type"]:
        tags["machine_type"] = str(row["machine_type"])
    if failure_flags:
        tags["failure_types"] = ",".join(failure_flags)

    return EquipmentLog(
        equipment_id=equipment_id,
        timestamp=timestamp,
        log_level=log_level,
        readings=readings,
        message=message,
        tags=tags,
    )
