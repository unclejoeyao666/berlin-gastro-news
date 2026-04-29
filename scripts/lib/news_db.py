"""SQLite news DB wrapper for Berlin Gastro News v2.

Ported from /Users/unclejoe/Media_Workspace/ai-daily-news/db/news_db.py
with adaptations for the gastro-news schema (translation columns,
slug uniqueness, source_id as stable string).
"""
from __future__ import annotations

import sqlite3
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

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
        # Resilient against uninitialized DB (table may not exist yet).
        try:
            for (h,) in conn.execute("SELECT story_hash FROM news_articles"):
                self.add(h)
        except sqlite3.OperationalError:
            pass


class NewsDB:
    def __init__(self, db_path: Union[str, Path], use_bloom: bool = True):
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

    @staticmethod
    def make_url_hash(url_normalized: str) -> str:
        return hashlib.sha256(url_normalized.encode("utf-8")).hexdigest()

    # ── Sources ────────────────────────────────────────

    def import_sources(self, sources_json_path: Union[str, Path]) -> Dict[str, int]:
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
        """Insert one article. Returns rowid on insert, None on duplicate.

        On successful INSERT, also records the URL in ``url_seen`` so the
        ledger survives later aging of news_articles rows.
        """
        conn = self.connect()
        title = article["title"].strip()
        source_name = article["source_name"].strip()
        story_hash = self.make_hash(title, source_name)
        url_norm = normalize_url(article.get("source_url"))
        url_hash = self.make_url_hash(url_norm) if url_norm else None

        if url_norm:
            row = conn.execute(
                "SELECT id FROM news_articles WHERE url_normalized = ?",
                (url_norm,),
            ).fetchone()
            if row:
                return None

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
                if url_hash:
                    conn.execute(
                        "INSERT OR IGNORE INTO url_seen "
                        "(url_hash, title_hash, first_seen_at, source_id) "
                        "VALUES (?, ?, datetime('now'), ?)",
                        (url_hash, story_hash, article.get("source_id")),
                    )
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

    def get_unplayed_by_quota(
        self,
        gastro_quota: int = 5,
        keyword_quota: int = 3,
        general_quota: int = 2,
        gastro_sources: Optional[Sequence[str]] = None,
        keywords: Optional[Sequence[str]] = None,
        keyword_blocked_sources: Optional[Sequence[str]] = None,
        max_general_per_source: int = 3,
        recency_days: int = 7,
    ) -> Dict[str, List[sqlite3.Row]]:
        """Pull unplayed articles split into 3 pools.

        Pools:
          * ``gastro``: rows whose ``source_id`` is in ``gastro_sources``.
          * ``keyword``: rows from non-gastro sources whose
            ``title || summary`` contains any of ``keywords``.
          * ``general``: highest-importance rows that don't fit above,
            capped at ``max_general_per_source`` from each single source
            so a busy feed can't dominate.

        Slots flow downward — if a higher-priority pool can't fill its
        quota, the unfilled slots roll into the next pool.

        Returns a dict ``{"gastro": [...], "keyword": [...], "general":
        [...], "fillover_used": int}``. Caller decides how to merge.
        """
        if not gastro_sources:
            gastro_sources = []
        if not keywords:
            keywords = []
        if not keyword_blocked_sources:
            keyword_blocked_sources = []

        conn = self.connect()

        recency_clause = ""
        params: List[Any] = []
        if recency_days and recency_days > 0:
            recency_clause = (
                "AND (published_at IS NULL OR "
                "datetime(published_at) >= datetime('now', ?))"
            )
            params.append(f"-{int(recency_days)} days")

        # ── Pool 1: gastro sources ──
        gastro: List[sqlite3.Row] = []
        if gastro_sources:
            placeholders = ",".join("?" * len(gastro_sources))
            sql = f"""
                SELECT * FROM news_articles
                 WHERE broadcast_status = 'unplayed'
                   AND source_id IN ({placeholders})
                   {recency_clause}
                 ORDER BY importance DESC, discovered_at DESC
                 LIMIT ?
            """
            gastro = list(conn.execute(
                sql,
                list(gastro_sources) + params + [gastro_quota],
            ).fetchall())

        # ── Pool 2: keyword hits in non-gastro sources ──
        keyword: List[sqlite3.Row] = []
        used_ids = {r["id"] for r in gastro}
        if keywords:
            kw_clauses = " OR ".join(
                "(LOWER(title) LIKE ? OR LOWER(summary) LIKE ?)"
                for _ in keywords
            )
            kw_params: List[Any] = []
            for kw in keywords:
                like = f"%{kw.lower()}%"
                kw_params.extend([like, like])

            blocked_clause = ""
            if keyword_blocked_sources:
                ph = ",".join("?" * len(keyword_blocked_sources))
                blocked_clause = f"AND source_id NOT IN ({ph})"

            sql = f"""
                SELECT * FROM news_articles
                 WHERE broadcast_status = 'unplayed'
                   AND ({kw_clauses})
                   {blocked_clause}
                   {recency_clause}
                 ORDER BY importance DESC, discovered_at DESC
                 LIMIT ?
            """
            limit_keyword = keyword_quota + max(
                0, gastro_quota - len(gastro)
            )
            keyword_rows = conn.execute(
                sql,
                kw_params + list(keyword_blocked_sources) + params
                + [limit_keyword + 50],  # buffer for de-dup
            ).fetchall()
            for row in keyword_rows:
                if row["id"] in used_ids:
                    continue
                keyword.append(row)
                used_ids.add(row["id"])
                if len(keyword) >= limit_keyword:
                    break

        # ── Pool 3: general fill ──
        gastro_set = set(gastro_sources)
        general: List[sqlite3.Row] = []
        per_source_count: Dict[str, int] = {}
        general_target = (
            general_quota
            + max(0, gastro_quota - len(gastro))
            + max(0, keyword_quota - len(keyword))
        )
        if general_target > 0:
            # Pull a generous candidate set then apply per-source cap.
            sql = f"""
                SELECT * FROM news_articles
                 WHERE broadcast_status = 'unplayed'
                   {recency_clause}
                 ORDER BY importance DESC, discovered_at DESC
                 LIMIT ?
            """
            candidate_limit = (general_target + 30) * 4
            for row in conn.execute(
                sql, params + [candidate_limit],
            ).fetchall():
                if row["id"] in used_ids:
                    continue
                src = row["source_id"] or ""
                if src in gastro_set:
                    continue  # we already drew from this pool
                if per_source_count.get(src, 0) >= max_general_per_source:
                    continue
                general.append(row)
                used_ids.add(row["id"])
                per_source_count[src] = per_source_count.get(src, 0) + 1
                if len(general) >= general_target:
                    break

        return {
            "gastro": gastro,
            "keyword": keyword,
            "general": general,
            "fillover": (gastro_quota - len(gastro))
                        + (keyword_quota - len(keyword)),
        }

    def quarantine(self, article_ids: Sequence[int], reason: str) -> int:
        """Mark articles as ``broadcast_status='archived'`` with reason."""
        if not article_ids:
            return 0
        conn = self.connect()
        placeholders = ",".join("?" * len(article_ids))
        cur = conn.execute(
            f"""
            UPDATE news_articles
               SET broadcast_status = 'archived',
                   quarantine_reason = ?
             WHERE id IN ({placeholders})
            """,
            [reason] + list(article_ids),
        )
        return cur.rowcount

    # ── url_seen ledger ────────────────────────────────

    def is_url_seen(
        self,
        url_hash: Optional[str],
        title_hash: Optional[str] = None,
    ) -> bool:
        """Returns True if either hash is recorded in ``url_seen``."""
        conn = self.connect()
        if url_hash:
            row = conn.execute(
                "SELECT 1 FROM url_seen WHERE url_hash = ? LIMIT 1",
                (url_hash,),
            ).fetchone()
            if row:
                return True
        if title_hash:
            row = conn.execute(
                "SELECT 1 FROM url_seen WHERE title_hash = ? LIMIT 1",
                (title_hash,),
            ).fetchone()
            if row:
                return True
        return False

    def record_url_seen(
        self,
        url_hash: Optional[str],
        title_hash: Optional[str] = None,
        source_id: Optional[str] = None,
        seen_at: Optional[str] = None,
    ) -> bool:
        """Idempotent. Returns True if a new row was inserted.

        Skips silently when ``url_hash`` is missing — title_hash alone is
        not unique enough to store as a primary key.
        """
        if not url_hash:
            return False
        conn = self.connect()
        cur = conn.execute(
            "INSERT OR IGNORE INTO url_seen "
            "(url_hash, title_hash, first_seen_at, source_id) "
            "VALUES (?, ?, COALESCE(?, datetime('now')), ?)",
            (url_hash, title_hash, seen_at, source_id),
        )
        return cur.rowcount > 0

    def record_url_seen_batch(
        self,
        rows: Sequence[Dict[str, Any]],
    ) -> int:
        """Bulk insert. Each row needs ``url_hash``; ``title_hash``,
        ``source_id``, ``seen_at`` are optional. Returns insert count."""
        if not rows:
            return 0
        conn = self.connect()
        inserted = 0
        conn.execute("BEGIN")
        try:
            for r in rows:
                if not r.get("url_hash"):
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO url_seen "
                    "(url_hash, title_hash, first_seen_at, source_id) "
                    "VALUES (?, ?, COALESCE(?, datetime('now')), ?)",
                    (
                        r["url_hash"],
                        r.get("title_hash"),
                        r.get("seen_at"),
                        r.get("source_id"),
                    ),
                )
                inserted += cur.rowcount
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return inserted

    # ── pruning / aging ────────────────────────────────

    def prune_articles(
        self,
        played_cutoff: Optional[str] = None,
        unplayed_cutoff: Optional[str] = None,
        archived_cutoff: Optional[str] = None,
    ) -> Dict[str, int]:
        """Delete articles older than the given ISO cutoffs by status.

        ``None`` for any cutoff means skip that bucket.

        ``played_cutoff`` matches against ``COALESCE(broadcast_date,
        discovered_at)`` so an article that lost its broadcast_date still
        ages from when it was harvested.

        Returns ``{"played": n, "unplayed": n, "archived": n}``.
        """
        conn = self.connect()
        counts = {"played": 0, "unplayed": 0, "archived": 0}
        if played_cutoff is not None:
            cur = conn.execute(
                "DELETE FROM news_articles "
                "WHERE broadcast_status = 'played' "
                "  AND COALESCE(broadcast_date, discovered_at) < ?",
                (played_cutoff,),
            )
            counts["played"] = cur.rowcount
        if unplayed_cutoff is not None:
            cur = conn.execute(
                "DELETE FROM news_articles "
                "WHERE broadcast_status = 'unplayed' "
                "  AND discovered_at < ?",
                (unplayed_cutoff,),
            )
            counts["unplayed"] = cur.rowcount
        if archived_cutoff is not None:
            cur = conn.execute(
                "DELETE FROM news_articles "
                "WHERE broadcast_status = 'archived' "
                "  AND discovered_at < ?",
                (archived_cutoff,),
            )
            counts["archived"] = cur.rowcount
        return counts

    def prune_url_seen(self, cutoff: str) -> int:
        """Delete url_seen rows whose first_seen_at < cutoff."""
        conn = self.connect()
        cur = conn.execute(
            "DELETE FROM url_seen WHERE first_seen_at < ?", (cutoff,)
        )
        return cur.rowcount

    def vacuum(self) -> None:
        self.connect().execute("VACUUM")

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
        """Articles with translation that need a published .md file.

        publish_article.py de-dupes by checking if the .md exists on disk,
        so this just returns everything with a translated_body. The CLI
        prints "exists, skipping" for ones already written — idempotent.
        """
        conn = self.connect()
        return conn.execute("""
            SELECT * FROM news_articles
            WHERE translated_body IS NOT NULL
              AND translated_body != ''
            ORDER BY published_at DESC
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
                   SUM(broadcast_status = 'archived') AS archived,
                   SUM(slug IS NOT NULL) AS published
              FROM news_articles
        """).fetchone()
        sources_n = conn.execute(
            "SELECT COUNT(*) FROM sources WHERE enabled = 1"
        ).fetchone()[0]
        try:
            url_seen_n = conn.execute(
                "SELECT COUNT(*) FROM url_seen"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            url_seen_n = 0
        return {
            "total_articles": row["total"] or 0,
            "unplayed": row["unplayed"] or 0,
            "played": row["played"] or 0,
            "archived": row["archived"] or 0,
            "published": row["published"] or 0,
            "active_sources": sources_n,
            "url_seen": url_seen_n,
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
