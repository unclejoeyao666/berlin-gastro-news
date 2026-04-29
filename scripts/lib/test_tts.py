"""Tests for the TTS cascade — verifies fallback order without making
real network or subprocess calls."""
from pathlib import Path

import pytest

from .tts import synthesize


def _ok_provider(name: str):
    """Build a fake provider that writes a valid mp3 stub and returns True."""
    def fn(text, mp3_path, log_lines=None):
        Path(mp3_path).write_bytes(b"ID3\x03" + b"\x00" * 256)
        if log_lines is not None:
            log_lines.append(f"[fake-{name}] wrote stub")
        return True
    fn.__name__ = f"fake_{name}"
    return fn


def _fail_provider(name: str):
    def fn(text, mp3_path, log_lines=None):
        if log_lines is not None:
            log_lines.append(f"[fake-{name}] simulated failure")
        return False
    fn.__name__ = f"fake_{name}"
    return fn


def test_first_provider_wins(tmp_path):
    out = tmp_path / "audio.mp3"
    name = synthesize(
        "你好",
        out,
        providers=[_ok_provider("edge"),
                   _ok_provider("minimax"),
                   _ok_provider("say")],
    )
    assert name == "fake_edge"
    assert out.exists()


def test_falls_through_to_say(tmp_path):
    out = tmp_path / "audio.mp3"
    log = tmp_path / "tts.log"
    name = synthesize(
        "你好",
        out,
        log_path=log,
        providers=[_fail_provider("edge"),
                   _fail_provider("minimax"),
                   _ok_provider("say")],
    )
    assert name == "fake_say"
    assert out.exists()
    log_content = log.read_text(encoding="utf-8")
    assert "fake_edge" in log_content
    assert "fake_minimax" in log_content
    assert "fake_say" in log_content


def test_all_fail_raises(tmp_path):
    out = tmp_path / "audio.mp3"
    log = tmp_path / "tts.log"
    with pytest.raises(RuntimeError, match="All TTS providers failed"):
        synthesize(
            "你好",
            out,
            log_path=log,
            providers=[_fail_provider("edge"),
                       _fail_provider("minimax"),
                       _fail_provider("say")],
        )
    assert log.exists()


def test_provider_must_produce_meaningful_file(tmp_path):
    """A provider that returns True but writes a tiny file is rejected."""
    def too_small(text, mp3_path, log_lines=None):
        Path(mp3_path).write_bytes(b"x")
        return True
    too_small.__name__ = "fake_small"
    out = tmp_path / "audio.mp3"
    with pytest.raises(RuntimeError):
        synthesize(
            "你好",
            out,
            providers=[too_small],
        )
