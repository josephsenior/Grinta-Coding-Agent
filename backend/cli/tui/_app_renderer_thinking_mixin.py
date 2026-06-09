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

ThinkingIntentSeverity = Literal['error', 'warning']


@dataclass(frozen=True)
class ThinkingRenderIntent:
    """Normalized rendering decision for text carried by thinking-like events."""

    kind: ThinkingIntentKind
    text: str = ''
    detail: str = ''
    tag: str = ''
    source_tool: str = ''
    severity: ThinkingIntentSeverity = 'error'


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

    def _classify_error_intent(
        self,
        thought: str,
        kind: str,
    ) -> ThinkingRenderIntent | None:
        if kind in (
            'recoverable_error',
            'recoverable_error_escalated',
        ):
            detail_line = self._first_meaningful_line(thought)
            return ThinkingRenderIntent(
                kind='error',
                text=thought,
                detail=detail_line,
                tag='ERROR',
                severity='warning',
            )
        if kind == 'truncated':
            detail_line = (
                "Previous tool call arguments were stream-truncated "
                "(JSON never closed)."
            )
            return ThinkingRenderIntent(
                kind='error',
                text=thought,
                detail=detail_line,
                tag='ERROR',
                severity='warning',
            )
        return None

    def _classify_search_intent(
        self,
        thought: str,
        source_tool: str,
    ) -> ThinkingRenderIntent | None:
        if source_tool in ('grep', 'glob') or '[SEARCH_RESULTS]' in thought:
            return ThinkingRenderIntent(
                kind='search',
                text=thought,
                source_tool=source_tool,
            )
        return None

    def _classify_by_source_tool(
        self,
        thought: str,
        source_tool: str,
        tag: str,
        payload: str,
        cleaned: str,
    ) -> ThinkingRenderIntent | None:
        if not source_tool:
            return None
        detail = payload or cleaned
        if source_tool == 'checkpoint':
            return ThinkingRenderIntent(
                kind='checkpoint',
                text=thought,
                detail=detail,
                tag=tag,
                source_tool=source_tool,
            )
        return ThinkingRenderIntent(
            kind='tool',
            text=thought,
            detail=detail,
            tag=tag,
            source_tool=source_tool,
        )

    def _classify_by_tag(
        self,
        thought: str,
        tag: str,
        payload: str,
    ) -> ThinkingRenderIntent:
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

    def _parse_think_tag(self, cleaned: str) -> tuple[str, str]:
        tag_match = INTERNAL_THINK_TAG_RE.match(cleaned)
        if tag_match is None:
            return '', cleaned
        tag = (tag_match.group('tag') or '').upper()
        payload = (tag_match.group('payload') or '').strip()
        return tag, payload

    def _classify_thinking_text(
        self,
        text: str,
        *,
        source_tool: str = '',
        kind: str = '',
    ) -> ThinkingRenderIntent:
        thought = self._canonical_thinking_text(text)
        if not self._is_visible_thinking_text(thought):
            return ThinkingRenderIntent(kind='suppress')

        error_intent = self._classify_error_intent(thought, kind)
        if error_intent is not None:
            return error_intent

        search_intent = self._classify_search_intent(thought, source_tool)
        if search_intent is not None:
            return search_intent

        cleaned = self._strip_tool_payload_markup(thought)
        tag, payload = self._parse_think_tag(cleaned)

        tool_intent = self._classify_by_source_tool(
            thought, source_tool, tag, payload, cleaned
        )
        if tool_intent is not None:
            return tool_intent

        return self._classify_by_tag(thought, tag, payload)

    @staticmethod
    def _first_meaningful_line(text: str) -> str:
        for line in (text or '').splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return (text or '').strip()

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

    def _render_thinking_text_intent(self, intent: ThinkingRenderIntent, finalize: bool) -> None:
        if self._should_render_thinking_text(intent.text):
            self._tui.add_thinking(intent.text)
        if finalize:
            self._tui.finalize_thinking()

    def _render_error_intent(self, intent: ThinkingRenderIntent) -> None:
        message = intent.detail or intent.text
        if intent.severity == 'warning':
            self._tui.add_warning(message)
        else:
            self._tui.add_error(message)

    def _render_thinking_payload(
        self,
        text: str,
        *,
        source_tool: str = '',
        finalize: bool = False,
        kind: str = '',
    ) -> bool:
        """Render a thinking-like payload according to its normalized intent."""
        intent = self._classify_thinking_text(
            text, source_tool=source_tool, kind=kind
        )
        if intent.kind == 'suppress':
            return True

        if intent.kind == 'thinking':
            self._render_thinking_text_intent(intent, finalize)
            return True

        if not self._should_render_thinking_artifact(intent):
            return True

        if intent.kind == 'search':
            self._handle_search_action(
                intent.text, source_tool=intent.source_tool or 'search'
            )
            return True

        if intent.kind == 'error':
            self._render_error_intent(intent)
            return True

        card = self._thinking_artifact_card(intent)
        if card is not None:
            self._write_card(card)
        return True

    def _memory_artifact_card(self, intent: ThinkingRenderIntent) -> ActivityCard:
        text = intent.text
        detail = intent.detail or text
        tag = intent.tag
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

    def _checkpoint_artifact_card(self, intent: ThinkingRenderIntent) -> ActivityCard:
        text = intent.text
        detail = intent.detail or text
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

    def _code_artifact_card(self, intent: ThinkingRenderIntent) -> ActivityCard:
        text = intent.text
        detail = intent.detail or text
        tag = intent.tag
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

    def _tool_artifact_card(self, intent: ThinkingRenderIntent) -> ActivityCard:
        text = intent.text
        detail = intent.detail or text
        tag = intent.tag
        source = intent.source_tool or tag.replace('_', ' ').title() or 'tool'
        return self._compact_activity_card(
            verb=source.replace('_', ' ').title(),
            detail=self._trim_card_detail(detail, fallback=source),
            badge_category='tool',
            title='Tool',
            body=text,
        )

    def _thinking_artifact_card(self, intent: ThinkingRenderIntent) -> ActivityCard | None:
        text = intent.text
        detail = intent.detail or text

        if intent.kind == 'memory':
            return self._memory_artifact_card(intent)

        if intent.kind == 'shared':
            return self._compact_activity_card(
                verb='Shared Board',
                detail=self._trim_card_detail(detail, fallback='shared task board'),
                badge_category='workers',
                title='Workers',
                body=text,
            )

        if intent.kind == 'checkpoint':
            return self._checkpoint_artifact_card(intent)

        if intent.kind == 'code':
            return self._code_artifact_card(intent)

        if intent.kind == 'tool':
            return self._tool_artifact_card(intent)

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
