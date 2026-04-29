from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from scripts.lib.news_db import NewsDB, BloomFilter  # noqa: E402


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    with NewsDB(str(db_path), use_bloom=False) as db:
        db.init()
    return str(db_path)


def make_article(**overrides):
    base = {
        "title": "Test article",
        "summary": "Short summary.",
        "content": "Full content.",
        "source_id": "test-source",
        "source_name": "Test Source",
        "source_url": "https://example.com/article-1",
        "published_at": "2026-04-26T08:00:00Z",
        "lang": "de",
        "importance": 5,
    }
    base.update(overrides)
    return base


def test_make_hash_deterministic():
    h1 = NewsDB.make_hash("Title", "Source")
    h2 = NewsDB.make_hash("Title", "Source")
    assert h1 == h2 and len(h1) == 64


def test_make_hash_different_inputs():
    assert NewsDB.make_hash("A", "S") != NewsDB.make_hash("B", "S")
    assert NewsDB.make_hash("A", "S1") != NewsDB.make_hash("A", "S2")


def test_init_creates_tables(tmp_db):
    with NewsDB(tmp_db) as db:
        rows = db.connect().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {r[0] for r in rows}
        assert {"sources", "news_articles", "broadcast_log"}.issubset(names)


def test_add_article_then_dedupe(tmp_db):
    with NewsDB(tmp_db) as db:
        rid = db.add_article(make_article())
        assert rid is not None
        # Same title + source = dup
        assert db.add_article(make_article()) is None


def test_url_normalization_dedupes_across_tracking_params(tmp_db):
    with NewsDB(tmp_db) as db:
        a1 = make_article(source_url="https://example.com/x?utm_source=a")
        a2 = make_article(title="Different Title",
                          source_url="https://example.com/x?utm_source=b")
        assert db.add_article(a1) is not None
        # Different title but same normalized URL → dedupe
        assert db.add_article(a2) is None


def test_get_unplayed_orders_by_importance(tmp_db):
    with NewsDB(tmp_db) as db:
        db.add_article(make_article(title="low", source_url="https://e.com/1", importance=1))
        db.add_article(make_article(title="high", source_url="https://e.com/2", importance=9))
        rows = db.get_unplayed(limit=10)
        assert rows[0]["title"] == "high"


def test_update_translation_and_mark_played(tmp_db):
    with NewsDB(tmp_db) as db:
        rid = db.add_article(make_article(source_url="https://e.com/1"))
        db.update_translation(
            rid,
            translated_title="中译标题",
            translated_summary="摘要",
            translated_body="正文",
            impact_analysis="影响",
            industry_tags=["gastro-law", "berlin-local"],
            slug="test-slug-2026-04-26",
        )
        db.mark_played([rid], briefing_date="2026-04-26")
        row = db.get_by_id(rid)
        assert row["translated_title"] == "中译标题"
        assert row["broadcast_status"] == "played"
        assert row["slug"] == "test-slug-2026-04-26"
        assert json.loads(row["industry_tags"]) == ["gastro-law", "berlin-local"]


def test_get_articles_pending_publication(tmp_db):
    with NewsDB(tmp_db) as db:
        # Article without translation → not pending
        rid1 = db.add_article(make_article(title="t1", source_url="https://e.com/1"))
        # Article with translation → pending
        rid2 = db.add_article(make_article(title="t2", source_url="https://e.com/2"))
        db.update_translation(
            rid2, "ct2", "cs2", "cb2", "ia2",
            ["gastro-law"], "slug-t2-2026-04-26",
        )
        pending = db.get_articles_pending_publication()
        ids = [r["id"] for r in pending]
        assert rid2 in ids
        assert rid1 not in ids


def test_import_sources_json(tmp_db, tmp_path):
    sources = {
        "sources": [
            {"id": "s1", "name": "Src One", "feed_url": "https://e.com/1.rss",
             "tier": 1, "lang": "de", "categories": ["a", "b"], "active": True},
            {"id": "s2", "name": "Src Two", "feed_url": "https://e.com/2.rss",
             "tier": 2, "lang": "en", "categories": [], "active": False},
        ]
    }
    p = tmp_path / "sources.json"
    p.write_text(json.dumps(sources), encoding="utf-8")
    with NewsDB(tmp_db) as db:
        stats = db.import_sources(str(p))
        assert stats["imported"] == 2
        active = db.get_active_sources()
        assert len(active) == 1
        assert active[0]["source_id"] == "s1"


def test_bloom_filter_basic():
    bf = BloomFilter(size=1024, hashes=4)
    bf.add("hello")
    assert "hello" in bf
    assert "world" not in bf  # unlikely false positive at this scale


# ── url_seen ledger ────────────────────────────────────


def test_make_url_hash_deterministic():
    h1 = NewsDB.make_url_hash("https://example.com/x")
    h2 = NewsDB.make_url_hash("https://example.com/x")
    assert h1 == h2 and len(h1) == 64
    assert NewsDB.make_url_hash("a") != NewsDB.make_url_hash("b")


def test_add_article_writes_url_seen(tmp_db):
    with NewsDB(tmp_db) as db:
        rid = db.add_article(make_article(source_url="https://example.com/x"))
        assert rid is not None
        url_hash = db.make_url_hash("https://example.com/x")
        assert db.is_url_seen(url_hash) is True


def test_is_url_seen_falls_back_to_title_hash(tmp_db):
    with NewsDB(tmp_db) as db:
        title_hash = db.make_hash("My Title", "Source")
        db.record_url_seen(
            url_hash="abc123",
            title_hash=title_hash,
            source_id="test-source",
        )
        # Lookup by title_hash succeeds even when url_hash is unknown
        assert db.is_url_seen(url_hash=None, title_hash=title_hash) is True


def test_record_url_seen_idempotent(tmp_db):
    with NewsDB(tmp_db) as db:
        first = db.record_url_seen("hash-1", "th-1", "src")
        second = db.record_url_seen("hash-1", "th-1", "src")
        assert first is True
        assert second is False


def test_record_url_seen_skips_when_no_url_hash(tmp_db):
    with NewsDB(tmp_db) as db:
        assert db.record_url_seen(url_hash=None, title_hash="th") is False


def test_record_url_seen_batch(tmp_db):
    with NewsDB(tmp_db) as db:
        rows = [
            {"url_hash": "h1", "title_hash": "t1", "source_id": "s1"},
            {"url_hash": "h2", "title_hash": "t2", "source_id": "s1"},
            {"url_hash": None, "title_hash": "t3"},  # skipped
        ]
        n = db.record_url_seen_batch(rows)
        assert n == 2


def test_dedup_via_url_seen_after_article_pruned(tmp_db):
    """The ledger must outlive aging — once url_seen knows a URL, future
    harvests skip it even if the news_articles row is gone."""
    with NewsDB(tmp_db) as db:
        rid = db.add_article(make_article(source_url="https://example.com/x"))
        url_hash = db.make_url_hash("https://example.com/x")

        # Simulate aging deleting the article row.
        db.connect().execute("DELETE FROM news_articles WHERE id = ?", (rid,))

        # Article gone, but url_seen retains the dedup signal.
        assert db.connect().execute(
            "SELECT COUNT(*) FROM news_articles"
        ).fetchone()[0] == 0
        assert db.is_url_seen(url_hash) is True


# ── pruning ────────────────────────────────────────────


def test_prune_articles_unplayed_cutoff(tmp_db):
    with NewsDB(tmp_db) as db:
        conn = db.connect()
        # Insert two unplayed articles with explicit discovered_at.
        db.add_article(make_article(title="old", source_url="https://e.com/old"))
        db.add_article(make_article(title="new", source_url="https://e.com/new"))
        conn.execute(
            "UPDATE news_articles SET discovered_at = '2025-01-01T00:00:00' "
            "WHERE title = 'old'"
        )
        conn.execute(
            "UPDATE news_articles SET discovered_at = '2026-04-29T00:00:00' "
            "WHERE title = 'new'"
        )

        counts = db.prune_articles(unplayed_cutoff="2025-06-01T00:00:00")
        assert counts["unplayed"] == 1
        rows = conn.execute(
            "SELECT title FROM news_articles ORDER BY title"
        ).fetchall()
        assert [r["title"] for r in rows] == ["new"]


def test_prune_articles_skips_played_when_cutoff_none(tmp_db):
    with NewsDB(tmp_db) as db:
        rid = db.add_article(make_article(source_url="https://e.com/x"))
        db.update_translation(rid, "ct", "cs", "cb", "ia", ["gastro-law"], "slug-x")
        db.mark_played([rid], briefing_date="2025-01-01")

        # played_cutoff=None → played articles untouched
        counts = db.prune_articles(
            played_cutoff=None,
            unplayed_cutoff="2030-01-01T00:00:00",
            archived_cutoff="2030-01-01T00:00:00",
        )
        assert counts["played"] == 0
        n = db.connect().execute("SELECT COUNT(*) FROM news_articles").fetchone()[0]
        assert n == 1


def test_prune_articles_archived_cutoff(tmp_db):
    with NewsDB(tmp_db) as db:
        rid_old = db.add_article(make_article(
            title="old-arch", source_url="https://e.com/old"
        ))
        rid_new = db.add_article(make_article(
            title="new-arch", source_url="https://e.com/new"
        ))
        db.quarantine([rid_old, rid_new], reason="test")
        db.connect().execute(
            "UPDATE news_articles SET discovered_at = '2025-01-01T00:00:00' "
            "WHERE id = ?", (rid_old,)
        )
        db.connect().execute(
            "UPDATE news_articles SET discovered_at = '2026-04-29T00:00:00' "
            "WHERE id = ?", (rid_new,)
        )

        counts = db.prune_articles(archived_cutoff="2026-01-01T00:00:00")
        assert counts["archived"] == 1
        remaining = db.connect().execute(
            "SELECT id FROM news_articles WHERE broadcast_status = 'archived'"
        ).fetchall()
        assert [r["id"] for r in remaining] == [rid_new]


def test_prune_url_seen(tmp_db):
    with NewsDB(tmp_db) as db:
        db.record_url_seen("h-old", "t1", "src", seen_at="2024-01-01T00:00:00")
        db.record_url_seen("h-new", "t2", "src", seen_at="2026-04-29T00:00:00")
        n = db.prune_url_seen(cutoff="2025-06-01T00:00:00")
        assert n == 1
        remaining = db.connect().execute(
            "SELECT url_hash FROM url_seen"
        ).fetchall()
        assert [r["url_hash"] for r in remaining] == ["h-new"]


def test_stats_includes_url_seen(tmp_db):
    with NewsDB(tmp_db) as db:
        db.record_url_seen("h1", "t1", "src")
        db.record_url_seen("h2", "t2", "src")
        s = db.stats()
        assert s["url_seen"] == 2
