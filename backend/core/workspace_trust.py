"""Persist and query workspace familiarity for first-run hardening prompts."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.core.workspace_resolution import workspace_storage_id

logger = logging.getLogger(__name__)

_TRUST_FILE = Path.home() / '.grinta' / 'workspace_trust.json'


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _load_store() -> dict[str, Any]:
    if not _TRUST_FILE.is_file():
        return {'workspaces': {}}
    try:
        data = json.loads(_TRUST_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        logger.warning('Could not read workspace trust file at %s', _TRUST_FILE)
        return {'workspaces': {}}
    if not isinstance(data, dict):
        return {'workspaces': {}}
    workspaces = data.get('workspaces')
    if not isinstance(workspaces, dict):
        data['workspaces'] = {}
    return data


def _save_store(data: dict[str, Any]) -> None:
    _TRUST_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _TRUST_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    tmp.replace(_TRUST_FILE)


def workspace_trust_key(workspace: Path) -> str:
    """Return a stable key for *workspace* in the trust registry."""
    resolved = workspace.expanduser().resolve()
    return workspace_storage_id(resolved)


def is_familiar_workspace(workspace: Path) -> bool:
    """Return True when the workspace has been acknowledged in a prior session."""
    key = workspace_trust_key(workspace)
    entry = _load_store().get('workspaces', {}).get(key)
    return isinstance(entry, dict) and bool(entry.get('acknowledged'))


def record_workspace_visit(
    workspace: Path,
    *,
    autonomy_level: str,
    prompted: bool,
) -> None:
    """Persist that *workspace* was opened and how autonomy was configured."""
    resolved = workspace.expanduser().resolve()
    key = workspace_trust_key(resolved)
    store = _load_store()
    workspaces = store.setdefault('workspaces', {})
    existing = workspaces.get(key)
    if not isinstance(existing, dict):
        existing = {}
    existing.update(
        {
            'path': str(resolved),
            'acknowledged': True,
            'autonomy_level': autonomy_level,
            'prompted_for_conservative': prompted,
            'last_seen': _now_iso(),
        }
    )
    if 'first_seen' not in existing:
        existing['first_seen'] = existing['last_seen']
    workspaces[key] = existing
    _save_store(store)


__all__ = [
    'is_familiar_workspace',
    'record_workspace_visit',
    'workspace_trust_key',
]
