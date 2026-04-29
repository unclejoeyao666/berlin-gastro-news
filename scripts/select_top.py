#!/usr/bin/env python3
"""Select top N unplayed articles for the daily briefing.

Two-step quota selection:
  1. Up to ``--gastro`` slots from tier-1 gastro sources.
  2. Up to ``--keyword`` slots from generic sources whose title/summary
     trips a gastro keyword.
  3. Up to ``--general`` slots from remaining unplayed news, capped at
     a few per source so a single feed can't dominate.

Outputs ``daily-selected.json`` with a per-article ``_pool`` label so
the translation step can see *why* something was picked.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.news_db import NewsDB
from scripts.lib import relevance

DB_PATH = ROOT / "data" / "news.db"
OUT_PATH = ROOT / "daily-selected.json"


GASTRO_KEYWORDS_LIKE = (
    # SQL pre-filter: cheap %LIKE% match. Avoid stems that overlap with
    # generic German words (e.g. "wirt" inside "Wirtschaft", "berlin"
    # inside any Berlin politics piece) — those are caught after the
    # SQL pull by ``relevance.is_gastro_relevant``.
    "gastronomie", "gastgewerbe", "restaurant", "café",
    "gaststätte", "gaststaette", "hotellerie", "hotelgewerbe",
    "kantine", "betriebsgastronomie", "imbiss", "biergarten",
    "wirtshaus", "lebensmittel", "lebensmittelhandel",
    "dehoga", "ahgz", "iha",
    "bäcker", "baecker", "bäckerei", "metzger", "fleischer",
    "konditor", "brauerei",
    "mehrwertsteuer", "mindestlohn", "tarifvertrag",
    "speisen", "getränke", "getraenke", "speisekarte",
    "tourismusbranche", "beherbergung",
    "zuckerabgabe", "zuckersteuer", "tierhaltungskennzeichnung",
    "lebensmittelsicherheit", "lebensmittelhygiene",
)

KEYWORD_BLOCKED = ("scmp", "dw-en", "politico-eu", "euobserver")


def row_to_dict(row, pool: str) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "summary": row["summary"],
        "source_id": row["source_id"],
        "source_name": row["source_name"],
        "source_name_cn": row["source_name_cn"],
        "source_url": row["source_url"],
        "published_at": row["published_at"],
        "lang": row["lang"],
        "source_categories": json.loads(row["source_categories"] or "[]"),
        "importance": row["importance"],
        "_pool": pool,
        "_translated": False,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--gastro", type=int, default=5,
                   help="Min slots from tier-1 gastro sources")
    p.add_argument("--keyword", type=int, default=3,
                   help="Min slots from keyword-matched generic sources")
    p.add_argument("--general", type=int, default=2,
                   help="Min slots for general unplayed fill")
    p.add_argument("--recency-days", type=int, default=7,
                   help="Only consider articles published within N days")
    p.add_argument("--out", default=str(OUT_PATH))
    args = p.parse_args()

    if args.gastro + args.keyword + args.general < args.count:
        # Allow under-allocation; callers can pass --count larger to test.
        # Otherwise, top them up onto general.
        args.general += args.count - (args.gastro + args.keyword + args.general)

    with NewsDB(str(DB_PATH)) as db:
        # Over-fetch general so we have something to backfill with after
        # the keyword post-filter drops false positives.
        pools = db.get_unplayed_by_quota(
            gastro_quota=args.gastro,
            keyword_quota=args.keyword,
            general_quota=args.general + args.keyword,  # extra slack
            gastro_sources=list(relevance.GASTRO_TIER1_SOURCES),
            keywords=GASTRO_KEYWORDS_LIKE,
            keyword_blocked_sources=KEYWORD_BLOCKED,
            recency_days=args.recency_days,
        )

    # Confirm keyword-pool hits with the relevance check — drops false
    # positives (e.g. an article whose only LIKE-match is a substring
    # like ``hotel`` inside a brand name).
    keyword_confirmed = []
    for r in pools["keyword"]:
        ok, _, _ = relevance.is_gastro_relevant(
            r["source_id"], r["title"], r["summary"], r["lang"] or "de",
        )
        if ok:
            keyword_confirmed.append(r)

    selected: list[dict] = []
    for r in pools["gastro"]:
        selected.append(row_to_dict(r, "gastro"))
        if len(selected) >= args.count:
            break
    for r in keyword_confirmed:
        if len(selected) >= args.count:
            break
        selected.append(row_to_dict(r, "keyword"))
    for r in pools["general"]:
        if len(selected) >= args.count:
            break
        selected.append(row_to_dict(r, "general"))

    if not selected:
        print("⚠️  no unplayed articles", file=sys.stderr)
        sys.exit(0)

    diagnostics = {
        "gastro_count": sum(1 for a in selected if a["_pool"] == "gastro"),
        "keyword_count": sum(1 for a in selected if a["_pool"] == "keyword"),
        "general_count": sum(1 for a in selected if a["_pool"] == "general"),
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "selected_at": datetime.now(timezone.utc).isoformat(),
            "count": len(selected),
            "diagnostics": diagnostics,
            "articles": selected,
        }, f, ensure_ascii=False, indent=2)

    print(f"✅ selected {len(selected)} → {args.out}")
    print(f"   pools: gastro={diagnostics['gastro_count']} "
          f"keyword={diagnostics['keyword_count']} "
          f"general={diagnostics['general_count']}")
    if diagnostics["gastro_count"] < args.gastro:
        print(f"⚠️  WARN: only {diagnostics['gastro_count']} gastro-source "
              f"articles (target {args.gastro}). "
              f"Check RSS health: ahgz-gastro / dehoga-berlin / bmel.",
              file=sys.stderr)
    for i, a in enumerate(selected, 1):
        marker = {
            "gastro": "🍽️ ",
            "keyword": "🔎 ",
            "general": "  ",
        }[a["_pool"]]
        print(f"  [{i:2d}] {marker} imp={a['importance']:3d} | "
              f"{(a['source_name_cn'] or a['source_name'])[:24]:24s} | "
              f"{a['title'][:60]}")


if __name__ == "__main__":
    main()
