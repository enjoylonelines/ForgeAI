#!/usr/bin/env python3
"""AI4I CSV replay simulator — measures agent early-warning performance.

Usage:
    python stream_simulator.py <csv_path> [--url http://localhost:8000] [--delay 0.0] [--lookahead 10]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time
from dataclasses import dataclass

import httpx
import pandas as pd

sys.path.insert(0, ".")
from utils.csv_parser import _normalize_ai4i_columns, _row_to_log


@dataclass
class RowResult:
    row_index: int
    equipment_id: str
    machine_failure: int
    risk_level: str
    early_exit: bool
    processing_time_sec: float
    error: str | None = None


def _load_csv(path: str) -> tuple[list, list[int]]:
    """Returns (EquipmentLog list, machine_failure flags). Preserves index alignment."""
    with open(path, "rb") as f:
        raw = f.read()

    df = pd.read_csv(io.BytesIO(raw))
    df.columns = [c.strip().lower() for c in df.columns]
    _normalize_ai4i_columns(df)
    df = df.loc[:, ~df.columns.duplicated()]  # UDI·Product ID 둘 다 equipment_id로 rename되어 중복 발생

    failure_flags: list[int] = []
    for _, row in df.iterrows():
        mf = row.get("machine_failure", 0)
        failure_flags.append(0 if (mf is None or (isinstance(mf, float) and pd.isna(mf))) else int(mf))

    cols = df.columns.tolist()
    logs = []
    for _, row in df.iterrows():
        try:
            logs.append(_row_to_log(row, cols))
        except Exception:
            logs.append(None)

    return logs, failure_flags


async def _call_analyze(client: httpx.AsyncClient, base_url: str, log) -> dict:
    payload = log.model_dump(mode="json")
    resp = await client.post(f"{base_url}/api/v1/analyze", json=payload, timeout=600.0)
    resp.raise_for_status()
    return resp.json()


def _compute_metrics(
    results: list[RowResult],
    failure_flags: list[int],
    lookahead: int,
) -> tuple[list[int], int]:
    """Returns (lead_times per failure event, false_alarm_count)."""
    lead_times: list[int] = []

    for i, mf in enumerate(failure_flags):
        if mf != 1:
            continue
        for j in range(i - 1, max(-1, i - 500), -1):
            if j < len(results) and results[j].risk_level in ("WARNING", "CRITICAL"):
                lead_times.append(i - j)
                break

    false_alarm_count = 0
    for i, res in enumerate(results):
        if res.risk_level not in ("WARNING", "CRITICAL"):
            continue
        window = failure_flags[i + 1 : i + 1 + lookahead]
        if not any(f == 1 for f in window):
            false_alarm_count += 1

    return lead_times, false_alarm_count


async def run(csv_path: str, base_url: str, delay: float, lookahead: int, limit: int | None = None) -> None:
    logs, failure_flags = _load_csv(csv_path)
    if limit:
        logs = logs[:limit]
        failure_flags = failure_flags[:limit]

    print(f"\n{'='*72}")
    print(f"  Stream Simulator (replay)  —  {csv_path}")
    print(f"  Rows: {len(logs)}  |  URL: {base_url}  |  Lookahead: {lookahead} rows")
    print(f"{'='*72}\n")

    results: list[RowResult] = []
    prev_risk = "SAFE"

    async with httpx.AsyncClient() as client:
        for i, (log, mf) in enumerate(zip(logs, failure_flags)):
            if log is None:
                print(f"[row {i:5d}] PARSE ERROR — skipped")
                results.append(RowResult(i, "?", mf, "SAFE", False, 0.0, "parse_error"))
                continue

            t0 = time.perf_counter()
            try:
                data = await _call_analyze(client, base_url, log)
                elapsed = time.perf_counter() - t0

                metrics = data.get("metrics", {})
                risk = metrics.get("risk_level", "SAFE")
                early_exit = metrics.get("early_exit", False)
                res = RowResult(i, log.equipment_id, mf, risk, early_exit, round(elapsed, 2))

            except Exception as exc:
                elapsed = time.perf_counter() - t0
                err_msg = str(exc) or type(exc).__name__
                res = RowResult(i, log.equipment_id, mf, "SAFE", False, round(elapsed, 2), err_msg[:80])

            results.append(res)

            failure_tag = "🔴 FAIL" if mf else "      "
            path_tag = "early_exit   " if res.early_exit else "full_pipeline"
            error_tag = f"  ERR: {res.error}" if res.error else ""
            print(
                f"[row {i:5d}] {log.equipment_id:<12} | "
                f"risk={res.risk_level:<8} | "
                f"{failure_tag} | {path_tag} | {res.processing_time_sec:.2f}s"
                f"{error_tag}"
            )

            if res.risk_level != prev_risk:
                print(f"           ↳ ⚡ TRANSITION  {prev_risk} → {res.risk_level}  @ row {i}")
                prev_risk = res.risk_level

            if delay > 0:
                await asyncio.sleep(delay)

    # ── Summary ──────────────────────────────────────────────────────────────
    lead_times, false_alarm_count = _compute_metrics(results, failure_flags, lookahead)

    total = len(results)
    ok_results = [r for r in results if r.error is None]
    warning_count = sum(1 for r in ok_results if r.risk_level == "WARNING")
    critical_count = sum(1 for r in ok_results if r.risk_level == "CRITICAL")
    early_exit_count = sum(1 for r in ok_results if r.early_exit)
    failure_total = sum(failure_flags)
    avg_time = sum(r.processing_time_sec for r in ok_results) / len(ok_results) if ok_results else 0.0
    safe_avg = sum(r.processing_time_sec for r in ok_results if r.early_exit) / early_exit_count if early_exit_count else 0.0
    full_results = [r for r in ok_results if not r.early_exit]
    full_avg = sum(r.processing_time_sec for r in full_results) / len(full_results) if full_results else 0.0

    print(f"\n{'='*72}")
    print("  SIMULATION SUMMARY")
    print(f"{'='*72}")
    print(f"  Total rows processed   : {total}")
    print(f"  Actual failures        : {failure_total}")
    print(f"  WARNING detections     : {warning_count}")
    print(f"  CRITICAL detections    : {critical_count}")
    print(f"  Early exit (SAFE)      : {early_exit_count}  ({early_exit_count / total * 100:.1f}%)")
    print(f"  Avg processing time    : {avg_time:.2f}s  "
          f"(SAFE early_exit={safe_avg:.2f}s / full_pipeline={full_avg:.2f}s)")
    print()
    print(f"  early_warning_count    : {len(lead_times)}")
    print(f"  false_alarm_count      : {false_alarm_count}  (lookahead={lookahead} rows)")
    if lead_times:
        print(f"  lead_time (rows)       : "
              f"min={min(lead_times)}  max={max(lead_times)}  avg={sum(lead_times) / len(lead_times):.1f}")
    else:
        print("  lead_time              : N/A — no failure was preceded by a WARNING/CRITICAL")
    print(f"{'='*72}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replay AI4I CSV row-by-row against /analyze and measure early-warning performance."
    )
    parser.add_argument("csv_path", help="Path to AI4I-format CSV file")
    parser.add_argument("--url", default="http://localhost:8000", help="API base URL without path prefix (default: http://localhost:8000)")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to wait between rows (default: 0)")
    parser.add_argument("--lookahead", type=int, default=10, help="False-alarm window: rows ahead to check for failure (default: 10)")
    parser.add_argument("--limit", type=int, default=None, help="Process only first N rows (default: all)")
    args = parser.parse_args()

    asyncio.run(run(args.csv_path, args.url, args.delay, args.lookahead, args.limit))


if __name__ == "__main__":
    main()
