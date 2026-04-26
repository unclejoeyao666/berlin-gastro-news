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
        rid1 = db.add_article(make_article(title="t1", source_url="https://e.com/1"))
        db.update_translation(
            rid1, "ct1", "cs1", "cb1", "ia1",
            ["gastro-law"], "slug-t1-2026-04-26",
        )
        # Add rid3 with translation but no slug
        rid3 = db.add_article(make_article(title="t3", source_url="https://e.com/3"))
        db.connect().execute(
            "UPDATE news_articles SET translated_body = 'body3' WHERE id = ?",
            (rid3,),
        )
        pending = db.get_articles_pending_publication()
        assert len(pending) == 1
        assert pending[0]["id"] == rid3


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
