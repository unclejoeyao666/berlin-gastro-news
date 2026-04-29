"""Data aging — bound DB growth.

Retention policy (chosen by user 2026-04-30):

* ``played``     → kept forever (None means skip).
* ``unplayed``   → 365 days from ``discovered_at``.
* ``archived``   → 60 days from ``discovered_at`` (quarantine usually
                   happens on the harvest day, so this works as
                   "60 days after quarantine" for normal flow).
* ``url_seen``   → 365 days from ``first_seen_at``.
* ``daily/<date>/`` intermediate files → 30 days from mtime.
  ``briefing.md``/``audio.mp3``/``daily-selected.json`` are never
  touched (they live in git).

Aging runs once per day at the tail of ``daily_wake.py``. CLI access
through ``scripts/aging.py``.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .news_db import NewsDB

# Files inside daily/<date>/ that count as intermediate (safe to age).
# Anything not in this list is preserved.
INTERMEDIATE_FILENAMES = {
    "intake.json",
    ".harvest.log",
    ".tts.log",
    "audio_script.tts.txt",
    ".state.json",
}

VACUUM_ROW_THRESHOLD = 100


@dataclass
class RetentionConfig:
    played_days: Optional[int] = None      # None = keep forever
    unplayed_days: int = 365
    archived_days: int = 60
    url_seen_days: int = 365
    daily_dir_days: int = 30


def _cutoff_iso(now: datetime, days: Optional[int]) -> Optional[str]:
    if days is None:
        return None
    return (now - timedelta(days=days)).isoformat(timespec="seconds")


def prune_db(
    db: NewsDB,
    cfg: RetentionConfig,
    now: Optional[datetime] = None,
    vacuum: bool = True,
) -> dict:
    """Prune news_articles + url_seen by retention rules.

    Returns ``{"played": n, "unplayed": n, "archived": n,
              "url_seen": n, "vacuumed": bool, "total_deleted": n}``.
    """
    now = now or datetime.now(timezone.utc)
    article_counts = db.prune_articles(
        played_cutoff=_cutoff_iso(now, cfg.played_days),
        unplayed_cutoff=_cutoff_iso(now, cfg.unplayed_days),
        archived_cutoff=_cutoff_iso(now, cfg.archived_days),
    )
    url_cutoff = _cutoff_iso(now, cfg.url_seen_days)
    url_pruned = db.prune_url_seen(url_cutoff) if url_cutoff else 0

    total = sum(article_counts.values()) + url_pruned
    vacuumed = False
    if vacuum and total > VACUUM_ROW_THRESHOLD:
        db.vacuum()
        vacuumed = True

    return {
        **article_counts,
        "url_seen": url_pruned,
        "vacuumed": vacuumed,
        "total_deleted": total,
    }


def prune_daily_dirs(
    daily_root: Path,
    cfg: RetentionConfig,
    now: Optional[datetime] = None,
) -> dict:
    """Walk daily/<YYYY>/<YYYY-MM>/<DATE>/ and delete intermediate files
    older than ``cfg.daily_dir_days``. Preserves briefing.md, audio.mp3,
    daily-selected.json regardless of age (they're git-tracked or still
    in active use).

    Returns ``{"files_removed": n, "dirs_visited": n}``.
    """
    now = now or datetime.now(timezone.utc)
    cutoff_ts = (now - timedelta(days=cfg.daily_dir_days)).timestamp()

    files_removed = 0
    dirs_visited = 0
    if not daily_root.exists():
        return {"files_removed": 0, "dirs_visited": 0}

    for date_dir in daily_root.glob("*/*/*"):
        if not date_dir.is_dir():
            continue
        dirs_visited += 1
        for child in date_dir.iterdir():
            if not child.is_file():
                continue
            if child.name not in INTERMEDIATE_FILENAMES:
                continue
            try:
                if child.stat().st_mtime < cutoff_ts:
                    child.unlink()
                    files_removed += 1
            except FileNotFoundError:
                pass

    return {"files_removed": files_removed, "dirs_visited": dirs_visited}


def prune(
    db: NewsDB,
    cfg: RetentionConfig,
    daily_root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Full aging pass: prune DB + intermediate daily files."""
    db_result = prune_db(db, cfg, now=now)
    dir_result = (
        prune_daily_dirs(daily_root, cfg, now=now) if daily_root else
        {"files_removed": 0, "dirs_visited": 0}
    )
    return {**db_result, **dir_result}


def backup_db(db_path: Path, suffix: str = "pre-aging") -> Path:
    """Copy DB file to a side path; returns the backup path."""
    bak = db_path.with_suffix(f"{db_path.suffix}.{suffix}.bak")
    shutil.copy2(db_path, bak)
    return bak
