#!/usr/bin/env python3
"""One-shot migration: archive 04-26 / 04-27 / 04-28 cold-start runs.

Why those three:
  * 2026-04-26 — every article translated as ``[原文待翻译]`` placeholder
                 (dry_run_translate.py); broadcast_log entry exists.
  * 2026-04-27 — placeholder translations published, no audio,
                 no broadcast_log entry, but daily/ files exist.
  * 2026-04-28 — agent picked all generic Tagesschau economy news and
                 force-tagged everything with ``gastro-law``;
                 audio.mp3 was never produced.

What it does:
  1. ``ALTER TABLE`` adds ``quarantine_reason`` if the column doesn't
     yet exist (idempotent).
  2. Marks the affected article ids ``broadcast_status='archived'``
     with a per-day reason string.
  3. Adds ``archived: true`` to the briefing frontmatter for those
     three dates.
  4. Adds ``archived: true`` to every related ``site/src/content/articles/<slug>.md``
     frontmatter.

Run with ``--confirm`` to actually apply changes; without that flag
it prints the plan only.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.news_db import NewsDB

DB_PATH = ROOT / "data" / "news.db"
BRIEFINGS_DIR = ROOT / "site" / "src" / "content" / "briefings"
ARTICLES_DIR = ROOT / "site" / "src" / "content" / "articles"
DAILY_ROOT = ROOT / "daily"

PLAN: Dict[str, Tuple[str, List[int]]] = {
    "2026-04-26": (
        "cold-start placeholder translations (dry_run_translate prefix)",
        # Filled below from broadcast_log if available.
        [],
    ),
    "2026-04-27": (
        "placeholder translations published without audio",
        [],
    ),
    "2026-04-28": (
        "off-topic Tagesschau selection with mis-tagged gastro-law",
        [],
    ),
}


def ensure_quarantine_column(db_path: Path) -> bool:
    """Idempotent ALTER TABLE."""
    conn = sqlite3.connect(str(db_path))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(news_articles)")]
    if "quarantine_reason" in cols:
        conn.close()
        return False
    conn.execute(
        "ALTER TABLE news_articles ADD COLUMN quarantine_reason TEXT"
    )
    conn.commit()
    conn.close()
    return True


def gather_ids(date_str: str) -> List[int]:
    """Find article ids for a date from broadcast_log + meta.json."""
    ids: List[int] = []
    with NewsDB(str(DB_PATH)) as db:
        conn = db.connect()
        row = conn.execute(
            "SELECT article_ids FROM broadcast_log WHERE broadcast_date = ?",
            (date_str,),
        ).fetchone()
        if row:
            try:
                ids.extend(json.loads(row["article_ids"]))
            except Exception:
                pass
    # Fallback: read meta.json for that day
    year, month, _ = date_str.split("-")
    meta = (DAILY_ROOT / year / f"{year}-{month}" / date_str
            / "meta.json")
    if meta.exists():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            for aid in data.get("article_ids", []):
                if aid not in ids:
                    ids.append(aid)
        except Exception:
            pass
    return ids


def slugs_for_ids(ids: List[int]) -> List[str]:
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with NewsDB(str(DB_PATH)) as db:
        conn = db.connect()
        rows = conn.execute(
            f"SELECT slug FROM news_articles WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    return [r["slug"] for r in rows if r["slug"]]


_FRONTMATTER_END_RE = re.compile(r"\n---\s*\n|\n---\s*$|---\s*\n", re.MULTILINE)


def add_frontmatter_flag(path: Path, key: str = "archived",
                         value: str = "true",
                         reason: str = "") -> bool:
    """Insert or update ``key: value`` line inside frontmatter.

    Robust to a malformed prior pass that may have glued the closing
    ``---`` onto the previous line. Always re-emits a clean
    ``---\\nbody\\n---\\n``.
    """
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    rest = text[3:]
    # Find the *next* run of three dashes terminating the block. We
    # accept ``\n---\n`` (well-formed), ``\n---`` at EOF, or even
    # ``foo---\n`` (broken — left by the first buggy migration pass).
    m = re.search(r"(?:\n)?---\s*(?:\n|$)", rest)
    if not m:
        return False
    frontmatter_inner = rest[: m.start()]
    body = rest[m.end():]
    fm_lines = [line for line in frontmatter_inner.splitlines() if line]

    new_lines: List[str] = []
    seen_key = False
    seen_reason = False
    for line in fm_lines:
        if line.startswith(f"{key}:"):
            new_lines.append(f"{key}: {value}")
            seen_key = True
        elif line.startswith("archiveReason:"):
            if reason:
                new_lines.append(f'archiveReason: "{reason}"')
                seen_reason = True
            # else drop it
        else:
            new_lines.append(line)
    if not seen_key:
        new_lines.append(f"{key}: {value}")
    if reason and not seen_reason:
        new_lines.append(f'archiveReason: "{reason}"')

    new_frontmatter = "\n".join(new_lines)
    body_normalized = body if body.startswith("\n") else "\n" + body
    new_text = "---\n" + new_frontmatter + "\n---" + body_normalized
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def archive_briefing(date_str: str, reason: str, dry_run: bool) -> bool:
    p = BRIEFINGS_DIR / f"{date_str}.md"
    if not p.exists():
        print(f"  ⚠️  briefing missing: {p.relative_to(ROOT)}")
        return False
    if dry_run:
        print(f"  would mark archived: {p.relative_to(ROOT)}")
        return True
    changed = add_frontmatter_flag(p, reason=reason)
    print(f"  {'✏️ ' if changed else '·  '} "
          f"{p.relative_to(ROOT)} ({'updated' if changed else 'no-op'})")
    return True


def archive_articles(slugs: List[str], reason: str,
                     dry_run: bool) -> int:
    n = 0
    for slug in slugs:
        p = ARTICLES_DIR / f"{slug}.md"
        if not p.exists():
            continue
        if dry_run:
            print(f"  would mark: articles/{slug}.md")
            n += 1
            continue
        if add_frontmatter_flag(p, reason=reason):
            print(f"  ✏️  articles/{slug}.md")
            n += 1
    return n


def quarantine_db(ids: List[int], reason: str, dry_run: bool) -> int:
    if not ids:
        return 0
    if dry_run:
        print(f"  would quarantine {len(ids)} articles in DB")
        return len(ids)
    with NewsDB(str(DB_PATH)) as db:
        n = db.quarantine(ids, reason)
    print(f"  ✏️  DB: {n} articles → broadcast_status='archived'")
    return n


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--confirm", action="store_true",
                   help="Apply changes. Without it, dry-run only.")
    args = p.parse_args()

    dry = not args.confirm
    if dry:
        print("🔍 DRY RUN — pass --confirm to apply\n")

    altered = ensure_quarantine_column(DB_PATH)
    if altered:
        print("✅ ALTER TABLE: added quarantine_reason\n")
    else:
        print("· quarantine_reason already present\n")

    total_db = 0
    for date_str, (reason, _) in PLAN.items():
        ids = gather_ids(date_str)
        slugs = slugs_for_ids(ids)
        print(f"📅 {date_str}: {len(ids)} article(s)")
        print(f"   reason: {reason}")
        archive_briefing(date_str, reason, dry)
        total_db += quarantine_db(ids, reason, dry)
        n = archive_articles(slugs, reason, dry)
        print(f"   articles flagged on disk: {n}\n")

    print(f"📊 total DB rows quarantined: {total_db}")
    if dry:
        print("\nRe-run with --confirm to apply.")


if __name__ == "__main__":
    main()
