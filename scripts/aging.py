#!/usr/bin/env python3
"""Manual CLI for the aging job.

Default policy follows ``RetentionConfig`` (played=∞, unplayed=365d,
archived=60d, url_seen=365d, daily_dir=30d). Per-bucket overrides let
you do one-off cleanups without changing the codified defaults.

Examples:

    # Show what would be pruned, no changes
    python3 scripts/aging.py --dry-run

    # Apply default policy (same as daily_wake.py runs)
    python3 scripts/aging.py --apply

    # One-shot aggressive shrink: drop unplayed older than 30 days
    python3 scripts/aging.py --apply --override-unplayed-days 30
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.aging import (
    RetentionConfig,
    prune,
    prune_daily_dirs,
    prune_db,
)
from scripts.lib.news_db import NewsDB

DB_PATH = ROOT / "data" / "news.db"
DAILY_ROOT = ROOT / "daily"


def build_config(args) -> RetentionConfig:
    cfg = RetentionConfig()
    if args.override_played_days is not None:
        cfg.played_days = (
            None if args.override_played_days < 0 else args.override_played_days
        )
    if args.override_unplayed_days is not None:
        cfg.unplayed_days = args.override_unplayed_days
    if args.override_archived_days is not None:
        cfg.archived_days = args.override_archived_days
    if args.override_url_seen_days is not None:
        cfg.url_seen_days = args.override_url_seen_days
    if args.override_daily_dir_days is not None:
        cfg.daily_dir_days = args.override_daily_dir_days
    return cfg


def cutoff_summary(cfg: RetentionConfig) -> dict:
    return {
        "played_days": cfg.played_days,
        "unplayed_days": cfg.unplayed_days,
        "archived_days": cfg.archived_days,
        "url_seen_days": cfg.url_seen_days,
        "daily_dir_days": cfg.daily_dir_days,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Print what WOULD be pruned without changing the DB.")
    p.add_argument("--apply", action="store_true",
                   help="Actually run the prune.")
    p.add_argument("--override-played-days", type=int, default=None,
                   help="Override played retention. Use -1 for never delete.")
    p.add_argument("--override-unplayed-days", type=int, default=None)
    p.add_argument("--override-archived-days", type=int, default=None)
    p.add_argument("--override-url-seen-days", type=int, default=None)
    p.add_argument("--override-daily-dir-days", type=int, default=None)
    p.add_argument("--no-vacuum", action="store_true")
    p.add_argument("--db", default=str(DB_PATH))
    args = p.parse_args()

    if not args.dry_run and not args.apply:
        p.error("Provide --dry-run or --apply.")

    cfg = build_config(args)
    print(f"Policy: {json.dumps(cutoff_summary(cfg), ensure_ascii=False)}")

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"❌ DB not found: {db_path}")
        sys.exit(2)

    if args.dry_run:
        # Count rows that WOULD be deleted via SELECT — no DELETE.
        import sqlite3
        from datetime import timedelta as _td
        from scripts.lib.aging import _cutoff_iso, INTERMEDIATE_FILENAMES
        now = datetime.now(timezone.utc)
        with NewsDB(str(db_path), use_bloom=False) as db:
            conn = db.connect()
            played_cut = _cutoff_iso(now, cfg.played_days)
            unplayed_cut = _cutoff_iso(now, cfg.unplayed_days)
            archived_cut = _cutoff_iso(now, cfg.archived_days)
            url_cut = _cutoff_iso(now, cfg.url_seen_days)

            def _count(sql, params):
                try:
                    return conn.execute(sql, params).fetchone()[0]
                except sqlite3.OperationalError:
                    return 0  # table not yet created (pre-migration)

            counts = {"played": 0, "unplayed": 0, "archived": 0, "url_seen": 0}
            if played_cut:
                counts["played"] = _count(
                    "SELECT COUNT(*) FROM news_articles "
                    "WHERE broadcast_status = 'played' "
                    "  AND COALESCE(broadcast_date, discovered_at) < ?",
                    (played_cut,),
                )
            if unplayed_cut:
                counts["unplayed"] = _count(
                    "SELECT COUNT(*) FROM news_articles "
                    "WHERE broadcast_status = 'unplayed' "
                    "  AND discovered_at < ?",
                    (unplayed_cut,),
                )
            if archived_cut:
                counts["archived"] = _count(
                    "SELECT COUNT(*) FROM news_articles "
                    "WHERE broadcast_status = 'archived' "
                    "  AND discovered_at < ?",
                    (archived_cut,),
                )
            if url_cut:
                counts["url_seen"] = _count(
                    "SELECT COUNT(*) FROM url_seen WHERE first_seen_at < ?",
                    (url_cut,),
                )

        dir_count = 0
        if DAILY_ROOT.exists():
            cutoff_ts = (datetime.now() - _td(days=cfg.daily_dir_days)).timestamp()
            for date_dir in DAILY_ROOT.glob("*/*/*"):
                if not date_dir.is_dir():
                    continue
                for child in date_dir.iterdir():
                    if (child.is_file() and
                        child.name in INTERMEDIATE_FILENAMES and
                        child.stat().st_mtime < cutoff_ts):
                        dir_count += 1

        print()
        print("Dry-run — would prune:")
        print(f"  played:        {counts['played']}")
        print(f"  unplayed:      {counts['unplayed']}")
        print(f"  archived:      {counts['archived']}")
        print(f"  url_seen:      {counts['url_seen']}")
        print(f"  intermediate files: {dir_count}")
        print()
        print("Re-run with --apply to execute.")
        return

    # --apply
    with NewsDB(str(db_path), use_bloom=False) as db:
        result = prune(db, cfg, daily_root=DAILY_ROOT)
    print()
    print("Pruned:")
    print(f"  played:        {result['played']}")
    print(f"  unplayed:      {result['unplayed']}")
    print(f"  archived:      {result['archived']}")
    print(f"  url_seen:      {result['url_seen']}")
    print(f"  intermediate files: {result['files_removed']}")
    print(f"  vacuumed:      {result['vacuumed']}")


if __name__ == "__main__":
    main()
