"""Shared helpers for file-edit tool handlers."""

from __future__ import annotations

from typing import Any, NoReturn


def _multi_edit_raise(
    summary: str,
    *,
    error_code: str,
    path: str | None = None,
    operation: str | None = None,
    failed_op_index: int | None = None,
    total_ops: int | None = None,
    retryable: bool = True,
    detail: str | None = None,
    line: int | None = None,
    symbol: str | None = None,
    candidates: list[dict[str, Any]] | None = None,
    match_count: int | None = None,
    transaction_rolled_back: bool = False,
    hint: str | None = None,
) -> NoReturn:
    from backend.execution.aes.structured_edit_errors import multi_edit_raise

    multi_edit_raise(
        summary,
        error_code=error_code,
        path=path,
        operation=operation,
        failed_op_index=failed_op_index,
        total_ops=total_ops,
        retryable=retryable,
        detail=detail,
        line=line,
        symbol=symbol,
        candidates=candidates,
        match_count=match_count,
        transaction_rolled_back=transaction_rolled_back,
        hint=hint,
    )


_MAX_MULTI_EDIT_FILES = 50
