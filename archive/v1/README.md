# v1 Archive

Frozen v1 implementation kept for reference and as fallback corpus.

## Contents

- `news-db.json` — v1 JSON news database (3.8 MB). Migrated to `data/news.db` via `scripts/migrate_v1_to_sqlite.py` (3226 articles imported, 110 marked played).
- `fetch_news.py`, `mark_presented.py`, `generate_site.py` — v1 Python scripts. Replaced by `scripts/harvest.py`, `publish_briefing.py`, and the Astro site respectively.
- `master-index.md` — v1 manual dedupe index. Replaced by SQLite UNIQUE constraints + bloom filter.
- `2026/04/<dd>/news_*.md` — v1 hand-curated daily briefings. May be reused as few-shot examples for v2 translation prompts.
- `site/` — v1 handcrafted HTML site (4 pages). Replaced by Astro project at repo root `site/`.
- `selected-today.json`, `curated-today.json` — v1 transient state files.

## Why kept

1. The hand-curated `news_*.md` files are higher-quality reference material than any RSS summary.
2. The v1 scoring/categorization logic in `fetch_news.py` informs the v2 importance algorithm in `scripts/harvest.py`.
3. Rollback safety.

## Do not

- Do not run any v1 script. They will fail because `sources.json` moved to `data/sources.json`.
- Do not write to v1 files. Treat as read-only.
