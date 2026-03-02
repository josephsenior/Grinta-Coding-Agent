"""Tests for backend.events.serialization.utils — remove_fields helper."""

from typing import Any, cast

import pytest

from backend.events.serialization.utils import remove_fields


class TestRemoveFields:
    """Tests for the remove_fields utility."""

    def test_remove_single_field(self):
        obj = {"a": 1, "b": 2, "c": 3}
        remove_fields(obj, {"b"})
        assert obj == {"a": 1, "c": 3}

    def test_remove_multiple_fields(self):
        obj = {"a": 1, "b": 2, "c": 3, "d": 4}
        remove_fields(obj, {"b", "d"})
        assert obj == {"a": 1, "c": 3}

    def test_remove_nonexistent_field(self):
        """Removing a field that doesn't exist should not raise."""
        obj = {"a": 1}
        remove_fields(obj, {"x", "y"})
        assert obj == {"a": 1}

    def test_nested_dict(self):
        """Should recursively remove fields from nested dicts."""
        obj = {
            "keep": 1,
            "remove_me": 2,
            "nested": {
                "keep": 10,
                "remove_me": 20,
            },
        }
        remove_fields(obj, {"remove_me"})
        assert obj == {"keep": 1, "nested": {"keep": 10}}

    def test_list_of_dicts(self):
        """Should recursively process lists of dicts."""
        obj = [
            {"a": 1, "b": 2},
            {"a": 3, "b": 4},
        ]
        remove_fields(obj, {"b"})
        assert obj == [{"a": 1}, {"a": 3}]

    def test_dict_with_list_values(self):
        """Should process list values within dicts."""
        obj = {
            "items": [
                {"keep": 1, "drop": 2},
                {"keep": 3, "drop": 4},
            ],
            "drop": 99,
        }
        remove_fields(obj, {"drop"})
        assert obj == {"items": [{"keep": 1}, {"keep": 3}]}

    def test_tuple_of_dicts(self):
        """Should process tuples of dicts."""
        obj = ({"a": 1, "b": 2}, {"a": 3, "b": 4})
        remove_fields(obj, {"b"})
        # Dicts inside the tuple should have 'b' removed
        assert obj[0] == {"a": 1}
        assert obj[1] == {"a": 3}

    def test_deeply_nested(self):
        """Should handle deeply nested structures."""
        obj = {
            "level1": {
                "level2": {
                    "level3": {
                        "keep": "yes",
                        "drop": "no",
                    },
                    "drop": "no",
                },
            },
        }
        remove_fields(obj, {"drop"})
        assert obj == {"level1": {"level2": {"level3": {"keep": "yes"}}}}

    def test_empty_dict(self):
        obj: dict[str, Any] = {}
        remove_fields(obj, {"a"})
        assert obj == {}

    def test_empty_list(self):
        obj: list[Any] = []
        remove_fields(obj, {"a"})
        assert obj == []

    def test_empty_fields_set(self):
        obj = {"a": 1, "b": 2}
        remove_fields(obj, set())
        assert obj == {"a": 1, "b": 2}

    def test_raises_on_dataclass(self):
        """Should raise ValueError if object has __dataclass_fields__."""
        from dataclasses import dataclass

        @dataclass
        class Dummy:
            x: int = 1

        with pytest.raises(ValueError, match="dataclass"):
            remove_fields(cast(Any, Dummy()), {"x"})

    def test_non_dict_non_list_noop(self):
        """Non-dict/list/tuple values are ignored (no error)."""
        # Passing a primitive should not raise
        remove_fields(cast(Any, 42), {"a"})
        remove_fields(cast(Any, "hello"), {"a"})
        remove_fields(cast(Any, None), {"a"})
