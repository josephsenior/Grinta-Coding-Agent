"""Workspace context helpers — project memory, changelog, and fingerprinting.

Project memory and changelog live under
``~/.grinta/workspaces/<id>/project_context/`` (not in the repo tree).

Workspace fingerprinting still probes the **code** directory (open project).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ── Sentinel-file → label mappings ──────────────────────────────────
_FINGERPRINTS: list[tuple[str, str]] = [
    ('pyproject.toml', 'Python (uv/pyproject)'),
    ('setup.py', 'Python (setup.py)'),
    ('setup.cfg', 'Python (setup.cfg)'),
    ('requirements.txt', 'Python (requirements)'),
    ('Cargo.toml', 'Rust'),
    ('package.json', 'JavaScript / Node.js'),
    ('go.mod', 'Go'),
    ('pom.xml', 'Java (Maven)'),
    ('build.gradle', 'Java / Kotlin (Gradle)'),
    ('build.gradle.kts', 'Kotlin (Gradle)'),
    ('CMakeLists.txt', 'C / C++ (CMake)'),
    ('Makefile', 'C / C++ (Make)'),
    ('composer.json', 'PHP'),
    ('Gemfile', 'Ruby'),
    ('mix.exs', 'Elixir'),
    ('pubspec.yaml', 'Dart / Flutter'),
    ('Dockerfile', 'Docker'),
    ('.github', 'GitHub project'),
]

_PROJECT_CONTEXT_SEGMENT = 'project_context'
_CONTEXT_FILE = 'context.md'
_CHANGELOG_FILE = 'changelog.jsonl'

_CONTEXT_TEMPLATE = """\
# Project Context

<!-- App reads this file at the start of every session. -->
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


def _workspace_anchor(cwd: Path | None) -> Path:
    """Filesystem anchor for the *code* project (used to derive workspace id).

    Explicit *cwd* wins so call sites can target a project dir; otherwise use the
    open workspace from config / env, then process CWD.
    """
    from backend.core.workspace_resolution import get_effective_workspace_root

    if cwd is not None:
        try:
            return Path(cwd).resolve()
        except OSError:
            return Path(cwd)
    ws = get_effective_workspace_root()
    if ws is not None:
        try:
            return Path(ws).resolve()
        except OSError:
            return Path(ws)
    try:
        return Path.cwd().resolve()
    except OSError:
        return Path.cwd()


def get_project_state_dir(cwd: Path | None = None) -> Path:
    """Return ``~/.grinta/workspaces/<id>/project_context`` for the open project."""
    from backend.core.workspace_resolution import workspace_grinta_root

    anchor = _workspace_anchor(cwd)
    return workspace_grinta_root(anchor) / _PROJECT_CONTEXT_SEGMENT


def ensure_project_state_dir(cwd: Path | None = None) -> Path:
    """Create project context dir (and ``.gitignore``) if missing."""
    project_state_dir = get_project_state_dir(cwd)
    project_state_dir.mkdir(parents=True, exist_ok=True)
    gitignore = project_state_dir / '.gitignore'
    if not gitignore.exists():
        gitignore.write_text('changelog.jsonl\ndownloads/\n', encoding='utf-8')
    return project_state_dir


# ── Project memory ───────────────────────────────────────────────────


def read_project_memory(cwd: Path | None = None) -> str | None:
    """Return the contents of ``.app/context.md``, or *None* if absent/empty."""
    path = get_project_state_dir(cwd) / _CONTEXT_FILE
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding='utf-8').strip()
        return text or None
    except OSError:
        return None


def write_context_template(cwd: Path | None = None) -> Path:
    """Create ``.app/context.md`` with a starter template if it doesn't exist.

    Returns the path to the file (created or pre-existing).
    """
    project_state_dir = ensure_project_state_dir(cwd)
    context_path = project_state_dir / _CONTEXT_FILE
    if not context_path.exists():
        fingerprint = detect_project_type(cwd)
        context_path.write_text(
            _CONTEXT_TEMPLATE.format(fingerprint=fingerprint),
            encoding='utf-8',
        )
    return context_path


# ── Workspace fingerprinting ─────────────────────────────────────────


def detect_project_type(cwd: Path | None = None) -> str:
    """Return a human-readable description of the project type.

    Probes the directory for well-known sentinel files and returns a
    comma-separated list of detected labels (e.g. ``"Python (uv), Docker"``).
    Falls back to ``"Unknown project"`` if nothing is recognised.
    """
    base = cwd or Path.cwd()
    detected: list[str] = []
    for name, label in _FINGERPRINTS:
        if (base / name).exists():
            detected.append(label)
    return ', '.join(detected) if detected else 'Unknown project'


def detect_test_runner(cwd: Path | None = None) -> str | None:
    """Best-effort guess at the test runner for this project."""
    base = cwd or Path.cwd()
    if (base / 'pytest.ini').exists() or (base / 'pyproject.toml').exists():
        return 'pytest'
    if (base / 'package.json').exists():
        return 'npm test'
    if (base / 'Cargo.toml').exists():
        return 'cargo test'
    if (base / 'go.mod').exists():
        return 'go test ./...'
    if (base / 'Makefile').exists():
        return 'make test'
    return None


# ── Agent changelog ──────────────────────────────────────────────────


def append_changelog(
    event_type: str,
    data: dict[str, Any],
    conversation_id: str = '',
    cwd: Path | None = None,
) -> None:
    """Append a structured entry to ``.app/changelog.jsonl``.

    Failures are silently swallowed — the changelog must never crash the app.
    """
    try:
        project_state_dir = ensure_project_state_dir(cwd)
        changelog_path = project_state_dir / _CHANGELOG_FILE
        now = datetime.now(UTC)
        entry: dict[str, Any] = {
            'ts': now.isoformat(),
            'date': now.strftime('%Y-%m-%d'),
            'event': event_type,
            'conversation_id': conversation_id,
        }
        entry.update(data)
        with changelog_path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, default=str) + '\n')
    except Exception:  # noqa: BLE001
        pass


def read_today_changelog(cwd: Path | None = None) -> list[dict[str, Any]]:
    """Return all changelog entries for today (UTC date)."""
    return _read_changelog_filtered(
        lambda e: e.get('date') == datetime.now(UTC).strftime('%Y-%m-%d'),
        cwd=cwd,
    )


def read_week_changelog(cwd: Path | None = None) -> list[dict[str, Any]]:
    """Return all changelog entries from the past 7 days (UTC)."""
    from datetime import timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=6)).strftime('%Y-%m-%d')
    return _read_changelog_filtered(
        lambda e: e.get('date', '') >= cutoff,
        cwd=cwd,
    )


def read_month_changelog(cwd: Path | None = None) -> list[dict[str, Any]]:
    """Return all changelog entries from the current calendar month (UTC)."""
    prefix = datetime.now(UTC).strftime('%Y-%m')
    return _read_changelog_filtered(
        lambda e: e.get('date', '').startswith(prefix),
        cwd=cwd,
    )


def read_all_changelog(cwd: Path | None = None) -> list[dict[str, Any]]:
    """Return all changelog entries."""
    return _read_changelog_filtered(lambda _: True, cwd=cwd)


def _read_changelog_filtered(
    predicate,
    cwd: Path | None = None,
) -> list[dict[str, Any]]:
    changelog_path = get_project_state_dir(cwd) / _CHANGELOG_FILE
    if not changelog_path.exists():
        return []
    entries: list[dict[str, Any]] = []
    try:
        for raw in changelog_path.read_text(encoding='utf-8').splitlines():
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
        cid = e.get('conversation_id', '')
        if cid:
            sessions.add(cid)
        ev = e.get('event', '')
        if ev == 'file_edit':
            path = e.get('path', '')
            if path:
                files.add(path)
            edits += 1
        elif ev == 'file_write':
            path = e.get('path', '')
            if path:
                files.add(path)
            new_files += 1
        elif ev == 'cost_update':
            cost = float(e.get('cost', 0.0))
            total_cost = max(total_cost, cost)
        elif ev == 'task_finished':
            tasks_done += 1
        elif ev == 'task_error':
            tasks_error += 1

    return {
        'sessions': len(sessions),
        'files': len(files),
        'edits': edits,
        'new_files': new_files,
        'total_cost': total_cost,
        'tasks_done': tasks_done,
        'tasks_error': tasks_error,
    }


def today_total_cost(cwd: Path | None = None) -> float:
    """Return the total LLM cost accumulated today (UTC) across all sessions.

    Reads the changelog and computes the max per-session cost then sums them.
    """
    entries = read_today_changelog(cwd)
    session_max: dict[str, float] = {}
    for e in entries:
        if e.get('event') == 'cost_update':
            cid = e.get('conversation_id', '__anon__')
            cost = float(e.get('cost', 0.0))
            if cost > session_max.get(cid, 0.0):
                session_max[cid] = cost
    return sum(session_max.values(), 0.0)


# ── Session tags & project labels ────────────────────────────────────

_TAGS_FILE = 'tags.json'


def _load_tags_store(cwd: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load the tags store from ``.app/tags.json``.

    Returns a dict mapping conversation_id → {"tags": [...], "project": str}.
    """
    path = get_project_state_dir(cwd) / _TAGS_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_tags_store(store: dict[str, dict[str, Any]], cwd: Path | None = None) -> None:
    """Persist the tags store to ``.app/tags.json``."""
    try:
        project_state_dir = ensure_project_state_dir(cwd)
        path = project_state_dir / _TAGS_FILE
        path.write_text(json.dumps(store, indent=2, default=str), encoding='utf-8')
    except Exception:
        pass


def get_conversation_meta(
    conversation_id: str, cwd: Path | None = None
) -> dict[str, Any]:
    """Return the stored metadata (tags, project) for a conversation."""
    store = _load_tags_store(cwd)
    return store.get(conversation_id, {'tags': [], 'project': ''})


def set_conversation_tags(
    conversation_id: str,
    tags: list[str],
    *,
    project: str | None = None,
    cwd: Path | None = None,
) -> None:
    """Set tags (and optionally project) for a conversation in the local store."""
    store = _load_tags_store(cwd)
    existing = store.get(conversation_id, {'tags': [], 'project': ''})
    existing['tags'] = sorted(
        set(t.strip().lstrip('#').lower() for t in tags if t.strip())
    )
    if project is not None:
        existing['project'] = project.strip()
    store[conversation_id] = existing
    _save_tags_store(store, cwd)


def list_projects(cwd: Path | None = None) -> list[str]:
    """Return a sorted list of all distinct project labels in the tags store."""
    store = _load_tags_store(cwd)
    projects = {v.get('project', '') for v in store.values()}
    return sorted(p for p in projects if p)


def list_all_tags(cwd: Path | None = None) -> list[str]:
    """Return a sorted list of all distinct tags in the tags store."""
    store = _load_tags_store(cwd)
    tags: set[str] = set()
    for v in store.values():
        tags.update(v.get('tags', []))
    return sorted(tags)
