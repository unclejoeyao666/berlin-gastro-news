#!/usr/bin/env python3
"""Dry-run helper: synthesize plausible translations from RSS data.

Real production translation is done by OpenClaw's Claude session.
This script exists to verify the pipeline end-to-end on day 1.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.news_db import NewsDB

DB_PATH = ROOT / "data" / "news.db"
SELECTED = ROOT / "daily-selected.json"

# Map source_categories → industry_tags (best-effort; real Claude does better)
CAT_TO_TAG = {
    "gastronomie": "gastro-law", "law": "gastro-law", "tax": "tax-finance",
    "food-safety": "hygiene-safety", "hygiene": "hygiene-safety",
    "business": "trends-consumer", "economy": "trends-consumer",
    "berlin": "berlin-local", "trade": "geopolitics-trade",
    "subsidies": "tax-finance", "finance": "tax-finance",
    "china": "geopolitics-trade", "asia": "geopolitics-trade",
    "geopolitics": "geopolitics-trade", "eu": "geopolitics-trade",
    "politics": "geopolitics-trade", "supply-chain": "supply-food",
    "agriculture": "supply-food", "equipment": "digital-tech",
    "hotellerie": "trends-consumer", "events": "events-marketing",
    "regulations": "gastro-law", "management": "digital-tech",
    "international": "geopolitics-trade", "general": "trends-consumer",
    "health": "hygiene-safety",
}
DEFAULT_TAG = "trends-consumer"


def slugify_id(article_id: int, title: str, pub: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower())[:30].strip("-")
    if not base:
        base = f"article-{article_id}"
    return f"{base}-{(pub or '2026-01-01')[:10]}"


def main():
    selected = json.loads(SELECTED.read_text(encoding="utf-8"))
    with NewsDB(str(DB_PATH)) as db:
        for art in selected["articles"]:
            row = db.get_by_id(art["id"])
            if not row:
                continue
            title = row["title"]
            summary = row["summary"] or "暂无摘要。"
            cats = json.loads(row["source_categories"] or "[]")
            tags = []
            for c in cats:
                t = CAT_TO_TAG.get(c)
                if t and t not in tags:
                    tags.append(t)
                if len(tags) >= 3:
                    break
            if not tags:
                tags = [DEFAULT_TAG]

            # Synthetic Chinese title prefix; real Claude would translate.
            zh_title = f"[原文待翻译] {title[:80]}"
            zh_summary = f"[原文待翻译] {summary[:160]}"
            zh_body = (
                f"> 此文为系统冷启动期间的占位内容，实际翻译由 OpenClaw 每日会话产出。\n\n"
                f"**原标题**：{title}\n\n"
                f"**原摘要**：{summary}\n"
            )
            impact = "（占位）后续由 AI 自动写入对柏林餐饮业的具体影响分析。"

            slug = slugify_id(row["id"], title, row["published_at"] or row["discovered_at"])
            db.update_translation(
                article_id=row["id"],
                translated_title=zh_title,
                translated_summary=zh_summary,
                translated_body=zh_body,
                impact_analysis=impact,
                industry_tags=tags,
                slug=slug,
            )
            print(f"  ✅ id={row['id']} tags={tags} slug={slug}")

    print("✅ dry-run translations written")


if __name__ == "__main__":
    main()
