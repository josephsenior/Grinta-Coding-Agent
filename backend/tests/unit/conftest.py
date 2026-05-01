"""Shared hooks for ``backend/tests/unit``."""

from __future__ import annotations

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
def _restore_os_capabilities_after_test() -> None:
    """Reset :data:`OS_CAPS` after each test (``override_os_capabilities`` is in-process)."""
    yield
    fresh = _os_caps.detect_os_capabilities()
    for name in _OS_CAP_FIELDS:
        object.__setattr__(_os_caps.OS_CAPS, name, getattr(fresh, name))
