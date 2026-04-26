# Berlin Gastro News v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace v1 (handcrafted Python HTML + 3.8 MB JSON) with a production-grade pipeline: SQLite-backed news DB, Astro static site on GitHub Pages, 12-tag industry taxonomy, daily TTS audio, and a stable file-package handoff for OpenClaw.

**Architecture:** Single repo `unclejoeyao666/berlin-gastro-news`. `data/news.db` (SQLite + bloom + FTS5, ported from ai-daily-news) is the source of truth. `scripts/` are deterministic Python helpers OpenClaw calls. `site/` is an Astro project (pattern from CashCow seo-site) deployed to GH Pages by `actions/deploy-pages@v4`. `daily/<YYYY-MM-DD>/` is the OpenClaw pickup contract. Translation/curation happens in OpenClaw's Claude session, not by API.

**Tech Stack:** Python 3.11+ (stdlib + feedparser), SQLite + FTS5, Astro 6 + @astrojs/mdx + @astrojs/sitemap + @astrojs/rss, Node 22, Microsoft Edge TTS via existing `minimax_tts.py`, GitHub Actions.

**Reference projects:** `/Users/unclejoe/Dev_Workspace/CashCow/seo-site` (Astro + GH Pages pattern), `/Users/unclejoe/Media_Workspace/ai-daily-news/db` (SQLite + bloom + FTS5 + harvest pattern).

---

## Phase 0: Repository Bootstrap

### Task 0.1: Archive v1 artifacts

**Files:**
- Move: `news-db.json`, `curated-today.json`, `selected-today.json`, `master-index.md`, `fetch_news.py`, `generate_site.py`, `mark_presented.py`, `2026/`, `site/`, `__pycache__/` → `archive/v1/`

- [ ] **Step 1: Create archive dir and move v1 files**

```bash
cd /Users/unclejoe/Media_Workspace/berlin-gastro-news
mkdir -p archive/v1
mv news-db.json curated-today.json selected-today.json master-index.md \
   fetch_news.py generate_site.py mark_presented.py \
   2026 site __pycache__ archive/v1/ 2>/dev/null || true
ls -la
```

Expected: root contains only `archive/`, `docs/`, `sources.json`, `README.md`, `.git/`.

- [ ] **Step 2: Move sources.json to data/ (it's reused, not archived)**

```bash
mkdir -p data
mv sources.json data/sources.json
```

- [ ] **Step 3: Write top-level .gitignore**

Create `.gitignore`:

```gitignore
# Python
__pycache__/
*.pyc
*.pyo
.venv/
.pytest_cache/

# SQLite WAL/SHM (db file itself IS tracked)
data/news.db-shm
data/news.db-wal

# Astro
site/node_modules/
site/dist/
site/.astro/

# Intermediate state
daily-selected.json
*.tmp.txt

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 4: Update README**

Replace `README.md`:

```markdown
# Berlin Gastro News

每日柏林餐饮商业新闻自动播报系统 — 抓取 → 翻译 → 站点发布 → 音频 → Discord。

**站点**：https://unclejoeyao666.github.io/berlin-gastro-news/
**架构设计**：[docs/superpowers/specs/2026-04-26-berlin-gastro-news-v2-design.md](docs/superpowers/specs/2026-04-26-berlin-gastro-news-v2-design.md)
**每日工作流**：[workflows/DAILY_WORKFLOW.md](workflows/DAILY_WORKFLOW.md)

## 项目结构

```
data/         SQLite 新闻数据库 + RSS 源
scripts/      Python 流水线脚本
site/         Astro 静态站点
daily/        每日成品文件包（briefing.md / audio_script.md / audio.mp3 / meta.json）
docs/         设计文档与执行计划
archive/v1/   v1 历史代码与数据
```

## 运行方式

由本地 OpenClaw 每天 06:00 (Berlin) 触发，按 `workflows/DAILY_WORKFLOW.md` 7 步流水线执行。

## License

私人项目，未授权第三方使用。
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: archive v1 artifacts and bootstrap v2 layout

Move v1 Python scripts, JSON DB, handcrafted HTML site, and dated
news markdown into archive/v1/. Move sources.json to data/. Establish
v2 root structure (data/, scripts/, site/, daily/, archive/v1/).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 0.2: Create remote repo and push

**Files:** none

- [ ] **Step 1: Create GitHub repo via gh CLI**

```bash
cd /Users/unclejoe/Media_Workspace/berlin-gastro-news
gh repo create unclejoeyao666/berlin-gastro-news --public \
  --description "Berlin gastro industry daily news briefing — auto-translated, tagged, with audio." \
  --source=. --remote=origin
```

Expected: prints `https://github.com/unclejoeyao666/berlin-gastro-news`.

- [ ] **Step 2: Push initial state**

```bash
git push -u origin main
```

Expected: branch tracks `origin/main`.

- [ ] **Step 3: Verify**

```bash
gh repo view unclejoeyao666/berlin-gastro-news --json name,url,visibility
```

Expected: shows `"visibility": "PUBLIC"`.

---

## Phase 1: Data Layer (SQLite)

### Task 1.1: Port SQLite schema

**Files:**
- Create: `data/schema.sql`

- [ ] **Step 1: Write schema.sql**

Create `data/schema.sql` (extends ai-daily-news schema with translation columns):

```sql
-- Berlin Gastro News v2 schema
-- SQLite 3 + FTS5

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       TEXT NOT NULL UNIQUE,    -- stable string ID from sources.json
    name            TEXT NOT NULL,
    name_cn         TEXT,
    feed_url        TEXT NOT NULL,
    type            TEXT NOT NULL DEFAULT 'rss',
    lang            TEXT NOT NULL DEFAULT 'de',
    tier            INTEGER NOT NULL DEFAULT 2,
    categories      TEXT,                    -- JSON array
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_fetched    TEXT,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS news_articles (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    title                    TEXT NOT NULL,
    summary                  TEXT,
    content                  TEXT,
    source_id                TEXT REFERENCES sources(source_id) ON DELETE SET NULL,
    source_name              TEXT NOT NULL,
    source_name_cn           TEXT,
    source_url               TEXT,
    url_normalized           TEXT,
    published_at             TEXT,
    discovered_at            TEXT NOT NULL DEFAULT (datetime('now')),
    story_hash               TEXT NOT NULL,
    lang                     TEXT NOT NULL DEFAULT 'de',
    source_categories        TEXT,                  -- JSON array (from sources.json)
    importance               INTEGER NOT NULL DEFAULT 0,
    broadcast_status         TEXT NOT NULL DEFAULT 'unplayed',  -- unplayed/played/archived
    broadcast_date           TEXT,

    -- v2 additions: translation + tagging + slug
    translated_title         TEXT,
    translated_summary       TEXT,
    translated_body          TEXT,
    impact_analysis          TEXT,
    industry_tags            TEXT,                  -- JSON array of tag slugs
    slug                     TEXT,
    published_briefing_date  TEXT,

    raw_json                 TEXT,
    CONSTRAINT uq_story_hash UNIQUE (story_hash)
);

CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
    title,
    summary,
    content,
    translated_title,
    translated_body,
    content='news_articles',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 1'
);

CREATE TRIGGER IF NOT EXISTS news_articles_ai AFTER INSERT ON news_articles BEGIN
    INSERT INTO news_fts(rowid, title, summary, content, translated_title, translated_body)
    VALUES (new.id, new.title, new.summary, new.content, new.translated_title, new.translated_body);
END;

CREATE TRIGGER IF NOT EXISTS news_articles_ad AFTER DELETE ON news_articles BEGIN
    INSERT INTO news_fts(news_fts, rowid, title, summary, content, translated_title, translated_body)
    VALUES ('delete', old.id, old.title, old.summary, old.content, old.translated_title, old.translated_body);
END;

CREATE TRIGGER IF NOT EXISTS news_articles_au AFTER UPDATE ON news_articles BEGIN
    INSERT INTO news_fts(news_fts, rowid, title, summary, content, translated_title, translated_body)
    VALUES ('delete', old.id, old.title, old.summary, old.content, old.translated_title, old.translated_body);
    INSERT INTO news_fts(rowid, title, summary, content, translated_title, translated_body)
    VALUES (new.id, new.title, new.summary, new.content, new.translated_title, new.translated_body);
END;

CREATE TABLE IF NOT EXISTS broadcast_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    broadcast_date  TEXT NOT NULL UNIQUE,
    article_ids     TEXT NOT NULL,
    article_count   INTEGER NOT NULL DEFAULT 0,
    briefing_url    TEXT,
    audio_url       TEXT,
    audio_path      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_articles_status ON news_articles(broadcast_status);
CREATE INDEX IF NOT EXISTS idx_articles_hash ON news_articles(story_hash);
CREATE INDEX IF NOT EXISTS idx_articles_pub ON news_articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_disc ON news_articles(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_unplayed_queue
    ON news_articles(broadcast_status, importance DESC, discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_url_norm
    ON news_articles(url_normalized) WHERE url_normalized IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_slug
    ON news_articles(slug) WHERE slug IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_articles_briefing
    ON news_articles(published_briefing_date) WHERE published_briefing_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources(enabled);

PRAGMA user_version = 2;
```

- [ ] **Step 2: Verify schema is valid SQLite**

```bash
sqlite3 /tmp/test.db < data/schema.sql
sqlite3 /tmp/test.db ".schema sources" | head -5
sqlite3 /tmp/test.db "PRAGMA user_version;"
rm /tmp/test.db
```

Expected: schema dumps without error; `user_version = 2`.

- [ ] **Step 3: Commit**

```bash
git add data/schema.sql .gitignore
git commit -m "data: add SQLite schema with FTS5 and v2 translation columns"
```

---

### Task 1.2: Port news_db.py and url normalization

**Files:**
- Create: `scripts/lib/__init__.py`
- Create: `scripts/lib/normalize.py`
- Create: `scripts/lib/news_db.py`
- Create: `scripts/lib/test_normalize.py`
- Create: `scripts/lib/test_news_db.py`

- [ ] **Step 1: Write failing tests for normalize_url**

Create `scripts/lib/test_normalize.py`:

```python
import pytest
from scripts.lib.normalize import normalize_url, sanitize_for_tts

def test_strips_utm_params():
    url = "https://example.com/article?utm_source=newsletter&utm_medium=email&id=42"
    assert normalize_url(url) == "https://example.com/article?id=42"

def test_strips_fbclid():
    url = "https://example.com/x?fbclid=abc123"
    assert normalize_url(url) == "https://example.com/x"

def test_drops_fragment():
    assert normalize_url("https://example.com/x#section-2") == "https://example.com/x"

def test_strips_trailing_slash():
    assert normalize_url("https://example.com/x/") == "https://example.com/x"

def test_strips_index_html():
    assert normalize_url("https://example.com/x/index.html") == "https://example.com/x"

def test_returns_none_for_invalid():
    assert normalize_url(None) is None
    assert normalize_url("") is None
    assert normalize_url("abc") is None

def test_preserves_real_query_params():
    url = "https://example.com/x?id=42&page=3"
    assert normalize_url(url) == "https://example.com/x?id=42&page=3"

def test_sanitize_for_tts_strips_markdown_headers():
    text = "# Title\n## Subtitle\nBody."
    assert "#" not in sanitize_for_tts(text)

def test_sanitize_for_tts_strips_urls():
    text = "See https://example.com for details."
    out = sanitize_for_tts(text)
    assert "https://" not in out
    assert "details" in out

def test_sanitize_for_tts_strips_markdown_emphasis():
    text = "This is **bold** and *italic*."
    out = sanitize_for_tts(text)
    assert "**" not in out and "*" not in out
    assert "bold" in out and "italic" in out

def test_sanitize_for_tts_normalizes_dashes():
    text = "Line one — line two."
    out = sanitize_for_tts(text)
    assert "—" not in out
```

Create `scripts/lib/__init__.py` (empty).

- [ ] **Step 2: Run tests; expect import errors / failures**

```bash
cd /Users/unclejoe/Media_Workspace/berlin-gastro-news
python3 -m pytest scripts/lib/test_normalize.py -v 2>&1 | head -20
```

Expected: ModuleNotFoundError for `scripts.lib.normalize`.

- [ ] **Step 3: Implement normalize.py**

Create `scripts/lib/normalize.py`:

```python
"""URL and text normalization helpers."""
import re
from typing import Optional

_TRACKING_RE = re.compile(
    r'(?:^|&)(?:utm_source|utm_medium|utm_campaign|utm_term|utm_content|'
    r'fbclid|gclid|gclsrc|dclid|msclkid|twclid|ref|igshid|share_id|si|'
    r'mc_cid|mc_eid|oly_enc_id|vero_id|__s|ss|s_kwcid|assetType|'
    r'mkt_tok|trk|nr_email_referer|ml_sub|ml_eid|wickedid)=[^&]*',
    re.IGNORECASE,
)
_INDEX_RE = re.compile(r'/(?:index|default|home)\.html?$', re.IGNORECASE)


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Strip tracking params, fragment, trailing slash, index.html."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if len(url) < 12 or not url.startswith(('http://', 'https://')):
        return None
    # Drop fragment
    url = url.split('#', 1)[0]
    # Split path?query
    if '?' in url:
        path, query = url.split('?', 1)
        # Remove tracking params
        cleaned = _TRACKING_RE.sub('', query)
        cleaned = cleaned.lstrip('&')
        url = path + ('?' + cleaned if cleaned else '')
    # Strip /index.html etc
    url = _INDEX_RE.sub('', url)
    # Strip trailing slash (but keep root)
    if url.count('/') > 2 and url.endswith('/'):
        url = url[:-1]
    return url if len(url) >= 12 else None


_MD_HEADER_RE = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_MD_EMPHASIS_RE = re.compile(r'(\*\*|__|\*|_|`)')
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\([^)]+\)')
_URL_RE = re.compile(r'https?://\S+')
_HR_RE = re.compile(r'^[\-\*=]{3,}\s*$', re.MULTILINE)
_TABLE_PIPE_RE = re.compile(r'\s*\|\s*')

_TTS_REPLACEMENTS = {
    '—': '，',
    '–': '，',
    '·': '，',
    '…': '。',
    '"': '"',
    '"': '"',
    ''': "'",
    ''': "'",
    '《': '',
    '》': '',
    '【': '',
    '】': '',
}


def sanitize_for_tts(markdown: str) -> str:
    """Convert Markdown body into plain text suitable for TTS."""
    if not markdown:
        return ""
    text = markdown
    # Strip markdown links but keep label text
    text = _MD_LINK_RE.sub(r'\1', text)
    # Strip bare URLs
    text = _URL_RE.sub('', text)
    # Strip headers
    text = _MD_HEADER_RE.sub('', text)
    # Strip horizontal rules
    text = _HR_RE.sub('', text)
    # Strip emphasis markers
    text = _MD_EMPHASIS_RE.sub('', text)
    # Strip table pipes
    text = _TABLE_PIPE_RE.sub('', text)
    # Replace problematic punctuation
    for src, dst in _TTS_REPLACEMENTS.items():
        text = text.replace(src, dst)
    # Collapse whitespace
    text = re.sub(r'\n{2,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()
```

- [ ] **Step 4: Run tests; expect pass**

```bash
python3 -m pytest scripts/lib/test_normalize.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 5: Implement news_db.py**

Create `scripts/lib/news_db.py`:

```python
"""SQLite news DB wrapper for Berlin Gastro News v2.

Ported from /Users/unclejoe/Media_Workspace/ai-daily-news/db/news_db.py
with adaptations for the gastro-news schema (translation columns,
slug uniqueness, source_id as stable string).
"""
import sqlite3
import json
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any, Iterable

from .normalize import normalize_url

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "data" / "schema.sql"


class BloomFilter:
    """Memory-efficient probabilistic dedupe pre-check."""

    def __init__(self, size: int = 1_000_000, hashes: int = 7):
        self.size = size
        self.hashes = hashes
        self.bits = bytearray((size + 7) // 8)
        self.seeds = [i * 31 + 17 for i in range(hashes)]

    def _positions(self, item: str) -> List[int]:
        h = hashlib.sha256(item.encode("utf-8")).hexdigest()
        out = []
        for s in self.seeds:
            hh = hashlib.sha256((h + str(s)).encode()).hexdigest()
            out.append(int(hh, 16) % self.size)
        return out

    def add(self, item: str) -> None:
        for p in self._positions(item):
            self.bits[p // 8] |= 1 << (p % 8)

    def __contains__(self, item: str) -> bool:
        return all(self.bits[p // 8] & (1 << (p % 8)) for p in self._positions(item))

    def load_from_db(self, conn: sqlite3.Connection) -> None:
        for (h,) in conn.execute("SELECT story_hash FROM news_articles"):
            self.add(h)


class NewsDB:
    def __init__(self, db_path: str | Path, use_bloom: bool = True):
        self.db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._bloom: Optional[BloomFilter] = None
        self._use_bloom = use_bloom

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA cache_size=-64000")
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.connect()
        if self._use_bloom:
            self._bloom = BloomFilter()
            self._bloom.load_from_db(self._conn)
        return self

    def __exit__(self, *args):
        self.close()

    def init(self) -> None:
        conn = self.connect()
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

    @staticmethod
    def make_hash(title: str, source_name: str) -> str:
        raw = f"{title.strip()}::{source_name.strip()}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    # ── Sources ────────────────────────────────────────

    def import_sources(self, sources_json_path: str | Path) -> Dict[str, int]:
        conn = self.connect()
        with open(sources_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sources = data.get("sources", data) if isinstance(data, dict) else data
        stats = {"imported": 0, "updated": 0}
        conn.execute("BEGIN")
        try:
            for s in sources:
                row = conn.execute(
                    "SELECT id FROM sources WHERE source_id = ?", (s["id"],)
                ).fetchone()
                cats = json.dumps(s.get("categories", []), ensure_ascii=False)
                if row:
                    conn.execute("""
                        UPDATE sources SET
                            name=?, name_cn=?, feed_url=?, type=?, lang=?,
                            tier=?, categories=?, enabled=?, notes=?
                        WHERE source_id=?
                    """, (
                        s["name"], s.get("name_cn"), s["feed_url"],
                        s.get("type", "rss"), s.get("lang", "de"),
                        s.get("tier", 2), cats,
                        1 if s.get("active", True) else 0,
                        s.get("notes"), s["id"],
                    ))
                    stats["updated"] += 1
                else:
                    conn.execute("""
                        INSERT INTO sources
                            (source_id, name, name_cn, feed_url, type, lang,
                             tier, categories, enabled, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        s["id"], s["name"], s.get("name_cn"), s["feed_url"],
                        s.get("type", "rss"), s.get("lang", "de"),
                        s.get("tier", 2), cats,
                        1 if s.get("active", True) else 0,
                        s.get("notes"),
                    ))
                    stats["imported"] += 1
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return stats

    def get_active_sources(self) -> List[sqlite3.Row]:
        conn = self.connect()
        return conn.execute(
            "SELECT * FROM sources WHERE enabled = 1 ORDER BY tier, source_id"
        ).fetchall()

    def update_source_fetched(self, source_id: str) -> None:
        conn = self.connect()
        conn.execute(
            "UPDATE sources SET last_fetched = ? WHERE source_id = ?",
            (datetime.now(timezone.utc).isoformat(), source_id),
        )

    # ── Articles ───────────────────────────────────────

    def add_article(self, article: Dict[str, Any]) -> Optional[int]:
        """Insert one article. Returns rowid on insert, None on duplicate."""
        conn = self.connect()
        title = article["title"].strip()
        source_name = article["source_name"].strip()
        story_hash = self.make_hash(title, source_name)
        url_norm = normalize_url(article.get("source_url"))

        # URL-first dedupe
        if url_norm:
            row = conn.execute(
                "SELECT id FROM news_articles WHERE url_normalized = ?",
                (url_norm,),
            ).fetchone()
            if row:
                return None

        # Hash dedupe (relies on UNIQUE constraint)
        try:
            cur = conn.execute("""
                INSERT OR IGNORE INTO news_articles
                    (title, summary, content, source_id, source_name, source_name_cn,
                     source_url, url_normalized, published_at, story_hash, lang,
                     source_categories, importance, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                title,
                article.get("summary", ""),
                article.get("content", ""),
                article.get("source_id"),
                source_name,
                article.get("source_name_cn"),
                article.get("source_url"),
                url_norm,
                article.get("published_at"),
                story_hash,
                article.get("lang", "de"),
                json.dumps(article.get("source_categories", []), ensure_ascii=False),
                article.get("importance", 0),
                json.dumps(article.get("raw_json"), ensure_ascii=False)
                if article.get("raw_json") else None,
            ))
            if cur.lastrowid and cur.rowcount > 0:
                if self._bloom:
                    self._bloom.add(story_hash)
                return cur.lastrowid
            return None
        except sqlite3.IntegrityError:
            return None

    def get_unplayed(self, limit: int = 10, min_importance: int = 0) -> List[sqlite3.Row]:
        conn = self.connect()
        return conn.execute("""
            SELECT * FROM news_articles
            WHERE broadcast_status = 'unplayed' AND importance >= ?
            ORDER BY importance DESC, discovered_at DESC
            LIMIT ?
        """, (min_importance, limit)).fetchall()

    def get_by_id(self, article_id: int) -> Optional[sqlite3.Row]:
        conn = self.connect()
        return conn.execute(
            "SELECT * FROM news_articles WHERE id = ?", (article_id,)
        ).fetchone()

    def update_translation(
        self,
        article_id: int,
        translated_title: str,
        translated_summary: str,
        translated_body: str,
        impact_analysis: str,
        industry_tags: List[str],
        slug: str,
    ) -> None:
        conn = self.connect()
        conn.execute("""
            UPDATE news_articles
               SET translated_title = ?,
                   translated_summary = ?,
                   translated_body = ?,
                   impact_analysis = ?,
                   industry_tags = ?,
                   slug = ?
             WHERE id = ?
        """, (
            translated_title, translated_summary, translated_body,
            impact_analysis,
            json.dumps(industry_tags, ensure_ascii=False),
            slug, article_id,
        ))

    def mark_played(self, article_ids: List[int], briefing_date: str) -> None:
        if not article_ids:
            return
        conn = self.connect()
        placeholders = ",".join("?" * len(article_ids))
        conn.execute("BEGIN")
        try:
            conn.execute(f"""
                UPDATE news_articles
                   SET broadcast_status = 'played',
                       broadcast_date = ?,
                       published_briefing_date = ?
                 WHERE id IN ({placeholders})
            """, [briefing_date, briefing_date] + list(article_ids))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def get_articles_pending_publication(self) -> List[sqlite3.Row]:
        """Articles with translation but no slug yet — need publish_article."""
        conn = self.connect()
        return conn.execute("""
            SELECT * FROM news_articles
            WHERE translated_body IS NOT NULL
              AND translated_body != ''
              AND (slug IS NULL OR slug = '')
        """).fetchall()

    def get_articles_for_briefing(self, briefing_date: str) -> List[sqlite3.Row]:
        conn = self.connect()
        return conn.execute("""
            SELECT * FROM news_articles
            WHERE published_briefing_date = ?
            ORDER BY importance DESC, id ASC
        """, (briefing_date,)).fetchall()

    def log_broadcast(
        self,
        broadcast_date: str,
        article_ids: List[int],
        briefing_url: Optional[str] = None,
        audio_url: Optional[str] = None,
        audio_path: Optional[str] = None,
    ) -> None:
        conn = self.connect()
        conn.execute("""
            INSERT OR REPLACE INTO broadcast_log
                (broadcast_date, article_ids, article_count,
                 briefing_url, audio_url, audio_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            broadcast_date,
            json.dumps(article_ids, ensure_ascii=False),
            len(article_ids), briefing_url, audio_url, audio_path,
        ))

    def stats(self) -> Dict[str, int]:
        conn = self.connect()
        row = conn.execute("""
            SELECT COUNT(*) AS total,
                   SUM(broadcast_status = 'unplayed') AS unplayed,
                   SUM(broadcast_status = 'played') AS played,
                   SUM(slug IS NOT NULL) AS published
              FROM news_articles
        """).fetchone()
        sources_n = conn.execute(
            "SELECT COUNT(*) FROM sources WHERE enabled = 1"
        ).fetchone()[0]
        return {
            "total_articles": row["total"] or 0,
            "unplayed": row["unplayed"] or 0,
            "played": row["played"] or 0,
            "published": row["published"] or 0,
            "active_sources": sources_n,
        }


def cli():
    import argparse
    p = argparse.ArgumentParser(description="news_db tooling")
    p.add_argument("db_path")
    p.add_argument("--init", action="store_true")
    p.add_argument("--import-sources", metavar="JSON")
    p.add_argument("--stats", action="store_true")
    args = p.parse_args()
    with NewsDB(args.db_path) as db:
        if args.init:
            db.init()
            print(f"[news_db] initialized {args.db_path}")
        if args.import_sources:
            stats = db.import_sources(args.import_sources)
            print(f"[news_db] sources: imported={stats['imported']} updated={stats['updated']}")
        if args.stats:
            for k, v in db.stats().items():
                print(f"  {k}: {v}")


if __name__ == "__main__":
    cli()
```

- [ ] **Step 6: Write tests for NewsDB**

Create `scripts/lib/test_news_db.py`:

```python
import json
import os
import tempfile
from pathlib import Path

import pytest

from scripts.lib.news_db import NewsDB, BloomFilter


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
        rid2 = db.add_article(make_article(title="t2", source_url="https://e.com/2"))
        db.update_translation(
            rid1, "ct1", "cs1", "cb1", "ia1",
            ["gastro-law"], "slug-t1-2026-04-26",
        )
        # rid2 has no translation → not pending publication
        # rid1 already has slug → not pending
        # Add rid3 with translation but no slug
        rid3 = db.add_article(make_article(title="t3", source_url="https://e.com/3"))
        db.connect().execute("""
            UPDATE news_articles SET translated_body = 'body3' WHERE id = ?
        """, (rid3,))
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
```

- [ ] **Step 7: Run tests**

```bash
python3 -m pytest scripts/lib/test_news_db.py -v
```

Expected: all 9 tests pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/
git commit -m "data: add NewsDB ORM, URL normalize helpers, and TTS sanitizer

Ported from ai-daily-news with Berlin Gastro News v2 schema additions
(translated_title/body/summary, impact_analysis, industry_tags, slug).
Includes BloomFilter for fast pre-dedupe and unit tests covering hash
determinism, URL-based dedupe, importance ordering, and source import."
```

---

### Task 1.3: Initialize DB and import sources

**Files:** none (data only)

- [ ] **Step 1: Initialize the SQLite DB**

```bash
cd /Users/unclejoe/Media_Workspace/berlin-gastro-news
python3 -m scripts.lib.news_db data/news.db --init
```

Expected: prints `[news_db] initialized data/news.db`.

- [ ] **Step 2: Import sources.json**

```bash
python3 -m scripts.lib.news_db data/news.db --import-sources data/sources.json
```

Expected: `[news_db] sources: imported=23 updated=0`.

- [ ] **Step 3: Verify**

```bash
sqlite3 data/news.db "SELECT source_id, name, tier, enabled FROM sources ORDER BY tier;" | head -10
```

Expected: ~23 rows.

- [ ] **Step 4: Commit DB**

```bash
git add data/news.db
git commit -m "data: initialize SQLite DB and import 23 RSS sources"
```

---

## Phase 2: Pipeline Scripts

### Task 2.1: harvest.py — RSS fetcher

**Files:**
- Create: `scripts/harvest.py`

- [ ] **Step 1: Verify feedparser installed**

```bash
python3 -c "import feedparser; print(feedparser.__version__)"
```

If not installed:
```bash
python3 -m pip install --user feedparser
```

- [ ] **Step 2: Write harvest.py**

Create `scripts/harvest.py`:

```python
#!/usr/bin/env python3
"""Harvest RSS feeds → SQLite. No translation, just raw ingestion."""
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
    "gastronomie": 10, "law": 9, "tax": 9, "food-safety": 8,
    "business": 7, "economy": 7, "berlin": 6, "trade": 6,
    "regulations": 6, "subsidies": 5, "finance": 5, "china": 5,
    "asia": 4, "geopolitics": 4, "eu": 4, "politics": 3,
    "health": 3, "hygiene": 3, "supply-chain": 2, "equipment": 2,
    "hotellerie": 2, "events": 1, "general": 1, "international": 1,
    "management": 1, "agriculture": 1,
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
```

- [ ] **Step 3: Run harvest**

```bash
cd /Users/unclejoe/Media_Workspace/berlin-gastro-news
python3 scripts/harvest.py 2>&1 | tail -30
```

Expected: per-source ✅/❌ lines, total DB ≥ 100 articles after first run.

- [ ] **Step 4: Verify in DB**

```bash
sqlite3 data/news.db "SELECT COUNT(*) FROM news_articles;"
sqlite3 data/news.db "SELECT source_name, COUNT(*) FROM news_articles GROUP BY source_name ORDER BY 2 DESC LIMIT 5;"
```

Expected: ≥ 100 articles distributed across sources.

- [ ] **Step 5: Commit**

```bash
git add scripts/harvest.py data/news.db
git commit -m "feat: add harvest.py — RSS ingestion with importance scoring"
```

---

### Task 2.2: select.py — pick top N for the day

**Files:**
- Create: `scripts/select.py`

- [ ] **Step 1: Write select.py**

Create `scripts/select.py`:

```python
#!/usr/bin/env python3
"""Select top N unplayed articles for the daily briefing.

Outputs daily-selected.json (intermediate state for Claude curation).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.news_db import NewsDB

DB_PATH = ROOT / "data" / "news.db"
OUT_PATH = ROOT / "daily-selected.json"


def row_to_dict(row) -> dict:
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
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=10)
    p.add_argument("--min-importance", type=int, default=0)
    p.add_argument("--out", default=str(OUT_PATH))
    args = p.parse_args()

    with NewsDB(str(DB_PATH)) as db:
        rows = db.get_unplayed(limit=args.count, min_importance=args.min_importance)
        if not rows:
            print("⚠️  no unplayed articles")
            sys.exit(0)
        selected = [row_to_dict(r) for r in rows]

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "selected_at": datetime.now(timezone.utc).isoformat(),
            "count": len(selected),
            "articles": selected,
        }, f, ensure_ascii=False, indent=2)

    print(f"✅ selected {len(selected)} articles → {args.out}")
    for i, a in enumerate(selected, 1):
        print(f"  [{i:2d}] imp={a['importance']:3d} | {a['source_name_cn'] or a['source_name']:24s} | {a['title'][:60]}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run select**

```bash
python3 scripts/select.py --count 10
```

Expected: 10 articles listed; `daily-selected.json` written at repo root.

- [ ] **Step 3: Inspect output**

```bash
python3 -c "import json; d=json.load(open('daily-selected.json')); print(d['count'], '|', d['articles'][0]['title'][:80])"
```

Expected: count=10, first article printed.

- [ ] **Step 4: Commit (skip the JSON; it's gitignored)**

```bash
git add scripts/select.py
git commit -m "feat: add select.py — top-N unplayed picker → daily-selected.json"
```

---

### Task 2.3: migrate_v1_to_sqlite.py — one-shot import of v1 JSON

**Files:**
- Create: `scripts/migrate_v1_to_sqlite.py`

- [ ] **Step 1: Write migration script**

Create `scripts/migrate_v1_to_sqlite.py`:

```python
#!/usr/bin/env python3
"""One-shot migration: archive/v1/news-db.json → data/news.db.

Idempotent: re-runs are safe (uses URL/hash dedupe).
Marks v1 'presented=true' items as 'played'.
"""
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
                    presented_at = item.get("presented_at", "")[:10] or "2026-01-01"
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
```

- [ ] **Step 2: Run migration**

```bash
python3 scripts/migrate_v1_to_sqlite.py
```

Expected: prints stats; total articles increases by however many v1 had that weren't already harvested.

- [ ] **Step 3: Verify counts**

```bash
sqlite3 data/news.db "SELECT broadcast_status, COUNT(*) FROM news_articles GROUP BY broadcast_status;"
```

Expected: at least some `played` rows from v1.

- [ ] **Step 4: Commit**

```bash
git add scripts/migrate_v1_to_sqlite.py data/news.db
git commit -m "feat: migrate v1 JSON DB into SQLite (one-shot)"
```

---

### Task 2.4: publish_article.py — DB → Astro article

**Files:**
- Create: `scripts/publish_article.py`

- [ ] **Step 1: Write publish_article.py**

Create `scripts/publish_article.py`:

```python
#!/usr/bin/env python3
"""Render translated articles from DB into site/src/content/articles/<slug>.md.

Run modes:
  --id N             Publish one article by DB id
  --all-pending      Publish every article with translated_body but no slug
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.news_db import NewsDB

DB_PATH = ROOT / "data" / "news.db"
ARTICLES_DIR = ROOT / "site" / "src" / "content" / "articles"

VALID_TAGS = {
    "gastro-law", "tax-finance", "labor-staffing", "energy-cost",
    "supply-food", "hygiene-safety", "digital-tech", "real-estate",
    "events-marketing", "trends-consumer", "geopolitics-trade", "berlin-local",
}


def slugify(text: str, max_len: int = 50) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s\-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def make_slug(row) -> str:
    """Build slug from translated_title (transliterated) + pubDate.

    If translated_title contains non-ASCII, fall back to source URL last segment.
    Always append YYYY-MM-DD.
    """
    pub = (row["published_at"] or row["discovered_at"])[:10]
    base = slugify(row["translated_title"] or "")
    if not base:
        # Try original title
        base = slugify(row["title"] or "")
    if not base:
        # Last resort: source_url last segment
        url = row["source_url"] or ""
        base = slugify(url.rstrip("/").rsplit("/", 1)[-1])[:30] or "article"
    return f"{base}-{pub}"[:60].rstrip("-")


def yaml_escape(s: str) -> str:
    s = (s or "").replace('"', '\\"').replace("\n", " ").strip()
    return f'"{s}"'


def render_frontmatter(row, slug: str, tags: list) -> str:
    pub = (row["published_at"] or row["discovered_at"])[:10]
    return "\n".join([
        "---",
        f"title: {yaml_escape(row['translated_title'])}",
        f"titleOriginal: {yaml_escape(row['title'])}",
        f"description: {yaml_escape(row['translated_summary'])}",
        f"pubDate: {pub}",
        f"sourceName: {yaml_escape(row['source_name'])}",
        f"sourceUrl: {yaml_escape(row['source_url'])}",
        f"sourceLang: {row['lang'] or 'de'}",
        f"tags: [{', '.join(yaml_escape(t) for t in tags)}]",
        "---",
        "",
    ])


def render_body(row) -> str:
    body = row["translated_body"] or ""
    impact = row["impact_analysis"] or ""
    out = body.strip() + "\n\n"
    if impact.strip():
        out += "## 对柏林餐饮业的影响\n\n"
        out += impact.strip() + "\n\n"
    out += "---\n\n## 原文参考\n\n"
    out += f"来源：[{row['source_name']}]({row['source_url']})"
    if row["published_at"]:
        out += f" · {row['published_at'][:10]}"
    out += "\n\n"
    if row["summary"]:
        out += "> " + row["summary"].replace("\n", "\n> ") + "\n"
    return out


def write_article(row, db: NewsDB, force: bool = False) -> Path:
    tags = json.loads(row["industry_tags"] or "[]")
    invalid = [t for t in tags if t not in VALID_TAGS]
    if invalid:
        raise ValueError(f"Invalid tags for article {row['id']}: {invalid}")
    if not tags:
        raise ValueError(f"Article {row['id']} has no tags")

    slug = row["slug"] or make_slug(row)
    # Ensure unique
    if not row["slug"]:
        # Check for collisions
        conn = db.connect()
        n = 1
        candidate = slug
        while conn.execute(
            "SELECT 1 FROM news_articles WHERE slug = ? AND id != ?",
            (candidate, row["id"]),
        ).fetchone():
            n += 1
            candidate = f"{slug}-{n}"
        slug = candidate
        conn.execute("UPDATE news_articles SET slug = ? WHERE id = ?", (slug, row["id"]))
        # Refresh row
        row = db.get_by_id(row["id"])

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTICLES_DIR / f"{slug}.md"
    if out_path.exists() and not force:
        print(f"⚠️  exists, skipping: {out_path.name}")
        return out_path

    content = render_frontmatter(row, slug, tags) + render_body(row)
    out_path.write_text(content, encoding="utf-8")
    print(f"✅ wrote {out_path.relative_to(ROOT)}")
    return out_path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--id", type=int, help="Publish single article by id")
    p.add_argument("--all-pending", action="store_true", help="Publish all with translated_body but no slug")
    p.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = p.parse_args()

    if not args.id and not args.all_pending:
        p.error("--id or --all-pending required")

    with NewsDB(str(DB_PATH)) as db:
        if args.id:
            row = db.get_by_id(args.id)
            if not row:
                print(f"❌ article {args.id} not found")
                sys.exit(1)
            if not row["translated_body"]:
                print(f"❌ article {args.id} has no translation")
                sys.exit(1)
            write_article(row, db, force=args.force)
        else:
            rows = db.get_articles_pending_publication()
            print(f"📂 {len(rows)} pending articles")
            for row in rows:
                try:
                    write_article(row, db, force=args.force)
                except ValueError as e:
                    print(f"⚠️  {e}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity test slugify**

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from scripts.publish_article import slugify
print(slugify('Berlin Gaststättengesetz – New Law'))
print(slugify(''))
print(slugify('   '))
"
```

Expected: 3 lines; first non-empty kebab slug, others empty.

- [ ] **Step 3: Commit**

```bash
git add scripts/publish_article.py
git commit -m "feat: add publish_article.py — DB → site/src/content/articles/*.md"
```

---

### Task 2.5: publish_briefing.py — daily index + pickup files

**Files:**
- Create: `scripts/publish_briefing.py`

- [ ] **Step 1: Write publish_briefing.py**

Create `scripts/publish_briefing.py`:

```python
#!/usr/bin/env python3
"""Publish the daily briefing.

Inputs:
  - daily-selected.json (10 article ids selected by select.py)
  - DB rows with translation already filled in
  - optional intro text from --intro-file

Outputs:
  1. site/src/content/briefings/<YYYY-MM-DD>.md
  2. daily/<YYYY>/<YYYY-MM>/<YYYY-MM-DD>/{briefing.md, meta.json}
  3. Marks all 10 articles broadcast_status='played'
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.news_db import NewsDB

DB_PATH = ROOT / "data" / "news.db"
SELECTED_JSON = ROOT / "daily-selected.json"
SITE_BRIEFINGS = ROOT / "site" / "src" / "content" / "briefings"
DAILY_ROOT = ROOT / "daily"
SITE_BASE = "/berlin-gastro-news"


def yaml_escape(s):
    s = (s or "").replace('"', '\\"').replace("\n", " ").strip()
    return f'"{s}"'


def parse_date(s: str | None) -> str:
    if not s or s == "today":
        return datetime.now(timezone(timedelta(hours=2))).strftime("%Y-%m-%d")
    return s


def render_briefing_collection(date_str: str, audio_url: str, slugs: list, intro: str) -> str:
    parts = [
        "---",
        f"title: {yaml_escape(f'柏林餐饮商业新闻简报 — {date_str}')}",
        f"date: {date_str}",
        f"audioUrl: {yaml_escape(audio_url)}",
        "articles:",
    ]
    for s in slugs:
        parts.append(f"  - {yaml_escape(s)}")
    parts.append("---")
    parts.append("")
    if intro.strip():
        parts.append(intro.strip())
        parts.append("")
    return "\n".join(parts)


def render_discord_briefing(date_str: str, rows: list, audio_url: str, site_url: str) -> str:
    """Markdown for Discord — short, link-heavy."""
    lines = [
        f"# 📰 柏林餐饮商业新闻简报 — {date_str}",
        "",
        f"🎧 [今日音频]({audio_url}) · 🌐 [完整网页]({site_url})",
        "",
    ]
    for i, row in enumerate(rows, 1):
        slug = row["slug"]
        title = row["translated_title"]
        summary = row["translated_summary"]
        url = f"{site_url.rstrip('/')}/articles/{slug}"
        lines.append(f"## {i}. [{title}]({url})")
        if summary:
            lines.append(summary)
        lines.append("")
    lines.append("---")
    lines.append(f"*共 {len(rows)} 条 · 来源：{', '.join(sorted(set(r['source_name_cn'] or r['source_name'] for r in rows)))}*")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="today")
    p.add_argument("--intro-file", help="Optional intro markdown file")
    p.add_argument("--selected", default=str(SELECTED_JSON))
    p.add_argument("--site-url",
                   default="https://unclejoeyao666.github.io/berlin-gastro-news")
    args = p.parse_args()

    date_str = parse_date(args.date)
    selected = json.loads(Path(args.selected).read_text(encoding="utf-8"))
    ids = [a["id"] for a in selected["articles"]]
    if not ids:
        print("⚠️  no articles in daily-selected.json")
        sys.exit(0)

    audio_rel = f"{SITE_BASE}/audio/{date_str}.mp3"
    audio_url_full = f"{args.site_url}/audio/{date_str}.mp3"
    briefing_url_full = f"{args.site_url}/briefings/{date_str}"

    intro = ""
    if args.intro_file and Path(args.intro_file).exists():
        intro = Path(args.intro_file).read_text(encoding="utf-8")

    with NewsDB(str(DB_PATH)) as db:
        rows = []
        for aid in ids:
            row = db.get_by_id(aid)
            if not row:
                print(f"⚠️  article {aid} missing")
                continue
            if not row["slug"]:
                print(f"❌ article {aid} has no slug — run publish_article first")
                sys.exit(2)
            if not row["translated_title"]:
                print(f"❌ article {aid} has no translation")
                sys.exit(2)
            rows.append(row)

        # Mark them played + assign briefing date
        db.mark_played([r["id"] for r in rows], briefing_date=date_str)

        # Briefing collection (Astro)
        SITE_BRIEFINGS.mkdir(parents=True, exist_ok=True)
        coll_path = SITE_BRIEFINGS / f"{date_str}.md"
        coll_content = render_briefing_collection(
            date_str, audio_rel, [r["slug"] for r in rows], intro,
        )
        coll_path.write_text(coll_content, encoding="utf-8")
        print(f"✅ {coll_path.relative_to(ROOT)}")

        # Daily pickup files
        year, month, _ = date_str.split("-")
        daily_dir = DAILY_ROOT / year / f"{year}-{month}" / date_str
        daily_dir.mkdir(parents=True, exist_ok=True)

        discord_path = daily_dir / "briefing.md"
        discord_path.write_text(
            render_discord_briefing(date_str, rows, audio_url_full, args.site_url),
            encoding="utf-8",
        )
        print(f"✅ {discord_path.relative_to(ROOT)}")

        meta = {
            "date": date_str,
            "article_ids": [r["id"] for r in rows],
            "article_slugs": [r["slug"] for r in rows],
            "briefing_url": briefing_url_full,
            "audio_url": audio_url_full,
            "site_base": args.site_url,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_path = daily_dir / "meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ {meta_path.relative_to(ROOT)}")

        # Log broadcast
        db.log_broadcast(
            broadcast_date=date_str,
            article_ids=[r["id"] for r in rows],
            briefing_url=briefing_url_full,
            audio_url=audio_url_full,
            audio_path=str((daily_dir / "audio.mp3").relative_to(ROOT)),
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/publish_briefing.py
git commit -m "feat: add publish_briefing.py — daily index + Discord pickup files"
```

---

### Task 2.6: render_audio.py — TTS wrapper

**Files:**
- Create: `scripts/render_audio.py`

- [ ] **Step 1: Verify TTS script available**

```bash
ls -la /Users/unclejoe/Doc_Workspace/scripts/minimax_tts.py
which node && node --version
```

Expected: file exists; node v22+ for Edge TTS.

- [ ] **Step 2: Write render_audio.py**

Create `scripts/render_audio.py`:

```python
#!/usr/bin/env python3
"""Render daily audio_script.md → audio.mp3, then mirror into site/public/audio/.

Inputs:
  daily/<YYYY>/<YYYY-MM>/<DATE>/audio_script.md
Outputs:
  daily/<YYYY>/<YYYY-MM>/<DATE>/audio.mp3
  site/public/audio/<DATE>.mp3
"""
import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.normalize import sanitize_for_tts

TTS_SCRIPT = Path("/Users/unclejoe/Doc_Workspace/scripts/minimax_tts.py")
DAILY_ROOT = ROOT / "daily"
SITE_AUDIO = ROOT / "site" / "public" / "audio"


def parse_date(s: str | None) -> str:
    if not s or s == "today":
        return datetime.now(timezone(timedelta(hours=2))).strftime("%Y-%m-%d")
    return s


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="today")
    p.add_argument("--provider", default="microsoft", choices=["microsoft", "minimax"])
    p.add_argument("--voice", default="zh-CN-XiaoxiaoNeural")
    p.add_argument("--rate", default="+0%")
    args = p.parse_args()

    date_str = parse_date(args.date)
    year, month, _ = date_str.split("-")
    day_dir = DAILY_ROOT / year / f"{year}-{month}" / date_str
    script_md = day_dir / "audio_script.md"
    if not script_md.exists():
        print(f"❌ {script_md.relative_to(ROOT)} not found")
        sys.exit(1)

    # Strip Markdown for TTS
    raw = script_md.read_text(encoding="utf-8")
    plain = sanitize_for_tts(raw)
    plain_txt = day_dir / "audio_script.tts.txt"
    plain_txt.write_text(plain, encoding="utf-8")
    print(f"📝 sanitized {len(raw)} → {len(plain)} chars → {plain_txt.relative_to(ROOT)}")

    out_mp3 = day_dir / "audio.mp3"
    cmd = [
        "python3", str(TTS_SCRIPT),
        "--file", str(plain_txt),
        str(out_mp3),
        "--provider", args.provider,
        "--voice", args.voice,
    ]
    if args.provider == "microsoft":
        cmd += ["--rate", args.rate]
    print(f"🎙️  {' '.join(cmd)}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print("❌ TTS failed:")
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
        sys.exit(2)
    print(r.stdout.strip())

    # Mirror into site/public/audio/
    SITE_AUDIO.mkdir(parents=True, exist_ok=True)
    target = SITE_AUDIO / f"{date_str}.mp3"
    shutil.copy2(out_mp3, target)
    size_kb = target.stat().st_size / 1024
    print(f"✅ {target.relative_to(ROOT)} ({size_kb:.1f} KB)")

    # Cleanup intermediate
    plain_txt.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke test sanitize**

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from scripts.lib.normalize import sanitize_for_tts
print(sanitize_for_tts('# Title\n## Sub\nSee https://example.com\n**bold** *italic* —dash—'))
"
```

Expected: no `#`, no URL, no `**`, no `—`.

- [ ] **Step 4: Commit**

```bash
git add scripts/render_audio.py
git commit -m "feat: add render_audio.py — TTS wrapper (Edge default, MiniMax fallback)"
```

---

### Task 2.7: git_publish.py — atomic add/commit/push

**Files:**
- Create: `scripts/git_publish.py`

- [ ] **Step 1: Write git_publish.py**

Create `scripts/git_publish.py`:

```python
#!/usr/bin/env python3
"""Stage, commit, and push the day's changes.

Always:
  - git pull --rebase first (avoid conflicts with parallel runs)
  - stage data/news.db, site/src/content/, site/public/audio/, daily/
  - commit with a templated message
  - push origin main
"""
import argparse
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_date(s: str | None) -> str:
    if not s or s == "today":
        return datetime.now(timezone(timedelta(hours=2))).strftime("%Y-%m-%d")
    return s


def run(cmd: list, check=True) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT, check=check, capture_output=True, text=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="today")
    p.add_argument("--no-push", action="store_true")
    args = p.parse_args()

    date_str = parse_date(args.date)

    # 1. Sync with remote
    run(["git", "pull", "--rebase", "origin", "main"], check=False)

    # 2. Stage
    paths = [
        "data/news.db",
        "site/src/content/articles",
        "site/src/content/briefings",
        "site/public/audio",
        "daily",
    ]
    run(["git", "add", "--"] + paths)

    # 3. Diff check
    diff = run(["git", "diff", "--cached", "--stat"], check=False)
    if not diff.stdout.strip():
        print("ℹ️  nothing to commit")
        return
    print(diff.stdout)

    # 4. Commit
    msg = (
        f"📰 Daily briefing: {date_str}\n\n"
        f"Auto-generated by berlin-gastro-news pipeline.\n"
    )
    run(["git", "commit", "-m", msg])

    # 5. Push
    if args.no_push:
        print("ℹ️  --no-push, stopping after commit")
        return
    push = run(["git", "push", "origin", "main"], check=False)
    print(push.stdout)
    if push.returncode != 0:
        print(push.stderr, file=sys.stderr)
        sys.exit(push.returncode)
    print(f"✅ pushed {date_str}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/git_publish.py
git commit -m "feat: add git_publish.py — pull/add/commit/push"
```

---

## Phase 3: Astro Site

### Task 3.1: Astro scaffold

**Files:**
- Create: `site/package.json`
- Create: `site/astro.config.mjs`
- Create: `site/tsconfig.json`
- Create: `site/.gitignore`
- Create: `site/src/content.config.ts`
- Create: `site/src/consts.ts`

- [ ] **Step 1: Verify Node 22+**

```bash
node --version
```

Expected: `v22.x.x` or higher.

- [ ] **Step 2: Write package.json**

Create `site/package.json`:

```json
{
  "name": "berlin-gastro-news-site",
  "type": "module",
  "version": "2.0.0",
  "engines": {
    "node": ">=22.12.0"
  },
  "scripts": {
    "dev": "astro dev",
    "build": "astro build",
    "preview": "astro preview",
    "astro": "astro"
  },
  "dependencies": {
    "@astrojs/mdx": "^5.0.2",
    "@astrojs/rss": "^4.0.17",
    "@astrojs/sitemap": "^3.7.1",
    "astro": "^6.0.6"
  }
}
```

- [ ] **Step 3: Write astro.config.mjs**

Create `site/astro.config.mjs`:

```javascript
// @ts-check
import mdx from '@astrojs/mdx';
import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://unclejoeyao666.github.io',
  base: '/berlin-gastro-news',
  trailingSlash: 'never',
  integrations: [mdx(), sitemap()],
});
```

- [ ] **Step 4: Write tsconfig.json**

Create `site/tsconfig.json`:

```json
{
  "extends": "astro/tsconfigs/strict",
  "include": [".astro/types.d.ts", "**/*"],
  "exclude": ["dist"]
}
```

- [ ] **Step 5: Write site/.gitignore**

Create `site/.gitignore`:

```gitignore
node_modules/
dist/
.astro/
.env
.env.production
```

- [ ] **Step 6: Write src/consts.ts**

Create `site/src/consts.ts`:

```typescript
export const SITE_TITLE = "柏林餐饮商业新闻";
export const SITE_DESCRIPTION = "每日柏林与德国餐饮业相关的法规、经济、市场动态。";
export const SITE_AUTHOR = "Berlin Gastro News";

export const TAG_LABELS: Record<string, string> = {
  "gastro-law": "餐饮法规",
  "tax-finance": "财税·补贴",
  "labor-staffing": "招工·人力",
  "energy-cost": "能源·成本",
  "supply-food": "食材·供应链",
  "hygiene-safety": "卫生·食品安全",
  "digital-tech": "数字化·AI",
  "real-estate": "场地·租赁",
  "events-marketing": "活动·营销",
  "trends-consumer": "消费趋势",
  "geopolitics-trade": "国际·贸易",
  "berlin-local": "柏林本地",
};

export const TAG_COLORS: Record<string, string> = {
  "gastro-law": "#8e44ad",
  "tax-finance": "#f39c12",
  "labor-staffing": "#e67e22",
  "energy-cost": "#c0392b",
  "supply-food": "#27ae60",
  "hygiene-safety": "#16a085",
  "digital-tech": "#2980b9",
  "real-estate": "#7f8c8d",
  "events-marketing": "#d35400",
  "trends-consumer": "#9b59b6",
  "geopolitics-trade": "#34495e",
  "berlin-local": "#1abc9c",
};

export const TAG_SLUGS = Object.keys(TAG_LABELS);
```

- [ ] **Step 7: Write src/content.config.ts**

Create `site/src/content.config.ts`:

```typescript
import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';
import { TAG_SLUGS } from './consts';

const tagEnum = z.enum(TAG_SLUGS as [string, ...string[]]);

const articles = defineCollection({
  loader: glob({ base: './src/content/articles', pattern: '**/*.md' }),
  schema: z.object({
    title: z.string(),
    titleOriginal: z.string(),
    description: z.string().max(300),
    pubDate: z.coerce.date(),
    sourceName: z.string(),
    sourceUrl: z.string().url(),
    sourceLang: z.enum(['de', 'en', 'zh']).default('de'),
    tags: z.array(tagEnum).min(1).max(3),
    heroImage: z.string().optional(),
  }),
});

const briefings = defineCollection({
  loader: glob({ base: './src/content/briefings', pattern: '**/*.md' }),
  schema: z.object({
    title: z.string(),
    date: z.coerce.date(),
    audioUrl: z.string().optional(),
    articles: z.array(z.string()).min(1).max(15),
  }),
});

export const collections = { articles, briefings };
```

- [ ] **Step 8: npm install**

```bash
cd site && npm install && cd ..
```

Expected: completes with no errors; creates `site/node_modules/` and `site/package-lock.json`.

- [ ] **Step 9: Commit**

```bash
git add site/package.json site/package-lock.json site/astro.config.mjs site/tsconfig.json site/.gitignore site/src/consts.ts site/src/content.config.ts
git commit -m "site: scaffold Astro project (collections, tags, base config)"
```

---

### Task 3.2: Layouts and components

**Files:**
- Create: `site/src/layouts/BaseLayout.astro`
- Create: `site/src/layouts/ArticleLayout.astro`
- Create: `site/src/layouts/BriefingLayout.astro`
- Create: `site/src/components/TagBadge.astro`
- Create: `site/src/components/ArticleCard.astro`
- Create: `site/src/components/AudioPlayer.astro`
- Create: `site/src/components/SiteHeader.astro`
- Create: `site/src/components/SiteFooter.astro`
- Create: `site/src/styles/global.css`

- [ ] **Step 1: global.css**

Create `site/src/styles/global.css`:

```css
:root {
  --bg: #ffffff;
  --bg-soft: #f8f9fa;
  --text: #1a1a1a;
  --text-soft: #5a6470;
  --border: #e1e6ec;
  --accent: #c0392b;
  --accent-soft: #fce4e0;
  --card-bg: #ffffff;
  --shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  --max-width: 920px;
  --radius: 10px;
  --font-sans: "Noto Sans SC", -apple-system, BlinkMacSystemFont, "Segoe UI",
    Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, monospace;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14171c;
    --bg-soft: #1c2026;
    --text: #e8eaed;
    --text-soft: #95a3b1;
    --border: #2a3038;
    --accent: #ff7a6b;
    --accent-soft: #3a1f1c;
    --card-bg: #1c2026;
    --shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
  }
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: var(--font-sans);
  background: var(--bg);
  color: var(--text);
  line-height: 1.7;
  -webkit-font-smoothing: antialiased;
}
.container { max-width: var(--max-width); margin: 0 auto; padding: 0 20px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
h1, h2, h3, h4 { line-height: 1.3; margin: 1.5em 0 0.6em; }
h1 { font-size: 1.8rem; }
h2 { font-size: 1.4rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4em; }
h3 { font-size: 1.15rem; }
hr { border: 0; border-top: 1px solid var(--border); margin: 2em 0; }
blockquote {
  border-left: 3px solid var(--border);
  padding: 0.4em 1em;
  color: var(--text-soft);
  margin: 1em 0;
  background: var(--bg-soft);
  border-radius: var(--radius);
}
code {
  font-family: var(--font-mono);
  background: var(--bg-soft);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}
audio { width: 100%; }
```

- [ ] **Step 2: BaseLayout.astro**

Create `site/src/layouts/BaseLayout.astro`:

```astro
---
import { SITE_TITLE, SITE_DESCRIPTION } from "../consts";
import "../styles/global.css";
import SiteHeader from "../components/SiteHeader.astro";
import SiteFooter from "../components/SiteFooter.astro";

interface Props {
  title?: string;
  description?: string;
  ogType?: "website" | "article";
}
const { title, description, ogType = "website" } = Astro.props;
const pageTitle = title ? `${title} · ${SITE_TITLE}` : SITE_TITLE;
const pageDescription = description ?? SITE_DESCRIPTION;
const canonical = new URL(Astro.url.pathname, Astro.site).toString();
---

<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>{pageTitle}</title>
    <meta name="description" content={pageDescription} />
    <link rel="canonical" href={canonical} />
    <link
      rel="alternate"
      type="application/rss+xml"
      title={SITE_TITLE}
      href={`${import.meta.env.BASE_URL.replace(/\/$/, "")}/rss.xml`}
    />
    <meta property="og:title" content={pageTitle} />
    <meta property="og:description" content={pageDescription} />
    <meta property="og:type" content={ogType} />
    <meta property="og:url" content={canonical} />
    <link
      href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap"
      rel="stylesheet"
    />
  </head>
  <body>
    <SiteHeader />
    <main class="container">
      <slot />
    </main>
    <SiteFooter />
  </body>
</html>
```

- [ ] **Step 3: SiteHeader.astro**

Create `site/src/components/SiteHeader.astro`:

```astro
---
import { SITE_TITLE } from "../consts";
const base = import.meta.env.BASE_URL.replace(/\/$/, "");
const links = [
  { href: `${base}/`, label: "首页" },
  { href: `${base}/archive`, label: "归档" },
  { href: `${base}/about`, label: "关于" },
];
---

<header>
  <div class="container">
    <a href={`${base}/`} class="brand">📰 {SITE_TITLE}</a>
    <nav>
      {links.map((l) => <a href={l.href}>{l.label}</a>)}
    </nav>
  </div>
</header>

<style>
  header {
    background: var(--bg-soft);
    border-bottom: 1px solid var(--border);
    padding: 14px 0;
    margin-bottom: 24px;
  }
  header .container {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }
  .brand {
    font-weight: 700;
    font-size: 1.1rem;
    color: var(--text);
  }
  nav {
    display: flex;
    gap: 16px;
  }
  nav a {
    color: var(--text-soft);
    font-size: 0.95rem;
  }
  nav a:hover {
    color: var(--accent);
    text-decoration: none;
  }
</style>
```

- [ ] **Step 4: SiteFooter.astro**

Create `site/src/components/SiteFooter.astro`:

```astro
---
const year = new Date().getFullYear();
---

<footer>
  <div class="container">
    <p>© {year} 柏林餐饮商业新闻 · 数据来源：23+ 权威 RSS 订阅 · 自动生成</p>
    <p>
      <a href={`${import.meta.env.BASE_URL.replace(/\/$/, "")}/rss.xml`}>RSS</a>
      ·
      <a href={`${import.meta.env.BASE_URL.replace(/\/$/, "")}/about`}>项目说明</a>
    </p>
  </div>
</footer>

<style>
  footer {
    border-top: 1px solid var(--border);
    margin-top: 60px;
    padding: 30px 0;
    color: var(--text-soft);
    font-size: 0.85rem;
    text-align: center;
  }
  footer p {
    margin: 0.4em 0;
  }
</style>
```

- [ ] **Step 5: TagBadge.astro**

Create `site/src/components/TagBadge.astro`:

```astro
---
import { TAG_LABELS, TAG_COLORS } from "../consts";

interface Props {
  slug: string;
}
const { slug } = Astro.props;
const label = TAG_LABELS[slug] ?? slug;
const color = TAG_COLORS[slug] ?? "#7f8c8d";
const base = import.meta.env.BASE_URL.replace(/\/$/, "");
---

<a href={`${base}/tags/${slug}`} class="tag" style={`--tag-color: ${color}`}>
  {label}
</a>

<style>
  .tag {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.78rem;
    line-height: 1.3;
    background: var(--tag-color);
    color: white;
    text-decoration: none;
    margin: 0 4px 4px 0;
    white-space: nowrap;
  }
  .tag:hover {
    opacity: 0.85;
    text-decoration: none;
  }
</style>
```

- [ ] **Step 6: AudioPlayer.astro**

Create `site/src/components/AudioPlayer.astro`:

```astro
---
interface Props {
  src: string;
  date?: string;
}
const { src, date } = Astro.props;
---

<div class="audio-player">
  <div class="meta">
    🎙️ {date ? `${date} · ` : ""}音频版简报
  </div>
  <audio controls preload="none" src={src}>
    您的浏览器不支持 audio 元素。<a href={src}>下载音频</a>
  </audio>
</div>

<style>
  .audio-player {
    background: var(--bg-soft);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 16px;
    margin: 16px 0;
  }
  .meta {
    font-size: 0.88rem;
    color: var(--text-soft);
    margin-bottom: 8px;
  }
</style>
```

- [ ] **Step 7: ArticleCard.astro**

Create `site/src/components/ArticleCard.astro`:

```astro
---
import type { CollectionEntry } from "astro:content";
import TagBadge from "./TagBadge.astro";

interface Props {
  article: CollectionEntry<"articles">;
  index?: number;
}
const { article, index } = Astro.props;
const base = import.meta.env.BASE_URL.replace(/\/$/, "");
const href = `${base}/articles/${article.id}`;
const dateStr = article.data.pubDate.toISOString().slice(0, 10);
---

<article class="card">
  <header class="head">
    {index !== undefined && <span class="num">{index}</span>}
    <h3>
      <a href={href}>{article.data.title}</a>
    </h3>
  </header>
  <div class="meta">
    <span>📌 {article.data.sourceName}</span>
    <span>📅 {dateStr}</span>
  </div>
  <p class="desc">{article.data.description}</p>
  <div class="tags">
    {article.data.tags.map((t) => <TagBadge slug={t} />)}
  </div>
</article>

<style>
  .card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-left: 4px solid var(--accent);
    border-radius: var(--radius);
    padding: 16px 18px;
    margin-bottom: 16px;
    box-shadow: var(--shadow);
  }
  .head {
    display: flex;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 4px;
  }
  .num {
    display: inline-block;
    background: var(--accent);
    color: white;
    width: 24px;
    height: 24px;
    line-height: 24px;
    text-align: center;
    border-radius: 50%;
    font-size: 0.85em;
    font-weight: 700;
    flex-shrink: 0;
  }
  h3 {
    margin: 0;
    font-size: 1.1rem;
  }
  h3 a {
    color: var(--text);
  }
  h3 a:hover {
    color: var(--accent);
    text-decoration: none;
  }
  .meta {
    color: var(--text-soft);
    font-size: 0.85rem;
    display: flex;
    gap: 14px;
    margin: 6px 0;
    flex-wrap: wrap;
  }
  .desc {
    margin: 10px 0;
    color: var(--text);
    font-size: 0.95rem;
  }
  .tags {
    margin-top: 10px;
  }
</style>
```

- [ ] **Step 8: ArticleLayout.astro**

Create `site/src/layouts/ArticleLayout.astro`:

```astro
---
import BaseLayout from "./BaseLayout.astro";
import TagBadge from "../components/TagBadge.astro";

interface Props {
  title: string;
  titleOriginal: string;
  description: string;
  pubDate: Date;
  sourceName: string;
  sourceUrl: string;
  sourceLang: "de" | "en" | "zh";
  tags: string[];
  heroImage?: string;
}
const props = Astro.props;
const dateStr = props.pubDate.toISOString().slice(0, 10);
---

<BaseLayout title={props.title} description={props.description} ogType="article">
  <article class="article">
    <header>
      <h1>{props.title}</h1>
      <p class="subtitle">{props.titleOriginal}</p>
      <div class="meta">
        <span>📌 {props.sourceName}</span>
        <span>📅 {dateStr}</span>
        <span>🌐 {props.sourceLang.toUpperCase()}</span>
      </div>
      <div class="tags">
        {props.tags.map((t) => <TagBadge slug={t} />)}
      </div>
    </header>
    <div class="body">
      <slot />
    </div>
    <footer>
      <p class="back">
        <a href={`${import.meta.env.BASE_URL.replace(/\/$/, "")}/`}>← 返回首页</a>
      </p>
    </footer>
  </article>
</BaseLayout>

<style>
  .article header {
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }
  .article h1 {
    margin: 0;
    font-size: 1.9rem;
  }
  .subtitle {
    color: var(--text-soft);
    font-style: italic;
    font-size: 0.95rem;
    margin: 8px 0;
  }
  .meta {
    display: flex;
    gap: 14px;
    color: var(--text-soft);
    font-size: 0.88rem;
    margin: 10px 0;
    flex-wrap: wrap;
  }
  .tags {
    margin-top: 10px;
  }
  .body :global(blockquote) {
    font-size: 0.95rem;
  }
  footer {
    margin-top: 40px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }
  .back a {
    color: var(--text-soft);
  }
</style>
```

- [ ] **Step 9: BriefingLayout.astro**

Create `site/src/layouts/BriefingLayout.astro`:

```astro
---
import BaseLayout from "./BaseLayout.astro";
import AudioPlayer from "../components/AudioPlayer.astro";

interface Props {
  title: string;
  date: Date;
  audioUrl?: string;
}
const props = Astro.props;
const dateStr = props.date.toISOString().slice(0, 10);
const audioFull =
  props.audioUrl && !props.audioUrl.startsWith("http")
    ? props.audioUrl
    : props.audioUrl;
---

<BaseLayout title={props.title} description={`柏林餐饮商业新闻 ${dateStr} 期`}>
  <header class="briefing-head">
    <h1>{props.title}</h1>
    <p class="date">📅 {dateStr}</p>
    {audioFull && <AudioPlayer src={audioFull} date={dateStr} />}
  </header>
  <div class="briefing-body">
    <slot />
  </div>
</BaseLayout>

<style>
  .briefing-head h1 {
    margin: 0 0 6px;
  }
  .briefing-head .date {
    color: var(--text-soft);
    margin: 4px 0 16px;
  }
</style>
```

- [ ] **Step 10: Commit**

```bash
git add site/src/
git commit -m "site: add layouts, components, and global styles"
```

---

### Task 3.3: Pages and routes

**Files:**
- Create: `site/src/pages/index.astro`
- Create: `site/src/pages/articles/[...slug].astro`
- Create: `site/src/pages/briefings/[...slug].astro`
- Create: `site/src/pages/tags/[tag].astro`
- Create: `site/src/pages/archive.astro`
- Create: `site/src/pages/about.astro`
- Create: `site/src/pages/rss.xml.js`

- [ ] **Step 1: index.astro (homepage)**

Create `site/src/pages/index.astro`:

```astro
---
import { getCollection, getEntry } from "astro:content";
import BaseLayout from "../layouts/BaseLayout.astro";
import ArticleCard from "../components/ArticleCard.astro";
import AudioPlayer from "../components/AudioPlayer.astro";

const articles = (await getCollection("articles"))
  .sort((a, b) => b.data.pubDate.getTime() - a.data.pubDate.getTime());

const briefings = (await getCollection("briefings"))
  .sort((a, b) => b.data.date.getTime() - a.data.date.getTime());

const latestBriefing = briefings[0];
const latestBriefingArticles = latestBriefing
  ? await Promise.all(
      latestBriefing.data.articles.map((slug) =>
        getEntry("articles", slug).catch(() => null)
      )
    ).then((rs) => rs.filter((r) => r !== null))
  : [];

const recent = articles.slice(0, 8);
const base = import.meta.env.BASE_URL.replace(/\/$/, "");
---

<BaseLayout>
  {latestBriefing && (
    <section>
      <h2>📅 当日简报 — {latestBriefing.data.date.toISOString().slice(0, 10)}</h2>
      {latestBriefing.data.audioUrl && (
        <AudioPlayer
          src={latestBriefing.data.audioUrl}
          date={latestBriefing.data.date.toISOString().slice(0, 10)}
        />
      )}
      <a href={`${base}/briefings/${latestBriefing.id}`} class="more">查看完整简报 →</a>
      {latestBriefingArticles.length > 0 && (
        <div class="cards">
          {latestBriefingArticles.slice(0, 3).map((a, i) => (
            <ArticleCard article={a!} index={i + 1} />
          ))}
        </div>
      )}
    </section>
  )}

  <section>
    <h2>📰 最新文章</h2>
    <div class="cards">
      {recent.map((a) => <ArticleCard article={a} />)}
    </div>
  </section>
</BaseLayout>

<style>
  .more {
    display: inline-block;
    margin: 8px 0 16px;
    font-size: 0.92rem;
  }
</style>
```

- [ ] **Step 2: articles/[...slug].astro**

Create `site/src/pages/articles/[...slug].astro`:

```astro
---
import { type CollectionEntry, getCollection, render } from "astro:content";
import ArticleLayout from "../../layouts/ArticleLayout.astro";

export async function getStaticPaths() {
  const posts = await getCollection("articles");
  return posts.map((post) => ({ params: { slug: post.id }, props: post }));
}

type Props = CollectionEntry<"articles">;
const post = Astro.props;
const { Content } = await render(post);
---

<ArticleLayout {...post.data}>
  <Content />
</ArticleLayout>
```

- [ ] **Step 3: briefings/[...slug].astro**

Create `site/src/pages/briefings/[...slug].astro`:

```astro
---
import { type CollectionEntry, getCollection, getEntry, render } from "astro:content";
import BriefingLayout from "../../layouts/BriefingLayout.astro";
import ArticleCard from "../../components/ArticleCard.astro";

export async function getStaticPaths() {
  const all = await getCollection("briefings");
  return all.map((b) => ({ params: { slug: b.id }, props: b }));
}

type Props = CollectionEntry<"briefings">;
const briefing = Astro.props;
const { Content } = await render(briefing);

const articles = (
  await Promise.all(
    briefing.data.articles.map((slug) =>
      getEntry("articles", slug).catch(() => null)
    )
  )
).filter((a) => a !== null) as CollectionEntry<"articles">[];
---

<BriefingLayout
  title={briefing.data.title}
  date={briefing.data.date}
  audioUrl={briefing.data.audioUrl}
>
  <Content />
  <div class="cards">
    {articles.map((a, i) => <ArticleCard article={a} index={i + 1} />)}
  </div>
</BriefingLayout>
```

- [ ] **Step 4: tags/[tag].astro**

Create `site/src/pages/tags/[tag].astro`:

```astro
---
import { getCollection } from "astro:content";
import BaseLayout from "../../layouts/BaseLayout.astro";
import ArticleCard from "../../components/ArticleCard.astro";
import { TAG_LABELS, TAG_SLUGS } from "../../consts";

export async function getStaticPaths() {
  const all = await getCollection("articles");
  return TAG_SLUGS.map((tag) => {
    const posts = all
      .filter((a) => a.data.tags.includes(tag))
      .sort((a, b) => b.data.pubDate.getTime() - a.data.pubDate.getTime());
    return {
      params: { tag },
      props: { tag, posts, label: TAG_LABELS[tag] ?? tag },
    };
  });
}

const { tag, posts, label } = Astro.props;
---

<BaseLayout title={`标签：${label}`} description={`所有标记为「${label}」的文章`}>
  <h1>🏷️ {label}</h1>
  <p class="count">{posts.length} 篇文章</p>
  {posts.length === 0 ? (
    <p>暂无文章。</p>
  ) : (
    <div class="cards">
      {posts.map((a) => <ArticleCard article={a} />)}
    </div>
  )}
</BaseLayout>

<style>
  .count {
    color: var(--text-soft);
    margin: 0 0 24px;
  }
</style>
```

- [ ] **Step 5: archive.astro**

Create `site/src/pages/archive.astro`:

```astro
---
import { getCollection } from "astro:content";
import BaseLayout from "../layouts/BaseLayout.astro";

const articles = (await getCollection("articles"))
  .sort((a, b) => b.data.pubDate.getTime() - a.data.pubDate.getTime());

const byMonth = new Map<string, typeof articles>();
for (const a of articles) {
  const key = a.data.pubDate.toISOString().slice(0, 7);
  if (!byMonth.has(key)) byMonth.set(key, []);
  byMonth.get(key)!.push(a);
}
const months = Array.from(byMonth.entries()).sort((a, b) => b[0].localeCompare(a[0]));
const base = import.meta.env.BASE_URL.replace(/\/$/, "");
---

<BaseLayout title="归档" description="按月份浏览所有文章">
  <h1>📚 归档</h1>
  <p class="meta">共 {articles.length} 篇文章 · {months.length} 个月份</p>
  {months.map(([month, posts]) => (
    <section>
      <h2>{month}</h2>
      <ul>
        {posts.map((a) => (
          <li>
            <span class="d">{a.data.pubDate.toISOString().slice(8, 10)}</span>
            <a href={`${base}/articles/${a.id}`}>{a.data.title}</a>
            <span class="src">— {a.data.sourceName}</span>
          </li>
        ))}
      </ul>
    </section>
  ))}
</BaseLayout>

<style>
  .meta {
    color: var(--text-soft);
  }
  ul {
    list-style: none;
    padding: 0;
  }
  li {
    padding: 6px 0;
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 10px;
    align-items: baseline;
    flex-wrap: wrap;
  }
  .d {
    font-family: var(--font-mono);
    color: var(--text-soft);
    font-size: 0.85rem;
    min-width: 30px;
  }
  .src {
    color: var(--text-soft);
    font-size: 0.85rem;
  }
</style>
```

- [ ] **Step 6: about.astro**

Create `site/src/pages/about.astro`:

```astro
---
import BaseLayout from "../layouts/BaseLayout.astro";
import { TAG_LABELS } from "../consts";
---

<BaseLayout title="关于" description="项目说明、数据来源与工作机制">
  <h1>ℹ️ 关于本项目</h1>

  <h2>🎯 目标</h2>
  <p>
    为在德国（柏林）经营餐饮业的从业者，建立一套自动化的中文新闻情报体系。
    覆盖餐饮法规、财税、招工、能源、食材、卫生、数字化、场地、营销、消费趋势、国际贸易、柏林本地等核心领域。
  </p>

  <h2>📡 数据来源</h2>
  <ul>
    <li><strong>餐饮专业：</strong>AHGZ Gastronomie / DEHOGA Berlin</li>
    <li><strong>政府官方：</strong>BMEL（联邦食品农业部）/ EFSA（欧洲食品安全局）</li>
    <li><strong>德国主流商业媒体：</strong>Tagesschau、Der Spiegel、FAZ、WirtschaftsWoche、Manager Magazin、ZDF</li>
    <li><strong>国际政治：</strong>南华早报、Politico EU、EUobserver、欧盟委员会</li>
    <li><strong>德语国际：</strong>Deutsche Welle (DE/EN)</li>
  </ul>

  <h2>🏷️ 行业标签</h2>
  <ul>
    {Object.entries(TAG_LABELS).map(([slug, label]) => (
      <li><code>{slug}</code> — {label}</li>
    ))}
  </ul>

  <h2>⚙️ 工作机制</h2>
  <ol>
    <li>每天早上自动从 23 个 RSS 源抓取最新新闻（去重）</li>
    <li>从未播报池中选出当日 Top10（按重要性 + 时效性打分）</li>
    <li>AI 对每篇做中文翻译 + 影响分析 + 行业打标</li>
    <li>生成静态网页 + 中文音频简报</li>
    <li>推送到 Discord 供决策参考</li>
  </ol>

  <h2>🔧 技术栈</h2>
  <ul>
    <li><strong>抓取：</strong>Python + feedparser</li>
    <li><strong>数据库：</strong>SQLite + FTS5</li>
    <li><strong>站点：</strong>Astro 6</li>
    <li><strong>音频：</strong>Microsoft Edge TTS（zh-CN-XiaoxiaoNeural）</li>
    <li><strong>部署：</strong>GitHub Actions → GitHub Pages</li>
  </ul>
</BaseLayout>
```

- [ ] **Step 7: rss.xml.js**

Create `site/src/pages/rss.xml.js`:

```javascript
import rss from "@astrojs/rss";
import { getCollection } from "astro:content";
import { SITE_TITLE, SITE_DESCRIPTION } from "../consts";

export async function GET(context) {
  const posts = (await getCollection("articles"))
    .sort((a, b) => b.data.pubDate.getTime() - a.data.pubDate.getTime())
    .slice(0, 50);
  return rss({
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    site: context.site,
    items: posts.map((p) => ({
      title: p.data.title,
      description: p.data.description,
      pubDate: p.data.pubDate,
      link: `/articles/${p.id}`,
      categories: p.data.tags,
    })),
  });
}
```

- [ ] **Step 8: First build attempt**

```bash
cd site && npm run build && cd ..
```

Expected: build succeeds. Probable warning: empty content collections (no articles yet) → fine. Output in `site/dist/`.

If it fails because content collections need at least one entry, write a minimal seed (next task) and retry.

- [ ] **Step 9: Commit**

```bash
git add site/src/pages/
git commit -m "site: add routes (index, articles, briefings, tags, archive, about, rss)"
```

---

### Task 3.4: Seed content (cold-start fixtures)

**Files:**
- Create: `site/src/content/articles/welcome-2026-04-26.md`
- Create: `site/src/content/briefings/2026-04-26-seed.md` (placeholder, removed by first real briefing)

- [ ] **Step 1: Write seed article**

Create `site/src/content/articles/welcome-2026-04-26.md`:

```markdown
---
title: "项目上线：柏林餐饮商业新闻 v2"
titleOriginal: "Berlin Gastro News v2 Launch"
description: "项目第二代上线 — 自动化中文翻译、行业标签、音频版简报。每日早晨更新。"
pubDate: 2026-04-26
sourceName: "Berlin Gastro News"
sourceUrl: "https://github.com/unclejoeyao666/berlin-gastro-news"
sourceLang: "zh"
tags: ["berlin-local", "digital-tech"]
---

欢迎来到柏林餐饮商业新闻 v2。

本站每日早晨自动汇总柏林与德国餐饮业相关的法规、财税、招工、能源、供应链、卫生、数字化、营销、消费趋势、国际贸易等核心动态，由 AI 完成中文翻译与影响分析，并提供 8-12 分钟的音频版简报。

## 与 v1 的区别

- 全文中译（不再是简短摘要）
- 12 个行业标签，按主题快速浏览
- 音频版简报（默认 Microsoft Edge TTS 中文女声）
- 数据库底层从 JSON 升级到 SQLite + FTS5

## 数据来源

23 个权威 RSS 源覆盖：

- AHGZ Gastronomie / DEHOGA Berlin
- BMEL / EFSA
- Tagesschau / Spiegel / FAZ / WiWo / Manager Magazin / ZDF
- 南华早报 / Politico EU / EUobserver

## 数据如何决策

每条新闻按"来源权威性 + 行业相关性 + 时效性"打分，每日选出 Top 10。
重复事件、不同报道会自动去重。

## 反馈

GitHub Issues 欢迎反馈：[unclejoeyao666/berlin-gastro-news](https://github.com/unclejoeyao666/berlin-gastro-news/issues)

## 对柏林餐饮业的影响

无 — 这是项目说明文章。明天起每日推送真实新闻。

---

## 原文参考

来源：[Berlin Gastro News](https://github.com/unclejoeyao666/berlin-gastro-news) · 2026-04-26

> 项目代码与设计文档均开源。
```

- [ ] **Step 2: Build again with seed content**

```bash
cd site && npm run build && cd ..
```

Expected: builds successfully; `site/dist/articles/welcome-2026-04-26/index.html` exists.

- [ ] **Step 3: Local preview check**

```bash
cd site && npm run preview &
PREVIEW_PID=$!
sleep 3
curl -sI http://localhost:4321/berlin-gastro-news/ | head -1
curl -sI http://localhost:4321/berlin-gastro-news/articles/welcome-2026-04-26 | head -1
kill $PREVIEW_PID 2>/dev/null
cd ..
```

Expected: both return `HTTP/1.1 200 OK`.

- [ ] **Step 4: Commit**

```bash
git add site/src/content/articles/
git commit -m "site: add launch announcement seed article"
```

---

## Phase 4: Deployment

### Task 4.1: GitHub Action workflow

**Files:**
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Write deploy.yml**

Create `.github/workflows/deploy.yml`:

```yaml
name: Build & Deploy

on:
  push:
    branches: [main]
    paths:
      - 'site/**'
      - '.github/workflows/deploy.yml'
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: site
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: site/package-lock.json

      - name: Install
        run: npm ci

      - name: Build
        run: npm run build

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./site/dist

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Commit and push**

```bash
git add .github/workflows/deploy.yml
git commit -m "ci: add GitHub Pages deploy workflow"
git push origin main
```

- [ ] **Step 3: Enable GitHub Pages via API**

```bash
gh api -X POST repos/unclejoeyao666/berlin-gastro-news/pages \
  -f build_type=workflow 2>&1 || \
gh api -X PUT repos/unclejoeyao666/berlin-gastro-news/pages \
  -f build_type=workflow
```

Expected: returns 201 (created) or 204 (updated). If "already exists" / 422, that's fine.

- [ ] **Step 4: Watch the workflow**

```bash
gh run watch --exit-status 2>&1 | tail -30
```

Expected: completes with green check. URL printed.

- [ ] **Step 5: Verify deployment**

```bash
sleep 30
curl -sI https://unclejoeyao666.github.io/berlin-gastro-news/ | head -3
curl -sI https://unclejoeyao666.github.io/berlin-gastro-news/articles/welcome-2026-04-26 | head -3
```

Expected: both `HTTP/2 200`.

---

## Phase 5: Daily Workflow Documentation

### Task 5.1: DAILY_WORKFLOW.md

**Files:**
- Create: `workflows/DAILY_WORKFLOW.md`

- [ ] **Step 1: Write workflow doc**

Create `workflows/DAILY_WORKFLOW.md`:

```markdown
# Berlin Gastro News — 每日工作流

> 由本地 OpenClaw 在 Europe/Berlin 06:00 触发；总耗时约 5-15 分钟（视新闻条数和翻译长度）。

## 7 步流水线

```
1. 抓取 RSS    → 入 SQLite
2. 选篇 Top10  → daily-selected.json
3. AI 翻译     → 写回 DB（translated_*）+ 生成 audio_script.md
4. 渲染文章    → site/src/content/articles/*.md
5. 渲染简报    → site/src/content/briefings/<date>.md + daily/<date>/{briefing.md, meta.json}
6. 合成音频    → daily/<date>/audio.mp3 + site/public/audio/<date>.mp3
7. 推送        → git pull/add/commit/push → GH Action 自动部署
```

## 完整命令序列

```bash
cd /Users/unclejoe/Media_Workspace/berlin-gastro-news

# 1. 抓取
python3 scripts/harvest.py

# 2. 选篇
python3 scripts/select.py --count 10

# 3. AI 翻译（OpenClaw 在自己的会话内做的认知工作；不调外部 API）
#   - 读 daily-selected.json 的每条
#   - WebFetch 原文（必要时；正文 < 500 字符或付费墙时降级）
#   - 翻译标题/全文/摘要 + 写影响分析 + 选 1-3 个 industry_tags
#   - 用以下伪代码写回 DB：
#     UPDATE news_articles
#     SET translated_title=?, translated_summary=?, translated_body=?,
#         impact_analysis=?, industry_tags=?  -- JSON array of valid slugs
#     WHERE id=?
#   - 生成 daily/<YYYY>/<YYYY-MM>/<DATE>/audio_script.md（朗读串稿，结构见下）

# 4. 渲染文章
python3 scripts/publish_article.py --all-pending

# 5. 渲染简报
python3 scripts/publish_briefing.py --date today

# 6. 音频合成
python3 scripts/render_audio.py --date today

# 7. 推送
python3 scripts/git_publish.py --date today
```

## 标签规则（步骤 3 必须遵守）

合法标签 slug：

| slug | 中文 |
|---|---|
| `gastro-law` | 餐饮法规 |
| `tax-finance` | 财税·补贴 |
| `labor-staffing` | 招工·人力 |
| `energy-cost` | 能源·成本 |
| `supply-food` | 食材·供应链 |
| `hygiene-safety` | 卫生·食品安全 |
| `digital-tech` | 数字化·AI |
| `real-estate` | 场地·租赁 |
| `events-marketing` | 活动·营销 |
| `trends-consumer` | 消费趋势 |
| `geopolitics-trade` | 国际·贸易 |
| `berlin-local` | 柏林本地 |

每篇必须 1-3 个标签，写到 `news_articles.industry_tags` 字段（JSON 数组）。

## audio_script.md 模板

```markdown
早上好，欢迎收听柏林餐饮商业新闻简报。今天是 YYYY 年 MM 月 DD 日，星期X。

今天为您播报 10 条值得关注的新闻。

第一条。<中译标题>。
<重点 + 影响分析浓缩，约 30-60 秒>。

第二条。<中译标题>。
<...>

[第 3-10 条]

以上就是今天的简报。详情请访问网站 unclejoeyao666 点 github 点 io 斜杠 berlin-gastro-news。
祝您生意兴隆，明天见。
```

要点：
- 总长度目标 8-12 分钟（约 1500-2500 中文字符）
- 不要写 Markdown 标题（render_audio.py 会 strip）
- 不要嵌入 URL（TTS 会读出 https）
- 数字与日期写汉字（TTS 更自然）

## Discord 投递（OpenClaw 的另一个 cron）

读 `daily/<YYYY>/<YYYY-MM>/<DATE>/`：
- `briefing.md` — Markdown 文字简报
- `audio.mp3` — 附件
- `meta.json` — 解析 article_slugs / briefing_url 用

## 失败重入

任何步骤失败：
1. 修复问题
2. 从失败步骤往后重跑（脚本都是 `--date YYYY-MM-DD` 幂等）
3. 重跑步骤 7（git_publish）会先 `git pull --rebase`

如 GH Action build 失败：检查 site/dist/ 本地能否 build；多半是 frontmatter schema 校验。

## 监测

- DB 健康：`python3 -m scripts.lib.news_db data/news.db --stats`
- 站点状态：`curl -sI https://unclejoeyao666.github.io/berlin-gastro-news/`
- 最近 5 期 broadcast_log：`sqlite3 data/news.db "SELECT broadcast_date, article_count FROM broadcast_log ORDER BY broadcast_date DESC LIMIT 5;"`
```

- [ ] **Step 2: Commit**

```bash
git add workflows/DAILY_WORKFLOW.md
git commit -m "docs: add DAILY_WORKFLOW.md (OpenClaw runbook)"
```

---

## Phase 6: End-to-End Dry Run

### Task 6.1: Dry-run with synthetic translation

We need to simulate step 3 (the human/Claude cognitive step) for the dry run. We'll use the most-recently-harvested top 3 articles, write minimal but valid translations, run steps 4-7, and verify the live site.

**Files:** none (data only); creates daily/2026-04-26/* and articles

- [ ] **Step 1: Pick top 3 unplayed articles**

```bash
cd /Users/unclejoe/Media_Workspace/berlin-gastro-news
python3 scripts/select.py --count 3
cat daily-selected.json | python3 -c "import json,sys; d=json.load(sys.stdin); [print(a['id'], '|', a['title'][:60]) for a in d['articles']]"
```

Expected: 3 article ids printed.

- [ ] **Step 2: Write a translation helper for the dry run**

Create `scripts/dry_run_translate.py` (this is a one-off helper used only for the dry run; it copies summary into translated_* fields and assigns plausible tags from source_categories):

```python
#!/usr/bin/env python3
"""Dry-run helper: synthesize plausible translations from RSS data.

Real production translation is done by OpenClaw's Claude session.
This script exists to verify the pipeline end-to-end on day 1.
"""
import json
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
    import re
    base = re.sub(r"[^a-z0-9]+", "-", title.lower())[:30].strip("-")
    if not base:
        base = f"article-{article_id}"
    return f"{base}-{pub[:10]}"


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
```

- [ ] **Step 3: Run the synthetic translation**

```bash
python3 scripts/dry_run_translate.py
```

Expected: 3 articles updated.

- [ ] **Step 4: Write a minimal audio_script.md**

```bash
DATE=$(date +%Y-%m-%d)
YEAR=${DATE:0:4}
MONTH=${DATE:0:7}
mkdir -p "daily/${YEAR}/${MONTH}/${DATE}"
cat > "daily/${YEAR}/${MONTH}/${DATE}/audio_script.md" <<'EOF'
早上好，欢迎收听柏林餐饮商业新闻简报。今天是测试播报。

今天为您播报三条简短测试新闻。

第一条。系统冷启动测试。本期为系统首次端到端测试，仅用于验证音频管线是否正常。

第二条。占位条目。完整的中文翻译与影响分析将在每日例行运行后自动产出。

第三条。结束语。感谢收听，明天将启用真实新闻。

以上就是测试播报。详情请访问网站 unclejoeyao666 点 github 点 io 斜杠 berlin-gastro-news。
EOF
echo "wrote daily/${YEAR}/${MONTH}/${DATE}/audio_script.md"
```

- [ ] **Step 5: Render articles**

```bash
python3 scripts/publish_article.py --all-pending
```

Expected: 3 .md files in `site/src/content/articles/`.

- [ ] **Step 6: Render briefing**

```bash
python3 scripts/publish_briefing.py --date today
```

Expected: writes `site/src/content/briefings/<date>.md` and `daily/<...>/{briefing.md, meta.json}`.

- [ ] **Step 7: Render audio**

```bash
python3 scripts/render_audio.py --date today
```

Expected: prints "[✓] 完成" and produces `daily/<...>/audio.mp3` + `site/public/audio/<date>.mp3` (~50-200 KB).

- [ ] **Step 8: Local Astro build**

```bash
cd site && npm run build && cd ..
```

Expected: builds; output mentions article + briefing + tag pages.

- [ ] **Step 9: Local preview verify**

```bash
cd site && npm run preview > /tmp/preview.log 2>&1 &
PID=$!
sleep 4
curl -sI "http://localhost:4321/berlin-gastro-news/" | head -1
curl -sI "http://localhost:4321/berlin-gastro-news/briefings/$(date +%Y-%m-%d)" | head -1
curl -sI "http://localhost:4321/berlin-gastro-news/tags/berlin-local" | head -1
kill $PID 2>/dev/null
cd ..
```

Expected: 3× `HTTP/1.1 200 OK`.

- [ ] **Step 10: Push and watch deploy**

```bash
python3 scripts/git_publish.py --date today
gh run watch --exit-status 2>&1 | tail -10
```

Expected: workflow succeeds.

- [ ] **Step 11: Live site smoke test**

```bash
sleep 45
DATE=$(date +%Y-%m-%d)
echo "Homepage:"
curl -sI "https://unclejoeyao666.github.io/berlin-gastro-news/" | head -2
echo "Briefing:"
curl -sI "https://unclejoeyao666.github.io/berlin-gastro-news/briefings/${DATE}" | head -2
echo "Audio:"
curl -sI "https://unclejoeyao666.github.io/berlin-gastro-news/audio/${DATE}.mp3" | head -2
echo "Tag:"
curl -sI "https://unclejoeyao666.github.io/berlin-gastro-news/tags/berlin-local" | head -2
echo "RSS:"
curl -sI "https://unclejoeyao666.github.io/berlin-gastro-news/rss.xml" | head -2
```

Expected: all 5 return `HTTP/2 200`.

---

### Task 6.2: Verify all 7 acceptance criteria

- [ ] **Verify item 1: Homepage live**

```bash
curl -s "https://unclejoeyao666.github.io/berlin-gastro-news/" | grep -c "当日简报\|最新文章"
```

Expected: ≥ 1.

- [ ] **Verify item 2: Article page has translation + impact + original**

```bash
SLUG=$(ls site/src/content/articles/ | grep -v welcome | head -1 | sed 's/\.md$//')
curl -s "https://unclejoeyao666.github.io/berlin-gastro-news/articles/${SLUG}" | grep -c "对柏林餐饮业的影响\|原文参考"
```

Expected: ≥ 2.

- [ ] **Verify item 3: All 12 tag pages exist**

```bash
for tag in gastro-law tax-finance labor-staffing energy-cost supply-food \
           hygiene-safety digital-tech real-estate events-marketing \
           trends-consumer geopolitics-trade berlin-local; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "https://unclejoeyao666.github.io/berlin-gastro-news/tags/${tag}")
  echo "${tag}: ${code}"
done
```

Expected: all 200.

- [ ] **Verify item 4: RSS and sitemap**

```bash
curl -s "https://unclejoeyao666.github.io/berlin-gastro-news/rss.xml" | head -3
curl -s "https://unclejoeyao666.github.io/berlin-gastro-news/sitemap-0.xml" | head -3
```

Expected: both produce XML.

- [ ] **Verify item 5: Audio playable**

```bash
DATE=$(date +%Y-%m-%d)
curl -sI "https://unclejoeyao666.github.io/berlin-gastro-news/audio/${DATE}.mp3" | grep -i "content-type\|content-length"
```

Expected: `content-type: audio/mpeg`, `content-length: > 10000`.

- [ ] **Verify item 6: daily/<date>/ pickup files**

```bash
DATE=$(date +%Y-%m-%d)
YEAR=${DATE:0:4}
MONTH=${DATE:0:7}
ls "daily/${YEAR}/${MONTH}/${DATE}/"
```

Expected: contains `briefing.md`, `audio_script.md`, `audio.mp3`, `meta.json`.

- [ ] **Verify item 7: Pipeline dry-run was unattended**

Already done in Task 6.1 — the only manual step was `dry_run_translate.py` which substitutes for the AI translation step in OpenClaw.

- [ ] **Step: Commit dry-run artifacts**

```bash
git add -A
git commit -m "test: end-to-end dry run validates 7 acceptance criteria"
git push origin main
```

---

## Phase 7: Polish

### Task 7.1: Add an archive note about v1

**Files:**
- Create: `archive/v1/README.md`

- [ ] **Step 1: Write archive note**

Create `archive/v1/README.md`:

```markdown
# v1 Archive

Frozen v1 implementation kept for reference and as fallback corpus.

## Contents

- `news-db.json` — v1 JSON news database (3.8 MB). Migrated to `data/news.db` via `scripts/migrate_v1_to_sqlite.py`.
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
```

- [ ] **Step 2: Commit**

```bash
git add archive/v1/README.md
git commit -m "docs: archive v1 README"
git push origin main
```

---

## Self-Review

After writing this plan, scanned against the spec:

| Spec section | Plan tasks | Coverage |
|---|---|---|
| §0 Scope | Phase 0-7 cover translation, site, audio, daily handoff | ✓ |
| §1 Repo topology | Task 0.1 (archive v1), 0.2 (gh repo) | ✓ |
| §2 SQLite schema | Task 1.1 | ✓ |
| §2 bloom + FTS5 + url normalize | Task 1.2 + tests | ✓ |
| §2 v1 migration | Task 2.3 | ✓ |
| §3 Industry tags (12) | Task 3.1 (consts.ts), Task 2.4 (validation), Task 3.3 (tag pages) | ✓ |
| §4 Article frontmatter schema | Task 3.1 (content.config.ts) + Task 2.4 (renderer) | ✓ |
| §4 Briefing frontmatter schema | Task 3.1 + Task 2.5 | ✓ |
| §5 Daily 7-step workflow | Task 5.1 (DAILY_WORKFLOW.md) + scripts in Phase 2 | ✓ |
| §6 Astro routes | Task 3.3 | ✓ |
| §7 TTS integration | Task 2.6 | ✓ |
| §8 GitHub Action | Task 4.1 | ✓ |
| §9 Migration plan | Task 0.1 + 2.3 | ✓ |
| §10 Risk: paywall | DAILY_WORKFLOW says fall back to RSS summary | ✓ |
| §10 Risk: failure reentry | git_publish does git pull --rebase; scripts are idempotent | ✓ |
| §10 Risk: TTS special chars | sanitize_for_tts in normalize.py + tests | ✓ |
| §10 Risk: slug collision | publish_article.py auto-suffixes | ✓ |
| §11 Slug rule | publish_article.py make_slug + tests | ✓ |
| §12 Order of work | Phases 0-7 follow it | ✓ |
| §13 Acceptance | Task 6.2 verifies all 7 | ✓ |
| §14 YAGNI list | Plan doesn't add anything not in spec | ✓ |

No gaps found. Plan is implementation-ready.

---

**End of plan.**
