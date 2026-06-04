"""_AppRendererThinkingMixin: classify and render thinking-like payloads."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from backend.cli._event_renderer.constants import (
    INTERNAL_THINK_TAG_RE,
    THINK_RESULT_JSON_RE,
    TOOL_RESULT_TAG_RE,
)
from backend.cli._event_renderer.unified_renderer import (
    ActivityCard,
    ActivityLine,
)
from backend.cli.theme import (
    NAVY_TEXT_MUTED,
)

ThinkingIntentKind = Literal[
    'thinking',
    'search',
    'memory',
    'shared',
    'checkpoint',
    'code',
    'tool',
    'suppress',
    'error',
]


@dataclass(frozen=True)
class ThinkingRenderIntent:
    """Normalized rendering decision for text carried by thinking-like events."""

    kind: ThinkingIntentKind
    text: str = ''
    detail: str = ''
    tag: str = ''
    source_tool: str = ''


class _AppRendererThinkingMixin:
    """Classify thinking payloads so only pure reasoning uses thinking blocks."""

    _MEMORY_THINK_TAGS = {
        'SCRATCHPAD',
        'SEMANTIC_RECALL_RESULT',
        'WORKING_MEMORY',
    }
    _CODE_THINK_TAGS = {
        'ANALYZE_PROJECT_STRUCTURE',
        'FIND_SYMBOLS',
        'READ',
        'READ_SYMBOL_DEFINITION',
        'VERIFY_FILE_LINES',
    }
    _CHECKPOINT_THINK_TAGS = {
        'CHECKPOINT',
        'CHECKPOINT_RESULT',
        'REVERT_RESULT',
        'ROLLBACK',
    }
    _TASK_THINK_TAGS = {
        'TASK_TRACKER',
    }

    @staticmethod
    def _is_visible_thinking_text(text: str) -> bool:
        thought = (text or '').strip()
        return bool(thought) and thought != 'Your thought has been logged.'

    @staticmethod
    def _canonical_thinking_text(text: str) -> str:
        return '\n'.join(line.rstrip() for line in (text or '').strip().splitlines())

    @staticmethod
    def _trim_card_detail(text: str, *, fallback: str, limit: int = 96) -> str:
        compact = ' '.join((text or '').strip().split())
        if not compact:
            compact = fallback
        return compact[: limit - 3].rstrip() + '...' if len(compact) > limit else compact

    @staticmethod
    def _strip_tool_payload_markup(text: str) -> str:
        cleaned = THINK_RESULT_JSON_RE.sub('', text or '').strip()
        cleaned = TOOL_RESULT_TAG_RE.sub('', cleaned).strip()
        return cleaned

    def _classify_thinking_text(
        self,
        text: str,
        *,
        source_tool: str = '',
    ) -> ThinkingRenderIntent:
        thought = self._canonical_thinking_text(text)
        if not self._is_visible_thinking_text(thought):
            return ThinkingRenderIntent(kind='suppress')

        if '[TOOL_CALL_RECOVERABLE_ERROR]' in thought:
            cleaned_error = thought.replace('[TOOL_CALL_RECOVERABLE_ERROR]', '').strip()
            prefix1 = "The previous tool call was invalid and was not executed. Details:"
            if cleaned_error.startswith(prefix1):
                cleaned_error = cleaned_error[len(prefix1):].strip()
            lines = cleaned_error.splitlines()
            detail_line = lines[0].strip() if lines else cleaned_error
            if detail_line.lower().startswith("details:"):
                detail_line = detail_line[8:].strip()
            return ThinkingRenderIntent(
                kind='error',
                text=thought,
                detail=detail_line,
                tag='ERROR',
            )

        if '[TOOL_CALL_RECOVERABLE_ERROR_ESCALATED]' in thought:
            cleaned_error = thought.replace('[TOOL_CALL_RECOVERABLE_ERROR_ESCALATED]', '').strip()
            return ThinkingRenderIntent(
                kind='error',
                text=thought,
                detail=cleaned_error,
                tag='ERROR',
            )

        if '[TOOL_CALL_TRUNCATED]' in thought:
            detail_line = "Previous tool call arguments were stream-truncated (JSON never closed)."
            return ThinkingRenderIntent(
                kind='error',
                text=thought,
                detail=detail_line,
                tag='ERROR',
            )

        if source_tool == 'search_code' or '<search_results>' in thought:
            return ThinkingRenderIntent(
                kind='search',
                text=thought,
                source_tool=source_tool,
            )

        cleaned = self._strip_tool_payload_markup(thought)
        tag_match = INTERNAL_THINK_TAG_RE.match(cleaned)
        tag = (tag_match.group('tag') if tag_match else '').upper()
        payload = (
            (tag_match.group('payload') or '').strip() if tag_match else cleaned
        )

        if source_tool:
            if source_tool == 'checkpoint':
                return ThinkingRenderIntent(
                    kind='checkpoint',
                    text=thought,
                    detail=payload or cleaned,
                    tag=tag,
                    source_tool=source_tool,
                )
            return ThinkingRenderIntent(
                kind='tool',
                text=thought,
                detail=payload or cleaned,
                tag=tag,
                source_tool=source_tool,
            )

        if tag in self._MEMORY_THINK_TAGS:
            return ThinkingRenderIntent(
                kind='memory',
                text=thought,
                detail=payload,
                tag=tag,
            )
        if tag == 'BLACKBOARD':
            return ThinkingRenderIntent(
                kind='shared',
                text=thought,
                detail=payload,
                tag=tag,
            )
        if tag in self._CHECKPOINT_THINK_TAGS:
            return ThinkingRenderIntent(
                kind='checkpoint',
                text=thought,
                detail=payload,
                tag=tag,
            )
        if tag in self._CODE_THINK_TAGS:
            return ThinkingRenderIntent(
                kind='code',
                text=thought,
                detail=payload,
                tag=tag,
            )
        if tag in self._TASK_THINK_TAGS:
            return ThinkingRenderIntent(
                kind='tool',
                text=thought,
                detail=payload,
                tag=tag,
            )

        return ThinkingRenderIntent(kind='thinking', text=thought)

    def _should_render_thinking_text(self, text: str) -> bool:
        thought = self._canonical_thinking_text(text)
        if not self._is_visible_thinking_text(thought):
            return False

        digest = hashlib.sha256(thought.encode('utf-8')).hexdigest()[:16]
        if digest == getattr(self, '_last_thinking_text_hash', ''):
            return False

        self._last_thinking_text_hash = digest
        return True

    def _should_render_thinking_artifact(self, intent: ThinkingRenderIntent) -> bool:
        digest = hashlib.sha256(
            f'{intent.kind}:{intent.text}'.encode('utf-8')
        ).hexdigest()[:16]
        if digest == getattr(self, '_last_thinking_artifact_hash', ''):
            return False
        self._last_thinking_artifact_hash = digest
        return True

    def _render_thinking_payload(
        self,
        text: str,
        *,
        source_tool: str = '',
        finalize: bool = False,
    ) -> bool:
        """Render a thinking-like payload according to its normalized intent."""
        intent = self._classify_thinking_text(text, source_tool=source_tool)
        if intent.kind == 'suppress':
            return True

        if intent.kind == 'thinking':
            if self._should_render_thinking_text(intent.text):
                self._tui.add_thinking(intent.text)
            if finalize:
                self._tui.finalize_thinking()
            return True

        if not self._should_render_thinking_artifact(intent):
            return True

        if intent.kind == 'search':
            self._handle_search_code_action(intent.text)
            return True

        card = self._thinking_artifact_card(intent)
        if card is not None:
            self._write_card(card)
        return True

    def _thinking_artifact_card(self, intent: ThinkingRenderIntent) -> ActivityCard | None:
        text = intent.text
        detail = intent.detail or text
        tag = intent.tag

        if intent.kind == 'memory':
            if tag == 'WORKING_MEMORY':
                verb = 'Memory'
                card_detail = self._trim_card_detail(detail, fallback='working memory')
            elif tag == 'SEMANTIC_RECALL_RESULT':
                verb = 'Recalled'
                card_detail = self._trim_card_detail(detail, fallback='semantic memory')
            else:
                verb = 'Scratchpad'
                card_detail = self._trim_card_detail(detail, fallback='scratchpad')
            return self._compact_activity_card(
                verb=verb,
                detail=card_detail,
                badge_category='memory',
                title='Memory',
                body=text,
            )

        if intent.kind == 'shared':
            return self._compact_activity_card(
                verb='Shared Board',
                detail=self._trim_card_detail(detail, fallback='shared task board'),
                badge_category='workers',
                title='Workers',
                body=text,
            )

        if intent.kind == 'checkpoint':
            lowered = text.lower()
            if 'rollback' in lowered or 'revert' in lowered:
                verb = 'Rollback'
                fallback = 'checkpoint rollback'
            else:
                verb = 'Checkpoint'
                fallback = 'checkpoint'
            return self._compact_activity_card(
                verb=verb,
                detail=self._trim_card_detail(detail, fallback=fallback),
                badge_category='tool',
                title='Tool',
                body=text,
            )

        if intent.kind == 'code':
            verb = {
                'FIND_SYMBOLS': 'Found',
                'READ': 'Read',
                'READ_SYMBOL_DEFINITION': 'Read',
                'VERIFY_FILE_LINES': 'Verified',
            }.get(tag, 'Analyzed')
            return self._compact_activity_card(
                verb=verb,
                detail=self._trim_card_detail(detail, fallback='code context'),
                badge_category='code',
                title='Code',
                body=text,
            )

        if intent.kind == 'tool':
            source = intent.source_tool or tag.replace('_', ' ').title() or 'tool'
            return self._compact_activity_card(
                verb=source.replace('_', ' ').title(),
                detail=self._trim_card_detail(detail, fallback=source),
                badge_category='tool',
                title='Tool',
                body=text,
            )

        if intent.kind == 'error':
            return ActivityCard(
                verb='Invalid Tool Call',
                detail=intent.detail,
                badge_category='error',
                title='Error',
                secondary='failed',
                secondary_kind='err',
                extra_lines=[],
                is_collapsible=False,
                start_collapsed=True,
            )

        return None

    def _compact_activity_card(
        self,
        *,
        verb: str,
        detail: str,
        badge_category: str,
        title: str,
        body: str,
    ) -> ActivityCard:
        lines = [line.rstrip() for line in (body or '').splitlines() if line.strip()]
        preview_lines = lines[:12]
        extra_lines = [
            ActivityLine(line, style=NAVY_TEXT_MUTED, indent=0)
            for line in preview_lines
        ]
        if len(lines) > len(preview_lines):
            extra_lines.append(
                ActivityLine(
                    f'... {len(lines) - len(preview_lines)} more lines',
                    style=NAVY_TEXT_MUTED,
                    indent=0,
                )
            )
        return ActivityCard(
            verb=verb,
            detail=detail,
            badge_category=badge_category,
            title=title,
            secondary='done',
            secondary_kind='ok',
            extra_lines=extra_lines,
            is_collapsible=bool(extra_lines),
            start_collapsed=True,
        )
