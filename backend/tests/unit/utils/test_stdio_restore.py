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
            assert sys.stdout is getattr(sys, '__stdout__')
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
