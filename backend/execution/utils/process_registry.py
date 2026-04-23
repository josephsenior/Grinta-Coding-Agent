from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Callable, Mapping

from backend.core.logger import app_logger as logger


class TaskCancellationService:
    """Track and hard-kill processes for a single conversation/runtime.

    This must be *session-scoped* (per conversation) to avoid one Stop action
    killing subprocesses belonging to other active sessions.

    Notes:
        - Tracks both `subprocess.Popen` handles and raw PIDs.
        - Raw PID tracking is required for processes spawned indirectly
          (e.g., PowerShell Start-Process, nohup background processes).
    """

    def __init__(self, *, label: str | None = None) -> None:
        self._label = label or "session"
        self._lock = threading.Lock()
        self._active_pids: set[int] = set()
        self._active_processes: dict[int, subprocess.Popen] = {}
        self._kill_callbacks: dict[str, Callable[[], None]] = {}

    def register_kill_callback(self, key: str, callback: Callable[[], None]) -> None:
        """Register a best-effort callback to run during `cancel_all()`.

        Used for session-scoped resources that aren't plain OS PIDs (e.g. tmux session).
        """
        if not key:
            return
        with self._lock:
            self._kill_callbacks[key] = callback

    def unregister_kill_callback(self, key: str) -> None:
        if not key:
            return
        with self._lock:
            self._kill_callbacks.pop(key, None)

    def register_process(self, process: subprocess.Popen) -> None:
        """Register a `Popen` handle for tracking."""
        pid = getattr(process, "pid", None)
        if not pid:
            return
        with self._lock:
            self._active_pids.add(pid)
            self._active_processes[pid] = process
            logger.debug("[TaskCancellationService] Registered process pid=%s", pid)

    def register_pid(self, pid: int) -> None:
        """Register a PID for tracking (when no `Popen` handle exists)."""
        if not pid:
            return
        with self._lock:
            self._active_pids.add(int(pid))
            logger.debug("[TaskCancellationService] Registered pid=%s", pid)

    def unregister_process(self, pid: int) -> None:
        with self._lock:
            self._active_pids.discard(pid)
            self._active_processes.pop(pid, None)
            logger.debug("[TaskCancellationService] Unregistered pid=%s", pid)

    def unregister_pid(self, pid: int) -> None:
        with self._lock:
            self._active_pids.discard(pid)
            logger.debug("[TaskCancellationService] Unregistered pid=%s", pid)

    def snapshot(self) -> Mapping[str, int]:
        """Best-effort snapshot for debugging."""
        with self._lock:
            return {
                "pids": len(self._active_pids),
                "process_handles": len(self._active_processes),
            }

    def cancel_all(self) -> None:
        """Hard kill all registered processes."""
        with self._lock:
            pids = list(self._active_pids)
            processes = dict(self._active_processes)
            callbacks = dict(self._kill_callbacks)
            self._active_pids.clear()
            self._active_processes.clear()
            self._kill_callbacks.clear()

        logger.info(
            "[TaskCancellationService:%s] HARD KILL: terminating %s tracked pids (%s handles)",
            self._label,
            len(pids),
            len(processes),
        )

        # 0) Run any registered kill callbacks (best-effort).
        for key, callback in callbacks.items():
            try:
                logger.warning(
                    "[TaskCancellationService:%s] Running kill callback: %s",
                    self._label,
                    key,
                )
                callback()
            except Exception as exc:
                logger.debug(
                    "[TaskCancellationService:%s] Kill callback failed (%s): %s",
                    self._label,
                    key,
                    exc,
                )

        # 1) Try to kill the tree directly on Windows first
        if os.name == "nt":
            for pid in pids:
                try:
                    self._kill_pid_best_effort(pid)
                except Exception as exc:
                    logger.debug(
                        "Failed to tree-kill %s on Windows: %s",
                        pid,
                        exc,
                    )

        # 2) Standard kill logic for everything else
        for pid, process in processes.items():
            try:
                # If we're on Windows, it should already be dead, but let's be safe
                logger.warning("[TaskCancellationService] Terminating pid=%s", pid)
                process.terminate()
                try:
                    process.wait(timeout=1.0 if os.name != "nt" else 0.1)
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "[TaskCancellationService] Force killing pid=%s", pid
                    )
                    process.kill()
            except Exception as exc:
                logger.error(
                    "[TaskCancellationService:%s] Failed to terminate pid=%s via handle: %s",
                    self._label,
                    pid,
                    exc,
                )

        # 3) Kill remaining raw PIDs (on Non-Windows)
        if os.name != "nt":
            for pid in pids:
                if pid in processes:
                    continue
                self._kill_pid_best_effort(pid)

        logger.info("[TaskCancellationService:%s] Hard kill complete", self._label)

    def _kill_pid_best_effort(self, pid: int) -> None:
        try:
            if os.name == "nt":
                # /T kills the process tree; /F forces termination.
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                logger.warning(
                    "[TaskCancellationService:%s] taskkill pid=%s", self._label, pid
                )
                return

            os.kill(pid, signal.SIGTERM)
            logger.warning(
                "[TaskCancellationService:%s] SIGTERM pid=%s", self._label, pid
            )
            try:
                os.kill(pid, 0)
            except OSError:
                return
            sigkill = getattr(signal, "SIGKILL", None)
            if sigkill is not None:
                os.kill(pid, sigkill)
            logger.warning(
                "[TaskCancellationService:%s] SIGKILL pid=%s", self._label, pid
            )
        except Exception as exc:
            logger.debug(
                "[TaskCancellationService:%s] Best-effort kill failed for pid=%s: %s",
                self._label,
                pid,
                exc,
            )
