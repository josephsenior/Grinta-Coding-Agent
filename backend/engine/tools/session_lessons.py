"""Persist durable lessons when a session finishes successfully."""

from __future__ import annotations

from backend.core.logger import app_logger as logger


def persist_finish_lessons(
    *,
    summary: str,
    session_id: str | None = None,
) -> None:
    """Write finish-summary lessons into workspace memory and lessons.md."""
    summary = (summary or '').strip()
    if not summary:
        return

    lesson_body = summary[:800]
    try:
        from backend.context.session_context import bind_session_context
        from backend.engine.tools.working_memory import _load_memory

        bind_session_context(session_id=session_id)
        wm = _load_memory()
        extras: list[str] = []
        for section in ('decisions', 'findings'):
            val = str(wm.get(section, '') or '').strip()
            if val:
                extras.append(f'**{section}**: {val[:400]}')
        if extras:
            lesson_body = f'{lesson_body}\n\n' + '\n'.join(extras[:2])
    except Exception:
        logger.debug('Failed to read working memory for finish lessons', exc_info=True)

    try:
        from backend.engine.tools.workspace_memory import persist_entry

        persist_entry(kind='lesson', key='session_summary', value=lesson_body[:600])
    except Exception:
        logger.debug('Failed to persist workspace memory lesson', exc_info=True)

    try:
        from backend.core.workspace_resolution import (
            get_effective_workspace_root,
            workspace_agent_state_dir,
        )
        from backend.engine.tools.lesson_store import append_markdown_lesson

        root = get_effective_workspace_root()
        if root is None:
            return
        lessons_path = workspace_agent_state_dir(root) / 'lessons.md'
        append_markdown_lesson(
            lessons_path,
            lesson_body[:1200],
            summary=summary[:100] or 'Session',
        )
    except Exception:
        logger.debug('Failed to append lessons.md on finish', exc_info=True)


__all__ = ['persist_finish_lessons']
