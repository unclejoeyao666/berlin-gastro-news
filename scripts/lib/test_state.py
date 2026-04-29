"""Tests for state.py."""
from pathlib import Path

from . import state as st


def test_empty_state_has_all_steps():
    s = st.empty_state("2026-04-30")
    assert s["date"] == "2026-04-30"
    for step in st.STEPS:
        assert s["steps"][step]["status"] == "pending"


def test_load_returns_empty_when_missing(tmp_path):
    p = tmp_path / ".state.json"
    s = st.load(p, "2026-04-30")
    assert s["date"] == "2026-04-30"
    assert all(b["status"] == "pending" for b in s["steps"].values())


def test_save_and_reload_roundtrip(tmp_path):
    p = tmp_path / ".state.json"
    s = st.empty_state("2026-04-30")
    s = st.mark(s, "harvest", "ok", stats={"unplayed": 50})
    st.save(p, s)
    s2 = st.load(p, "2026-04-30")
    assert s2["steps"]["harvest"]["status"] == "ok"
    assert s2["steps"]["harvest"]["stats"]["unplayed"] == 50
    assert s2["steps"]["select"]["status"] == "pending"


def test_load_adds_new_steps_to_old_state(tmp_path):
    """Old state file missing newer steps should still load cleanly."""
    p = tmp_path / ".state.json"
    p.write_text(
        '{"date": "2026-04-30", "steps": '
        '{"harvest": {"status": "ok"}}}',
        encoding="utf-8",
    )
    s = st.load(p, "2026-04-30")
    assert s["steps"]["harvest"]["status"] == "ok"
    assert s["steps"]["push"]["status"] == "pending"


def test_next_pending_walks_in_order():
    s = st.empty_state("2026-04-30")
    assert st.next_pending(s) == "harvest"
    s = st.mark(s, "harvest", "ok")
    assert st.next_pending(s) == "select"
    s = st.mark(s, "select", "ok")
    s = st.mark(s, "translate", "ok")
    assert st.next_pending(s) == "publish_article"


def test_next_pending_with_from_step():
    s = st.empty_state("2026-04-30")
    s = st.mark(s, "harvest", "ok")
    s = st.mark(s, "select", "ok")
    assert st.next_pending(s, from_step="audio") == "audio"


def test_next_pending_returns_none_when_all_done():
    s = st.empty_state("2026-04-30")
    for step in st.STEPS:
        s = st.mark(s, step, "ok")
    assert st.next_pending(s) is None


def test_failed_step_is_not_done():
    s = st.empty_state("2026-04-30")
    s = st.mark(s, "harvest", "failed", error="boom")
    assert not st.is_done(s, "harvest")
    assert st.next_pending(s) == "harvest"


def test_corrupt_state_file_rebuilds(tmp_path):
    p = tmp_path / ".state.json"
    p.write_text("{ this is not json", encoding="utf-8")
    s = st.load(p, "2026-04-30")
    assert all(b["status"] == "pending" for b in s["steps"].values())


def test_reset_running_demotes_in_flight_steps(tmp_path):
    s = st.empty_state("2026-04-30")
    s = st.mark(s, "harvest", "ok")
    s = st.mark(s, "select", "running")
    reset = st.reset_running(s)
    assert reset == ["select"]
    assert s["steps"]["select"]["status"] == "pending"
    assert "started_at" not in s["steps"]["select"]
    assert s["steps"]["harvest"]["status"] == "ok"


def test_save_is_atomic_no_temp_left_behind(tmp_path):
    """A successful save must leave only ``.state.json`` in the dir."""
    p = tmp_path / ".state.json"
    s = st.empty_state("2026-04-30")
    st.save(p, s)
    files = sorted(x.name for x in tmp_path.iterdir())
    assert files == [".state.json"]


def test_save_overwrites_existing_file(tmp_path):
    p = tmp_path / ".state.json"
    st.save(p, st.empty_state("2026-04-30"))
    s = st.empty_state("2026-04-30")
    s = st.mark(s, "harvest", "ok", stats={"x": 1})
    st.save(p, s)
    reloaded = st.load(p, "2026-04-30")
    assert reloaded["steps"]["harvest"]["status"] == "ok"
    assert reloaded["steps"]["harvest"]["stats"]["x"] == 1
