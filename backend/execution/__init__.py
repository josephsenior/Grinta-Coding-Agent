"""Runtime and supporting infrastructure for App agents.

This module provides the Runtime interface and its implementations.
In this version, only LocalRuntimeInProcess is supported.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from backend.execution.base import Runtime
from backend.execution.orchestrator import (
    RuntimeAcquireResult,
    RuntimeOrchestrator,
    runtime_orchestrator,
)
from backend.execution.runtime_factory import get_runtime_cls
from backend.execution.runtime_pool import (
    PooledRuntime,
    RuntimePool,
    SingleUseRuntimePool,
    WarmPoolPolicy,
    WarmRuntimePool,
)
from backend.execution.watchdog import runtime_watchdog
from backend.utils.import_utils import get_impl

if TYPE_CHECKING:  # Only for static type checking
    from backend.execution.drivers.local.local_runtime_inprocess import (
        LocalRuntimeInProcess,
    )


def _lazy_import(module_path: str, attr: str) -> Any:
    module = importlib.import_module(module_path)
    return getattr(module, attr)


__all__ = [
    'PooledRuntime',
    'LocalRuntimeInProcess',
    'RuntimeExecutor',
    'RuntimePool',
    'Runtime',
    'RuntimeOrchestrator',
    'RuntimeAcquireResult',
    'runtime_orchestrator',
    'runtime_watchdog',
    'SingleUseRuntimePool',
    'WarmPoolPolicy',
    'WarmRuntimePool',
    'get_runtime_cls',
    'get_impl',
]


def __getattr__(name: str) -> Any:  # Lazy access to runtime classes
    if name == 'LocalRuntimeInProcess':
        return _lazy_import(
            'backend.execution.drivers.local.local_runtime_inprocess',
            'LocalRuntimeInProcess',
        )
    if name == 'RuntimeExecutor':
        return _lazy_import(
            'backend.execution.action_execution_server',
            'RuntimeExecutor',
        )
    raise AttributeError(name)
