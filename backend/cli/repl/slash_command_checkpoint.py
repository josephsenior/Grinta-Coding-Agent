"""Checkpoint inspection handlers for :class:`SlashCommandsMixin`.

Supports the ``/checkpoint list`` and ``/checkpoint diff`` subcommands.
The handlers read the active rollback manager from the controller's
middleware; if no manager is wired up they emit a friendly hint instead
of raising.

Note: ``format_checkpoint_entry`` and ``compute_checkpoint_diff_text`` are
kept as ``@staticmethod`` on the mixin class itself (not extracted here)
because tests invoke them as class-level static methods:
``SlashCommandsMixin._format_checkpoint_entry(entry)``.
"""

from __future__ import annotations

from typing import Any


def resolve_rollback_manager(host: Any) -> Any:
    """Return the active RollbackManager for the current session.

    The value is resolved via the controller's middleware, or ``None`` if
    checkpoints are not available in this session.
    """
    try:
        controller = getattr(host, '_controller', None) or getattr(
            host, '_orchestrator', None
        )
        if controller is None:
            return None
        mw = getattr(controller, '_rollback_middleware', None)
        if mw is None:
            return None
        return getattr(mw, '_manager', None)
    except Exception:
        return None


def parse_checkpoint_limit(host: Any, args: list[str]) -> int | None:
    if not args:
        return 10
    try:
        return max(1, int(args[0]))
    except ValueError:
        host._warn('Usage: /checkpoint list [limit]')
        return None


def notify_no_rollback_manager(host: Any, message: str) -> None:
    if host._renderer is not None:
        host._renderer.add_system_message(message, title='checkpoint')


def handle_checkpoint_list(host: Any, args: list[str]) -> None:
    """Render up to ``limit`` checkpoints (default 10, newest first)."""
    limit = parse_checkpoint_limit(host, args)
    if limit is None:
        return
    manager = host._resolve_rollback_manager()
    if manager is None:
        notify_no_rollback_manager(
            host,
            'No active rollback manager (workspace may not be initialised yet).',
        )
        return
    try:
        entries = manager.list_checkpoints()
    except Exception as exc:
        host._warn(f'Failed to list checkpoints: {exc}')
        return
    if not entries:
        if host._renderer is not None:
            host._renderer.add_system_message(
                'No checkpoints recorded yet.', title='checkpoint'
            )
        return
    # Newest first.
    entries = sorted(entries, key=lambda e: e.get('timestamp', 0), reverse=True)[:limit]
    body = '\n'.join(host._format_checkpoint_entry(e) for e in entries)
    if host._renderer is not None:
        host._renderer.add_system_message(body, title='checkpoint list')


def find_checkpoint_match(
    host: Any,
    manager: Any,
    cp_id: str,
) -> dict[str, Any] | None:
    try:
        entries = manager.list_checkpoints()
    except Exception as exc:
        host._warn(f'Failed to list checkpoints: {exc}')
        return None
    match = next(
        (e for e in entries if str(e.get('id', '')).startswith(cp_id)),
        None,
    )
    if match is None:
        host._warn(f'Checkpoint not found: {cp_id}')
    return match


def handle_checkpoint_diff(host: Any, args: list[str]) -> None:
    """Show a git diff (or directory diff fallback) since a checkpoint."""
    if not args:
        host._warn('Usage: /checkpoint diff <id>')
        return
    cp_id = args[0]
    manager = host._resolve_rollback_manager()
    if manager is None:
        notify_no_rollback_manager(host, 'No active rollback manager.')
        return
    match = find_checkpoint_match(host, manager, cp_id)
    if match is None:
        return
    diff_text = host._compute_checkpoint_diff_text(
        match.get('git_commit_sha'),
        manager.workspace_path,
    )
    if host._renderer is not None:
        # Trim to keep the panel manageable.
        if len(diff_text) > 8000:
            diff_text = diff_text[:8000] + '\n[... diff truncated ...]\n'
        host._renderer.add_markdown_block(
            f'checkpoint diff {match.get("id", "?")[:12]}',
            f'```diff\n{diff_text}\n```',
        )
