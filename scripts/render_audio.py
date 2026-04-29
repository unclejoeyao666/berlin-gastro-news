#!/usr/bin/env python3
"""Render daily ``audio_script.md`` → ``audio.mp3`` via the TTS cascade.

Pipeline:
  1. Sanitize Markdown for TTS (``lib.normalize.sanitize_for_tts``).
  2. Persist the cleaned text alongside the script as
     ``audio_script.tts.txt`` so a human can always re-synthesize.
  3. Run the cascade in ``lib.tts.synthesize``: edge-tts → MiniMax →
     ``say`` + ffmpeg.
  4. Mirror the result into ``site/public/audio/<date>.mp3``.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.normalize import sanitize_for_tts
from scripts.lib.tts import synthesize

DAILY_ROOT = ROOT / "daily"
SITE_AUDIO = ROOT / "site" / "public" / "audio"


def parse_date(s) -> str:
    if not s or s == "today":
        return datetime.now(timezone(timedelta(hours=2))).strftime("%Y-%m-%d")
    return s


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default="today")
    args = p.parse_args()

    date_str = parse_date(args.date)
    year, month, _ = date_str.split("-")
    day_dir = DAILY_ROOT / year / f"{year}-{month}" / date_str
    script_md = day_dir / "audio_script.md"
    if not script_md.exists():
        print(f"❌ {script_md.relative_to(ROOT)} not found")
        sys.exit(1)

    raw = script_md.read_text(encoding="utf-8")
    plain = sanitize_for_tts(raw)
    plain_txt = day_dir / "audio_script.tts.txt"
    plain_txt.write_text(plain, encoding="utf-8")
    print(f"📝 sanitized {len(raw)} → {len(plain)} chars → "
          f"{plain_txt.relative_to(ROOT)}")

    out_mp3 = day_dir / "audio.mp3"
    log_path = day_dir / ".tts.log"

    try:
        provider = synthesize(plain, out_mp3, log_path=log_path)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        # Keep audio_script.tts.txt + .tts.log on disk for postmortem
        sys.exit(2)

    SITE_AUDIO.mkdir(parents=True, exist_ok=True)
    target = SITE_AUDIO / f"{date_str}.mp3"
    shutil.copy2(out_mp3, target)
    size_kb = target.stat().st_size / 1024
    print(f"✅ {target.relative_to(ROOT)} ({size_kb:.1f} KB) "
          f"via {provider}")

    # Tidy up the cleaned text only on success
    plain_txt.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
