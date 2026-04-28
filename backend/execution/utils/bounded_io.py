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

import subprocess
import threading
from dataclasses import dataclass

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
                process.kill()
                return process.wait(timeout=5), timed_out
            if timeout is None:
                continue
            elapsed += slice_s
            if elapsed < timeout:
                continue
            process.kill()
            timed_out = True
            return process.wait(timeout=5), timed_out


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
) -> BoundedResult:
    """Drop-in safer replacement for ``process.communicate(timeout=...)``.

    The child must have been started with ``stdout=PIPE`` and ``stderr=PIPE``
    in **binary** mode (do not pass ``text=True`` to ``Popen``). Decoding is
    handled here so we can count bytes precisely.

    On overflow either stream the process is terminated; on timeout the
    process is terminated and ``timed_out=True`` is set.
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

    try:
        rc, timed_out = _wait_for_bounded_process(process, over, timeout=timeout)
    finally:
        # Ensure threads exit even if something went wrong.
        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)

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
