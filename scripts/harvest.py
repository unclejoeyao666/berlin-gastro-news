#!/usr/bin/env python3
"""Harvest RSS feeds → SQLite. No translation, just raw ingestion."""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.news_db import NewsDB

DB_PATH = ROOT / "data" / "news.db"

CATEGORY_WEIGHTS = {
    # Boosted gastro-relevant categories so non-gastro sources can't
    # outscore tier-1 industry feeds purely on volume.
    "gastronomie": 22, "hotellerie": 16, "food-safety": 18,
    "berlin": 14, "supply-chain": 8, "hygiene": 8, "agriculture": 6,
    # Moderate weights for general business / finance / law.
    "law": 9, "tax": 9, "business": 7, "economy": 7,
    "regulations": 7, "subsidies": 6, "finance": 5,
    # Geopolitics: still relevant for trade impact, but downweighted.
    "trade": 6, "china": 5, "asia": 4, "geopolitics": 4, "eu": 4,
    "politics": 2, "health": 3,
    # Truly generic / off-topic categories pinned low.
    "equipment": 2, "events": 1, "general": 1,
    "international": 1, "management": 1,
}

NOISE_URL_PATTERNS = [
    r"/sen/wirtschaft/(?:konjunktur|gruenden|digitalisierung|startups|"
    r"netzwerk|europa-und-internationales|foerderprogramme|projekte)",
    r"/sen/gesundheit/.*(?:service|angebote)/",
]


def clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_published(entry) -> str:
    for field in ("published_parsed", "updated_parsed"):
        t = entry.get(field)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


def is_noise(url: str, title: str, summary: str) -> bool:
    for pat in NOISE_URL_PATTERNS:
        if re.search(pat, url or ""):
            return True
    if len(title) < 10 and not summary:
        return True
    return False


def compute_importance(source_tier: int, categories, published_iso: str) -> int:
    score = 0
    score += (3 - source_tier) * 20
    for c in categories or []:
        score += CATEGORY_WEIGHTS.get(c, 0)
    try:
        pub = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
        hours_old = (datetime.now(timezone.utc) - pub).total_seconds() / 3600
        if hours_old < 24:
            score += 15
        elif hours_old < 48:
            score += 10
        elif hours_old < 72:
            score += 5
    except Exception:
        pass
    return min(score, 100)


def harvest_source(db: NewsDB, source_row) -> dict:
    stats = {"new": 0, "dup": 0, "noise": 0, "error": None}
    try:
        feed = feedparser.parse(source_row["feed_url"])
        if feed.bozo and not feed.entries:
            stats["error"] = str(getattr(feed, "bozo_exception", "parse error"))
            return stats
        cats = json.loads(source_row["categories"] or "[]")
        for entry in feed.entries:
            url = entry.get("link", "")
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", entry.get("description", "")))
            if not title:
                continue
            if is_noise(url, title, summary):
                stats["noise"] += 1
                continue
            published = parse_published(entry)
            importance = compute_importance(source_row["tier"], cats, published)
            article = {
                "title": title,
                "summary": summary[:1000],
                "content": "",
                "source_id": source_row["source_id"],
                "source_name": source_row["name"],
                "source_name_cn": source_row["name_cn"],
                "source_url": url,
                "published_at": published,
                "lang": source_row["lang"],
                "source_categories": cats,
                "importance": importance,
            }
            rid = db.add_article(article)
            if rid:
                stats["new"] += 1
            else:
                stats["dup"] += 1
        db.update_source_fetched(source_row["source_id"])
    except Exception as e:
        stats["error"] = str(e)
    return stats


def main():
    print(f"📰 Harvest start — {datetime.now().isoformat(timespec='seconds')}")
    print("=" * 60)
    with NewsDB(str(DB_PATH)) as db:
        sources = db.get_active_sources()
        totals = {"new": 0, "dup": 0, "noise": 0, "errors": 0}
        for s in sources:
            stats = harvest_source(db, s)
            totals["new"] += stats["new"]
            totals["dup"] += stats["dup"]
            totals["noise"] += stats["noise"]
            if stats["error"]:
                totals["errors"] += 1
                print(f"  ❌ {s['name']:30s} error: {stats['error'][:60]}")
            else:
                print(f"  ✅ {s['name']:30s} new={stats['new']:3d} dup={stats['dup']:3d} noise={stats['noise']:3d}")
            time.sleep(0.3)
        print("=" * 60)
        print(f"📊 Total: new={totals['new']} dup={totals['dup']} noise={totals['noise']} errors={totals['errors']}")
        s = db.stats()
        print(f"📦 DB: total={s['total_articles']} unplayed={s['unplayed']} played={s['played']}")


if __name__ == "__main__":
    main()
