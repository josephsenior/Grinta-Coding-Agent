"""Tests for backend.events.serialization.utils."""

from __future__ import annotations

import pytest

from backend.events.serialization.utils import remove_fields


class TestRemoveFields:
    def test_dict_removes_fields(self):
        d = {"a": 1, "b": 2, "c": 3}
        remove_fields(d, {"a", "c"})
        assert d == {"b": 2}

    def test_nested_dict(self):
        d = {"outer": {"a": 1, "b": 2}, "c": 3}
        remove_fields(d, {"a", "c"})
        assert d == {"outer": {"b": 2}}

    def test_list_of_dicts(self):
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        remove_fields(data, {"a"})
        assert data == [{"b": 2}, {"b": 4}]

    def test_empty_fields(self):
        d = {"a": 1}
        remove_fields(d, set())
        assert d == {"a": 1}

    def test_missing_fields_no_error(self):
        d = {"a": 1}
        remove_fields(d, {"x", "y"})
        assert d == {"a": 1}

    def test_deeply_nested(self):
        d = {"l1": {"l2": {"target": "remove", "keep": "yes"}}}
        remove_fields(d, {"target"})
        assert d == {"l1": {"l2": {"keep": "yes"}}}

    def test_dataclass_raises(self):
        from dataclasses import dataclass

        @dataclass
        class Foo:
            x: int = 1

        with pytest.raises(ValueError, match="dataclass"):
            remove_fields(Foo(), {"x"})

    def test_tuple_of_dicts(self):
        data = ({"a": 1, "b": 2},)
        remove_fields(data, {"a"})
        assert data[0] == {"b": 2}
