#!/usr/bin/env python3
"""Harvest RSS feeds → SQLite. Two-phase: fetch + score in memory,
then quota-aware cap before writing to news_articles. Every fetched
URL (kept or dropped) is recorded in url_seen so dedup survives later
aging of news_articles rows.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import feedparser

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.news_db import NewsDB
from scripts.lib.normalize import normalize_url
from scripts.lib.relevance import (
    GASTRO_TIER1_SOURCES,
    GASTRO_TIER2_SOURCES,
    is_gastro_relevant,
)

DB_PATH = ROOT / "data" / "news.db"
DAILY_ROOT = ROOT / "daily"

# Caps — overridable via env for ad-hoc loosening (recovery-playbook
# documents this).
HARVEST_CAP = int(os.getenv("BERLIN_GASTRO_HARVEST_CAP", "25"))
KEYWORD_KEEP = int(os.getenv("BERLIN_GASTRO_KEYWORD_KEEP", "10"))
GENERAL_KEEP = int(os.getenv("BERLIN_GASTRO_GENERAL_KEEP", "5"))

CATEGORY_WEIGHTS = {
    "gastronomie": 22, "hotellerie": 16, "food-safety": 18,
    "berlin": 14, "supply-chain": 8, "hygiene": 8, "agriculture": 6,
    "law": 9, "tax": 9, "business": 7, "economy": 7,
    "regulations": 7, "subsidies": 6, "finance": 5,
    "trade": 6, "china": 5, "asia": 4, "geopolitics": 4, "eu": 4,
    "politics": 2, "health": 3,
    "equipment": 2, "events": 1, "general": 1,
    "international": 1, "management": 1,
}

NOISE_URL_PATTERNS = [
    r"/sen/wirtschaft/(?:konjunktur|gruenden|digitalisierung|startups|"
    r"netzwerk|europa-und-internationales|foerderprogramme|projekte)",
    r"/sen/gesundheit/.*(?:service|angebote)/",
]

BUCKETS = ("gastro_t1", "gastro_t2", "general_keyword", "general_other")


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


def classify_bucket(source_id: str, title: str, summary: str, lang: str) -> str:
    """Return one of BUCKETS for this entry."""
    if source_id in GASTRO_TIER1_SOURCES:
        return "gastro_t1"
    if source_id in GASTRO_TIER2_SOURCES:
        return "gastro_t2"
    relevant, _, _ = is_gastro_relevant(source_id, title, summary, lang)
    return "general_keyword" if relevant else "general_other"


def fetch_candidates(
    db: NewsDB, source_row,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Pull a feed and return (candidates, stats).

    candidates carry their bucket, importance score, and the hashes
    needed for url_seen accounting. Already-seen URLs are filtered out
    here (cheap pre-check before expensive bucketing).
    """
    stats = {
        "fetched": 0, "noise": 0, "seen": 0,
        "candidates": 0, "errors": [],
    }
    candidates: List[Dict[str, Any]] = []

    try:
        feed = feedparser.parse(source_row["feed_url"])
    except Exception as e:
        stats["errors"].append(str(e))
        return candidates, stats
    if feed.bozo and not feed.entries:
        stats["errors"].append(str(getattr(feed, "bozo_exception", "parse error")))
        return candidates, stats

    cats = json.loads(source_row["categories"] or "[]")
    source_id = source_row["source_id"]
    source_name = source_row["name"]
    lang = source_row["lang"]

    for entry in feed.entries:
        stats["fetched"] += 1
        url = entry.get("link", "")
        title = clean_html(entry.get("title", ""))
        summary = clean_html(entry.get("summary", entry.get("description", "")))
        if not title:
            continue
        if is_noise(url, title, summary):
            stats["noise"] += 1
            continue

        url_norm = normalize_url(url) if url else None
        url_hash = NewsDB.make_url_hash(url_norm) if url_norm else None
        title_hash = NewsDB.make_hash(title, source_name)

        if db.is_url_seen(url_hash, title_hash):
            stats["seen"] += 1
            continue

        published = parse_published(entry)
        importance = compute_importance(source_row["tier"], cats, published)
        bucket = classify_bucket(source_id, title, summary, lang)

        candidates.append({
            "title": title,
            "summary": summary[:1000],
            "content": "",
            "source_id": source_id,
            "source_name": source_name,
            "source_name_cn": source_row["name_cn"],
            "source_url": url,
            "published_at": published,
            "lang": lang,
            "source_categories": cats,
            "importance": importance,
            "_url_hash": url_hash,
            "_title_hash": title_hash,
            "_bucket": bucket,
            "_score": importance,
        })
        stats["candidates"] += 1

    db.update_source_fetched(source_id)
    return candidates, stats


def apply_cap(by_bucket: Dict[str, List[Dict[str, Any]]]) -> Tuple[
    List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]
]:
    """Pick keepers from each bucket according to the rules.

    gastro_t1 / gastro_t2 → kept in full
    general_keyword       → top KEYWORD_KEEP by score
    general_other         → top GENERAL_KEEP by score
    Hard cap: HARVEST_CAP overall (sorted by score).

    Returns (keep, dropped, bucket_kept_counts).
    """
    by_score = lambda c: -c["_score"]  # noqa: E731

    keep: List[Dict[str, Any]] = []
    keep += sorted(by_bucket["gastro_t1"], key=by_score)
    keep += sorted(by_bucket["gastro_t2"], key=by_score)
    keep += sorted(by_bucket["general_keyword"], key=by_score)[:KEYWORD_KEEP]
    keep += sorted(by_bucket["general_other"], key=by_score)[:GENERAL_KEEP]

    keep = sorted(keep, key=by_score)[:HARVEST_CAP]
    keep_hashes = {c["_url_hash"] for c in keep if c["_url_hash"]}
    keep_titles = {c["_title_hash"] for c in keep}

    dropped: List[Dict[str, Any]] = []
    for bucket in BUCKETS:
        for c in by_bucket[bucket]:
            if c["_url_hash"] and c["_url_hash"] in keep_hashes:
                continue
            if not c["_url_hash"] and c["_title_hash"] in keep_titles:
                continue
            dropped.append(c)

    bucket_kept = {b: 0 for b in BUCKETS}
    for c in keep:
        bucket_kept[c["_bucket"]] += 1

    return keep, dropped, bucket_kept


def write_harvest_log(
    log_dir: Path,
    per_source_stats: Dict[str, Dict[str, Any]],
    bucket_kept: Dict[str, int],
    bucket_total: Dict[str, int],
    keep: List[Dict[str, Any]],
    dropped: List[Dict[str, Any]],
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / ".harvest.log"

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "caps": {
            "HARVEST_CAP": HARVEST_CAP,
            "KEYWORD_KEEP": KEYWORD_KEEP,
            "GENERAL_KEEP": GENERAL_KEEP,
        },
        "buckets": {
            b: {"total": bucket_total[b], "kept": bucket_kept[b]}
            for b in BUCKETS
        },
        "totals": {
            "kept": len(keep),
            "dropped": len(dropped),
        },
        "per_source": per_source_stats,
        "kept_titles": [
            {
                "title": c["title"],
                "source_id": c["source_id"],
                "score": c["_score"],
                "bucket": c["_bucket"],
            }
            for c in keep
        ],
        "dropped_titles": [
            {
                "title": c["title"],
                "source_id": c["source_id"],
                "score": c["_score"],
                "bucket": c["_bucket"],
            }
            for c in sorted(dropped, key=lambda c: -c["_score"])[:50]
        ],
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return log_path


def daily_log_dir(now: datetime) -> Path:
    return DAILY_ROOT / now.strftime("%Y") / now.strftime("%Y-%m") / now.strftime("%Y-%m-%d")


def main():
    now = datetime.now()
    print(f"📰 Harvest start — {now.isoformat(timespec='seconds')}")
    print(f"   caps: HARVEST_CAP={HARVEST_CAP} "
          f"KEYWORD_KEEP={KEYWORD_KEEP} GENERAL_KEEP={GENERAL_KEEP}")
    print("=" * 60)

    by_bucket: Dict[str, List[Dict[str, Any]]] = {b: [] for b in BUCKETS}
    per_source_stats: Dict[str, Dict[str, Any]] = {}

    with NewsDB(str(DB_PATH)) as db:
        sources = db.get_active_sources()
        for s in sources:
            cands, stats = fetch_candidates(db, s)
            for c in cands:
                by_bucket[c["_bucket"]].append(c)
            per_source_stats[s["source_id"]] = {
                "name": s["name"],
                **{k: v for k, v in stats.items() if k != "errors"},
                "errors": stats["errors"],
            }
            err_str = (
                f" ERR: {stats['errors'][0][:50]}"
                if stats["errors"] else ""
            )
            print(f"  {'❌' if stats['errors'] else '✅'} "
                  f"{s['name']:30s} "
                  f"fetched={stats['fetched']:3d} "
                  f"seen={stats['seen']:3d} "
                  f"noise={stats['noise']:3d} "
                  f"cands={stats['candidates']:3d}{err_str}")
            time.sleep(0.3)

        bucket_total = {b: len(by_bucket[b]) for b in BUCKETS}
        keep, dropped, bucket_kept = apply_cap(by_bucket)

        # Insert keepers (writes article + url_seen on success).
        new_count = 0
        dup_count = 0
        for c in keep:
            article = {
                k: v for k, v in c.items()
                if not k.startswith("_")
            }
            rid = db.add_article(article)
            if rid:
                new_count += 1
            else:
                dup_count += 1

        # Record dropped URLs in url_seen so we don't re-process them
        # tomorrow. Skip those without a url_hash (can't store without
        # the PK).
        ledger_rows = [
            {
                "url_hash": c["_url_hash"],
                "title_hash": c["_title_hash"],
                "source_id": c["source_id"],
            }
            for c in dropped if c["_url_hash"]
        ]
        ledger_added = db.record_url_seen_batch(ledger_rows)

        log_path = write_harvest_log(
            daily_log_dir(now),
            per_source_stats,
            bucket_kept, bucket_total,
            keep, dropped,
        )

        print("=" * 60)
        print(f"📊 Buckets (kept/total): " + "  ".join(
            f"{b}={bucket_kept[b]}/{bucket_total[b]}" for b in BUCKETS
        ))
        print(f"📊 Inserted: new={new_count} dup={dup_count} "
              f"dropped={len(dropped)} ledger+={ledger_added}")
        s = db.stats()
        print(f"📦 DB: total={s['total_articles']} "
              f"unplayed={s['unplayed']} played={s['played']} "
              f"archived={s['archived']} url_seen={s['url_seen']}")
        print(f"📝 log: {log_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
