from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root in path so `scripts.lib.*` imports resolve
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from scripts.lib.normalize import normalize_url, sanitize_for_tts  # noqa: E402


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
