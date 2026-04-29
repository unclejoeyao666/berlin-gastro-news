#!/usr/bin/env python3
"""Cron / LaunchAgent entry point.

The OpenClaw LaunchAgent has a hard timeout that may kill any single
``daily_pipeline`` invocation mid-flight. This wake script is designed
to be **safely re-runnable as often as you like**: every invocation
inspects ``.state.json`` for the most recent few days and only
re-executes whatever still hasn't reached ``ok``.

Recommended cron schedule:

    Every hour from 06:00 to 12:00 (Europe/Berlin):
        scripts/daily_wake.py --budget-seconds 1500

    Daily at 06:00 — kicks off today's pipeline
    Daily at 07:00–12:00 — picks up any unfinished step left by a
                           timed-out earlier run

Behaviour:
  * Walks dates oldest → newest within ``--lookback-days``.
  * Per date, calls ``daily_pipeline.py --resume --budget-seconds X``.
  * Per date, deducts elapsed budget so total wall-clock stays under
    ``--budget-seconds``.
  * Pauses gracefully when budget exhausted — next wake-up resumes.
  * Appends a single line to ``daily-wake.log`` for traceability.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import state as st
from scripts.lib.aging import RetentionConfig, prune
from scripts.lib.news_db import NewsDB

DAILY_ROOT = ROOT / "daily"
LOG_PATH = ROOT / "daily-wake.log"
DB_PATH = ROOT / "data" / "news.db"
AGING_MIN_BUDGET_SECONDS = 30


def parse_today() -> str:
    return datetime.now(timezone(timedelta(hours=2))).strftime("%Y-%m-%d")


def state_path_for(date_str: str) -> Path:
    year, month, _ = date_str.split("-")
    return DAILY_ROOT / year / f"{year}-{month}" / date_str / ".state.json"


def is_complete(state: dict) -> bool:
    """All steps OK, including the agent-driven translate step."""
    for s in st.STEPS:
        if not st.is_done(state, s):
            return False
    return True


def candidates(today: str, lookback: int) -> List[str]:
    """Recent dates worth checking (oldest first)."""
    base = datetime.fromisoformat(today)
    out: List[str] = []
    for i in range(lookback, -1, -1):
        d = base - timedelta(days=i)
        out.append(d.strftime("%Y-%m-%d"))
    return out


def append_log(entry: dict) -> None:
    line = json.dumps({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **entry,
    }, ensure_ascii=False)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_pipeline(date_str: str, budget_seconds: int) -> Tuple[int, str]:
    cmd = [
        "python3", "scripts/daily_pipeline.py",
        "--date", date_str,
        "--resume",
        "--budget-seconds", str(budget_seconds),
    ]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def run_aging(remaining_seconds: int) -> dict:
    """Apply DB retention + intermediate file cleanup. Idempotent."""
    if remaining_seconds < AGING_MIN_BUDGET_SECONDS:
        return {"skipped": "budget", "remaining": remaining_seconds}
    if not DB_PATH.exists():
        return {"skipped": "no-db"}
    cfg = RetentionConfig()
    try:
        with NewsDB(str(DB_PATH), use_bloom=False) as db:
            return prune(db, cfg, daily_root=DAILY_ROOT)
    except Exception as e:
        return {"error": str(e)[:200]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--lookback-days", type=int, default=2,
                   help="How many past days (in addition to today) "
                        "to inspect for incomplete pipelines.")
    p.add_argument("--budget-seconds", type=int, default=1500,
                   help="Total wall-clock budget for this wake.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would run, don't actually run.")
    args = p.parse_args()

    today = parse_today()
    deadline = time.monotonic() + args.budget_seconds

    todo: List[str] = []
    for d in candidates(today, args.lookback_days):
        path = state_path_for(d)
        if path.exists():
            state = st.load(path, d)
            if is_complete(state):
                continue
            todo.append(d)
        elif d == today:
            # Today has no state yet → start fresh
            todo.append(d)

    if not todo:
        append_log({"event": "wake", "todo": [], "note": "all caught up"})
        print(f"✅ wake: nothing to do (all dates complete)")
    else:
        print(f"⏰ wake: dates to advance = {todo}")
        append_log({"event": "wake", "todo": todo,
                    "budget_seconds": args.budget_seconds})

        if args.dry_run:
            print("(dry-run — exiting)")
            return

        for d in todo:
            remaining = max(0, int(deadline - time.monotonic()))
            if remaining < 60:
                append_log({"event": "budget-exhausted",
                            "remaining": remaining, "next": d})
                print(f"⏸  budget exhausted ({remaining}s) before {d}")
                return
            print(f"\n=== {d} (budget {remaining}s) ===")
            rc, output = run_pipeline(d, remaining)
            # Always print pipeline output so cron logs are useful
            sys.stdout.write(output)
            sys.stdout.flush()
            # Reload state to log progress
            state = st.load(state_path_for(d), d)
            finished = sum(1 for s in st.STEPS if st.is_done(state, s))
            append_log({"event": "step-batch", "date": d,
                        "rc": rc,
                        "steps_done": finished,
                        "total_steps": len(st.STEPS)})
            if rc != 0 and not is_complete(state):
                # Don't bail — try the next date; cron will retry this one
                # next wake-up.
                print(f"⚠️  {d} pipeline returned rc={rc}; "
                      f"will retry on next wake")

    if args.dry_run:
        return

    # Tail: run aging once (idempotent) before we exit. Independent of
    # whether any date moved; aging is a global concern.
    remaining = max(0, int(deadline - time.monotonic()))
    age_result = run_aging(remaining)
    if "skipped" in age_result:
        print(f"🕰  age: skipped ({age_result['skipped']})")
    elif "error" in age_result:
        print(f"🕰  age: error — {age_result['error']}")
    else:
        print(f"🕰  age: pruned "
              f"played={age_result['played']} "
              f"unplayed={age_result['unplayed']} "
              f"archived={age_result['archived']} "
              f"url_seen={age_result['url_seen']} "
              f"files={age_result['files_removed']} "
              f"vacuumed={age_result['vacuumed']}")
    append_log({"event": "age", **age_result})
    append_log({"event": "wake-complete", "todo": todo})


if __name__ == "__main__":
    main()
