"""Tests for backend.api.session lazy exports."""

from __future__ import annotations

import pytest


def test_session_package_getattr_returns_session_class() -> None:
    import backend.api.session as session_pkg

    Session = session_pkg.Session
    from backend.api.session.session import Session as RealSession

    assert Session is RealSession


def test_session_package_unknown_attr_raises() -> None:
    import backend.api.session as session_pkg

    with pytest.raises(AttributeError, match="foo"):
        _ = session_pkg.foo  # type: ignore[attr-defined]
