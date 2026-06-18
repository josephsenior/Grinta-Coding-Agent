"""Auto-check middleware for tool invocations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.ledger.observation import Observation
    from backend.orchestration.tool_pipeline import ToolInvocationContext


def _treesitter_syntax_check(
    path: str, content: bytes | None = None
) -> tuple[bool, str] | None:
    """Check syntax using the shared whole-file syntax service.

    Args:
        path: File path (used to determine language from extension).
        content: File content as bytes.  When provided the file is NOT read
            from disk — this is critical because the path may only exist
            inside a sandbox / container.

    Returns:
        (is_valid, error_detail) or None if language not supported.
    """
    from backend.utils.treesitter.syntax_check import check_syntax

    return check_syntax(path, content).as_legacy_tuple()


def _collect_syntax_errors(node: Any, source: bytes, max_errors: int = 5) -> list[str]:
    """Walk tree-sitter AST and collect ERROR/MISSING node descriptions."""
    from backend.utils.treesitter.syntax_check import collect_tree_sitter_syntax_errors

    return collect_tree_sitter_syntax_errors(node, source, max_errors=max_errors)


def _extract_syntax_check_payload(
    action: object, observation: Observation | None = None
) -> tuple[str, bytes | None] | None:
    from backend.ledger.action import FileEditAction

    if not isinstance(action, FileEditAction):
        return None

    edit_action = action
    observed_new_content = getattr(observation, 'new_content', None)
    if isinstance(observed_new_content, str):
        raw: str | None = observed_new_content
    elif edit_action.command in {'create_file'}:
        raw = edit_action.file_text or edit_action.new_str
    else:
        return None
    return edit_action.path, raw.encode('utf-8') if raw else None


def _append_syntax_check_result(
    observation: Observation,
    result: tuple[bool, str],
) -> None:
    current = getattr(observation, 'content', '') or ''
    is_valid, detail = result
    if is_valid:
        observation.content = current + '\n<SYNTAX_CHECK_PASSED />'
        return
    observation.content = (
        current + f'\n<SYNTAX_CHECK_FAILED>\n{detail}\n</SYNTAX_CHECK_FAILED>'
    )


class AutoCheckMiddleware(ToolInvocationMiddleware):
    """Automatically checks syntax of files after editing.

    Uses tree-sitter for language-agnostic syntax validation (45+ languages).
    No subprocess overhead, no false positives from unresolved imports.
    """

    async def observe(
        self, ctx: ToolInvocationContext, observation: Observation | None
    ) -> None:
        if observation is None:
            return
        from backend.ledger.observation import ErrorObservation

        if isinstance(observation, ErrorObservation):
            return

        payload = _extract_syntax_check_payload(ctx.action, observation)
        if payload is None:
            return

        path, content = payload
        result = _treesitter_syntax_check(path, content)
        if result is None:
            return  # unsupported language or tree-sitter unavailable

        _append_syntax_check_result(observation, result)
