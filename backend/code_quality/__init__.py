"""Production-grade code quality and validation module for forge.

Provides advanced code quality checks with multiple backend support (ruff, pylint)
and proper error formatting. Fully self-contained implementation.
"""

from backend.code_quality.linter import DefaultLinter, LintError, LintResult

__all__ = ["DefaultLinter", "LintResult", "LintError"]
