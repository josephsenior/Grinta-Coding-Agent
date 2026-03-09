"""Critic that scores a run by whether the relevant test suite passes after the task."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from backend.core.logger import forge_logger as logger
from backend.review.base import BaseCritic, CriticResult

if TYPE_CHECKING:
    from backend.events import Event


# Patterns that identify test files touched during the session.
_TEST_FILE_RE = re.compile(r"test_.*\.py$|_test\.py$", re.IGNORECASE)


def _extract_touched_files(events: Sequence[Event]) -> list[str]:
    """Return unique file paths mentioned in FileEditActions / CmdRunActions."""
    paths: list[str] = []
    for event in events:
        # FileEditAction stores the target path in .path
        path = getattr(event, "path", None)
        if isinstance(path, str) and path:
            paths.append(path)
    return list(dict.fromkeys(paths))  # deduplicate, preserve order


def _collect_test_dirs(touched: list[str], workspace_root: str) -> list[Path]:
    """Return unique test directories that cover the touched source files."""
    root = Path(workspace_root)
    dirs: list[Path] = []

    # If any touched file is itself a test file, run its directory.
    for p in touched:
        if _TEST_FILE_RE.search(p):
            d = (root / p).parent
            if d.exists() and d not in dirs:
                dirs.append(d)

    # Fallback: look for a tests/ directory alongside each touched source file.
    for p in touched:
        source = root / p
        candidate = source.parent / "tests"
        if candidate.exists() and candidate not in dirs:
            dirs.append(candidate)

    return dirs


def _run_pytest(test_dirs: list[Path], workspace_root: str) -> tuple[int, int, str]:
    """Run pytest on *test_dirs* and return (passed, failed, summary_line)."""
    if not test_dirs:
        return 0, 0, "no tests found"

    cmd = [
        "python", "-m", "pytest",
        *[str(d) for d in test_dirs],
        "--tb=no", "-q", "--no-header",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=workspace_root,
        )
        output = result.stdout + result.stderr
        # Parse "N passed, M failed" from pytest summary line.
        passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
        failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
        # Last non-empty line is the concise summary.
        summary = next((l for l in reversed(output.splitlines()) if l.strip()), "")
        return passed, failed, summary
    except subprocess.TimeoutExpired:
        return 0, 0, "pytest timed out after 120s"
    except Exception as exc:
        logger.debug("TestPassCritic: pytest run failed: %s", exc)
        return 0, 0, f"pytest error: {exc}"


class SuitePassCritic(BaseCritic):
    """Score a run based on test outcomes for files touched during the task.

    Scoring:
      - No relevant tests found → 1.0 (no regressions possible)
      - All tests pass → 1.0
      - Some tests pass → ratio of passed / (passed + failed)
      - All tests fail → 0.0
    """

    def __init__(self, workspace_root: str = ".") -> None:
        self.workspace_root = workspace_root

    def evaluate(
        self, events: Sequence[Event], diff_patch: str | None = None
    ) -> CriticResult:
        touched = _extract_touched_files(events)
        test_dirs = _collect_test_dirs(touched, self.workspace_root)

        if not test_dirs:
            return CriticResult(score=1.0, message="✅ Verification Passed: No relevant tests found; no regressions detected.")

        passed, failed, summary = _run_pytest(test_dirs, self.workspace_root)
        total = passed + failed

        if total == 0:
            return CriticResult(score=1.0, message=f"✅ Verification Passed: Tests ran but no results parsed. Raw: {summary}")

        score = passed / total
        if score == 1.0:
            msg = f"✅ Verification Passed: All {passed} tests passed successfully. {summary}"
        elif score == 0.0:
            msg = f"❌ Verification Failed: {failed} pytest failures detected. Continuing iteration."
        else:
            msg = f"⚠️ Verification Incomplete: {passed}/{total} tests pass ({score * 100:.0f}%). Continuing iteration."

        return CriticResult(score=score, message=msg)
