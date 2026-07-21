"""ADR-014 기준 근거 추적 % 측정 스크립트.

판정 기준 (4가지 요건 모두 충족 시 '추적 가능'):
  1. rule_engine stage signals.failure_type ≠ "NONE"
  2. sop_search stage signals.chunk_count ≥ 1
  3. validator stage 존재 (grounding_score > 0 또는 ungrounded_steps 비어있음)
  4. decisions.jsonl에 rule_engine / sop_search / action_plan / validator 4개 스테이지 모두 기록

SAFE early-exit 처리 (ADR-014 §분모 정의):
  rule_engine decision == "SAFE" 이고 sop_search 스테이지가 없는 케이스는 분모에서 제외한다.

사용법:
  uv run python scripts/measure_traceability.py [decisions.jsonl 경로]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_REQUIRED_STAGES = {"rule_engine", "sop_search", "action_plan", "validator"}


def _is_safe_early_exit(events: list[dict]) -> bool:
    stages = {e["stage"] for e in events}
    rule_events = [e for e in events if e["stage"] == "rule_engine"]
    if not rule_events:
        return False
    rule_decision = rule_events[-1].get("decision", "")
    return rule_decision == "SAFE" and "sop_search" not in stages


def _is_traceable(events: list[dict]) -> tuple[bool, list[str]]:
    """ADR-014 4개 요건 검사. 실패 사유 리스트도 반환한다."""
    stages = {e["stage"] for e in events}
    reasons: list[str] = []

    # 요건 4: 4개 스테이지 모두 존재
    missing = _REQUIRED_STAGES - stages
    if missing:
        reasons.append(f"누락 stage: {missing}")

    # 요건 1: failure_type ≠ NONE
    rule_events = [e for e in events if e["stage"] == "rule_engine"]
    if rule_events:
        failure_type = rule_events[-1].get("signals", {}).get("failure_type", "NONE")
        if failure_type in ("NONE", None):
            reasons.append(f"failure_type=NONE (rule_engine 판정 근거 없음)")
    else:
        reasons.append("rule_engine 이벤트 없음")

    # 요건 2: chunk_count ≥ 1
    sop_events = [e for e in events if e["stage"] == "sop_search"]
    if sop_events:
        chunk_count = sop_events[-1].get("signals", {}).get("chunk_count", 0)
        if chunk_count < 1:
            reasons.append(f"sop chunk_count={chunk_count} (SOP 청크 미검색)")
    elif "sop_search" in stages:
        pass  # 위에서 already handled
    # sop_search 자체가 없으면 요건 4에서 이미 잡힘

    # 요건 3: validator 존재 + grounding 확인
    val_events = [e for e in events if e["stage"] == "validator"]
    if val_events:
        signals = val_events[-1].get("signals", {})
        grounding_score = signals.get("grounding_score", 0.0)
        ungrounded = signals.get("ungrounded_steps", [])
        if grounding_score == 0.0 and ungrounded:
            reasons.append(f"grounding_score=0, ungrounded_steps={ungrounded}")

    return (len(reasons) == 0), reasons


def measure(path: str) -> int:
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
            event = json.loads(line)
            by_cid[event["correlation_id"]].append(event)
        except (json.JSONDecodeError, KeyError):
            continue

    if not by_cid:
        print("[WARN] 레코드 없음")
        return 0

    total_all = len(by_cid)
    safe_excluded = 0
    traceable = 0
    non_traceable_ids: list[tuple[str, list[str]]] = []

    for cid, events in by_cid.items():
        if _is_safe_early_exit(events):
            safe_excluded += 1
            continue
        ok, reasons = _is_traceable(events)
        if ok:
            traceable += 1
        else:
            non_traceable_ids.append((cid, reasons))

    denominator = total_all - safe_excluded
    if denominator == 0:
        print("분모=0 (모든 판정이 SAFE early-exit)")
        return 0

    rate = traceable / denominator * 100

    print(f"전체 correlation_id : {total_all}")
    print(f"SAFE early-exit 제외: {safe_excluded}")
    print(f"측정 대상           : {denominator}")
    print(f"추적 가능 판정      : {traceable}")
    print(f"\n근거 추적 %         : {traceable}/{denominator} = {rate:.1f}%")

    if non_traceable_ids:
        print(f"\n[INCOMPLETE] {len(non_traceable_ids)}건:")
        for cid, reasons in non_traceable_ids[:20]:
            print(f"  {cid}")
            for r in reasons:
                print(f"    - {r}")
        if len(non_traceable_ids) > 20:
            print(f"  ... 외 {len(non_traceable_ids) - 20}건")

    return 0 if rate >= 80.0 else 1


if __name__ == "__main__":
    log_path = sys.argv[1] if len(sys.argv) > 1 else "./logs/decisions.jsonl"
    sys.exit(measure(log_path))
