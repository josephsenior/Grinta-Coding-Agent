"""Tests for subprocess-safe stdio restoration."""

from __future__ import annotations

import subprocess
import sys
from io import StringIO


class _PrintCaptureLike(StringIO):
    """Minimal Textual-style stdout stand-in without .encoding."""


def test_real_stdio_for_subprocess_restores_streams() -> None:
    from backend.utils.stdio_restore import real_stdio_for_subprocess

    fake = _PrintCaptureLike()
    saved = sys.stdout
    sys.stdout = fake
    try:
        with real_stdio_for_subprocess():
            assert hasattr(sys.stdout, 'encoding')
            proc = subprocess.Popen(
                ['python', '-c', 'print("ok")'],
                stdout=subprocess.PIPE,
                text=True,
            )
            out, _ = proc.communicate(timeout=10)
            assert proc.returncode == 0
            assert 'ok' in out
        assert sys.stdout is fake
    finally:
        sys.stdout = saved


def test_real_stdio_when_dunder_stdout_also_lacks_encoding() -> None:
    from backend.utils.stdio_restore import real_stdio_for_subprocess

    fake = _PrintCaptureLike()
    saved_stdout = sys.stdout
    saved_dunder = sys.__stdout__
    sys.stdout = fake
    sys.__stdout__ = fake
    try:
        with real_stdio_for_subprocess():
            assert isinstance(sys.stdout, object)
            assert hasattr(sys.stdout, 'encoding')
            assert sys.stdout.encoding == 'utf-8'
            proc = subprocess.Popen(
                ['python', '-c', 'print("ok")'],
                stdout=subprocess.PIPE,
                text=True,
            )
            out, _ = proc.communicate(timeout=10)
            assert proc.returncode == 0
            assert 'ok' in out
        assert sys.stdout is fake
    finally:
        sys.stdout = saved_stdout
        sys.__stdout__ = saved_dunder


def test_stdio_encoding_proxy_delegation() -> None:
    from unittest.mock import MagicMock

    from backend.utils.stdio_restore import _StdioEncodingProxy

    mock_inner = MagicMock()
    proxy = _StdioEncodingProxy(mock_inner)

    # 1. Test write
    proxy.write('data')
    mock_inner.write.assert_called_once_with('data')

    # 2. Test flush
    proxy.flush()
    mock_inner.flush.assert_called_once()

    # 3. Test getattr
    mock_inner.isatty.return_value = True
    assert proxy.isatty() is True
    mock_inner.isatty.assert_called_once()
