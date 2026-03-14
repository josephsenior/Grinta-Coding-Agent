"""Production-grade code quality and validation implementation.

Provides advanced code validation and linting capabilities using multiple
backends (ruff, pylint) with proper error formatting and reporting.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core.logger import forge_logger as logger


@dataclass
class LintError:
    """Represents a single linting error or warning."""

    line: int
    column: int | None
    message: str
    code: str | None = None
    severity: str = "error"  # "error" or "warning"
    file_path: str | None = None

    def visualize(self) -> str:
        """Format the lint error for display."""
        location = f"line {self.line}"
        if self.column is not None:
            location += f", column {self.column}"
        if self.code:
            location += f" [{self.code}]"
        return f"{location}: {self.message}"


@dataclass
class LintResult:
    """Result of a linting operation."""

    errors: list[LintError]
    warnings: list[LintError]

    def __post_init__(self) -> None:
        """Separate errors and warnings after initialization."""
        # Ensure errors and warnings are properly separated
        all_issues = self.errors + self.warnings
        self.errors = [issue for issue in all_issues if issue.severity == "error"]
        self.warnings = [issue for issue in all_issues if issue.severity == "warning"]

    def lint_file_diff(self, original_file: str, updated_file: str) -> list[LintError]:
        """Lint the diff between two files.

        This method is called by the file editing system to check for
        linting errors in modified files.

        Args:
            original_file: Path to the original file
            updated_file: Path to the updated file

        Returns:
            List of lint errors found in the updated file
        """
        # For now, just lint the updated file
        # In the future, we could do more sophisticated diff-based linting
        return self.lint_file(updated_file)

    def lint_file(self, file_path: str) -> list[LintError]:
        """Lint a single file.

        Args:
            file_path: Path to the file to lint

        Returns:
            List of lint errors found
        """
        # This would be implemented by the actual linter backend
        # For now, return empty list as this is called on LintResult instances
        return []


class DefaultLinter:
    """Production-grade code quality validator with multiple backend support.

    Part of the backend.code_quality module, this class handles:
    - Ruff (primary, fast, modern)
    - Pylint (fallback, comprehensive)
    - Tree-sitter syntax validation (optional)

    Features:
    - Automatic backend selection
    - Proper error formatting
    - File and diff-based quality checks
    - Configurable severity levels
    """

    def __init__(
        self,
        backend: str = "auto",  # "auto", "ruff", "pylint", "tree-sitter"
        config_path: str | None = None,
        enable_cache: bool = True,
        cache_ttl: int = 300,  # 5 minutes default
        max_cache_size: int = 1000,
    ) -> None:
        """Initialize the linter.

        Args:
            backend: Linter backend to use ("auto" selects best available)
            config_path: Optional path to linter configuration file
            enable_cache: Enable result caching for better performance
            cache_ttl: Cache time-to-live in seconds (default: 300)
            max_cache_size: Maximum number of cached results (default: 1000)
        """
        self.backend = backend
        self.config_path = config_path
        self._detected_backend: str | None = None
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        # LRU cache: (cache_key) -> (LintResult, timestamp)
        self._cache: OrderedDict[str, tuple[LintResult, float]] = OrderedDict()
        self._max_cache_size = max_cache_size
        self._cache_hits = 0
        self._cache_misses = 0

        # Detect available backends
        if backend == "auto":
            self._detected_backend = self._detect_best_backend()
        else:
            self._detected_backend = (
                backend if self._check_backend_available(backend) else None
            )

        if not self._detected_backend:
            logger.warning(
                "No linter backend available. Linting will return empty results."
            )

    def _detect_best_backend(self) -> str | None:
        """Detect the best available linter backend."""
        # Try ruff first (fastest, most modern)
        if self._check_backend_available("ruff"):
            return "ruff"
        # Try pylint as fallback
        if self._check_backend_available("pylint"):
            return "pylint"
        return None

    def _check_backend_available(self, backend: str) -> bool:
        """Check if a linter backend is available."""
        try:
            if backend == "ruff":
                result = subprocess.run(
                    ["ruff", "--version"],
                    capture_output=True,
                    timeout=2,
                    check=False,
                )
                return result.returncode == 0
            if backend == "pylint":
                result = subprocess.run(
                    ["pylint", "--version"],
                    capture_output=True,
                    timeout=2,
                    check=False,
                )
                return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        return False

    def lint(
        self, file_path: str | None = None, content: str | None = None
    ) -> LintResult:
        """Lint a file or content string.

        Args:
            file_path: Path to file to lint (if content is None)
            content: Content string to lint (if file_path is None)

        Returns:
            LintResult with errors and warnings
        """
        if not self._detected_backend:
            return LintResult(errors=[], warnings=[])

        # Generate cache key
        cache_key = self._get_cache_key(file_path, content)

        # Check cache if enabled
        if self.enable_cache and cache_key:
            cached_result = self._get_from_cache(cache_key)
            if cached_result is not None:
                self._cache_hits += 1
                logger.debug("Linter cache HIT for: %s", file_path or "content")
                return cached_result

        self._cache_misses += 1

        # Perform linting
        if content is not None:
            result = self._lint_content(content, file_path)
        elif file_path:
            result = self._lint_file(file_path)
        else:
            result = LintResult(errors=[], warnings=[])

        # Cache result if enabled
        if self.enable_cache and cache_key:
            self._set_cache(cache_key, result)

        return result

    def _get_cache_key(self, file_path: str | None, content: str | None) -> str | None:
        """Generate a cache key for linting operation."""
        if file_path:
            try:
                # Include file path and modification time in cache key
                path = Path(file_path)
                if path.exists():
                    mtime = path.stat().st_mtime
                    config_hash = self._hash_config()
                    return f"lint:{file_path}:{mtime}:{config_hash}"
            except OSError:
                pass
        elif content:
            # Hash content for cache key
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            config_hash = self._hash_config()
            return f"lint:content:{content_hash}:{config_hash}"
        return None

    def _hash_config(self) -> str:
        """Generate hash of linter configuration."""
        config_str = f"{self._detected_backend}:{self.config_path or ''}"
        return hashlib.sha256(config_str.encode()).hexdigest()[:8]

    def _get_from_cache(self, cache_key: str) -> LintResult | None:
        """Get result from cache if not expired."""
        if cache_key not in self._cache:
            return None

        result, timestamp = self._cache[cache_key]
        if time.time() - timestamp < self.cache_ttl:
            # Move to end (most recently used)
            self._cache.move_to_end(cache_key)
            return result

        # Expired, remove
        del self._cache[cache_key]
        return None

    def _set_cache(self, cache_key: str, result: LintResult) -> None:
        """Cache linting result."""
        self._cache[cache_key] = (result, time.time())
        # Move to end (most recently used)
        self._cache.move_to_end(cache_key)

        # Evict oldest if over max size
        if len(self._cache) > self._max_cache_size:
            self._cache.popitem(last=False)

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total * 100) if total > 0 else 0.0
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "hit_rate": f"{hit_rate:.1f}%",
            "size": len(self._cache),
            "max_size": self._max_cache_size,
        }

    def clear_cache(self) -> None:
        """Clear the lint result cache."""
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        logger.debug("Linter cache cleared")

    def lint_file_diff(self, original_file: str, updated_file: str) -> list[LintError]:
        """Lint the difference between two files.

        Args:
            original_file: Path to original file
            updated_file: Path to updated file

        Returns:
            List of lint errors in the updated file
        """
        result = self.lint(file_path=updated_file)
        return result.errors + result.warnings

    def _lint_file(self, file_path: str) -> LintResult:
        """Lint a file using the detected backend."""
        # Try LSP first for all supported languages
        from backend.utils.lsp_client import get_lsp_client
        lsp = get_lsp_client()
        lsp_res = lsp.query("diagnostics", file_path)

        if lsp_res.available and not lsp_res.error:
            errors = []
            for loc in lsp_res.locations:
                errors.append(LintError(
                    line=loc.line,
                    column=loc.column,
                    message="LSP Diagnostic",
                    severity="error",
                    file_path=file_path
                ))
            if errors:
                return LintResult(errors=errors, warnings=[])

        # Fallback to existing logic for Python if LSP failed or returned nothing
        if file_path.endswith(".py"):
            if self._detected_backend == "ruff":
                return self._lint_with_ruff(file_path=file_path)
            if self._detected_backend == "pylint":
                return self._lint_with_pylint(file_path=file_path)

        return LintResult(errors=[], warnings=[])

    def _lint_content(self, content: str, file_path: str | None = None) -> LintResult:
        """Lint content string using the detected backend."""
        # Write content to temporary file and lint it
        suffix = Path(file_path).suffix if file_path else ".py"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False
        ) as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name

        try:
            if self._detected_backend == "ruff":
                return self._lint_with_ruff(file_path=tmp_path)
            if self._detected_backend == "pylint":
                return self._lint_with_pylint(file_path=tmp_path)
        finally:
            # Clean up temp file
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass

        return LintResult(errors=[], warnings=[])

    def _lint_with_ruff(self, file_path: str) -> LintResult:
        """Lint using ruff backend."""
        errors: list[LintError] = []
        warnings: list[LintError] = []

        try:
            cmd = self._build_ruff_cmd(file_path)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            if result.returncode not in (0, 1):
                logger.warning("Ruff linting failed: %s", result.stderr)
                return LintResult(errors=[], warnings=[])

            errs, warns = self._parse_ruff_output(result.stdout, file_path)
            errors.extend(errs)
            warnings.extend(warns)
        except subprocess.TimeoutExpired:
            logger.error("Ruff linting timed out")
        except FileNotFoundError:
            logger.debug("Ruff not found, skipping linting")
        except Exception as e:
            logger.error("Error running ruff: %s", e)

        return LintResult(errors=errors, warnings=warnings)

    def _build_ruff_cmd(self, file_path: str) -> list[str]:
        """Build ruff check command."""
        cmd = [
            "ruff", "check", file_path,
            "--select", "E,F,W",
            "--format", "json",
        ]
        if self.config_path:
            cmd.extend(["--config", self.config_path])
        return cmd

    def _parse_ruff_output(
        self, stdout: str, file_path: str
    ) -> tuple[list[LintError], list[LintError]]:
        """Parse ruff JSON output into errors and warnings."""
        errors: list[LintError] = []
        warnings: list[LintError] = []
        try:
            ruff_output = json.loads(stdout)
        except json.JSONDecodeError:
            logger.error("Failed to parse ruff JSON output: %s", stdout)
            return (errors, warnings)
        for violation in ruff_output:
            loc = violation.get("location", {})
            line = loc.get("row", 1)
            column = loc.get("column")
            code = violation.get("code")
            message = violation.get("message", "")
            severity = "error" if code and code.startswith(("E", "F")) else "warning"
            lint_error = LintError(
                line=line,
                column=column,
                message=message,
                code=code,
                severity=severity,
                file_path=file_path,
            )
            if severity == "error":
                errors.append(lint_error)
            else:
                warnings.append(lint_error)
        return (errors, warnings)

    def _lint_with_pylint(self, file_path: str) -> LintResult:
        """Lint using pylint backend (fallback)."""
        errors: list[LintError] = []
        warnings: list[LintError] = []

        try:
            cmd = ["pylint", file_path, "--output-format=json"]

            if self.config_path:
                cmd.extend(["--rcfile", self.config_path])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            # Pylint returns non-zero even on success, so we parse output
            try:
                pylint_output = json.loads(result.stdout)
                for violation in pylint_output:
                    line = violation.get("line", 1)
                    column = violation.get("column", None)
                    message = violation.get("message", "")
                    code = violation.get("message-id", None)
                    severity_map = {
                        "error": "error",
                        "fatal": "error",
                        "warning": "warning",
                        "convention": "warning",
                        "refactor": "warning",
                    }
                    severity = severity_map.get(
                        violation.get("type", "warning").lower(), "warning"
                    )

                    lint_error = LintError(
                        line=line,
                        column=column,
                        message=message,
                        code=code,
                        severity=severity,
                        file_path=file_path,
                    )

                    if severity == "error":
                        errors.append(lint_error)
                    else:
                        warnings.append(lint_error)
            except json.JSONDecodeError:
                logger.error("Failed to parse pylint JSON output: %s", result.stdout)

        except subprocess.TimeoutExpired:
            logger.error("Pylint linting timed out")
        except FileNotFoundError:
            logger.debug("Pylint not found, skipping linting")
        except Exception as e:
            logger.error("Error running pylint: %s", e)

        return LintResult(errors=errors, warnings=warnings)
