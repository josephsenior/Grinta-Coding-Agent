"""Auto-check middleware for tool invocations."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from backend.orchestration.tool_pipeline import ToolInvocationMiddleware

if TYPE_CHECKING:
    from backend.orchestration.tool_pipeline import ToolInvocationContext
    from backend.ledger.observation import Observation


def _treesitter_syntax_check(path: str, content: bytes | None = None) -> tuple[bool, str] | None:
    """Check syntax using tree-sitter.

    Args:
        path: File path (used to determine language from extension).
        content: File content as bytes.  When provided the file is NOT read
            from disk — this is critical because the path may only exist
            inside a sandbox / container.

    Returns:
        (is_valid, error_detail) or None if language not supported.
    """
    from backend.utils.treesitter_editor import (
        LANGUAGE_EXTENSIONS,
        TREE_SITTER_AVAILABLE,
        _get_parser,
    )

    if not TREE_SITTER_AVAILABLE or _get_parser is None:
        return None

    _, ext = os.path.splitext(path)
    ext = ext.lower()
    language = LANGUAGE_EXTENSIONS.get(ext)
    if not language:
        return None

    try:
        parser = _get_parser(language)
    except Exception:
        return None
    if not parser:
        return None

    # If no content supplied, try reading from disk (local-runtime case).
    if content is None:
        try:
            with open(path, "rb") as f:
                content = f.read()
        except (OSError, IOError):
            return None

    tree = parser.parse(content)
    errors = _collect_syntax_errors(tree.root_node, content, max_errors=5)
    if not errors:
        return (True, "")
    detail = "; ".join(errors)
    return (False, detail)


def _collect_syntax_errors(
    node: Any, source: bytes, max_errors: int = 5
) -> list[str]:
    """Walk tree-sitter AST and collect ERROR/MISSING node descriptions."""
    errors: list[str] = []

    def _walk(n: Any) -> None:
        if len(errors) >= max_errors:
            return
        if n.type == "ERROR" or n.is_missing:
            row = n.start_point[0] + 1
            col = n.start_point[1] + 1
            # Extract the problematic source snippet
            snippet = source[n.start_byte : n.end_byte].decode("utf-8", errors="replace")
            if len(snippet) > 60:
                snippet = snippet[:60] + "..."
            kind = "missing node" if n.is_missing else "syntax error"
            errors.append(f"line {row}:{col} {kind}: {snippet!r}")
            return  # don't recurse into ERROR subtrees
        for child in n.children:
            _walk(child)

    _walk(node)
    return errors


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
        from backend.ledger.action import FileEditAction, FileWriteAction
        from backend.ledger.observation import ErrorObservation

        if isinstance(observation, ErrorObservation):
            return
        if not isinstance(ctx.action, (FileEditAction, FileWriteAction)):
            return
        path = getattr(ctx.action, "path", None)
        if not path:
            return

        # Extract content from the action so we don't need filesystem access
        # (the file may only exist inside a sandbox/container).
        raw = None
        if isinstance(ctx.action, FileEditAction):
            raw = getattr(ctx.action, "file_text", None) or getattr(ctx.action, "content", None)
        elif isinstance(ctx.action, FileWriteAction):
            raw = getattr(ctx.action, "content", None)

        content = raw.encode("utf-8") if raw else None

        result = _treesitter_syntax_check(path, content)
        if result is None:
            return  # unsupported language or tree-sitter unavailable

        current = getattr(observation, "content", "") or ""
        is_valid, detail = result
        if is_valid:
            observation.content = current + "\n<SYNTAX_CHECK_PASSED />"
        else:
            observation.content = current + f"\n<SYNTAX_CHECK_FAILED>\n{detail}\n</SYNTAX_CHECK_FAILED>"
