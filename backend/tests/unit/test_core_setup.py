"""Tests for backend.core.setup — generate_sid and filter_plugins_by_config."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.core.setup import generate_sid


class TestGenerateSid:
    def _fake_config(self):
        return SimpleNamespace()

    def test_returns_string(self):
        sid = generate_sid(self._fake_config())
        assert isinstance(sid, str)

    def test_max_length_32(self):
        sid = generate_sid(self._fake_config())
        assert len(sid) <= 32

    def test_deterministic_with_same_name(self):
        cfg = self._fake_config()
        sid1 = generate_sid(cfg, session_name="test-session")
        sid2 = generate_sid(cfg, session_name="test-session")
        assert sid1 == sid2

    def test_different_names_different_sids(self):
        cfg = self._fake_config()
        sid1 = generate_sid(cfg, session_name="session-a")
        sid2 = generate_sid(cfg, session_name="session-b")
        assert sid1 != sid2

    def test_short_name_included(self):
        cfg = self._fake_config()
        sid = generate_sid(cfg, session_name="abc")
        assert sid.startswith("abc-")

    def test_long_name_truncated(self):
        cfg = self._fake_config()
        long_name = "a" * 50
        sid = generate_sid(cfg, session_name=long_name)
        assert len(sid) <= 32
        assert sid.startswith("a" * 16)

    def test_without_session_name_uses_uuid(self):
        cfg = self._fake_config()
        sid = generate_sid(cfg)
        assert len(sid) <= 32
        assert "-" in sid
