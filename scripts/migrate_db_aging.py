#!/usr/bin/env python3
"""One-shot migration: enable Phase 2 DB-size controls.

Steps:
  1. Backup `data/news.db` → `data/news.db.pre-aging.bak`
  2. Apply schema (idempotent CREATE TABLE / INDEX for url_seen)
  3. Backfill url_seen from every existing news_articles row
  4. Apply default retention (typically a no-op on fresh-ish data)
  5. VACUUM
  6. Print before/after stats

Idempotent — running twice is safe; backfill uses INSERT OR IGNORE,
retention is by absolute cutoff.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.aging import (
    RetentionConfig,
    backup_db,
    prune_db,
)
from scripts.lib.news_db import NewsDB

DB_PATH = ROOT / "data" / "news.db"


def backfill_url_seen(db: NewsDB) -> int:
    """Populate url_seen from existing news_articles rows."""
    conn = db.connect()
    rows = conn.execute("""
        SELECT url_normalized, story_hash, discovered_at, source_id
          FROM news_articles
         WHERE url_normalized IS NOT NULL AND url_normalized != ''
    """).fetchall()

    batch = []
    for r in rows:
        batch.append({
            "url_hash": NewsDB.make_url_hash(r["url_normalized"]),
            "title_hash": r["story_hash"],
            "source_id": r["source_id"],
            "seen_at": r["discovered_at"],
        })
    return db.record_url_seen_batch(batch)


def db_size_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def collect_stats(db: NewsDB, db_path: Path) -> Dict[str, object]:
    s = db.stats()
    s["db_size"] = db_size_bytes(db_path)
    return s


def print_diff(before: Dict[str, object], after: Dict[str, object]) -> None:
    print()
    print("Stats:")
    fields = ("total_articles", "unplayed", "played", "archived",
              "url_seen", "db_size")
    width = max(len(f) for f in fields)
    for f in fields:
        b = before.get(f, 0)
        a = after.get(f, 0)
        delta = (a - b) if isinstance(a, int) and isinstance(b, int) else 0
        if f == "db_size":
            b_str = fmt_size(int(b))
            a_str = fmt_size(int(a))
            d_str = (f"{'+' if delta >= 0 else ''}{fmt_size(abs(int(delta)))}"
                     if delta else "—")
        else:
            b_str = str(b)
            a_str = str(a)
            d_str = (f"{'+' if delta >= 0 else ''}{delta}" if delta else "—")
        print(f"  {f:<{width}}  before={b_str:<10}  after={a_str:<10}  Δ={d_str}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--confirm", action="store_true",
                   help="Required to actually mutate the DB.")
    p.add_argument("--db", default=str(DB_PATH),
                   help="Path to news.db (default: data/news.db)")
    p.add_argument("--skip-backup", action="store_true",
                   help="Don't create a .bak (use only if already backed up).")
    args = p.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"❌ DB not found: {db_path}")
        sys.exit(2)

    if not args.confirm:
        print("Dry run. Add --confirm to apply.")
        with NewsDB(str(db_path), use_bloom=False) as db:
            stats = collect_stats(db, db_path)
        print(f"Current DB: {db_path} {fmt_size(stats['db_size'])}")
        for k in ("total_articles", "unplayed", "played", "archived"):
            print(f"  {k}: {stats[k]}")
        try:
            seen_n = stats.get("url_seen", 0)
        except Exception:
            seen_n = 0
        print(f"  url_seen: {seen_n}")
        print()
        print("Will:")
        print("  1. Backup → data/news.db.pre-aging.bak")
        print("  2. Apply schema (CREATE TABLE url_seen IF NOT EXISTS)")
        print("  3. Backfill url_seen from news_articles "
              f"(~{stats['total_articles']} rows expected)")
        print("  4. Prune unplayed > 365d / archived > 60d "
              "(played untouched per user policy)")
        print("  5. VACUUM if > 100 rows pruned")
        return

    print("=" * 60)
    print(f"Migration target: {db_path}")

    if not args.skip_backup:
        bak = backup_db(db_path)
        print(f"✅ Backup: {bak}")

    with NewsDB(str(db_path), use_bloom=False) as db:
        before = collect_stats(db, db_path)
        print(f"Before: {before['total_articles']} articles, "
              f"{before['url_seen']} url_seen rows, "
              f"{fmt_size(before['db_size'])}")

        # 1. Apply schema (idempotent CREATE IF NOT EXISTS).
        db.init()
        print("✅ Schema applied (url_seen table ready)")

        # 2. Backfill url_seen.
        backfilled = backfill_url_seen(db)
        print(f"✅ Backfill: +{backfilled} url_seen rows")

        # 3. Apply retention.
        cfg = RetentionConfig()  # user policy: played=None, unplayed=365, archived=60
        now = datetime.now(timezone.utc)
        result = prune_db(db, cfg, now=now, vacuum=True)
        print(f"✅ Retention applied:")
        print(f"   played pruned   : {result['played']}")
        print(f"   unplayed pruned : {result['unplayed']}")
        print(f"   archived pruned : {result['archived']}")
        print(f"   url_seen pruned : {result['url_seen']}")
        print(f"   vacuumed        : {result['vacuumed']}")

        # If we didn't VACUUM as part of pruning, VACUUM anyway to reflect
        # the schema change on disk.
        if not result["vacuumed"]:
            db.vacuum()
            print("✅ VACUUM (schema settle)")

        after = collect_stats(db, db_path)

    print_diff(before, after)
    print()
    print("Migration complete.")


if __name__ == "__main__":
    main()
