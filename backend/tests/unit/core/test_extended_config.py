"""Tests for backend.core.config.extended_config — ExtendedConfig RootModel."""

from __future__ import annotations

import pytest

from backend.core.config.extended_config import ExtendedConfig


class TestExtendedConfig:
    # ── from_dict / constructor ──────────────────────────────────────

    def test_from_dict_empty(self):
        cfg = ExtendedConfig.from_dict({})
        assert str(cfg) == "ExtendedConfig()"

    def test_from_dict_with_data(self):
        cfg = ExtendedConfig.from_dict({"foo": 1, "bar": "baz"})
        assert cfg["foo"] == 1
        assert cfg["bar"] == "baz"

    def test_constructor(self):
        cfg = ExtendedConfig({"x": 42})
        assert cfg["x"] == 42

    # ── __getitem__ ──────────────────────────────────────────────────

    def test_getitem_missing_raises(self):
        cfg = ExtendedConfig.from_dict({})
        with pytest.raises(KeyError):
            cfg["missing"]

    # ── __getattr__ ──────────────────────────────────────────────────

    def test_getattr_success(self):
        cfg = ExtendedConfig.from_dict({"alpha": 99})
        assert cfg.alpha == 99

    def test_getattr_missing_raises(self):
        cfg = ExtendedConfig.from_dict({})
        with pytest.raises(AttributeError, match="no attribute 'missing'"):
            cfg.missing

    # ── __str__ / __repr__ ───────────────────────────────────────────

    def test_str_contains_values(self):
        cfg = ExtendedConfig.from_dict({"k": "v"})
        s = str(cfg)
        assert "k=" in s
        assert "'v'" in s
        assert "ExtendedConfig(" in s

    def test_repr_same_as_str(self):
        cfg = ExtendedConfig.from_dict({"a": 1})
        assert repr(cfg) == str(cfg)

    # ── round-trip ───────────────────────────────────────────────────

    def test_nested_dict(self):
        cfg = ExtendedConfig.from_dict({"nested": {"inner": True}})
        assert cfg["nested"]["inner"] is True

    def test_list_values(self):
        cfg = ExtendedConfig.from_dict({"items": [1, 2, 3]})
        assert cfg["items"] == [1, 2, 3]
