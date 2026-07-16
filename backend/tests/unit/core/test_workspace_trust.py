"""Unit tests for workspace trust registry and unfamiliar-workspace prompts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.workspace_trust import (
    is_familiar_workspace,
    record_workspace_visit,
    workspace_trust_key,
)


def test_workspace_trust_key_is_stable(tmp_path: Path) -> None:
    workspace = tmp_path / 'project'
    workspace.mkdir()
    assert workspace_trust_key(workspace) == workspace_trust_key(workspace)


def test_record_and_query_workspace_visit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_file = tmp_path / 'workspace_trust.json'
    monkeypatch.setattr('backend.core.workspace_trust._TRUST_FILE', trust_file)

    workspace = tmp_path / 'repo'
    workspace.mkdir()
    assert not is_familiar_workspace(workspace)

    record_workspace_visit(
        workspace,
        autonomy_level='conservative',
        prompted=True,
    )
    assert is_familiar_workspace(workspace)


@pytest.mark.asyncio
async def test_maybe_apply_unfamiliar_workspace_skips_familiar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.cli.workspace_trust_prompt import (
        maybe_apply_unfamiliar_workspace_hardening,
    )

    trust_file = tmp_path / 'workspace_trust.json'
    monkeypatch.setattr('backend.core.workspace_trust._TRUST_FILE', trust_file)
    workspace = tmp_path / 'known'
    workspace.mkdir()
    record_workspace_visit(workspace, autonomy_level='balanced', prompted=False)

    controller = MagicMock()
    with patch(
        'backend.cli.settings.get_persisted_autonomy_level',
        return_value='balanced',
    ):
        level = await maybe_apply_unfamiliar_workspace_hardening(
            controller,
            workspace,
            agent_name='Orchestrator',
        )
    assert level == 'balanced'


@pytest.mark.asyncio
async def test_maybe_apply_unfamiliar_workspace_switches_to_conservative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.cli.workspace_trust_prompt import (
        maybe_apply_unfamiliar_workspace_hardening,
    )

    trust_file = tmp_path / 'workspace_trust.json'
    monkeypatch.setattr('backend.core.workspace_trust._TRUST_FILE', trust_file)
    workspace = tmp_path / 'new-repo'
    workspace.mkdir()

    controller = MagicMock(autonomy_controller=MagicMock(autonomy_level='balanced'))
    with (
        patch(
            'backend.cli.settings.get_persisted_autonomy_level',
            return_value='balanced',
        ),
        patch(
            'backend.cli.settings.update_autonomy_level',
        ) as update_mock,
        patch(
            'backend.cli.settings.mode_runtime.apply_autonomy_to_controller',
        ),
        patch(
            'backend.cli.workspace_trust_prompt._prompt_for_conservative',
            new=AsyncMock(return_value='conservative'),
        ),
    ):
        level = await maybe_apply_unfamiliar_workspace_hardening(
            controller,
            workspace,
            agent_name='Orchestrator',
        )

    assert level == 'conservative'
    update_mock.assert_called_once_with('conservative', 'Orchestrator')
    assert is_familiar_workspace(workspace)
