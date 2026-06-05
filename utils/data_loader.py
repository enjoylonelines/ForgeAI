from __future__ import annotations

"""
AI4I 2020 Predictive Maintenance Dataset 로더.
data/ai4i2020.csv가 있으면 로컬 파일을 우선 사용하고,
없으면 ucimlrepo 패키지로 네트워크에서 다운로드한다.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from models.equipment_log import EquipmentLog, SensorReading

_AI4I_DATASET_ID = 601
_LOCAL_CSV = Path(__file__).parent.parent / "data" / "ai4i2020.csv"

_SENSOR_UNIT_MAP = {
    "Air temperature [K]": "K",
    "Process temperature [K]": "K",
    "Rotational speed [rpm]": "rpm",
    "Torque [Nm]": "Nm",
    "Tool wear [min]": "min",
}

_FAILURE_COLS = ["TWF", "HDF", "PWF", "OSF", "RNF"]


def _load_raw_df() -> pd.DataFrame:
    if _LOCAL_CSV.exists():
        return pd.read_csv(_LOCAL_CSV)
    from ucimlrepo import fetch_ucirepo
    dataset = fetch_ucirepo(id=_AI4I_DATASET_ID)
    X: pd.DataFrame = dataset.data.features.copy()
    y: pd.DataFrame = dataset.data.targets.copy()
    return pd.concat([X, y], axis=1)


def load_ai4i_logs(limit: int | None = None) -> list[EquipmentLog]:
    """
    AI4I 2020 데이터셋을 로드하여 EquipmentLog 리스트를 반환한다.

    Args:
        limit: 반환할 최대 로그 수. None이면 전체 반환.

    Returns:
        EquipmentLog 리스트 (타임스탬프는 시뮬레이션용으로 생성됨)
    """
    df = _load_raw_df()

    if limit is not None:
        df = df.head(limit)

    base_time = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    logs: list[EquipmentLog] = []

    for i, row in df.iterrows():
        timestamp = base_time + timedelta(minutes=int(str(i)) * 5)
        log = _row_to_equipment_log(row, timestamp)
        logs.append(log)

    return logs


def load_ai4i_anomaly_samples(n: int = 20) -> list[EquipmentLog]:
    """고장 샘플만 추출하여 반환한다 (machine_failure == 1)."""
    df = _load_raw_df()
    failure_df = df[df["Machine failure"] == 1].head(n)
    base_time = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)

    logs: list[EquipmentLog] = []
    for seq, (i, row) in enumerate(failure_df.iterrows()):
        timestamp = base_time + timedelta(minutes=seq * 5)
        logs.append(_row_to_equipment_log(row, timestamp))
    return logs


def load_ai4i_mixed_samples(n_failure: int = 6, n_normal: int = 4) -> list[EquipmentLog]:
    """고장 샘플과 정상 샘플을 혼합하여 반환한다.

    early_exit 개선율 측정 시 정상 샘플이 있어야 의미 있는 수치가 나온다.
    반환 순서는 실제 시뮬레이션처럼 고장/정상이 섞인 순서로 정렬된다.
    """
    df = _load_raw_df()
    failure_df = df[df["Machine failure"] == 1].head(n_failure)
    normal_df = df[df["Machine failure"] == 0].head(n_normal)
    combined = pd.concat([failure_df, normal_df]).sort_index().reset_index(drop=True)

    base_time = datetime(2026, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
    logs: list[EquipmentLog] = []
    for seq, (_, row) in enumerate(combined.iterrows()):
        timestamp = base_time + timedelta(minutes=seq * 5)
        logs.append(_row_to_equipment_log(row, timestamp))
    return logs


def _row_to_equipment_log(row: pd.Series, timestamp: datetime) -> EquipmentLog:
    product_id = str(row.get("Product ID", f"EQ-{row.name}"))
    machine_type = str(row.get("Type", "M"))

    active_failures = [f for f in _FAILURE_COLS if row.get(f, 0)]
    machine_failure = int(row.get("Machine failure", 0))

    if active_failures:
        log_level = "ERROR"
        message = f"Machine failure detected: {', '.join(active_failures)}"
    elif machine_failure:
        log_level = "WARN"
        message = "Machine failure flag set (unclassified)"
    else:
        log_level = "INFO"
        message = "Normal operation"

    readings = [
        SensorReading(sensor_id="air_temperature_k", unit="K",
                      value=float(row.get("Air temperature [K]", 0))),
        SensorReading(sensor_id="process_temperature_k", unit="K",
                      value=float(row.get("Process temperature [K]", 0))),
        SensorReading(sensor_id="rotational_speed_rpm", unit="rpm",
                      value=float(row.get("Rotational speed [rpm]", 0))),
        SensorReading(sensor_id="torque_nm", unit="Nm",
                      value=float(row.get("Torque [Nm]", 0))),
        SensorReading(sensor_id="tool_wear_min", unit="min",
                      value=float(row.get("Tool wear [min]", 0))),
    ]

    tags: dict[str, str] = {
        "machine_type": machine_type,
        "machine_failure": str(machine_failure),
    }
    if active_failures:
        tags["failure_types"] = ",".join(active_failures)

    return EquipmentLog(
        equipment_id=product_id,
        timestamp=timestamp,
        log_level=log_level,
        readings=readings,
        message=message,
        tags=tags,
    )


if __name__ == "__main__":
    print("Loading AI4I 2020 dataset sample (10 anomaly cases)...")
    samples = load_ai4i_anomaly_samples(n=10)
    for log in samples:
        print(f"  {log.equipment_id} | {log.log_level} | {log.message[:60]}")
    print(f"Total: {len(samples)} logs loaded")
