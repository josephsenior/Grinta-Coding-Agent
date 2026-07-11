"""Shared hooks for ``backend/tests/unit``."""

from __future__ import annotations

import typing

import pytest

from backend.core import os_capabilities as _os_caps

_OS_CAP_FIELDS = (
    'is_windows',
    'is_posix',
    'is_linux',
    'is_macos',
    'shell_kind',
    'supports_pty',
    'signal_strategy',
    'path_sep',
    'default_python_exec',
    'sys_platform',
    'os_name',
)


@pytest.fixture(autouse=True)
def _clear_env_before_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear Grinta environment variables before each test to ensure deterministic behavior."""
    for key in (
        'GRINTA_ALLOW_SHELL_WRITES',
        'PROJECT_ROOT',
        'APP_PROJECT_ROOT',
        'GRINTA_INVOCATION_CWD',
        'GRINTA_LOG_ROOT',
        'GRINTA_REPO_ROOT',
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _restore_os_capabilities_after_test() -> typing.Generator[None, None, None]:
    """Reset :data:`OS_CAPS` after each test (``override_os_capabilities`` is in-process)."""
    yield
    fresh = _os_caps.detect_os_capabilities()
    for name in _OS_CAP_FIELDS:
        object.__setattr__(_os_caps.OS_CAPS, name, getattr(fresh, name))


@pytest.fixture(autouse=True)
def _reset_session_event_logger_state() -> typing.Generator[None, None, None]:
    """Reset the process-wide session event logger between tests to prevent
    the bound ``_SESSION_ID`` from leaking across test boundaries.
    """
    from backend.core.logging import session_event_logger as sel_mod

    saved = sel_mod._SESSION_ID
    sel_mod._SESSION_ID = None
    try:
        yield
    finally:
        sel_mod._SESSION_ID = saved
