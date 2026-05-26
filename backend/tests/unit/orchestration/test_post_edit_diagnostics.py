from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.ledger.action.files import FileEditAction
from backend.ledger.observation import FileEditObservation
from backend.orchestration.middleware.post_edit_diagnostics import (
    PostEditDiagnosticsMiddleware,
)
from backend.orchestration.tool_pipeline import ToolInvocationContext
from backend.utils.lsp_client import LspLocation, LspResult


def _ctx(action: object) -> ToolInvocationContext:
    controller = SimpleNamespace(config=SimpleNamespace(enable_lsp_query=True))
    return ToolInvocationContext(
        controller=controller,  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        state=MagicMock(),
    )


@pytest.mark.asyncio
async def test_post_edit_diagnostics_appends_passed_receipt(tmp_path) -> None:
    path = tmp_path / 'app.py'
    path.write_text('def ok():\n    return 1\n', encoding='utf-8')
    action = FileEditAction(path=str(path), command='edit')
    obs = FileEditObservation(content='Edited', path=str(path))
    lsp = MagicMock(query=MagicMock(return_value=LspResult(available=True)))

    with (
        patch(
            'backend.utils.runtime_detect.lsp_command_for_extension',
            return_value=('pylsp',),
        ),
        patch('backend.utils.lsp_client.get_lsp_client', return_value=lsp),
    ):
        await PostEditDiagnosticsMiddleware(timeout_seconds=0.25).observe(
            _ctx(action), obs
        )

    assert '<LSP_DIAGNOSTICS status="passed">' in obs.content
    assert obs.tool_result['lsp_diagnostics']['status'] == 'passed'
    lsp.query.assert_called_once_with(
        'diagnostics', str(path.resolve()), process_timeout=0.25
    )


@pytest.mark.asyncio
async def test_post_edit_diagnostics_reports_lsp_failures(tmp_path) -> None:
    path = tmp_path / 'app.py'
    path.write_text('x: int = "bad"\n', encoding='utf-8')
    action = FileEditAction(path=str(path), command='edit')
    obs = FileEditObservation(content='Edited', path=str(path))
    result = LspResult(
        available=True,
        locations=[
            LspLocation(
                file=str(path),
                line=1,
                column=1,
                message='type mismatch',
            )
        ],
    )

    with (
        patch(
            'backend.utils.runtime_detect.lsp_command_for_extension',
            return_value=('pyright-langserver', '--stdio'),
        ),
        patch(
            'backend.utils.lsp_client.get_lsp_client',
            return_value=MagicMock(query=MagicMock(return_value=result)),
        ),
    ):
        await PostEditDiagnosticsMiddleware().observe(_ctx(action), obs)

    assert '<LSP_DIAGNOSTICS status="failed">' in obs.content
    assert 'type mismatch' in obs.content
    assert obs.tool_result['lsp_diagnostics']['files'][0]['diagnostics'] == 1


@pytest.mark.asyncio
async def test_post_edit_diagnostics_reports_installed_lsp_skip(tmp_path) -> None:
    path = tmp_path / 'app.py'
    path.write_text('def ok():\n    return 1\n', encoding='utf-8')
    action = FileEditAction(path=str(path), command='edit')
    obs = FileEditObservation(content='Edited', path=str(path))

    with patch(
        'backend.utils.runtime_detect.lsp_command_for_extension',
        return_value=None,
    ):
        await PostEditDiagnosticsMiddleware().observe(_ctx(action), obs)

    assert '<LSP_DIAGNOSTICS status="skipped">' in obs.content
    assert 'no installed LSP' in obs.content


@pytest.mark.asyncio
async def test_post_edit_diagnostics_uses_structured_edit_file_receipts(tmp_path) -> None:
    path = tmp_path / 'app.py'
    path.write_text('def ok():\n    return 1\n', encoding='utf-8')
    action = FileEditAction(path='', command='multi_edit')
    obs = FileEditObservation(content='Edited', path='')
    obs.tool_result = {
        'files': [{'path': 'app.py', 'absolute_path': str(path)}],
    }

    with (
        patch(
            'backend.utils.runtime_detect.lsp_command_for_extension',
            return_value=('pylsp',),
        ),
        patch(
            'backend.utils.lsp_client.get_lsp_client',
            return_value=MagicMock(
                query=MagicMock(return_value=LspResult(available=True))
            ),
        ),
    ):
        await PostEditDiagnosticsMiddleware().observe(_ctx(action), obs)

    assert '<LSP_DIAGNOSTICS status="passed">' in obs.content
    assert obs.tool_result['lsp_diagnostics']['files'][0]['path'] == str(
        path.resolve()
    )


@pytest.mark.asyncio
async def test_post_edit_diagnostics_ignores_unknown_extensions(tmp_path) -> None:
    path = tmp_path / 'notes.xyz'
    path.write_text('plain text', encoding='utf-8')
    action = FileEditAction(path=str(path), command='edit')
    obs = FileEditObservation(content='Edited', path=str(path))

    await PostEditDiagnosticsMiddleware().observe(_ctx(action), obs)

    assert 'LSP_DIAGNOSTICS' not in obs.content
