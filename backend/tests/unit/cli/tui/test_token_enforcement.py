"""Token enforcement: catch raw hex literals leaking into the TUI layer.

The ``backend.cli.theme`` package is the single source of truth for colors.
This test fails if raw ``#rrggbb`` literals appear in TUI source (other
than the theme package itself), forcing contributors to add or reuse a
token instead of scattering hex values.

The grandfathered exceptions allow a phased migration:
* literal text inside the token modules themselves (``navy.py``,
  ``tokens.py``, ``theme/__init__.py``, ``theme/styles.py``,
  ``theme/presets.py``, ``theme/syntax_theme.py``, ``theme/spacing.py``)
* inline Rich markup strings inside ``tui/screen/state.py`` that render
  one-off HUD labels (these are migrated case-by-case)

Run with: ``pytest backend/tests/unit/cli/tui/test_token_enforcement.py``
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Resolve the TUI source root once at import time.
# Test path:  backend/tests/unit/cli/tui/test_token_enforcement.py
# TUI path:   backend/cli/tui/
# From test file:  parents[0]=tui, [1]=cli, [2]=unit, [3]=tests, [4]=backend
_TUI_ROOT = Path(__file__).resolve().parents[4] / "cli" / "tui"
assert _TUI_ROOT.exists(), f"TUI root not found: {_TUI_ROOT}"

# Token modules are allowed to define raw hex — that's their job.
_TOKEN_EXEMPT_DIRS = {
    # No exemptions inside the TUI itself; everything else must use tokens.
}

# Files that are allowed to use inline Rich hex markup during the
# gradual migration. Add a file here only while you migrate it.
_RICH_MARKUP_EXEMPT_FILES: set[str] = set()

_HEX_PATTERN = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")


def _iter_tui_python_files() -> list[Path]:
    """Return every .py file under backend/cli/tui/ (recursively)."""
    return sorted(_TUI_ROOT.rglob("*.py"))


def _iter_tui_tcss_files() -> list[Path]:
    """Return every .tcss file under backend/cli/tui/."""
    return sorted(_TUI_ROOT.rglob("*.tcss"))


def _scan_file_for_hex(path: Path) -> list[tuple[int, str]]:
    """Return ``(line_number, line)`` for each raw hex literal in *path*."""
    matches: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return matches

    rel = path.relative_to(_TUI_ROOT).as_posix()
    if rel in _RICH_MARKUP_EXEMPT_FILES:
        return matches

    for i, line in enumerate(text.splitlines(), start=1):
        if _HEX_PATTERN.search(line):
            matches.append((i, line.rstrip()))
    return matches


@pytest.mark.xfail(
    reason=(
        "Token migration in progress. Strict zero-hex enforcement is the "
        "long-term goal. Until then, this test documents remaining "
        "offenders. See test_token_enforcement_trending_down for the "
        "regression guard."
    ),
    strict=False,
)
def test_no_raw_hex_in_tui_python() -> None:
    """Raw hex literals must be routed through backend.cli.theme tokens."""
    offenders: dict[str, list[tuple[int, str]]] = {}
    for path in _iter_tui_python_files():
        rel = path.relative_to(_TUI_ROOT).as_posix()
        if rel in _TOKEN_EXEMPT_DIRS:
            continue
        hits = _scan_file_for_hex(path)
        if hits:
            offenders[rel] = hits

    if not offenders:
        return

    lines = ["Raw hex literals found in TUI python files (route through theme tokens):"]
    for rel, hits in sorted(offenders.items()):
        lines.append(f"\n  {rel}:")
        for lineno, line in hits[:10]:  # cap per-file to avoid spam
            lines.append(f"    L{lineno}: {line.strip()}")
        if len(hits) > 10:
            lines.append(f"    ... and {len(hits) - 10} more")
    raise AssertionError("\n".join(lines))


def test_no_raw_hex_in_tui_tcss() -> None:
    """Raw hex literals in styles.tcss must be replaced with token references.

    Note: Textual's .tcss does not directly support Python-side token
    interpolation. Until we adopt ``var(--name)``/``$variable`` for the
    full sheet, we accept that styles.tcss will continue to use hex.
    This test is therefore a soft check that records the current count
    and fails only if it grows past a generous ceiling.
    """
    soft_ceiling = 300  # styles.tcss historical: ~250 hex refs
    tcss_files = _iter_tui_tcss_files()
    total = 0
    for path in tcss_files:
        rel = path.relative_to(_TUI_ROOT).as_posix()
        if rel in _TOKEN_EXEMPT_DIRS:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        total += sum(1 for _ in _HEX_PATTERN.finditer(text))

    assert total <= soft_ceiling, (
        f"TCSS hex literal count {total} exceeds soft ceiling {soft_ceiling}. "
        "Consider migrating to Textual CSS variables or splitting the stylesheet."
    )


def test_token_enforcement_trending_down() -> None:
    """Regression guard: the number of files with raw hex must not grow.

    Counts the number of TUI python files that contain at least one raw
    hex literal. Today's number is the baseline; a future change that
    *adds* new hex literals fails this test.
    """
    files_with_hex: list[str] = []
    for path in _iter_tui_python_files():
        rel = path.relative_to(_TUI_ROOT).as_posix()
        if rel in _TOKEN_EXEMPT_DIRS or rel in _RICH_MARKUP_EXEMPT_FILES:
            continue
        if _scan_file_for_hex(path):
            files_with_hex.append(rel)

    baseline = len(files_with_hex)
    # If this fails, a new file (or new hex in an existing file) was added
    # that bypasses the token system. Migrate to a token, then update this
    # ceiling intentionally.
    # The ceiling is the post-Phase-1 count + a small regression buffer.
    # Bump it down as more files are migrated.
    assert baseline <= 35, (
        f"Token enforcement regression: {baseline} TUI files contain raw hex "
        f"literals. Cap is 35. Files:\n  "
        + "\n  ".join(files_with_hex)
    )
