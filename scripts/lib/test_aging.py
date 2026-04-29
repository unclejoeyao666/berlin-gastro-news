from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from scripts.lib.aging import (  # noqa: E402
    RetentionConfig,
    prune_daily_dirs,
    prune_db,
    prune,
    INTERMEDIATE_FILENAMES,
    VACUUM_ROW_THRESHOLD,
)
from scripts.lib.news_db import NewsDB  # noqa: E402


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    with NewsDB(str(db_path), use_bloom=False) as db:
        db.init()
    with NewsDB(str(db_path), use_bloom=False) as db:
        yield db


def make_article(**overrides):
    base = {
        "title": "Test article",
        "summary": "Short summary.",
        "content": "Full content.",
        "source_id": "test-source",
        "source_name": "Test Source",
        "source_url": "https://example.com/article",
        "published_at": "2026-04-26T08:00:00Z",
        "lang": "de",
        "importance": 5,
    }
    base.update(overrides)
    return base


# ── retention cutoffs ──────────────────────────────────


def test_played_kept_forever_when_days_is_none(db):
    rid = db.add_article(make_article(source_url="https://e.com/x"))
    db.update_translation(rid, "ct", "cs", "cb", "ia", ["gastro-law"], "slug-x")
    db.mark_played([rid], briefing_date="2025-01-01")
    db.connect().execute(
        "UPDATE news_articles SET broadcast_date = '2024-01-01T00:00:00' "
        "WHERE id = ?", (rid,)
    )

    cfg = RetentionConfig(played_days=None)
    result = prune_db(db, cfg, now=datetime(2026, 4, 30, tzinfo=timezone.utc))
    assert result["played"] == 0
    n = db.connect().execute(
        "SELECT COUNT(*) FROM news_articles WHERE id = ?", (rid,)
    ).fetchone()[0]
    assert n == 1


def test_played_pruned_when_days_set(db):
    rid_old = db.add_article(make_article(
        title="old", source_url="https://e.com/old"
    ))
    rid_new = db.add_article(make_article(
        title="new", source_url="https://e.com/new"
    ))
    for rid in (rid_old, rid_new):
        db.update_translation(rid, "ct", "cs", "cb", "ia", ["gastro-law"],
                              f"slug-{rid}")
    db.mark_played([rid_old], briefing_date="2024-01-01")
    db.mark_played([rid_new], briefing_date="2026-04-29")
    db.connect().execute(
        "UPDATE news_articles SET broadcast_date = '2024-01-01T00:00:00' "
        "WHERE id = ?", (rid_old,)
    )

    cfg = RetentionConfig(played_days=90)
    result = prune_db(db, cfg, now=datetime(2026, 4, 30, tzinfo=timezone.utc))
    assert result["played"] == 1
    rows = db.connect().execute("SELECT id FROM news_articles").fetchall()
    assert {r["id"] for r in rows} == {rid_new}


def test_unplayed_365_day_cutoff(db):
    # 366 days old → pruned
    rid_old = db.add_article(make_article(
        title="old", source_url="https://e.com/old"
    ))
    db.connect().execute(
        "UPDATE news_articles SET discovered_at = '2025-04-29T00:00:00' "
        "WHERE id = ?", (rid_old,)
    )
    # 4 days old → retained
    rid_new = db.add_article(make_article(
        title="new", source_url="https://e.com/new"
    ))
    db.connect().execute(
        "UPDATE news_articles SET discovered_at = '2026-04-26T00:00:00' "
        "WHERE id = ?", (rid_new,)
    )

    cfg = RetentionConfig(unplayed_days=365)
    result = prune_db(db, cfg,
                     now=datetime(2026, 4, 30, tzinfo=timezone.utc))
    assert result["unplayed"] == 1
    rows = db.connect().execute("SELECT id FROM news_articles").fetchall()
    assert {r["id"] for r in rows} == {rid_new}


def test_archived_60_day_cutoff(db):
    rid_old = db.add_article(make_article(
        title="archived-old", source_url="https://e.com/old"
    ))
    rid_new = db.add_article(make_article(
        title="archived-new", source_url="https://e.com/new"
    ))
    db.quarantine([rid_old, rid_new], reason="test")
    db.connect().execute(
        "UPDATE news_articles SET discovered_at = '2026-01-01T00:00:00' "
        "WHERE id = ?", (rid_old,)
    )
    db.connect().execute(
        "UPDATE news_articles SET discovered_at = '2026-04-26T00:00:00' "
        "WHERE id = ?", (rid_new,)
    )

    cfg = RetentionConfig(archived_days=60)
    result = prune_db(db, cfg,
                     now=datetime(2026, 4, 30, tzinfo=timezone.utc))
    assert result["archived"] == 1


def test_url_seen_pruned_separately(db):
    db.record_url_seen("h-old", "t1", "src", seen_at="2024-01-01T00:00:00")
    db.record_url_seen("h-new", "t2", "src", seen_at="2026-04-29T00:00:00")

    cfg = RetentionConfig(url_seen_days=365)
    result = prune_db(db, cfg,
                     now=datetime(2026, 4, 30, tzinfo=timezone.utc))
    assert result["url_seen"] == 1


def test_url_seen_survives_article_aging(db):
    """Critical invariant: deleting an article must not delete its
    url_seen entry. Otherwise dedup breaks across the prune boundary."""
    rid = db.add_article(make_article(source_url="https://e.com/x"))
    url_hash = db.make_url_hash("https://e.com/x")
    db.connect().execute(
        "UPDATE news_articles SET discovered_at = '2024-01-01T00:00:00' "
        "WHERE id = ?", (rid,)
    )

    cfg = RetentionConfig(unplayed_days=365)
    prune_db(db, cfg, now=datetime(2026, 4, 30, tzinfo=timezone.utc))

    # Article gone, url_seen retained.
    n_articles = db.connect().execute(
        "SELECT COUNT(*) FROM news_articles"
    ).fetchone()[0]
    assert n_articles == 0
    assert db.is_url_seen(url_hash) is True


def test_vacuum_threshold_below(db):
    # Only one row pruned → no vacuum
    rid = db.add_article(make_article(source_url="https://e.com/x"))
    db.connect().execute(
        "UPDATE news_articles SET discovered_at = '2024-01-01T00:00:00' "
        "WHERE id = ?", (rid,)
    )
    cfg = RetentionConfig(unplayed_days=365)
    result = prune_db(db, cfg,
                     now=datetime(2026, 4, 30, tzinfo=timezone.utc))
    assert result["total_deleted"] == 1
    assert result["vacuumed"] is False


def test_vacuum_threshold_above(db):
    # Insert > VACUUM_ROW_THRESHOLD url_seen rows that are all old
    rows = [
        {"url_hash": f"h-{i}", "title_hash": f"t-{i}",
         "source_id": "src", "seen_at": "2024-01-01T00:00:00"}
        for i in range(VACUUM_ROW_THRESHOLD + 5)
    ]
    db.record_url_seen_batch(rows)
    cfg = RetentionConfig(url_seen_days=365)
    result = prune_db(db, cfg,
                     now=datetime(2026, 4, 30, tzinfo=timezone.utc))
    assert result["url_seen"] == VACUUM_ROW_THRESHOLD + 5
    assert result["vacuumed"] is True


# ── daily/<date>/ pruning ──────────────────────────────


def test_prune_daily_dirs_removes_old_intermediates(tmp_path):
    daily_root = tmp_path / "daily"
    date_dir = daily_root / "2025" / "2025-12" / "2025-12-15"
    date_dir.mkdir(parents=True)

    # Old intermediate file → should be removed
    old_file = date_dir / ".harvest.log"
    old_file.write_text("dropped: 100\n")
    old_ts = (datetime.now() - timedelta(days=60)).timestamp()
    import os
    os.utime(old_file, (old_ts, old_ts))

    # Old preserved file → must NOT be removed
    keep_file = date_dir / "briefing.md"
    keep_file.write_text("# briefing")
    os.utime(keep_file, (old_ts, old_ts))

    # Recent intermediate file → keep
    recent = date_dir / "intake.json"
    recent.write_text("[]")

    cfg = RetentionConfig(daily_dir_days=30)
    result = prune_daily_dirs(daily_root, cfg)

    assert result["files_removed"] == 1
    assert not old_file.exists()
    assert keep_file.exists()
    assert recent.exists()


def test_prune_daily_dirs_handles_missing_root(tmp_path):
    cfg = RetentionConfig()
    result = prune_daily_dirs(tmp_path / "nonexistent", cfg)
    assert result == {"files_removed": 0, "dirs_visited": 0}


def test_intermediate_filenames_are_complete():
    """Sanity check on the allow-list — must include the well-known
    intermediates without accidentally including briefing/audio."""
    assert "intake.json" in INTERMEDIATE_FILENAMES
    assert ".state.json" in INTERMEDIATE_FILENAMES
    assert ".harvest.log" in INTERMEDIATE_FILENAMES
    assert "briefing.md" not in INTERMEDIATE_FILENAMES
    assert "audio.mp3" not in INTERMEDIATE_FILENAMES
    assert "daily-selected.json" not in INTERMEDIATE_FILENAMES


def test_full_prune_combines_db_and_dirs(tmp_path):
    db_path = tmp_path / "x.db"
    daily_root = tmp_path / "daily"
    date_dir = daily_root / "2025" / "2025-12" / "2025-12-15"
    date_dir.mkdir(parents=True)
    old = date_dir / ".harvest.log"
    old.write_text("x")
    import os
    old_ts = (datetime.now() - timedelta(days=60)).timestamp()
    os.utime(old, (old_ts, old_ts))

    with NewsDB(str(db_path), use_bloom=False) as db:
        db.init()
    with NewsDB(str(db_path), use_bloom=False) as db:
        rid = db.add_article(make_article(source_url="https://e.com/x"))
        db.connect().execute(
            "UPDATE news_articles SET discovered_at = '2024-01-01T00:00:00' "
            "WHERE id = ?", (rid,)
        )

        result = prune(
            db, RetentionConfig(unplayed_days=365, daily_dir_days=30),
            daily_root=daily_root,
            now=datetime(2026, 4, 30, tzinfo=timezone.utc),
        )

    assert result["unplayed"] == 1
    assert result["files_removed"] == 1
