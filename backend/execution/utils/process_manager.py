"""Process manager for tracking and cleaning up long-running processes.

Prevents orphaned processes (npm run dev, http.server, etc.) from running
forever after conversation stops.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger
from backend.utils.async_utils import call_sync_from_async

if TYPE_CHECKING:
    pass


@dataclass
class ManagedProcess:
    """Represents a managed long-running process."""

    command: str
    process_name: str  # Simplified - extract main process name (npm, python, etc.)
    started_at: float
    command_id: str


class ProcessManager:
    """Manager for tracking and cleaning up long-running processes.

    Usage:
        manager = ProcessManager()

        # Register process when started
        manager.register_process(command, command_id)

        # Cleanup when conversation stops
        await manager.cleanup_all(runtime)
    """

    def __init__(self):
        """Initialize process tracking structures and async cleanup lock."""
        self._processes: dict[str, ManagedProcess] = {}
        self._cleanup_lock = asyncio.Lock()
        _PM_METRICS._init_if_needed()

    def _extract_process_name(self, command: str) -> str:
        """Extract the main process name from command for pkill.

        Args:
            command: Full command string

        Returns:
            Process name (e.g., 'python', 'npm', 'node')

        """
        cmd_lower = command.lower().strip()

        # Common patterns
        if 'python' in cmd_lower:
            return 'python' if 'python3' not in cmd_lower else 'python3'
        if 'pnpm' in cmd_lower:
            return 'pnpm'
        if 'npm' in cmd_lower:
            return 'npm'
        if 'node' in cmd_lower:
            return 'node'
        if 'yarn' in cmd_lower:
            return 'yarn'

        # Default: first word of command
        return command.split()[0] if command.split() else 'unknown'

    def register_process(
        self,
        command: str,
        command_id: str,
    ) -> None:
        """Register a long-running process for tracking.

        Args:
            command: The command being executed
            command_id: Unique identifier for this command execution

        """
        process_name = self._extract_process_name(command)
        process = ManagedProcess(
            command=command,
            process_name=process_name,
            started_at=time.time(),
            command_id=command_id,
        )
        self._processes[command_id] = process
        logger.info(
            '📝 Registered long-running process: %s (process: %s, ID: %s)',
            command[:80],
            process_name,
            command_id,
        )
        _PM_METRICS.on_register()

    def unregister_process(self, command_id: str) -> None:
        """Unregister a process that has terminated naturally.

        Args:
            command_id: Unique identifier for the command

        """
        if command_id in self._processes:
            process = self._processes.pop(command_id)
            logger.info('✅ Process terminated naturally: %s', process.command[:80])
            _PM_METRICS.on_natural_termination(time.time() - process.started_at)

    async def cleanup_all(
        self, runtime=None, timeout_seconds: int = 5
    ) -> dict[str, bool]:
        """Cleanup all tracked processes using pkill.

        Args:
            runtime: Runtime instance (if available) for executing cleanup commands
            timeout_seconds: Seconds to wait for SIGTERM before SIGKILL

        Returns:
            Dictionary mapping command_id to success status

        """
        async with self._cleanup_lock:
            if not self._processes:
                logger.info('No long-running processes to cleanup')
                return {}

            logger.info(
                '🧹 Starting cleanup of %s long-running processes', len(self._processes)
            )
            results = {}
            to_cleanup = list(self._processes.items())
            _PM_METRICS.on_cleanup_attempts(len(to_cleanup))

            # 🛡️ CRITICAL FIX: Kill by FULL command, not just process name
            # Before: pkill -f 'python' killed ALL python processes (including runtime!)
            # After: Kill each specific command individually
            for cmd_id, process in to_cleanup:
                try:
                    # Step 1: Send SIGTERM (graceful shutdown) using the FULL command
                    logger.info('Sending SIGTERM to process: %s', process.command[:80])
                    if runtime:
                        from backend.ledger.action import CmdRunAction

                        # Escape single quotes in command for safety
                        safe_command = process.command.replace("'", "'\\''")
                        await call_sync_from_async(
                            runtime.run,
                            CmdRunAction(
                                command=f"pkill -TERM -f '{safe_command}' || true"
                            ),
                        )

                    # Step 2: Wait briefly for graceful shutdown
                    await asyncio.sleep(1)  # Reduced from 5s to 1s for faster cleanup

                    # Step 3: Send SIGKILL (force kill) to any remaining instances
                    logger.info('Sending SIGKILL if needed: %s', process.command[:80])
                    if runtime:
                        safe_command = process.command.replace("'", "'\\''")
                        await call_sync_from_async(
                            runtime.run,
                            CmdRunAction(
                                command=f"pkill -9 -f '{safe_command}' || true"
                            ),
                        )
                    _PM_METRICS.on_forced_kill_attempt()

                    logger.info('✅ Terminated process: %s', process.command[:80])
                    results[cmd_id] = True
                    _PM_METRICS.on_cleanup_result(
                        success=True, lifetime_sec=time.time() - process.started_at
                    )

                except Exception as e:
                    logger.error('Error cleaning up process %s: %s', cmd_id, e)
                    results[cmd_id] = False
                    _PM_METRICS.on_cleanup_result(
                        success=False, lifetime_sec=time.time() - process.started_at
                    )

            # Clear all tracked processes
            self._processes.clear()
            _PM_METRICS.on_clear_all()

            logger.info(
                '✅ Cleanup completed. Success: %s/%s',
                sum(results.values()),
                len(results),
            )
            return results

    def get_running_processes(self) -> list[ManagedProcess]:
        """Get list of currently tracked processes.

        Returns:
            List of managed processes

        """
        return list(self._processes.values())

    def count(self) -> int:
        """Get count of tracked processes.

        Returns:
            Number of tracked processes

        """
        return len(self._processes)


class _ProcessManagerMetrics:
    """Thread-safe counters for ProcessManager telemetry."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._initialized = False
        self._data: dict[str, float] = {}

    def _init_if_needed(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self._data = {
                'registered_total': 0,
                'natural_terminations_total': 0,
                'cleanup_attempts_total': 0,
                'cleanup_successes_total': 0,
                'cleanup_failures_total': 0,
                'forced_kill_attempts_total': 0,
                'active_processes': 0,
                'lifetime_ms_sum': 0.0,
                'lifetime_ms_count': 0,
            }
            self._initialized = True

    def on_register(self) -> None:
        self._init_if_needed()
        with self._lock:
            self._data['registered_total'] += 1
            self._data['active_processes'] += 1

    def on_natural_termination(self, lifetime_sec: float) -> None:
        self._init_if_needed()
        with self._lock:
            self._data['natural_terminations_total'] += 1
            self._data['active_processes'] = max(0, self._data['active_processes'] - 1)
            self._data['lifetime_ms_sum'] += max(0.0, float(lifetime_sec) * 1000.0)
            self._data['lifetime_ms_count'] += 1

    def on_cleanup_attempts(self, count: int) -> None:
        self._init_if_needed()
        with self._lock:
            self._data['cleanup_attempts_total'] += max(0, int(count))

    def on_forced_kill_attempt(self) -> None:
        self._init_if_needed()
        with self._lock:
            self._data['forced_kill_attempts_total'] += 1

    def on_cleanup_result(self, success: bool, lifetime_sec: float) -> None:
        self._init_if_needed()
        with self._lock:
            key = 'cleanup_successes_total' if success else 'cleanup_failures_total'
            self._data[key] += 1
            # Active processes decremented per cleaned item
            self._data['active_processes'] = max(0, self._data['active_processes'] - 1)
            self._data['lifetime_ms_sum'] += max(0.0, float(lifetime_sec) * 1000.0)
            self._data['lifetime_ms_count'] += 1

    def on_clear_all(self) -> None:
        # No-op: active_processes handled per item; ensure not negative
        self._init_if_needed()
        with self._lock:
            self._data['active_processes'] = max(0, self._data['active_processes'])

    def snapshot(self) -> dict[str, float]:
        self._init_if_needed()
        with self._lock:
            return dict(self._data)

    def health_snapshot(self) -> dict[str, Any]:
        """Return structured health info for diagnostics."""
        snap = self.snapshot()
        avg_lifetime_ms = (
            snap['lifetime_ms_sum'] / snap['lifetime_ms_count']
            if snap['lifetime_ms_count']
            else 0.0
        )
        return {
            'registered_total': snap['registered_total'],
            'natural_terminations_total': snap['natural_terminations_total'],
            'cleanup_attempts_total': snap['cleanup_attempts_total'],
            'cleanup_successes_total': snap['cleanup_successes_total'],
            'cleanup_failures_total': snap['cleanup_failures_total'],
            'forced_kill_attempts_total': snap['forced_kill_attempts_total'],
            'active_processes': snap['active_processes'],
            'avg_lifetime_ms': avg_lifetime_ms,
            'lifetime_samples': snap['lifetime_ms_count'],
        }


_PM_METRICS = _ProcessManagerMetrics()


def get_process_manager_metrics_snapshot() -> dict[str, float]:
    """Return a snapshot of ProcessManager telemetry counters/gauges."""
    _PM_METRICS._init_if_needed()
    return _PM_METRICS.snapshot()


def get_process_manager_health_snapshot(
    active_processes: list[ManagedProcess] | None = None,
) -> dict[str, Any]:
    """Return a structured health snapshot for the process manager."""
    metrics = _PM_METRICS.health_snapshot()
    processes = [
        {
            'command': proc.command,
            'process_name': proc.process_name,
            'started_at': proc.started_at,
            'command_id': proc.command_id,
            'lifetime_sec': max(0.0, time.time() - proc.started_at),
        }
        for proc in (active_processes or [])
    ]

    warnings = _generate_pm_warnings(metrics, processes)
    severity = _assess_pm_severity(metrics, warnings)
    recommendations = _generate_pm_recommendations(metrics, warnings)

    return {
        'metrics': metrics,
        'tracked_processes': processes,
        'warnings': warnings,
        'severity': severity,
        'recommendations': recommendations,
        'timestamp': time.time(),
    }


def _generate_pm_warnings(metrics: dict[str, Any], processes: list[dict]) -> list[str]:
    """Generate diagnostic warnings based on metrics and active processes."""
    warnings = []
    if metrics['active_processes'] > 0 and not processes:
        warnings.append('active_processes_without_details')
    if metrics['active_processes'] > 5:
        warnings.append('high_active_process_count')
    if metrics['forced_kill_attempts_total'] > 0:
        warnings.append('forced_kill_attempts_detected')
    return warnings


def _assess_pm_severity(metrics: dict[str, Any], warnings: list[str]) -> str:
    """Determine the health severity level."""
    if metrics['cleanup_failures_total'] > 0:
        return 'red'
    if 'forced_kill_attempts_detected' in warnings:
        return 'yellow'
    return 'green'


def _generate_pm_recommendations(
    metrics: dict[str, Any], warnings: list[str]
) -> list[str]:
    """Provide actionable recommendations based on health assessment."""
    recommendations = []
    if 'active_processes_without_details' in warnings:
        recommendations.append('verify_process_tracking_registration_and_cleanup_hooks')
    if 'high_active_process_count' in warnings:
        recommendations.append('review_long_running_command_policy_and_timeouts')
    if 'forced_kill_attempts_detected' in warnings:
        recommendations.append('inspect_graceful_shutdown_paths_before_force_kill')
    if metrics['cleanup_failures_total'] > 0:
        recommendations.append('investigate_runtime_permissions_and_process_ownership')
    return recommendations


__all__ = [
    'ProcessManager',
    'ManagedProcess',
    'get_process_manager_metrics_snapshot',
    'get_process_manager_health_snapshot',
]
