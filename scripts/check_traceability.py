"""JSONL 결정 이벤트 파일에서 correlation_id별 추적 가능률을 출력한다."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_REQUIRED_STAGES = {"rule_engine", "perception", "sop_search", "action_plan", "validator", "routing"}
_MIN_ROUTING = 3


def check(path: str) -> int:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] 파일 없음: {path}", file=sys.stderr)
        return 1

    by_cid: dict[str, list[dict]] = defaultdict(list)
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            by_cid[json.loads(line)["correlation_id"]].append(json.loads(line))
        except (json.JSONDecodeError, KeyError):
            continue

    if not by_cid:
        print("[WARN] 레코드 없음")
        return 0

    total = len(by_cid)
    complete = 0

    for cid, events in by_cid.items():
        stages = {e["stage"] for e in events}
        routing_count = sum(1 for e in events if e["stage"] == "routing")
        non_routing = stages - {"routing"}
        required_non_routing = _REQUIRED_STAGES - {"routing"}
        missing = required_non_routing - non_routing
        routing_ok = routing_count >= _MIN_ROUTING

        if not missing and routing_ok:
            complete += 1
        else:
            print(f"[INCOMPLETE] {cid}")
            if missing:
                print(f"  누락 stage: {missing}")
            if not routing_ok:
                print(f"  routing 레코드 부족: {routing_count} < {_MIN_ROUTING}")

    rate = complete / total * 100
    print(f"\n추적 가능률: {complete}/{total} ({rate:.1f}%)")
    return 0 if rate == 100.0 else 1


if __name__ == "__main__":
    log_path = sys.argv[1] if len(sys.argv) > 1 else "./logs/decisions.jsonl"
    sys.exit(check(log_path))
