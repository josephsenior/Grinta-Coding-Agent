"""Tests for backend/runtime/utils/windows_exceptions.py."""

from __future__ import annotations

import pytest

from backend.execution.utils.windows_exceptions import DotNetMissingError


class TestDotNetMissingError:
    # ── Inheritance ─────────────────────────────────────────────────

    def test_is_exception_subclass(self) -> None:
        assert issubclass(DotNetMissingError, Exception)

    # ── Construction ────────────────────────────────────────────────

    def test_stores_message(self) -> None:
        err = DotNetMissingError("missing .NET")
        assert err.message == "missing .NET"

    def test_details_defaults_to_none(self) -> None:
        err = DotNetMissingError("msg")
        assert err.details is None

    def test_stores_details_when_provided(self) -> None:
        err = DotNetMissingError("msg", details="install dotnet 8")
        assert err.details == "install dotnet 8"

    def test_str_is_message(self) -> None:
        err = DotNetMissingError("installation required")
        assert str(err) == "installation required"

    # ── Raising / catching ───────────────────────────────────────────

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(DotNetMissingError) as exc_info:
            raise DotNetMissingError("dotnet not found")
        assert exc_info.value.message == "dotnet not found"

    def test_caught_as_exception(self) -> None:
        with pytest.raises(Exception):
            raise DotNetMissingError("no .NET")

    def test_with_details_raised_correctly(self) -> None:
        with pytest.raises(DotNetMissingError) as exc_info:
            raise DotNetMissingError("error", details="detail text")
        assert exc_info.value.details == "detail text"

    # ── args are preserved via super().__init__ ──────────────────────

    def test_args_contain_message(self) -> None:
        err = DotNetMissingError("some message", details="detail")
        assert err.args == ("some message",)

    def test_empty_message(self) -> None:
        err = DotNetMissingError("")
        assert err.message == ""
        assert str(err) == ""
