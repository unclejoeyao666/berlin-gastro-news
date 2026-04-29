#!/usr/bin/env python3
"""Agent-driven translation writer.

This is the *only* sanctioned way the OpenClaw agent should write
translations into the DB. The CLI enforces:
  * input shape (translated_title / summary / body / impact_analysis /
    industry_tags / slug_hint / audio_segment),
  * tag set (must be in VALID_TAGS) + tag-to-content semantic match,
  * relevance gate (skip with reason for off-topic articles),
  * progress tracking (``daily-selected.json`` flag updates).

Subcommands:
  write     — store one translation
  skip      — quarantine one article as off-topic
  finalize  — assemble ``daily/<date>/audio_script.md`` from segments

Usage examples:
  python3 scripts/translate_helper.py write --id 4612 \
      --json-file translations/4612.json
  python3 scripts/translate_helper.py skip --id 4604 \
      --reason "macro economy / not gastro"
  python3 scripts/translate_helper.py finalize --date today
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import relevance
from scripts.lib.news_db import NewsDB

DB_PATH = ROOT / "data" / "news.db"
SELECTED_JSON = ROOT / "daily-selected.json"
DAILY_ROOT = ROOT / "daily"

REQUIRED_FIELDS = (
    "translated_title",
    "translated_summary",
    "translated_body",
    "impact_analysis",
    "industry_tags",
)


def parse_date(s) -> str:
    if not s or s == "today":
        return datetime.now(timezone(timedelta(hours=2))).strftime("%Y-%m-%d")
    return s


def day_dir_for(date_str: str) -> Path:
    year, month, _ = date_str.split("-")
    return DAILY_ROOT / year / f"{year}-{month}" / date_str


def slugify(text: str, max_len: int = 50) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9\s\-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len].rstrip("-")


def build_slug(payload: Dict[str, Any], row, fallback_id: int) -> str:
    hint = (payload.get("slug_hint") or "").strip()
    base = slugify(hint) if hint else slugify(payload.get("translated_title", ""))
    if not base:
        base = f"article-{fallback_id}"
    pub = (row["published_at"] or row["discovered_at"] or "")[:10]
    if not pub:
        pub = parse_date("today")
    return f"{base}-{pub}"[:60].rstrip("-")


def load_selected() -> Dict[str, Any]:
    if not SELECTED_JSON.exists():
        raise SystemExit(f"❌ {SELECTED_JSON.relative_to(ROOT)} missing — "
                         "run select_top.py first")
    return json.loads(SELECTED_JSON.read_text(encoding="utf-8"))


def save_selected(data: Dict[str, Any]) -> None:
    SELECTED_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_in_selected(data: Dict[str, Any], article_id: int) -> Dict[str, Any]:
    for a in data["articles"]:
        if a["id"] == article_id:
            return a
    raise SystemExit(f"❌ article id={article_id} not in daily-selected.json")


# ── write ────────────────────────────────────────────────────────


def cmd_write(args) -> int:
    payload = json.loads(Path(args.json_file).read_text(encoding="utf-8"))

    missing = [k for k in REQUIRED_FIELDS if not payload.get(k)]
    if missing:
        print(f"❌ missing fields: {missing}", file=sys.stderr)
        return 2

    tags = payload["industry_tags"]
    if not isinstance(tags, list) or not (1 <= len(tags) <= 3):
        print("❌ industry_tags must be a list of 1-3 valid tag slugs",
              file=sys.stderr)
        return 2

    summary = payload["translated_summary"]
    if len(summary) > 200:
        print(f"❌ translated_summary too long ({len(summary)} chars > 200)",
              file=sys.stderr)
        return 2

    selected = load_selected()
    sel_entry = find_in_selected(selected, args.id)

    with NewsDB(str(DB_PATH)) as db:
        row = db.get_by_id(args.id)
        if not row:
            print(f"❌ article id={args.id} not in DB", file=sys.stderr)
            return 1

        # Tag semantic check (uses original DE/EN text + body)
        text_for_check = "\n".join(filter(None, [
            row["title"] or "",
            row["summary"] or "",
            row["content"] or "",
        ]))
        ok, warns = relevance.validate_tags(
            tags, row["source_id"],
            title=row["title"] or "",
            summary=row["summary"] or "",
            body=row["content"] or "",
        )
        if not ok and not args.force:
            print("❌ tag/content mismatch:", file=sys.stderr)
            for w in warns:
                print(f"   {w}", file=sys.stderr)
            print("   pass --force to override (and reflect in PR notes)",
                  file=sys.stderr)
            return 3
        if warns and args.force:
            print("⚠️  forcing despite warnings:", file=sys.stderr)
            for w in warns:
                print(f"   {w}", file=sys.stderr)

        # Compute slug
        slug = payload.get("slug") or build_slug(payload, row, args.id)

        db.update_translation(
            article_id=args.id,
            translated_title=payload["translated_title"],
            translated_summary=summary,
            translated_body=payload["translated_body"],
            impact_analysis=payload["impact_analysis"],
            industry_tags=tags,
            slug=slug,
        )
        print(f"✅ wrote translation for id={args.id} slug={slug} "
              f"tags={tags}")

    sel_entry["_translated"] = True
    sel_entry["_skipped"] = False
    sel_entry["_slug"] = slug
    sel_entry["_translated_title"] = payload["translated_title"]
    sel_entry["_audio_segment"] = (payload.get("audio_segment")
                                    or payload["translated_summary"])
    save_selected(selected)
    return 0


# ── skip ─────────────────────────────────────────────────────────


def cmd_skip(args) -> int:
    selected = load_selected()
    sel_entry = find_in_selected(selected, args.id)
    with NewsDB(str(DB_PATH)) as db:
        if not db.get_by_id(args.id):
            print(f"❌ article id={args.id} not in DB", file=sys.stderr)
            return 1
        db.quarantine([args.id], reason=args.reason)
    sel_entry["_skipped"] = True
    sel_entry["_translated"] = False
    sel_entry["_skip_reason"] = args.reason
    save_selected(selected)
    print(f"⏭  quarantined id={args.id}: {args.reason}")
    return 0


# ── finalize: build audio_script.md ─────────────────────────────


WEEKDAY_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五",
              "星期六", "星期日"]


def num_to_zh(n: int) -> str:
    digits = "零一二三四五六七八九"
    if 0 <= n <= 9:
        return digits[n]
    if 10 <= n < 20:
        return "十" + (digits[n - 10] if n > 10 else "")
    if n < 100:
        tens = n // 10
        ones = n % 10
        return digits[tens] + "十" + (digits[ones] if ones else "")
    return str(n)


def date_zh(date_str: str) -> str:
    d = datetime.fromisoformat(date_str)
    digits = "零一二三四五六七八九"
    year = "".join(digits[int(c)] for c in str(d.year))
    return f"{year}年{num_to_zh(d.month)}月{num_to_zh(d.day)}日"


ORDINAL_ZH = ["第一条", "第二条", "第三条", "第四条", "第五条",
              "第六条", "第七条", "第八条", "第九条", "第十条",
              "第十一条", "第十二条", "第十三条", "第十四条", "第十五条"]


def render_audio_script(date_str: str,
                        translated: List[Dict[str, Any]]) -> str:
    d = datetime.fromisoformat(date_str)
    weekday = WEEKDAY_ZH[d.weekday()]
    n = len(translated)
    n_zh = num_to_zh(n) if n <= 15 else str(n)
    parts: List[str] = [
        f"早上好，欢迎收听柏林餐饮商业新闻简报。"
        f"今天是 {date_zh(date_str)}，{weekday}。",
        "",
        f"今天为您播报 {n_zh} 条值得关注的新闻。",
        "",
    ]
    for i, art in enumerate(translated):
        ord_str = ORDINAL_ZH[i] if i < len(ORDINAL_ZH) else f"第{i + 1}条"
        title = art.get("_translated_title") or art.get("title", "")
        segment = (art.get("_audio_segment")
                   or art.get("translated_summary")
                   or "")
        # Strip URLs and headers from the segment if any survived
        segment = re.sub(r"https?://\S+", "", segment).strip()
        parts.append(f"{ord_str}。{title}。")
        parts.append(segment)
        parts.append("")
    parts.append("以上就是今天的简报。详情请访问网站 unclejoeyao666 点 "
                 "github 点 io 斜杠 berlin-gastro-news。")
    parts.append("祝您生意兴隆，明天见。")
    parts.append("")
    return "\n".join(parts)


def cmd_finalize(args) -> int:
    date_str = parse_date(args.date)
    selected = load_selected()
    translated = [a for a in selected["articles"] if a.get("_translated")]
    skipped = [a for a in selected["articles"] if a.get("_skipped")]
    pending = [a for a in selected["articles"]
               if not (a.get("_translated") or a.get("_skipped"))]

    if pending and not args.allow_pending:
        print(f"❌ {len(pending)} article(s) still pending: "
              f"{[a['id'] for a in pending]}", file=sys.stderr)
        print("   resolve via write/skip first, "
              "or pass --allow-pending if you intentionally want to "
              "finalize a partial set.",
              file=sys.stderr)
        return 1
    if not translated:
        print("❌ no translated articles to render", file=sys.stderr)
        return 1

    out = day_dir_for(date_str) / "audio_script.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = render_audio_script(date_str, translated)
    out.write_text(text, encoding="utf-8")
    print(f"✅ wrote {out.relative_to(ROOT)} "
          f"({len(translated)} stories, {len(skipped)} skipped, "
          f"{len(text)} chars)")
    return 0


# ── status (handy diagnostic) ───────────────────────────────────


def cmd_status(args) -> int:
    selected = load_selected()
    translated = sum(1 for a in selected["articles"] if a.get("_translated"))
    skipped = sum(1 for a in selected["articles"] if a.get("_skipped"))
    pending = len(selected["articles"]) - translated - skipped
    print(f"📋 daily-selected.json @ {selected.get('selected_at')}")
    print(f"   translated: {translated}")
    print(f"   skipped:    {skipped}")
    print(f"   pending:    {pending}")
    for a in selected["articles"]:
        if a.get("_translated"):
            mark = "✅"
        elif a.get("_skipped"):
            mark = "⏭ "
        else:
            mark = "⏳"
        pool = a.get("_pool", "??")
        src = a.get("source_id") or "n/a"
        title = a.get("title", "")
        print(f"  {mark} id={a['id']:4d} pool={pool:7s} "
              f"src={src:22s} {title[:60]}")
    return 0


# ── argv ─────────────────────────────────────────────────────────


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)

    pw = sub.add_parser("write", help="Write one translation")
    pw.add_argument("--id", type=int, required=True)
    pw.add_argument("--json-file", required=True,
                    help="Path to JSON with translation payload")
    pw.add_argument("--force", action="store_true",
                    help="Override tag/content mismatch warnings")
    pw.set_defaults(fn=cmd_write)

    ps = sub.add_parser("skip", help="Quarantine one article")
    ps.add_argument("--id", type=int, required=True)
    ps.add_argument("--reason", required=True,
                    help="Why this article isn't relevant today")
    ps.set_defaults(fn=cmd_skip)

    pf = sub.add_parser("finalize", help="Render audio_script.md")
    pf.add_argument("--date", default="today")
    pf.add_argument("--allow-pending", action="store_true",
                    help="Allow finalizing while some articles are still "
                         "untranslated and unskipped")
    pf.set_defaults(fn=cmd_finalize)

    pst = sub.add_parser("status", help="Show selected.json progress")
    pst.set_defaults(fn=cmd_status)

    args = p.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
