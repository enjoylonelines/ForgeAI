#!/usr/bin/env python3
"""Reapply the current deterministic scorer to an existing experiment run."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from run_experiment import RunResult, score_response, summarize


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    results: list[RunResult] = []
    for path in sorted(args.run_dir.glob("*-[0-9].json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        condition = payload["condition"]
        repetition = payload["repetition"]
        response = payload["response"]
        score = score_response(condition, response)
        payload["score"] = score
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        results.append(RunResult(condition, repetition, response, score))

    summary_path = args.run_dir / "summary.json"
    report = json.loads(summary_path.read_text(encoding="utf-8"))
    report["rescored_at"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = summarize(results)
    summary_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
