"""Tests for bounded subprocess I/O helpers."""

from __future__ import annotations

import subprocess
import sys

import pytest

from backend.execution.utils.bounded_io import (
    DEFAULT_MAX_BYTES_PER_STREAM,
    BoundedResult,
    _decoded_bounded_stream_text,
    _drain,
    async_bounded_subprocess_exec,
    bounded_communicate,
)


def test_decoded_bounded_stream_no_truncation_marker_when_under_cap() -> None:
    text = _decoded_bounded_stream_text(
        bytearray(b'hello'),
        cap=100,
        encoding='utf-8',
        truncated=False,
    )
    assert text == 'hello'


def test_decoded_bounded_stream_appends_marker_when_truncated_and_full() -> None:
    buf = bytearray(b'x' * 10)
    text = _decoded_bounded_stream_text(
        buf,
        cap=10,
        encoding='utf-8',
        truncated=True,
    )
    assert 'OUTPUT TRUNCATED' in text


def test_drain_handles_none_stream() -> None:
    import threading

    over = threading.Event()
    _drain(None, bytearray(), 100, over)
    # no crash


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX echo binary pipes')
def test_bounded_communicate_small_process_posix() -> None:
    proc = subprocess.Popen(
        ['/bin/echo', 'hi'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    result = bounded_communicate(proc, timeout=5.0)
    assert isinstance(result, BoundedResult)
    assert 'hi' in result.stdout
    assert result.timed_out is False


def test_bounded_communicate_windows_cmd_echo() -> None:
    if sys.platform != 'win32':
        pytest.skip('Windows-only')
    proc = subprocess.Popen(
        ['cmd', '/c', 'echo', 'ok'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    result = bounded_communicate(proc, timeout=10.0)
    assert result.returncode == 0
    assert 'ok' in result.stdout.lower()


def test_bounded_communicate_supports_stdin() -> None:
    proc = subprocess.Popen(
        [
            sys.executable,
            '-c',
            'import sys; data = sys.stdin.read(); print(data.upper())',
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    result = bounded_communicate(proc, timeout=10.0, stdin_data=b'hello')
    assert result.returncode == 0
    assert result.stdout.strip() == 'HELLO'


def test_default_cap_constant() -> None:
    assert DEFAULT_MAX_BYTES_PER_STREAM > 1024 * 1024


@pytest.mark.asyncio
async def test_async_bounded_subprocess_exec_supports_stdin() -> None:
    result = await async_bounded_subprocess_exec(
        [
            sys.executable,
            '-c',
            'import sys; data = sys.stdin.read(); print(data.upper())',
        ],
        stdin_data='hello',
        process_timeout=10.0,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == 'HELLO'


@pytest.mark.asyncio
async def test_async_bounded_subprocess_exec_truncates_and_kills() -> None:
    result = await async_bounded_subprocess_exec(
        [
            sys.executable,
            '-c',
            "import sys; sys.stdout.write('x' * 1000000); sys.stdout.flush()",
        ],
        process_timeout=10.0,
        max_bytes_per_stream=1024,
    )

    assert result.truncated is True
    assert 'OUTPUT TRUNCATED' in result.stdout
