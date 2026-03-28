"""Tests for scratchpad persistence and prompt ordering."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backend.engine.tools import note as m


@pytest.fixture
def scratchpad_root(tmp_path, monkeypatch):
    """Isolate scratchpad under tmp_path/.forge/agent_notes.json."""
    monkeypatch.setattr(
        "backend.core.workspace_resolution.get_effective_workspace_root",
        lambda: tmp_path,
    )
    return tmp_path


def test_legacy_flat_file_no_meta_sorts_alphabetically(scratchpad_root):
    d = scratchpad_root / ".forge"
    d.mkdir(parents=True)
    (d / "agent_notes.json").write_text(
        json.dumps({"zebra": "z", "alpha": "a"}),
        encoding="utf-8",
    )
    out = m.scratchpad_entries_for_prompt()
    assert out == [("alpha", "a"), ("zebra", "z")]


def test_timestamps_newest_first(scratchpad_root):
    d = scratchpad_root / ".forge"
    d.mkdir(parents=True)
    blob = {
        "first": "1",
        "second": "2",
        m._SCRATCHPAD_META_KEY: {"updated": {"first": 1.0, "second": 100.0}},
    }
    (d / "agent_notes.json").write_text(json.dumps(blob), encoding="utf-8")
    out = m.scratchpad_entries_for_prompt()
    assert [k for k, _ in out] == ["second", "first"]


def test_casefold_dedupe_keeps_newer_timestamp(scratchpad_root):
    d = scratchpad_root / ".forge"
    d.mkdir(parents=True)
    blob = {
        "Auth": "old",
        "auth": "new",
        m._SCRATCHPAD_META_KEY: {"updated": {"Auth": 100.0, "auth": 200.0}},
    }
    (d / "agent_notes.json").write_text(json.dumps(blob), encoding="utf-8")
    out = m.scratchpad_entries_for_prompt()
    assert len(out) == 1
    assert out[0][1] == "new"


def test_build_note_writes_meta_and_roundtrip(scratchpad_root):
    with patch(
        "backend.engine.tools.note.time.time",
        side_effect=[10.0, 20.0],
    ):
        m.build_note_action("k1", "v1")
        m.build_note_action("k2", "v2")
    notes = m._load_notes()
    assert notes == {"k1": "v1", "k2": "v2"}
    ordered = m.scratchpad_entries_for_prompt()
    assert [x[0] for x in ordered] == ["k2", "k1"]
