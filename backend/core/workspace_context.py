"""Workspace context helpers — project memory, changelog, and fingerprinting.

Three responsibilities
----------------------
1. **Project memory**: reads/writes ``.forge/context.md`` — a human-editable
   file the agent receives at the start of every session.
2. **Workspace fingerprinting**: detects the project type by probing well-known
   sentinel files so the TUI can display it and pre-populate the context template.
3. **Agent changelog**: appends newline-delimited JSON entries to
   ``.forge/changelog.jsonl`` so the TUI can render an end-of-day summary.

The ``.forge/`` directory is created automatically on first write.
A ``.gitignore`` inside it excludes ``changelog.jsonl`` by default
(the context file is intentionally committed so the whole team benefits).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

# ── Sentinel-file → label mappings ──────────────────────────────────
_FINGERPRINTS: list[tuple[str, str]] = [
    ("pyproject.toml", "Python (Poetry/pyproject)"),
    ("setup.py", "Python (setup.py)"),
    ("setup.cfg", "Python (setup.cfg)"),
    ("requirements.txt", "Python (requirements)"),
    ("Cargo.toml", "Rust"),
    ("package.json", "JavaScript / Node.js"),
    ("go.mod", "Go"),
    ("pom.xml", "Java (Maven)"),
    ("build.gradle", "Java / Kotlin (Gradle)"),
    ("build.gradle.kts", "Kotlin (Gradle)"),
    ("CMakeLists.txt", "C / C++ (CMake)"),
    ("Makefile", "C / C++ (Make)"),
    ("composer.json", "PHP"),
    ("Gemfile", "Ruby"),
    ("mix.exs", "Elixir"),
    ("pubspec.yaml", "Dart / Flutter"),
    ("Dockerfile", "Docker"),
    (".github", "GitHub project"),
]

_FORGE_DIR = ".forge"
_CONTEXT_FILE = "context.md"
_CHANGELOG_FILE = "changelog.jsonl"

_CONTEXT_TEMPLATE = """\
# Project Context

<!-- Forge reads this file at the start of every session. -->
<!-- Describe your project, code conventions, and working preferences. -->
<!-- Changes here take effect immediately on the next session start.  -->

## Project type
{fingerprint}

## How to run tests
<!-- e.g.  pytest -q        /  make test  /  npm test          -->

## How to build / run the server
<!-- e.g.  python start_server.py  /  cargo run  /  npm start   -->

## Code style
<!-- e.g.  Black, 88 chars, single quotes, type-hints required  -->

## Important files to know about
<!-- Files the agent should pay special attention to              -->

## Off-limits
<!-- Files / directories the agent should never modify           -->

## Other notes
<!-- Anything else the agent should know going into every session -->
"""


# ── Directory helpers ────────────────────────────────────────────────

def get_forge_dir(cwd: Path | None = None) -> Path:
    """Return the path to the ``.forge/`` directory for *cwd* (or CWD)."""
    return (cwd or Path.cwd()) / _FORGE_DIR


def ensure_forge_dir(cwd: Path | None = None) -> Path:
    """Create ``.forge/`` (and its ``.gitignore``) if they don't exist."""
    forge_dir = get_forge_dir(cwd)
    forge_dir.mkdir(exist_ok=True)
    gitignore = forge_dir / ".gitignore"
    if not gitignore.exists():
        # Only ignore the volatile changelog; context.md should be committed.
        gitignore.write_text("changelog.jsonl\n", encoding="utf-8")
    return forge_dir


# ── Project memory ───────────────────────────────────────────────────

def read_project_memory(cwd: Path | None = None) -> str | None:
    """Return the contents of ``.forge/context.md``, or *None* if absent/empty."""
    path = get_forge_dir(cwd) / _CONTEXT_FILE
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or None
    except OSError:
        return None


def write_context_template(cwd: Path | None = None) -> Path:
    """Create ``.forge/context.md`` with a starter template if it doesn't exist.

    Returns the path to the file (created or pre-existing).
    """
    forge_dir = ensure_forge_dir(cwd)
    context_path = forge_dir / _CONTEXT_FILE
    if not context_path.exists():
        fingerprint = detect_project_type(cwd)
        context_path.write_text(
            _CONTEXT_TEMPLATE.format(fingerprint=fingerprint),
            encoding="utf-8",
        )
    return context_path


# ── Workspace fingerprinting ─────────────────────────────────────────

def detect_project_type(cwd: Path | None = None) -> str:
    """Return a human-readable description of the project type.

    Probes the directory for well-known sentinel files and returns a
    comma-separated list of detected labels (e.g. ``"Python (Poetry), Docker"``).
    Falls back to ``"Unknown project"`` if nothing is recognised.
    """
    base = cwd or Path.cwd()
    detected: list[str] = []
    for name, label in _FINGERPRINTS:
        if (base / name).exists():
            detected.append(label)
    return ", ".join(detected) if detected else "Unknown project"


def detect_test_runner(cwd: Path | None = None) -> str | None:
    """Best-effort guess at the test runner for this project."""
    base = cwd or Path.cwd()
    if (base / "pytest.ini").exists() or (base / "pyproject.toml").exists():
        return "pytest"
    if (base / "package.json").exists():
        return "npm test"
    if (base / "Cargo.toml").exists():
        return "cargo test"
    if (base / "go.mod").exists():
        return "go test ./..."
    if (base / "Makefile").exists():
        return "make test"
    return None


# ── Agent changelog ──────────────────────────────────────────────────

def append_changelog(
    event_type: str,
    data: dict[str, Any],
    conversation_id: str = "",
    cwd: Path | None = None,
) -> None:
    """Append a structured entry to ``.forge/changelog.jsonl``.

    Failures are silently swallowed — the changelog must never crash the TUI.
    """
    try:
        forge_dir = ensure_forge_dir(cwd)
        changelog_path = forge_dir / _CHANGELOG_FILE
        now = datetime.now(UTC)
        entry: dict[str, Any] = {
            "ts": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "event": event_type,
            "conversation_id": conversation_id,
        }
        entry.update(data)
        with changelog_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass


def read_today_changelog(cwd: Path | None = None) -> list[dict[str, Any]]:
    """Return all changelog entries for today (UTC date)."""
    return _read_changelog_filtered(
        lambda e: e.get("date") == datetime.now(UTC).strftime("%Y-%m-%d"),
        cwd=cwd,
    )


def read_all_changelog(cwd: Path | None = None) -> list[dict[str, Any]]:
    """Return all changelog entries."""
    return _read_changelog_filtered(lambda _: True, cwd=cwd)


def _read_changelog_filtered(
    predicate,
    cwd: Path | None = None,
) -> list[dict[str, Any]]:
    changelog_path = get_forge_dir(cwd) / _CHANGELOG_FILE
    if not changelog_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        for raw in changelog_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
                if predicate(entry):
                    entries.append(entry)
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return entries


# ── Today's summary stats ────────────────────────────────────────────

def today_stats(cwd: Path | None = None) -> dict[str, Any]:
    """Aggregate today's changelog into a stats dict for the home-screen banner."""
    entries = read_today_changelog(cwd)
    sessions: set[str] = set()
    files: set[str] = set()
    edits = 0
    new_files = 0
    total_cost: float = 0.0
    tasks_done = 0
    tasks_error = 0

    for e in entries:
        cid = e.get("conversation_id", "")
        if cid:
            sessions.add(cid)
        ev = e.get("event", "")
        if ev == "file_edit":
            path = e.get("path", "")
            if path:
                files.add(path)
            edits += 1
        elif ev == "file_write":
            path = e.get("path", "")
            if path:
                files.add(path)
            new_files += 1
        elif ev == "cost_update":
            cost = float(e.get("cost", 0.0))
            total_cost = max(total_cost, cost)
        elif ev == "task_finished":
            tasks_done += 1
        elif ev == "task_error":
            tasks_error += 1

    return {
        "sessions": len(sessions),
        "files": len(files),
        "edits": edits,
        "new_files": new_files,
        "total_cost": total_cost,
        "tasks_done": tasks_done,
        "tasks_error": tasks_error,
    }
