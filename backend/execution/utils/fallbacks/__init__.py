"""Fallback utilities for cross-platform runtime."""

from backend.execution.utils.fallbacks.file_ops import PythonFileOps
from backend.execution.utils.fallbacks.search import PythonSearcher

__all__ = ["PythonFileOps", "PythonSearcher"]
