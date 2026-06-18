"""Post-edit LSP diagnostics middleware.

Tree-sitter/compiler checks answer "does this file parse?" quickly. This
middleware adds the next layer: when a locally installed language server exists
for the touched file, ask it for diagnostics and append a bounded receipt to
the observation the agent sees.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from backend.core.logger import app_logger as logger
from backend.orchestration.tool_pipeline import ToolInvocationMiddleware
from backend.utils.async_helpers.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from backend.ledger.observation import Observation
    from backend.orchestration.tool_pipeline import ToolInvocationContext

LspDiagnosticStatus = Literal['passed', 'failed', 'skipped']


@dataclass(frozen=True)
class LspDiagnosticReceipt:
    path: str
    status: LspDiagnosticStatus
    diagnostics: int = 0
    detail: str = ''
    reason: str = ''


class PostEditDiagnosticsMiddleware(ToolInvocationMiddleware):
    """Run short LSP diagnostics after mutating file edits."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 3.0,
        max_files: int = 8,
        max_diagnostics: int = 20,
        max_file_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_files = max_files
        self.max_diagnostics = max_diagnostics
        self.max_file_bytes = max_file_bytes

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None or not _auto_lsp_diagnostics_enabled(ctx):
            return

        try:
            from backend.ledger.observation import ErrorObservation

            if isinstance(observation, ErrorObservation):
                return

            paths = _extract_post_edit_paths(ctx, observation)
            if not paths:
                return

            receipts: list[LspDiagnosticReceipt] = []
            for raw_path in paths[: self.max_files]:
                resolved = _resolve_for_diagnostics(raw_path, ctx)
                # LSP queries spawn a subprocess and block on I/O; run them on
                # the sync-from-async pool so the event loop stays responsive.
                receipt = await call_sync_from_async(
                    _run_lsp_diagnostics,
                    resolved,
                    timeout_seconds=self.timeout_seconds,
                    max_diagnostics=self.max_diagnostics,
                    max_file_bytes=self.max_file_bytes,
                )
                if receipt is not None:
                    receipts.append(receipt)

            actionable = [
                receipt
                for receipt in receipts
                if receipt.status != 'skipped'
                or receipt.reason != 'not a known LSP file type'
            ]
            if not actionable:
                return

            _append_lsp_diagnostics(observation, actionable)
        except Exception:
            logger.debug('PostEditDiagnosticsMiddleware skipped', exc_info=True)


def _auto_lsp_diagnostics_enabled(ctx: ToolInvocationContext) -> bool:
    raw = os.environ.get('GRINTA_DISABLE_AUTO_LSP_DIAGNOSTICS', '').strip().lower()
    if raw in {'1', 'true', 'yes', 'on'}:
        return False

    config = getattr(ctx.controller, 'config', None) or getattr(
        ctx.controller, '_config', None
    )
    if getattr(config, 'enable_lsp_query', True) is False:
        return False
    agent_config = getattr(config, 'agent', None)
    if getattr(agent_config, 'enable_lsp_query', True) is False:
        return False
    return True


def _extract_post_edit_paths(
    ctx: ToolInvocationContext, observation: Observation
) -> list[str]:
    action = ctx.action
    paths: list[str] = []
    paths.extend(_extract_paths_from_tool_result(observation))
    paths.extend(_extract_paths_from_action(action))

    obs_path = getattr(observation, 'path', '')
    if isinstance(obs_path, str) and obs_path:
        paths.append(obs_path)

    return _dedupe(paths)


def _extract_paths_from_tool_result(observation: Observation) -> list[str]:
    paths: list[str] = []
    tool_result = getattr(observation, 'tool_result', None)
    if not isinstance(tool_result, dict):
        return paths
    files = tool_result.get('files')
    if not isinstance(files, list):
        return paths
    for item in files:
        if not isinstance(item, dict):
            continue
        raw_path = item.get('absolute_path') or item.get('path')
        if isinstance(raw_path, str) and raw_path.strip():
            paths.append(raw_path.strip())
    return paths


def _extract_paths_from_action(action: Any) -> list[str]:
    from backend.ledger.action import FileEditAction

    if not isinstance(action, FileEditAction):
        return []

    edit_action = action
    command = str(edit_action.command or '').strip().lower()
    if command == 'read_file':
        return []
    return [edit_action.path] if edit_action.path else []


def _resolve_for_diagnostics(raw_path: str, ctx: ToolInvocationContext) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()

    workspace = _workspace_from_context(ctx)
    if workspace:
        return (Path(workspace).expanduser() / path).resolve()
    return (Path.cwd() / path).resolve()


def _workspace_from_context(ctx: ToolInvocationContext) -> str | None:
    try:
        runtime = getattr(ctx.controller, 'runtime', None)
        workspace = getattr(runtime, 'workspace_dir', None) or getattr(
            runtime, 'workspace_path', None
        )
        if workspace:
            return str(workspace)
    except Exception:
        return None
    return None


def _run_lsp_diagnostics(
    path: Path,
    *,
    timeout_seconds: float,
    max_diagnostics: int,
    max_file_bytes: int,
) -> LspDiagnosticReceipt | None:
    skip_reason = _check_skip_conditions(path, max_file_bytes)
    if skip_reason:
        return LspDiagnosticReceipt(
            path=str(path), status='skipped', reason=skip_reason
        )

    command = _installed_lsp_command(path)
    if command is None:
        return LspDiagnosticReceipt(
            path=str(path),
            status='skipped',
            reason=f'no installed LSP for {path.suffix or "this file type"}',
        )

    result = _query_lsp(path, timeout_seconds)
    if isinstance(result, LspDiagnosticReceipt):
        return result
    return _evaluate_lsp_result(result, path, max_diagnostics)


def _check_skip_conditions(path: Path, max_file_bytes: int) -> str | None:
    if not _known_lsp_extension(path):
        return 'not a known LSP file type'
    if not path.exists() or not path.is_file():
        return 'file not found after edit'
    try:
        if path.stat().st_size > max_file_bytes:
            return 'file too large for automatic LSP diagnostics'
    except OSError:
        return 'file stat failed'
    return None


def _query_lsp(path: Path, timeout_seconds: float):
    try:
        from backend.utils.lsp.lsp_client import get_lsp_client

        return get_lsp_client().query(
            'diagnostics',
            str(path),
            process_timeout=timeout_seconds,
        )
    except TypeError:
        return LspDiagnosticReceipt(
            path=str(path),
            status='skipped',
            reason='LSP client does not support bounded diagnostics',
        )
    except Exception as exc:
        return LspDiagnosticReceipt(
            path=str(path),
            status='skipped',
            reason=f'LSP diagnostics error: {exc}',
        )


def _evaluate_lsp_result(
    result: Any, path: Path, max_diagnostics: int
) -> LspDiagnosticReceipt:
    if not getattr(result, 'available', True):
        return LspDiagnosticReceipt(
            path=str(path), status='skipped', reason='LSP unavailable'
        )
    if getattr(result, 'error', ''):
        return LspDiagnosticReceipt(
            path=str(path),
            status='skipped',
            reason=f'LSP error: {str(result.error)[:300]}',
        )

    locations = list(getattr(result, 'locations', []) or [])
    if not locations:
        return LspDiagnosticReceipt(path=str(path), status='passed')

    rendered = '; '.join(str(loc) for loc in locations[:max_diagnostics])
    return LspDiagnosticReceipt(
        path=str(path),
        status='failed',
        diagnostics=len(locations),
        detail=rendered[:2000],
    )


def _known_lsp_extension(path: Path) -> bool:
    ext = path.suffix.lower()
    try:
        from backend.utils.runtime_detect import LSP_SERVERS

        return any(ext in spec.extensions for spec in LSP_SERVERS)
    except Exception:
        return False


def _installed_lsp_command(path: Path) -> tuple[str, ...] | None:
    try:
        from backend.utils.runtime_detect import lsp_command_for_extension

        return lsp_command_for_extension(path.suffix.lower())
    except Exception:
        return None


def _append_lsp_diagnostics(
    observation: Observation, receipts: list[LspDiagnosticReceipt]
) -> None:
    status = _overall_status(receipts)
    lines = [f'<LSP_DIAGNOSTICS status="{status}">']
    for receipt in receipts:
        line = f'- {receipt.path}: lsp={receipt.status}'
        if receipt.diagnostics:
            line += f' diagnostics={receipt.diagnostics}'
        if receipt.reason:
            line += f' reason={_one_line(receipt.reason)}'
        if receipt.detail:
            line += f' detail={_one_line(receipt.detail)}'
        lines.append(line)
    lines.append('</LSP_DIAGNOSTICS>')

    current = getattr(observation, 'content', '') or ''
    observation.content = current + '\n' + '\n'.join(lines)

    tool_result = getattr(observation, 'tool_result', None)
    if not isinstance(tool_result, dict):
        tool_result = {}
    tool_result['lsp_diagnostics'] = {
        'status': status,
        'files': [asdict(receipt) for receipt in receipts],
    }
    observation.tool_result = tool_result


def _overall_status(receipts: list[LspDiagnosticReceipt]) -> LspDiagnosticStatus:
    statuses = {receipt.status for receipt in receipts}
    if 'failed' in statuses:
        return 'failed'
    if statuses == {'skipped'}:
        return 'skipped'
    return 'passed'


def _one_line(value: str) -> str:
    return ' '.join(value.split())


def _dedupe(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        key = os.path.normcase(os.path.normpath(path))
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


__all__ = ['PostEditDiagnosticsMiddleware']
