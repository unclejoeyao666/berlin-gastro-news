#!/usr/bin/env python3
"""One-shot migration: archive/v1/news-db.json → data/news.db.

Idempotent: re-runs are safe (uses URL/hash dedupe).
Marks v1 'presented=true' items as 'played'.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.news_db import NewsDB

V1_JSON = ROOT / "archive" / "v1" / "news-db.json"
DB_PATH = ROOT / "data" / "news.db"


def main():
    if not V1_JSON.exists():
        print(f"❌ not found: {V1_JSON}")
        sys.exit(1)
    with open(V1_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("items", [])
    print(f"📂 v1 items: {len(items)}")

    stats = {"new": 0, "dup": 0, "marked_played": 0}
    with NewsDB(str(DB_PATH)) as db:
        conn = db.connect()
        for item in items:
            article = {
                "title": item.get("title", ""),
                "summary": item.get("summary", ""),
                "source_id": item.get("source_id"),
                "source_name": item.get("source_name", "Unknown"),
                "source_name_cn": item.get("source_name_cn"),
                "source_url": item.get("url"),
                "published_at": item.get("published"),
                "lang": item.get("lang", "de"),
                "source_categories": item.get("categories", []),
                "importance": item.get("priority", 0),
            }
            if not article["title"]:
                continue
            rid = db.add_article(article)
            if rid:
                stats["new"] += 1
                if item.get("presented"):
                    presented_at = (item.get("presented_at") or "")[:10] or "2026-01-01"
                    conn.execute("""
                        UPDATE news_articles
                           SET broadcast_status='played', broadcast_date=?
                         WHERE id=?
                    """, (presented_at, rid))
                    stats["marked_played"] += 1
            else:
                stats["dup"] += 1
        s = db.stats()

    print(f"✅ migrated: new={stats['new']} dup={stats['dup']} played={stats['marked_played']}")
    print(f"📦 DB: total={s['total_articles']} unplayed={s['unplayed']} played={s['played']}")


if __name__ == "__main__":
    main()
