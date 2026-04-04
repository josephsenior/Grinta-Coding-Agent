"""Runtime implementations for App.

This package exposes implementation classes lazily to avoid importing heavy
runtime dependencies unless they are actually used.

Non-local runtime implementations were removed from this branch; the package
now lazily exposes `LocalRuntimeInProcess` only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # Only for static typing
    from backend.execution.drivers.local.local_runtime_inprocess import (
        LocalRuntimeInProcess,
    )


__all__ = ['LocalRuntimeInProcess']


def __getattr__(name: str):
    if name == 'LocalRuntimeInProcess':
        from importlib import import_module

        return getattr(
            import_module('backend.execution.drivers.local.local_runtime_inprocess'),
            'LocalRuntimeInProcess',
        )
    raise AttributeError(name)
