"""Bounded I/O helpers for subprocess execution.

``subprocess.Popen.communicate()`` reads the entire stdout/stderr stream into
memory before returning. A misbehaving child (a runaway ``cat`` of a multi-GB
log, a recursive ``find /``, an interactive REPL that floods output) can
exhaust the agent's RAM before the per-observation truncator ever runs.

``bounded_communicate`` reads each stream on a background thread, enforces a
hard byte cap per stream, and kills the child as soon as the cap is exceeded
on either stream. The returned buffers are guaranteed to be at most
``max_bytes_per_stream`` bytes.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

# Default per-stream cap. 8 MiB is large enough for almost any real command
# output and small enough to keep peak agent RSS bounded even under abuse.
DEFAULT_MAX_BYTES_PER_STREAM: int = 8 * 1024 * 1024

_TRUNCATION_MARKER = (
    '\n\n[OUTPUT TRUNCATED: stream exceeded {limit} bytes; '
    'process killed to protect agent memory]\n'
)


@dataclass
class BoundedResult:
    """Outcome of a bounded subprocess read."""

    stdout: str
    stderr: str
    returncode: int
    truncated: bool
    timed_out: bool


def _drain(
    stream,
    buf: bytearray,
    cap: int,
    over_event: threading.Event,
) -> None:
    """Read from ``stream`` into ``buf`` until cap or EOF; signal on overflow."""
    if stream is None:
        return
    try:
        for chunk in iter(lambda: stream.read(64 * 1024), b''):
            if not chunk:
                break
            remaining = cap - len(buf)
            if remaining <= 0:
                over_event.set()
                break
            buf.extend(chunk[:remaining])
            if len(buf) >= cap:
                over_event.set()
                break
    except (ValueError, OSError):
        # Stream closed mid-read; nothing to do.
        return
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _feed_stdin(process: subprocess.Popen, stdin_data: bytes | str | None) -> None:
    """Write optional stdin to a child process and close the pipe.

    ``subprocess.communicate(input=...)`` cannot be used here because it reads
    stdout/stderr into unbounded in-memory buffers. Feeding stdin from a small
    helper thread preserves the important ``communicate`` behavior without
    losing the bounded-reader guarantees.
    """
    if stdin_data is None or process.stdin is None:
        return
    try:
        process.stdin.write(stdin_data)  # type: ignore[arg-type]
        process.stdin.flush()
    except (BrokenPipeError, OSError, TypeError, ValueError):
        return
    finally:
        try:
            process.stdin.close()
        except Exception:
            pass


def _wait_for_bounded_process(
    process: subprocess.Popen,
    over: threading.Event,
    *,
    timeout: float | None,
) -> tuple[int, bool]:
    timed_out = False
    slice_s = 0.25
    elapsed = 0.0
    while True:
        try:
            return process.wait(timeout=slice_s), timed_out
        except subprocess.TimeoutExpired:
            if over.is_set():
                kill_process_tree(process)
                return process.wait(timeout=5), timed_out
            if timeout is None:
                continue
            elapsed += slice_s
            if elapsed < timeout:
                continue
            kill_process_tree(process)
            timed_out = True
            return process.wait(timeout=5), timed_out


def kill_process_tree(process: subprocess.Popen) -> None:
    """Best-effort termination of a subprocess and its children."""
    pid = getattr(process, 'pid', None)
    if not pid:
        return
    if os.name == 'nt':
        try:
            subprocess.run(
                ['taskkill', '/PID', str(pid), '/T', '/F'],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return
        except Exception:
            process.kill()
            return

    killpg = getattr(os, 'killpg', None)
    try:
        if killpg is None:
            raise AttributeError('os.killpg is unavailable on this platform')
        killpg(pid, signal.SIGTERM)
    except Exception:
        with contextlib.suppress(Exception):
            process.terminate()
    try:
        process.wait(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        pass
    sigkill = getattr(signal, 'SIGKILL', None)
    if sigkill is not None and killpg is not None:
        try:
            killpg(pid, sigkill)
            return
        except Exception:
            pass
    with contextlib.suppress(Exception):
        process.kill()


def _decoded_bounded_stream_text(
    buf: bytearray,
    *,
    cap: int,
    encoding: str,
    truncated: bool,
) -> str:
    text = buf.decode(encoding, errors='replace')
    if not truncated or len(buf) < cap:
        return text
    return text + _TRUNCATION_MARKER.format(limit=cap)


def bounded_communicate(
    process: subprocess.Popen,
    timeout: float | None = None,
    max_bytes_per_stream: int = DEFAULT_MAX_BYTES_PER_STREAM,
    encoding: str = 'utf-8',
    stdin_data: bytes | str | None = None,
) -> BoundedResult:
    """Drop-in safer replacement for ``process.communicate(timeout=...)``.

    The child must have been started with ``stdout=PIPE`` and ``stderr=PIPE``
    in **binary** mode (do not pass ``text=True`` to ``Popen``). Decoding is
    handled here so we can count bytes precisely.

    On overflow either stream the process is terminated; on timeout the
    process is terminated and ``timed_out=True`` is set. If ``stdin_data`` is
    provided and the process was started with ``stdin=PIPE``, it is written and
    the pipe is closed from a helper thread.
    """
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    over = threading.Event()

    t_out = threading.Thread(
        target=_drain,
        args=(process.stdout, stdout_buf, max_bytes_per_stream, over),
        daemon=True,
    )
    t_err = threading.Thread(
        target=_drain,
        args=(process.stderr, stderr_buf, max_bytes_per_stream, over),
        daemon=True,
    )
    t_out.start()
    t_err.start()
    t_in: threading.Thread | None = None
    if stdin_data is not None and process.stdin is not None:
        t_in = threading.Thread(
            target=_feed_stdin,
            args=(process, stdin_data),
            daemon=True,
        )
        t_in.start()

    try:
        rc, timed_out = _wait_for_bounded_process(process, over, timeout=timeout)
    finally:
        # Ensure threads exit even if something went wrong.
        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)
        if t_in is not None:
            t_in.join(timeout=1.0)

    truncated = over.is_set()
    out_text = _decoded_bounded_stream_text(
        stdout_buf,
        cap=max_bytes_per_stream,
        encoding=encoding,
        truncated=truncated,
    )
    err_text = _decoded_bounded_stream_text(
        stderr_buf,
        cap=max_bytes_per_stream,
        encoding=encoding,
        truncated=truncated,
    )

    return BoundedResult(
        stdout=out_text,
        stderr=err_text,
        returncode=rc if rc is not None else process.returncode or 0,
        truncated=truncated,
        timed_out=timed_out,
    )


async def _read_async_stream_bounded(
    stream: asyncio.StreamReader | None,
    process: asyncio.subprocess.Process,
    cap: int,
) -> tuple[bytearray, bool]:
    """Read an asyncio subprocess stream until EOF or cap; kill on overflow."""
    buf = bytearray()
    truncated = False
    if stream is None:
        return buf, truncated

    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            return buf, truncated
        remaining = cap - len(buf)
        if remaining <= 0:
            truncated = True
            break
        buf.extend(chunk[:remaining])
        if len(chunk) > remaining or len(buf) >= cap:
            truncated = True
            break

    try:
        process.kill()
    except ProcessLookupError:
        pass
    return buf, truncated


async def _write_async_stdin(
    process: asyncio.subprocess.Process,
    stdin_data: bytes | str | None,
    encoding: str,
) -> None:
    if stdin_data is None or process.stdin is None:
        return
    data = stdin_data.encode(encoding) if isinstance(stdin_data, str) else stdin_data
    try:
        process.stdin.write(data)
        await process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError, OSError):
        return
    finally:
        try:
            process.stdin.close()
            await process.stdin.wait_closed()
        except Exception:
            pass


async def async_bounded_subprocess_exec(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    process_timeout: float | None = None,
    max_bytes_per_stream: int = DEFAULT_MAX_BYTES_PER_STREAM,
    encoding: str = 'utf-8',
    stdin_data: bytes | str | None = None,
) -> BoundedResult:
    """Run a subprocess with asyncio and bounded stdout/stderr buffers."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd is not None else None,
    )
    stdout_task = asyncio.create_task(
        _read_async_stream_bounded(
            process.stdout,
            process,
            max_bytes_per_stream,
        )
    )
    stderr_task = asyncio.create_task(
        _read_async_stream_bounded(
            process.stderr,
            process,
            max_bytes_per_stream,
        )
    )
    stdin_task = asyncio.create_task(_write_async_stdin(process, stdin_data, encoding))

    timed_out = False
    try:
        returncode = await asyncio.wait_for(process.wait(), timeout=process_timeout)
    except TimeoutError:
        timed_out = True
        try:
            process.kill()
        except ProcessLookupError:
            pass
        returncode = await process.wait()

    stdout_buf, stdout_truncated = await stdout_task
    stderr_buf, stderr_truncated = await stderr_task
    await stdin_task
    # Give Proactor pipe transports on Windows a chance to finish close callbacks
    # before callers using short-lived event loops tear the loop down.
    transport = getattr(process, '_transport', None)
    if transport is not None:
        transport.close()
    await asyncio.sleep(0.05)
    truncated = stdout_truncated or stderr_truncated
    return BoundedResult(
        stdout=_decoded_bounded_stream_text(
            stdout_buf,
            cap=max_bytes_per_stream,
            encoding=encoding,
            truncated=stdout_truncated,
        ),
        stderr=_decoded_bounded_stream_text(
            stderr_buf,
            cap=max_bytes_per_stream,
            encoding=encoding,
            truncated=stderr_truncated,
        ),
        returncode=returncode if returncode is not None else process.returncode or 0,
        truncated=truncated,
        timed_out=timed_out,
    )
