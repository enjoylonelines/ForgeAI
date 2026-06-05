#!/usr/bin/env python3
"""
AI4I 2020 데이터셋 end-to-end 파이프라인 검증 스크립트.

서버 없이 ForgePipeline을 직접 호출하여 실제 샘플에 대한
전체 파이프라인 동작과 예방 로직 개선율을 확인한다.

사용법:
    python scripts/validate_ai4i.py              # 기본: 고장 6 + 정상 4 (mixed)
    python scripts/validate_ai4i.py --failure-only --n 10
    python scripts/validate_ai4i.py --verbose
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.forge_pipeline import ForgePipeline
from utils.data_loader import load_ai4i_anomaly_samples, load_ai4i_mixed_samples

_COL = "{:<4} {:<14} {:<12} {:<10} {:<10} {:<7} {:<8} {}"
_HDR = _COL.format("#", "Equipment ID", "Failure", "Risk", "Anomaly", "Score", "Result", "sec")
_SEP = "-" * 82


async def run_validation(n: int, failure_only: bool, verbose: bool) -> None:
    if failure_only:
        print(f"AI4I 2020 고장 샘플 {n}개 로드 중...")
        logs = load_ai4i_anomaly_samples(n=n)
    else:
        n_fail, n_norm = max(1, round(n * 0.6)), max(1, round(n * 0.4))
        print(f"AI4I 2020 혼합 샘플 로드 중 (고장 {n_fail}개 + 정상 {n_norm}개)...")
        logs = load_ai4i_mixed_samples(n_failure=n_fail, n_normal=n_norm)

    print(f"로드 완료: {len(logs)}개\n")

    pipeline = ForgePipeline()
    rows: list[dict] = []
    failed = 0

    print(_HDR)
    print(_SEP)

    for i, log in enumerate(logs, 1):
        cid = f"ai4i-e2e-{uuid.uuid4().hex[:8]}"
        failure_type = log.tags.get("failure_types", "NONE")
        t0 = time.monotonic()
        try:
            result = await pipeline.run(log, cid)
            elapsed = time.monotonic() - t0
            m = result.metrics
            vr = result.validation_result
            ar = result.anomaly_report

            row = {
                "index": i,
                "equipment_id": log.equipment_id,
                "failure_type": failure_type,
                "risk_level": m.risk_level,
                "early_exit": m.early_exit,
                "retry_count": m.retry_count,
                "has_anomaly": ar.has_anomaly if ar else None,
                "grounding_score": vr.overall_grounding_score if vr else None,
                "recommendation": vr.recommendation if vr else "—",
                "elapsed": elapsed,
                "stages": m.stages_completed,
            }
            rows.append(row)

            anomaly_str = ("YES" if ar and ar.has_anomaly else "NO") if ar else "—(exit)"
            score_str = f"{vr.overall_grounding_score:.3f}" if vr else "—"
            rec_str = vr.recommendation if vr else "—"
            risk_str = m.risk_level + (" ✓" if m.early_exit else "")

            print(_COL.format(
                i, log.equipment_id, failure_type,
                risk_str, anomaly_str, score_str, rec_str, f"{elapsed:.1f}s",
            ))
            if verbose:
                if ar:
                    print(f"     summary : {ar.summary[:80]}")
                if result.risk_assessment:
                    print(f"     risk    : {result.risk_assessment.summary[:80]}")
                print(f"     stages  : {' → '.join(m.stages_completed)}")

        except Exception as exc:
            elapsed = time.monotonic() - t0
            failed += 1
            print(_COL.format(i, log.equipment_id, failure_type, "ERROR", "—", "—", "—", f"{elapsed:.1f}s  ({exc})"))

    _print_summary(rows, failed)


def _print_summary(rows: list[dict], failed: int) -> None:
    if not rows:
        print("\n결과 없음.")
        return

    total = len(rows) + failed
    success = len(rows)
    early_exits = sum(1 for r in rows if r["early_exit"])
    warnings = sum(1 for r in rows if r["risk_level"] == "WARNING" and not r["early_exit"])
    criticals = sum(1 for r in rows if r["risk_level"] == "CRITICAL")
    detected = sum(1 for r in rows if r["has_anomaly"])
    scored = [r for r in rows if r["grounding_score"] is not None]
    avg_score = sum(r["grounding_score"] for r in scored) / len(scored) if scored else 0.0
    approved = sum(1 for r in rows if r["recommendation"] == "APPROVE")
    review = sum(1 for r in rows if r["recommendation"] == "REVIEW")
    reject = sum(1 for r in rows if r["recommendation"] == "REJECT")
    total_retries = sum(r["retry_count"] for r in rows)
    llm_calls_saved = early_exits * 4

    print("\n" + "=" * 82)
    print("요약")
    print("=" * 82)
    print(f"  전체 샘플        : {total}")
    print(f"  성공             : {success}  /  실패(예외): {failed}")
    print()
    print("  [예방 로직 개선율]")
    print(f"  SAFE 조기 종료   : {early_exits}/{success}  ({early_exits/success*100:.1f}%)  — 이하 단계 스킵")
    print(f"  WARNING 예방 감지: {warnings}/{success}  ({warnings/success*100:.1f}%)  — 이상 감지 전 선제 조치")
    print(f"  CRITICAL 감지    : {criticals}/{success}  ({criticals/success*100:.1f}%)")
    print(f"  절약된 LLM 호출  : {llm_calls_saved}콜  (조기종료 {early_exits}건 × 4단계)")
    print()
    print("  [이상 감지 / 검증]")
    if success - early_exits > 0:
        full_run = success - early_exits
        print(f"  풀 파이프라인 실행: {full_run}건")
        print(f"  이상 감지        : {detected}/{full_run}  ({detected/full_run*100:.0f}%)" if full_run else "")
    print(f"  평균 grounding   : {avg_score:.3f}")
    print(f"  APPROVE          : {approved}  /  REVIEW: {review}  /  REJECT: {reject}")
    print(f"  총 재시도 횟수   : {total_retries}")

    failure_types: dict[str, dict] = {}
    for r in rows:
        ft = r["failure_type"]
        failure_types.setdefault(ft, {"count": 0, "detected": 0, "score_sum": 0.0, "early": 0})
        failure_types[ft]["count"] += 1
        failure_types[ft]["detected"] += int(bool(r["has_anomaly"]))
        failure_types[ft]["score_sum"] += r["grounding_score"] or 0.0
        failure_types[ft]["early"] += int(r["early_exit"])

    if len(failure_types) > 1:
        print("\n  고장 유형별:")
        print(f"  {'Type':<12} {'건수':>4}  {'감지':>4}  {'early_exit':>10}  {'avg_score':>9}")
        for ft, v in sorted(failure_types.items()):
            avg = v["score_sum"] / v["count"] if v["count"] else 0.0
            print(f"  {ft:<12} {v['count']:>4}  {v['detected']:>4}  {v['early']:>10}  {avg:>9.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI4I end-to-end 파이프라인 검증")
    parser.add_argument("--n", type=int, default=10, help="총 샘플 수 (기본 10)")
    parser.add_argument("--failure-only", action="store_true", help="고장 샘플만 사용")
    parser.add_argument("--verbose", action="store_true", help="각 행 상세 출력")
    args = parser.parse_args()

    asyncio.run(run_validation(n=args.n, failure_only=args.failure_only, verbose=args.verbose))


if __name__ == "__main__":
    main()
