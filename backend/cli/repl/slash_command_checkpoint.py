"""Checkpoint inspection and management handlers for :class:`SlashCommandsMixin`.

Supports the ``/checkpoint list``, ``/checkpoint diff``, and
``/checkpoint revert`` subcommands.  The handlers read the active rollback
manager from the controller's middleware; if no manager is wired up they
emit a friendly hint instead of raising.

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
    """Render up to ``limit`` checkpoints (default 10, newest first).

    By default only user-visible (tier 2) checkpoints are shown.  Pass
    ``--all`` as the first argument to include system transactions (tier 1).
    """
    show_all = bool(args and args[0] == '--all')
    remaining = args[1:] if show_all else args
    limit = parse_checkpoint_limit(host, remaining)
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
        # Show all tiers when --all is requested; otherwise only tier-2 user checkpoints.
        entries = manager.list_checkpoints(tier=None if show_all else 2)
    except Exception as exc:
        host._warn(f'Failed to list checkpoints: {exc}')
        return
    if not entries:
        msg = 'No checkpoints recorded yet.'
        if not show_all:
            msg += ' (system transactions hidden; use /checkpoint list --all to see them)'
        if host._renderer is not None:
            host._renderer.add_system_message(msg, title='checkpoint')
        return
    # Newest first.
    entries = sorted(entries, key=lambda e: e.get('timestamp', 0), reverse=True)[:limit]
    body = '\n'.join(host._format_checkpoint_entry(e) for e in entries)
    if not show_all:
        body += '\n(system transactions hidden — use /checkpoint list --all to see all)'
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


def handle_checkpoint_revert(host: Any, args: list[str]) -> bool:
    """Immediately roll back the workspace to a saved checkpoint.

    Usage::

        /checkpoint revert <id-prefix>
        /revert <id-prefix>

    The ``id-prefix`` can be any unambiguous prefix of a checkpoint ID as
    shown by ``/checkpoint list``.
    """
    if not args:
        host._warn('Usage: /checkpoint revert <id-prefix>')
        return True
    cp_id = args[0]
    manager = host._resolve_rollback_manager()
    if manager is None:
        notify_no_rollback_manager(
            host,
            'No active rollback manager.  Cannot revert.',
        )
        return True
    # Search both tiers so the user can revert to a system transaction too.
    match = find_checkpoint_match(host, manager, cp_id)
    if match is None:
        return True
    full_id = match['id']
    if host._renderer is not None:
        host._renderer.add_system_message(
            f'Reverting workspace to checkpoint {full_id[:12]}\u2026  Please wait.',
            title='checkpoint revert',
        )
    try:
        success = manager.rollback_to(full_id)
    except Exception as exc:
        host._warn(f'Revert failed: {exc}')
        return True
    if success:
        if host._renderer is not None:
            host._renderer.add_system_message(
                f'\u2705  Workspace restored to checkpoint {full_id[:12]}.  '
                'Any changes after that point have been undone.',
                title='checkpoint revert',
            )
    else:
        host._warn(
            f'Revert to checkpoint {full_id[:12]} failed.  '
            'Check logs for details (git or file snapshot may be missing).'
        )
    return True
