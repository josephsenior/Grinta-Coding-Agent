"""Production-grade code quality and validation module for app.

Provides advanced code quality checks with multiple backend support (ruff, pylint)
and proper error formatting. Fully self-contained implementation.
"""

from backend.validation.code_quality.linter import DefaultLinter, LintError, LintResult

__all__ = ["DefaultLinter", "LintResult", "LintError"]
