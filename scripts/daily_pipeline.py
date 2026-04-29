#!/usr/bin/env python3
"""End-to-end orchestrator for the Berlin Gastro News daily pipeline.

Executes the deterministic steps in order, persists progress to
``daily/<date>/.state.json``, and pauses at the cognitive translation
step until the agent has filled in ``daily-selected.json`` (each entry
must carry ``_translated: true`` or ``_skipped: true``).

Common usage:

    python3 scripts/daily_pipeline.py --date today           # auto pace
    python3 scripts/daily_pipeline.py --date today --status  # inspect
    python3 scripts/daily_pipeline.py --date today --step harvest
    python3 scripts/daily_pipeline.py --date today --resume  # rerun pending
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import state as st
from scripts.lib.news_db import NewsDB

DB_PATH = ROOT / "data" / "news.db"
SELECTED_JSON = ROOT / "daily-selected.json"
DAILY_ROOT = ROOT / "daily"
SITE_BASE_URL = "https://unclejoeyao666.github.io/berlin-gastro-news"

GASTRO_QUOTA = 5
KEYWORD_QUOTA = 3
GENERAL_QUOTA = 2
MIN_AUDIO_BYTES = 100_000  # 100 KB ~ 30 s


# ── Helpers ──────────────────────────────────────────────────────


def parse_date(s) -> str:
    if not s or s == "today":
        return datetime.now(timezone(timedelta(hours=2))).strftime("%Y-%m-%d")
    return s


def day_dir_for(date_str: str) -> Path:
    year, month, _ = date_str.split("-")
    return DAILY_ROOT / year / f"{year}-{month}" / date_str


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                          check=check)


# ── Step implementations ────────────────────────────────────────


def step_harvest(date_str: str, state: Dict) -> Dict:
    print("→ harvest")
    r = run(["python3", "scripts/harvest.py"])
    print(r.stdout.rstrip())
    if r.stderr.strip():
        print(r.stderr.rstrip(), file=sys.stderr)
    with NewsDB(str(DB_PATH)) as db:
        s = db.stats()
    return st.mark(state, "harvest", "ok",
                   stats={"unplayed": s["unplayed"],
                          "total": s["total_articles"]})


def step_select(date_str: str, state: Dict) -> Dict:
    print("→ select")
    r = run([
        "python3", "scripts/select_top.py",
        "--count", "10",
        "--gastro", str(GASTRO_QUOTA),
        "--keyword", str(KEYWORD_QUOTA),
        "--general", str(GENERAL_QUOTA),
    ])
    print(r.stdout.rstrip())
    if r.stderr.strip():
        print(r.stderr.rstrip(), file=sys.stderr)
    if not SELECTED_JSON.exists():
        return st.mark(state, "select", "failed",
                       error="daily-selected.json not produced")
    sel = json.loads(SELECTED_JSON.read_text(encoding="utf-8"))
    diag = sel.get("diagnostics", {})
    return st.mark(state, "select", "ok",
                   selected_ids=[a["id"] for a in sel["articles"]],
                   diagnostics=diag)


def step_translate(date_str: str, state: Dict) -> Dict:
    """Cognitive step. Pipeline checks completion only.

    Each entry in ``daily-selected.json`` must carry ``_translated:
    true`` (translation written via ``translate_helper.py write``) or
    ``_skipped: true`` (article quarantined as off-topic).
    """
    print("→ translate (cognitive — agent must drive)")
    if not SELECTED_JSON.exists():
        return st.mark(state, "translate", "failed",
                       error="daily-selected.json missing")
    sel = json.loads(SELECTED_JSON.read_text(encoding="utf-8"))
    pending = [
        a for a in sel["articles"]
        if not (a.get("_translated") or a.get("_skipped"))
    ]
    if pending:
        ids = [a["id"] for a in pending]
        msg = (
            f"{len(pending)} article(s) still need translation: "
            f"{ids[:5]}{'...' if len(ids) > 5 else ''}\n"
            "  → run scripts/translate_helper.py write/skip per id, "
            "then re-run this pipeline."
        )
        print("  ⏸  " + msg.replace("\n  ", "\n     "))
        return st.mark(state, "translate", "pending",
                       pending_ids=ids)
    translated = [a for a in sel["articles"] if a.get("_translated")]
    audio_script_md = day_dir_for(date_str) / "audio_script.md"
    if not audio_script_md.exists():
        return st.mark(state, "translate", "failed",
                       error=("translation marked complete but no "
                              "audio_script.md — run "
                              "translate_helper.py finalize"))
    return st.mark(state, "translate", "ok",
                   translated_ids=[a["id"] for a in translated],
                   skipped_count=len(sel["articles"]) - len(translated))


def step_publish_article(date_str: str, state: Dict) -> Dict:
    print("→ publish_article")
    r = run(["python3", "scripts/publish_article.py", "--all-pending"])
    print(r.stdout.rstrip())
    if r.stderr.strip():
        print(r.stderr.rstrip(), file=sys.stderr)
    return st.mark(state, "publish_article", "ok")


def step_publish_brief(date_str: str, state: Dict) -> Dict:
    print("→ publish_brief")
    r = run([
        "python3", "scripts/publish_briefing.py",
        "--date", date_str,
        "--site-url", SITE_BASE_URL,
        # --log-broadcast intentionally omitted: orchestrator handles it
    ])
    print(r.stdout.rstrip())
    if r.stderr.strip():
        print(r.stderr.rstrip(), file=sys.stderr)
    site_brief = (ROOT / "site/src/content/briefings"
                  / f"{date_str}.md")
    daily_brief = day_dir_for(date_str) / "briefing.md"
    if not (site_brief.exists() and daily_brief.exists()):
        return st.mark(state, "publish_brief", "failed",
                       error=("missing site or daily briefing "
                              "after publish_briefing"))
    return st.mark(state, "publish_brief", "ok")


def step_audio(date_str: str, state: Dict) -> Dict:
    print("→ audio")
    r = run(["python3", "scripts/render_audio.py",
             "--date", date_str], check=False)
    print(r.stdout.rstrip())
    if r.stderr.strip():
        print(r.stderr.rstrip(), file=sys.stderr)
    if r.returncode != 0:
        return st.mark(state, "audio", "failed",
                       error=f"render_audio rc={r.returncode}")
    mp3 = day_dir_for(date_str) / "audio.mp3"
    site_mp3 = ROOT / "site/public/audio" / f"{date_str}.mp3"
    if not mp3.exists() or mp3.stat().st_size < MIN_AUDIO_BYTES:
        return st.mark(state, "audio", "failed",
                       error=(f"mp3 missing or too small: "
                              f"{mp3.stat().st_size if mp3.exists() else 0}"
                              f" bytes < {MIN_AUDIO_BYTES}"))
    if not site_mp3.exists():
        return st.mark(state, "audio", "failed",
                       error="site/public/audio/<date>.mp3 missing "
                             "after render_audio")

    # Now write broadcast_log — audio is real and on disk.
    sel = json.loads(SELECTED_JSON.read_text(encoding="utf-8"))
    article_ids = [a["id"] for a in sel["articles"] if a.get("_translated")]
    audio_url = f"{SITE_BASE_URL}/audio/{date_str}.mp3"
    briefing_url = f"{SITE_BASE_URL}/briefings/{date_str}"
    with NewsDB(str(DB_PATH)) as db:
        db.log_broadcast(
            broadcast_date=date_str,
            article_ids=article_ids,
            briefing_url=briefing_url,
            audio_url=audio_url,
            audio_path=str(mp3.relative_to(ROOT)),
        )
    return st.mark(state, "audio", "ok",
                   mp3_size=mp3.stat().st_size, article_count=len(article_ids))


def step_push(date_str: str, state: Dict) -> Dict:
    print("→ push")
    r = run(["python3", "scripts/git_publish.py", "--date", date_str],
            check=False)
    print(r.stdout.rstrip())
    if r.stderr.strip():
        print(r.stderr.rstrip(), file=sys.stderr)
    if r.returncode != 0:
        return st.mark(state, "push", "failed",
                       error=f"git_publish rc={r.returncode}")
    return st.mark(state, "push", "ok")


STEP_FUNCS = {
    "harvest": step_harvest,
    "select": step_select,
    "translate": step_translate,
    "publish_article": step_publish_article,
    "publish_brief": step_publish_brief,
    "audio": step_audio,
    "push": step_push,
}


# ── Status / orchestrator ───────────────────────────────────────


def print_status(state: Dict) -> None:
    print(f"📋 state for {state.get('date')}")
    for step in st.STEPS:
        block = st.get(state, step)
        status = block.get("status", "pending")
        marker = {
            "ok": "✅",
            "pending": "⏳",
            "running": "▶️ ",
            "failed": "❌",
            "skipped": "⏭️ ",
        }.get(status, "?")
        extras = []
        for k, v in block.items():
            if k not in ("status", "started_at", "finished_at"):
                if isinstance(v, (list, dict)):
                    extras.append(f"{k}={json.dumps(v, ensure_ascii=False)[:60]}")
                else:
                    extras.append(f"{k}={v}")
        print(f"  {marker} {step:18s} {status:8s} "
              f"{block.get('finished_at', '')[:19]}"
              f"{' | ' + ', '.join(extras) if extras else ''}")


def run_one_step(step: str, date_str: str, state_path: Path,
                 state: Dict) -> Dict:
    fn = STEP_FUNCS.get(step)
    if not fn:
        raise ValueError(f"unknown step: {step}")
    state = st.mark(state, step, "running")
    st.save(state_path, state)
    try:
        state = fn(date_str, state)
    except subprocess.CalledProcessError as e:
        state = st.mark(state, step, "failed",
                        error=e.stderr.strip()[:500] or str(e))
    except Exception as e:
        state = st.mark(state, step, "failed", error=str(e))
    st.save(state_path, state)
    return state


def _budget_left(deadline: Optional[float]) -> Optional[float]:
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="today")
    p.add_argument("--step", choices=list(STEP_FUNCS.keys()),
                   help="Run a single step regardless of state.")
    p.add_argument("--from", dest="from_step", choices=list(STEP_FUNCS.keys()),
                   help="Start from this step.")
    p.add_argument("--to", dest="to_step", choices=list(STEP_FUNCS.keys()),
                   help="Stop after this step (inclusive).")
    p.add_argument("--resume", action="store_true",
                   help="Skip already-ok steps and run the rest.")
    p.add_argument("--status", action="store_true",
                   help="Print state and exit.")
    p.add_argument("--budget-seconds", type=int, default=0,
                   help="Soft wall-clock limit. After each step we check "
                        "remaining budget; if it'd be insufficient for "
                        "the next step we exit cleanly so the next wake "
                        "can resume. 0 disables.")
    args = p.parse_args()

    date_str = parse_date(args.date)
    day_dir = day_dir_for(date_str)
    day_dir.mkdir(parents=True, exist_ok=True)
    state_path = day_dir / ".state.json"
    state = st.load(state_path, date_str)

    # Demote any "running" step left over from an interrupted run so
    # we redo it cleanly. Steps are idempotent.
    reset = st.reset_running(state)
    if reset:
        print(f"♻️  resetting interrupted steps: {', '.join(reset)}")
        st.save(state_path, state)

    if args.status:
        print_status(state)
        return

    if args.step:
        state = run_one_step(args.step, date_str, state_path, state)
        print_status(state)
        if st.get(state, args.step).get("status") != "ok":
            sys.exit(1)
        return

    # Default: walk through all pending steps.
    start_from = args.from_step
    if not start_from and not args.resume:
        # Implicit resume — pipeline should be idempotent
        args.resume = True
    cursor = st.next_pending(state, from_step=start_from)
    if cursor is None:
        print("✅ all steps already completed")
        print_status(state)
        return

    deadline = (time.monotonic() + args.budget_seconds
                if args.budget_seconds else None)
    stop_after = args.to_step

    while cursor:
        # Soft budget check: leave at least 30 s for the next step.
        left = _budget_left(deadline)
        if left is not None and left < 30:
            print(f"⏸  budget exhausted ({left:.0f}s left) — pausing "
                  f"before {cursor}; rerun --resume to continue")
            print_status(state)
            return
        state = run_one_step(cursor, date_str, state_path, state)
        block = st.get(state, cursor)
        if block.get("status") != "ok":
            # Translate step is allowed to be "pending" — agent must drive
            if cursor == "translate" and block.get("status") == "pending":
                print("⏸  translate is agent-driven; rerun --resume "
                      "after translate_helper write/skip + finalize")
                print_status(state)
                return
            print_status(state)
            sys.exit(1 if block.get("status") == "failed" else 0)
        if stop_after and cursor == stop_after:
            print(f"⏹  reached --to {stop_after}; stopping")
            print_status(state)
            return
        cursor = st.next_pending(state)
    print_status(state)


if __name__ == "__main__":
    main()
