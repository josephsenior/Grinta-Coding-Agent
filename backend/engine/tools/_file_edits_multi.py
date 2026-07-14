"""File edit handlers used by function-calling tool dispatch.

Pure code motion: split from ``backend.engine.function_calling`` to keep
that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import Any, NoReturn

from backend.core.errors import FunctionCallValidationError, ToolExecutionError
from backend.core.logging.logger import app_logger as logger
from backend.engine.function_calling.helpers import (
    parse_bool_argument,
)
from backend.engine.tools._file_edits_common import (
    _MAX_MULTI_EDIT_FILES,
    _multi_edit_raise,
)
from backend.engine.tools._file_ops import (
    _guard_content_arguments,
)
from backend.ledger.action import (
    Action,
    MessageAction,
)


def _resolve_multi_edit_path(raw_path: str, item_index: int) -> tuple[str, str]:
    """Resolve a multi_edit target to a workspace-scoped absolute path."""
    from backend.core.type_safety.path_validation import PathValidationError, SafePath
    from backend.core.workspace_resolution import require_effective_workspace_root

    try:
        workspace_root = require_effective_workspace_root()
        safe_path = SafePath.validate(
            raw_path,
            workspace_root=str(workspace_root),
            must_be_relative=True,
        )
    except (PathValidationError, ValueError) as exc:
        raise FunctionCallValidationError(
            f'multi_edit item {item_index}: invalid path {raw_path!r}: {exc}'
        ) from exc
    return str(safe_path.path), safe_path.relative_to_workspace()


def _multi_edit_relative_path(item_path: str, workspace_root: str | Path) -> str:
    root = Path(workspace_root)
    return str(Path(item_path).resolve().relative_to(root.resolve()))


def _parse_multi_edit_operation(
    raw_item: Mapping[str, Any],
    idx: int,
) -> tuple[str, dict[str, Any]]:
    operation = str(raw_item.get('operation') or '').strip().lower()
    allowed = {'replace_string'}
    if operation not in allowed:
        raise FunctionCallValidationError(
            f'multi_edit item {idx}: unsupported internal operation {operation!r}. '
            f'Allowed operations: {sorted(allowed)}.'
        )
    return operation, dict(raw_item)


def _raise_multi_edit_syntax_failure(
    rel_path: str,
    detail: str,
    *,
    failed_op_index: int | None = None,
    total_ops: int | None = None,
) -> NoReturn:
    from backend.core.errors.structured_edit_errors import (
        compact_syntax_detail,
        extract_syntax_line,
    )

    _multi_edit_raise(
        'multi_edit syntax validation failed.',
        error_code='SYNTAX_VALIDATION_FAILED',
        path=rel_path,
        operation='multi_edit',
        failed_op_index=failed_op_index,
        total_ops=total_ops,
        line=extract_syntax_line(detail),
        detail=compact_syntax_detail(detail),
        retryable=True,
    )


def _validate_multi_edit_file_final(
    temp_editor: Any,
    temp_path: Path,
    rel_path: str,
    original_content: str | None,
    *,
    failed_op_index: int | None = None,
    total_ops: int | None = None,
) -> str | None:
    """Return a syntax warning for the agent, or None when clean."""
    if not temp_path.exists():
        return None
    final_content = temp_path.read_text(encoding='utf-8')
    if final_content == (original_content or ''):
        return None

    warnings: list[str] = []
    regression_error = temp_editor._detect_introduced_syntax_error(
        temp_path, original_content, final_content
    )
    if regression_error is not None:
        _raise_multi_edit_syntax_failure(
            rel_path,
            regression_error,
            failed_op_index=failed_op_index,
            total_ops=total_ops,
        )

    is_valid, msg = temp_editor._maybe_validate_syntax_for_file(
        temp_path, final_content
    )
    if not is_valid:
        _raise_multi_edit_syntax_failure(
            rel_path,
            str(msg or ''),
            failed_op_index=failed_op_index,
            total_ops=total_ops,
        )
    if msg and msg.startswith('WARNING:'):
        warnings.append(msg)
    return '\n'.join(warnings) if warnings else None


def _apply_multi_edit_operation(
    *,
    rel_path: str,
    temp_path: Path,
    operation: str,
    item: dict[str, Any],
    temp_editor: Any,
    failed_op_index: int | None = None,
    total_ops: int | None = None,
) -> None:
    from backend.core.errors.structured_edit_errors import summarize_editor_error

    if operation == 'replace_string':
        old_string = item.get('old_string')
        new_string = item.get('new_string')
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            raise FunctionCallValidationError(
                "multi_edit replace_string operation requires 'old_string' and 'new_string'."
            )
        result = temp_editor(
            command='replace_string',
            path=rel_path,
            old_string=old_string,
            new_str=new_string,
            replace_all=parse_bool_argument(item.get('replace_all', False)),
        )
        if result.error:
            error_code, summary, retryable, extra = summarize_editor_error(result)
            _multi_edit_raise(
                summary,
                error_code=error_code,
                path=rel_path,
                operation='replace_string',
                failed_op_index=failed_op_index,
                total_ops=total_ops,
                retryable=retryable,
                detail=extra.get('detail'),
                line=extra.get('line'),
                match_count=extra.get('match_count'),
            )
        return

    raise FunctionCallValidationError(
        f'multi_edit: unsupported internal operation {operation!r}.'
    )


def _validate_multi_edit_arguments(raw_edits: Any) -> None:
    if not isinstance(raw_edits, list) or not raw_edits:
        raise FunctionCallValidationError(
            "multi_edit requires a non-empty 'file_edits' array."
        )
    _guard_content_arguments({'file_edits': raw_edits})
    if len(raw_edits) > _MAX_MULTI_EDIT_FILES:
        raise FunctionCallValidationError(
            f'multi_edit supports at most {_MAX_MULTI_EDIT_FILES} files per call '
            f'(got {len(raw_edits)}). Split the batch.'
        )


def _parse_multi_edit_items(
    raw_edits: list,
) -> list[tuple[str, str, str, dict[str, Any]]]:
    parsed: list[tuple[str, str, str, dict[str, Any]]] = []
    seen_paths: set[str] = set()
    for idx, item in enumerate(raw_edits):
        if not isinstance(item, Mapping):
            raise FunctionCallValidationError(
                f'multi_edit item {idx} must be an object.'
            )
        item_path = item.get('path')
        if not isinstance(item_path, str) or not item_path.strip():
            raise FunctionCallValidationError(
                f"multiedit validation failed: item {idx} missing required field 'path'."
            )
        requested_path = item_path.strip()
        canonical_path, display_path = _resolve_multi_edit_path(requested_path, idx)
        seen_paths.add(canonical_path)
        operation, normalized_item = _parse_multi_edit_operation(item, idx)
        parsed.append((canonical_path, display_path, operation, normalized_item))
    return parsed


def _apply_multi_edit_to_temp_files(
    parsed: list[tuple[str, str, str, dict[str, Any]]],
    seen_paths: set[str],
    workspace_root: str | Path,
    temp_root: Path,
    temp_editor: Any,
) -> tuple[dict[str, str | None], dict[str, str], list[str]]:
    """Apply multi_edit operations in declaration order against per-file temp copies.

    Each operation sees the temp file as left by all prior operations in the batch.
    Syntax is validated once per file after all operations complete.
    """
    original_snapshots: dict[str, str | None] = {}
    final_contents: dict[str, str] = {}
    temp_paths: dict[str, Path] = {}
    syntax_warnings: list[str] = []

    file_count = len({item_path for item_path, _, _, _ in parsed})
    logger.info(
        'multi_edit: applying %s operation(s) across %s file(s) on temp copies',
        len(parsed),
        file_count,
    )

    for op_index, (item_path, _display_path, operation, item) in enumerate(parsed):
        real_path = Path(item_path)
        rel_path = _multi_edit_relative_path(item_path, workspace_root)
        temp_path = temp_root / rel_path
        if item_path not in temp_paths:
            temp_paths[item_path] = temp_path
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            if real_path.exists():
                original_snapshots[item_path] = real_path.read_text(encoding='utf-8')
                shutil.copyfile(real_path, temp_path)
            else:
                original_snapshots[item_path] = None
        _apply_multi_edit_operation(
            rel_path=rel_path,
            temp_path=temp_path,
            operation=operation,
            item=item,
            temp_editor=temp_editor,
            failed_op_index=op_index,
            total_ops=len(parsed),
        )

    for item_path, temp_path in temp_paths.items():
        rel_path = _multi_edit_relative_path(item_path, workspace_root)
        if not temp_path.exists():
            _multi_edit_raise(
                'multi_edit failed: produced no output file.',
                error_code='NO_OUTPUT_FILE',
                path=rel_path,
                operation='multi_edit',
                retryable=True,
            )
        warning = _validate_multi_edit_file_final(
            temp_editor,
            temp_path,
            rel_path,
            original_snapshots.get(item_path),
            failed_op_index=len(parsed) - 1 if parsed else None,
            total_ops=len(parsed) or None,
        )
        if warning:
            syntax_warnings.append(f'{rel_path}:\n{warning}')
        final_contents[item_path] = temp_path.read_text(encoding='utf-8')

    return original_snapshots, final_contents, syntax_warnings


def _verify_no_concurrent_modifications(
    original_snapshots: dict[str, str | None],
    workspace_root: str | Path,
) -> None:
    for item_path, old_content in original_snapshots.items():
        real_path = Path(item_path)
        disk_now = real_path.read_text(encoding='utf-8') if real_path.exists() else None
        if disk_now != old_content:
            _multi_edit_raise(
                'multi_edit aborted: file changed on disk during batch preparation.',
                error_code='CONCURRENT_MODIFICATION',
                path=_multi_edit_relative_path(item_path, workspace_root),
                operation='multi_edit',
                detail='Re-read the file and retry.',
                retryable=True,
            )


def _commit_multi_edit_transaction(
    refactor: Any,
    transaction: Any,
    final_contents: dict[str, str],
) -> Any:
    for item_path, final_content in final_contents.items():
        operation = 'modify' if Path(item_path).exists() else 'create'
        refactor.add_file_edit(
            transaction, item_path, final_content, operation=operation
        )
    return refactor.commit(transaction, validate=False)


def _format_multi_edit_success(
    parsed: list, result: Any, *, syntax_warnings: list[str] | None = None
) -> MessageAction:
    paths = sorted(
        {display_path for _item_path, display_path, _operation, _item in parsed}
    )
    operation_count = len(parsed)
    file_count = len(paths)
    if len(paths) == 1:
        file_lines = f'  • {paths[0]}'
    else:
        file_lines = '\n'.join(f'  • {p}' for p in paths)
    content = (
        f'✓ multi_edit committed {operation_count} operation(s) across '
        f'{file_count} file(s) atomically\n'
        f'{file_lines}'
    )
    if syntax_warnings:
        content += '\n\n[SYNTAX WARNINGS]\n' + '\n\n'.join(syntax_warnings)
    return MessageAction(content=content)


def _format_multi_edit_failure(result: Any) -> NoReturn:
    errors = list(result.errors or [result.message])
    primary = str(errors[0] if errors else 'transaction failed')
    _multi_edit_raise(
        'multi_edit transaction rolled back.',
        error_code='TRANSACTION_ROLLBACK',
        operation='multi_edit',
        detail=primary,
        transaction_rolled_back=True,
        retryable=True,
    )


def _handle_multi_edit_command(_path: str, arguments: Mapping[str, Any]) -> Action:
    """Apply an atomic multi-file batch edit via :class:`AtomicRefactor`.

    All edits commit together or all are rolled back from per-file backups.
    The returned ``MessageAction`` summarizes the outcome.
    """
    raw_edits = arguments.get('file_edits')
    _validate_multi_edit_arguments(raw_edits)
    assert isinstance(raw_edits, list)
    parsed = _parse_multi_edit_items(raw_edits)
    seen_paths = {p for p, _, _, _ in parsed}

    from backend.core.workspace_resolution import require_effective_workspace_root
    from backend.engine.tools.atomic_refactor import AtomicRefactor
    from backend.execution.utils.file_editor import FileEditor, _file_lock_for_path

    workspace_root = require_effective_workspace_root()
    refactor = AtomicRefactor()
    transaction = refactor.begin_transaction()
    syntax_warnings: list[str] = []
    try:
        with ExitStack() as stack:
            for item_path in sorted(seen_paths):
                stack.enter_context(_file_lock_for_path(Path(item_path)))
            with tempfile.TemporaryDirectory(
                prefix='grinta-multi-edit-'
            ) as temp_root_str:
                temp_root = Path(temp_root_str)
                temp_editor = FileEditor(workspace_root=str(temp_root))
                temp_editor._defer_syntax_validation = True
                original_snapshots, final_contents, syntax_warnings = (
                    _apply_multi_edit_to_temp_files(
                        parsed,
                        seen_paths,
                        workspace_root,
                        temp_root,
                        temp_editor,
                    )
                )
            _verify_no_concurrent_modifications(original_snapshots, workspace_root)
            result = _commit_multi_edit_transaction(
                refactor, transaction, final_contents
            )
    except FunctionCallValidationError:
        raise
    except ToolExecutionError:
        raise
    except Exception as e:
        try:
            refactor.rollback(transaction)
        except Exception:
            pass
        _multi_edit_raise(
            f'multi_edit failed: {e}',
            error_code='MULTI_EDIT_COMMIT_FAILED',
            operation='multi_edit',
            detail=str(e),
            transaction_rolled_back=True,
            retryable=True,
        )

    if result.success:
        return _format_multi_edit_success(
            parsed, result, syntax_warnings=syntax_warnings
        )
    _format_multi_edit_failure(result)
