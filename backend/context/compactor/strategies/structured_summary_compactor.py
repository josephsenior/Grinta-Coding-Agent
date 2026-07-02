"""Free-prose compactor that converts history into a state summary.

A single unconstrained LLM call produces a rich narrative summary; the model
allocates its full attention to synthesis instead of schema compliance. A
minimal deterministic sanity gate (non-empty + substantial length) blocks
empty / tiny outputs. On any failure the compactor flags itself degraded so
the pipeline rejects the compaction and never replaces history with emptiness.

Canonical task state is maintained independently by the deterministic
``reduce_events_into_state`` track; this compactor does not produce a
canonical patch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.context.compactor.compactor import BaseLLMCompactor, Compaction
from backend.context.view import View
from backend.core.logging.logger import app_logger as logger
from backend.core.message import Message, TextContent
from backend.ledger.event import Event
from backend.ledger.observation.agent import AgentCondensationObservation

# Default minimum length for an accepted prose summary. Shorter outputs are
# treated as degraded (model refusal / truncation / empty) so the pipeline
# falls back to deterministic compaction instead of wiping history.
DEFAULT_MIN_PROSE_LENGTH = 2000
# Default number of same-prompt retries when the sanity gate fails. 0 means a
# short/empty output immediately degrades to the deterministic fallback; the
# model is otherwise trusted to surface what matters without brittle repair.
DEFAULT_MAX_REPAIR_ATTEMPTS = 0
# Maximum summary budget in tokens. Actual budget is
# min(context_window * 0.05, DEFAULT_SUMMARY_BUDGET_TOKENS).
DEFAULT_SUMMARY_BUDGET_TOKENS = 12_000

# Nudge appended on a retry when the previous output was too short.
_REPAIR_NUDGE = (
    '\n\nYour previous summary was too short to preserve the session context. '
    'Produce a complete compaction covering the full arc: the USER GOAL section '
    '(synthesized from all user messages), what was accomplished, decisions and '
    'their rationale, current blockers, remaining work, and failed approaches '
    'to avoid. Be precise and complete.'
)


class StructuredSummaryCompactor(BaseLLMCompactor):
    """Free-prose compactor with a deterministic sanity gate.

    Maintains a condensed history and prunes old events when it grows too
    large. Produces a single unconstrained prose summary; canonical task state
    is maintained separately by the deterministic canonical-state track.
    """

    def __init__(
        self,
        llm: Any,
        max_size: int = 100,
        keep_first: int = 1,
        max_event_length: int = 10000,
        *,
        min_prose_length: int = DEFAULT_MIN_PROSE_LENGTH,
        max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
    ) -> None:
        """Initialize the prose compactor.

        Args:
            llm: Language model instance for generating the summary.
            max_size: Maximum number of events before condensation is triggered.
            keep_first: Number of initial events to always preserve.
            max_event_length: Maximum character length for individual event content.
            min_prose_length: Minimum character length for an accepted prose summary.
            max_repair_attempts: Same-prompt retries when the sanity gate fails.
        """
        super().__init__(
            llm=llm,
            max_size=max_size,
            keep_first=keep_first,
            max_event_length=max_event_length,
        )
        self.min_prose_length = min_prose_length
        self.max_repair_attempts = max_repair_attempts
        self._has_user_messages = False

    def _validate_llm(self) -> None:
        """No function-calling requirement: prose compaction uses plain completion."""

    def _get_summary_char_limit(self) -> int:
        """Calculate the char limit for the prose summary.

        Uses ``min(context_window * 0.05, 12 000 tokens)`` converted to
        characters (~4 chars/token). Falls back to the full 12 000 token cap
        when the LLM context window is unknown.
        """
        tokens = DEFAULT_SUMMARY_BUDGET_TOKENS
        try:
            if self.llm is not None and hasattr(self.llm, 'config'):
                max_input = getattr(self.llm.config, 'max_input_tokens', None)
                if isinstance(max_input, int) and max_input > 0:
                    tokens = min(int(max_input * 0.05), DEFAULT_SUMMARY_BUDGET_TOKENS)
        except Exception:
            pass
        return tokens * 4

    @staticmethod
    def _get_extra_config_args(config: Any) -> dict[str, Any]:
        """Pass prose-specific config through to the constructor."""
        extra_args: dict[str, Any] = {}
        if hasattr(config, 'max_event_length'):
            extra_args['max_event_length'] = config.max_event_length
        if hasattr(config, 'min_prose_length'):
            extra_args['min_prose_length'] = config.min_prose_length
        if hasattr(config, 'max_repair_attempts'):
            extra_args['max_repair_attempts'] = config.max_repair_attempts
        return extra_args

    async def get_compaction(self, view: View) -> Compaction:
        """Generate condensation from view by summarizing pruned events.

        If the LLM call fails (network, rate-limit, provider outage) or the
        produced prose fails the sanity gate after any retries, the compactor
        falls back to a non-LLM degraded summary and flags itself degraded so
        the pipeline rejects the compaction instead of hard-stalling or wiping
        context.
        """
        _head, pruned_events, summary_event = self._prepare_view_sections(view)
        if not pruned_events:
            return self._create_compaction_result(pruned_events, '')

        # Load pre-condensation snapshot to inject all user messages
        # verbatim into the compaction prompt as ground truth for
        # goal synthesis.
        snapshot = self._load_snapshot_for_prompt()

        # Extract previous ## USER GOAL section for tripwire comparison.
        previous_goal = ''
        if summary_event and summary_event.message:
            previous_goal = self._extract_section(
                summary_event.message, '## USER GOAL'
            )

        prompt = self._build_condensation_prompt(
            summary_event, pruned_events, snapshot=snapshot,
            char_limit=self._get_summary_char_limit()
        )

        self.last_degraded = False

        try:
            prose = await self._get_llm_prose_summary(prompt)
            attempts = 0
            while (
                not self._passes_prose_sanity_gate(prose)
                and attempts < self.max_repair_attempts
            ):
                attempts += 1
                logger.info(
                    'Condensation prose sanity gate failed (len=%d < %d); '
                    'retry %d/%d',
                    len(prose),
                    self.min_prose_length,
                    attempts,
                    self.max_repair_attempts,
                )
                prose = await self._get_llm_prose_summary(prompt, nudge=True)

            if self._passes_prose_sanity_gate(prose):
                summary_text = prose
                self._check_goal_regression(prose, previous_goal)
            else:
                self.last_degraded = True
                logger.warning(
                    'Condensation prose sanity gate failed after %d retry(es); '
                    'falling back to degraded summary so history is not wiped.',
                    attempts,
                )
                summary_text = self._degraded_summary(
                    summary_event,
                    pruned_events,
                    ValueError('prose sanity gate failed'),
                )
        except Exception as e:
            self.last_degraded = True
            logger.warning(
                'Condensation LLM call failed (%s: %s); falling back to '
                'degraded summary so the agent can continue.',
                type(e).__name__,
                e,
            )
            summary_text = self._degraded_summary(summary_event, pruned_events, e)

        return self._create_compaction_result(pruned_events, summary_text)

    def _passes_prose_sanity_gate(self, prose: str) -> bool:
        """Return True when the prose is non-empty, substantial, and has a USER GOAL section.

        Intentionally relaxed: no refusal/error regex (a model refusal is too
        short to pass the length floor anyway) and no anchor recall. The model
        is trusted to surface what matters; the gate only guards against the
        silent empty-output failure mode and ensures the USER GOAL section
        exists when user messages were injected.

        The USER GOAL check is structural (does the header exist?), not
        content regex (we don't check what the goal says). It only fires when
        user messages were injected into the prompt — if there are no user
        messages, the section is not required.
        """
        if not prose:
            return False
        if len(prose.strip()) < self.min_prose_length:
            return False
        if self._has_user_messages and '## USER GOAL' not in prose:
            return False
        return True

    def _check_goal_regression(
        self, prose: str, previous_goal_text: str | None,
    ) -> None:
        """Non-blocking tripwire: warn if the USER GOAL section shrank significantly.

        Catches the exact failure pattern observed in production: the goal
        silently compressing across compactions until the original objective
        is lost. This is NOT content validation — it's a length comparison
        between the previous and current goal sections. A legitimate pivot
        ("forget all that, just fix this typo") will trigger a false positive,
        which is fine: the warning is logged for audit, the compaction is
        accepted.
        """
        if not previous_goal_text:
            return
        new_goal = self._extract_section(prose, '## USER GOAL')
        if not new_goal:
            return
        prev_len = len(previous_goal_text.strip())
        new_len = len(new_goal.strip())
        if prev_len > 0 and new_len < prev_len * 0.6:
            logger.warning(
                'USER GOAL section regressed: %d -> %d chars (%.0f%% of '
                'previous). Possible pivot or content loss — review advised.',
                prev_len,
                new_len,
                (new_len / prev_len) * 100,
            )

    async def _get_llm_prose_summary(self, prompt: str, *, nudge: bool = False) -> str:
        """Get a free-prose summary from the LLM (no tools, no schema).

        Streams the completion when a ``streaming_emitter`` is configured
        on the compactor (so the TUI can show the summary in real time);
        otherwise falls back to a single non-streaming call.
        """
        assert self.llm is not None, 'LLM required for prose compactor'
        messages = [
            Message(
                role='user',
                content=[TextContent(text=prompt + (_REPAIR_NUDGE if nudge else ''))],
            )
        ]
        formatted = self.llm.format_messages_for_llm(messages)
        if getattr(self, 'streaming_emitter', None) is not None:
            response = await self._stream_llm_completion(formatted)
        else:
            response = await self.llm.acompletion(messages=formatted)
        self._add_response_metadata(response)
        return self._extract_prose_content(response)

    def _extract_prose_content(self, response: Any) -> str:
        """Extract the prose text from an LLM completion response."""
        try:
            choices = getattr(response, 'choices', None)
            if not choices:
                return ''
            message = choices[0].message
            content = getattr(message, 'content', None)
            if isinstance(content, str):
                return content
            # Some providers return a list of content blocks; join text parts.
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, str):
                        parts.append(block)
                        continue
                    text = getattr(block, 'text', None)
                    if isinstance(text, str):
                        parts.append(text)
                return '\n'.join(parts)
            return ''
        except (AttributeError, IndexError, TypeError) as e:
            logger.warning(
                'Failed to extract prose content from LLM response: %s', e
            )
            return ''

    def _degraded_summary(
        self,
        summary_event: AgentCondensationObservation,
        pruned_events: list[Event],
        error: BaseException,
    ) -> str:
        """Build a non-LLM placeholder summary used when the summarizer fails.

        Preserves the previous summary (if any) and lists the IDs and types of
        the events being pruned so the agent retains a minimal audit trail.
        """
        prior = str(summary_event) if summary_event else ''
        lines: list[str] = [
            '# State Summary (degraded)',
            f'NOTE: condensation summarizer unavailable ({type(error).__name__}). '
            'Pruned events listed by id/type only; re-summarization will be '
            'attempted on the next compaction cycle.',
        ]
        if prior and prior != 'No events summarized':
            lines.append('## Previous Summary')
            lines.append(prior)
        if pruned_events:
            lines.append('## Pruned Events')
            for ev in pruned_events[:200]:  # hard cap to keep this small
                ev_id = getattr(ev, 'id', '?')
                lines.append(f'- {type(ev).__name__} id={ev_id}')
            if len(pruned_events) > 200:
                lines.append(f'- ... and {len(pruned_events) - 200} more')
        return '\n'.join(lines)

    def _prepare_view_sections(
        self, view: View
    ) -> tuple[list[Event], list[Event], AgentCondensationObservation]:
        """Prepare view sections: head, pruned events, and summary event."""
        head = list(view[: self.keep_first])
        target_size = self.max_size // 2
        events_from_tail = target_size - len(head) - 1

        # Get or create summary event
        summary_event: AgentCondensationObservation
        try:
            candidate_event = view[self.keep_first]
        except IndexError:
            candidate_event = None

        if isinstance(candidate_event, AgentCondensationObservation):
            summary_event = candidate_event
        else:
            summary_event = AgentCondensationObservation('No events summarized')

        # Get pruned events (exclude summary events). Build the stop index
        # explicitly so tail_count=0 means "through the end", not slice stop 0.
        tail_count = max(0, events_from_tail)
        stop = len(view) - tail_count if tail_count else len(view)
        pruned_slice = view[self.keep_first : stop]
        pruned_events: list[Event] = [
            event
            for event in pruned_slice
            if not isinstance(event, AgentCondensationObservation)
        ]

        return head, pruned_events, summary_event

    @staticmethod
    def _load_snapshot_for_prompt() -> dict[str, Any] | None:
        """Load the pre-condensation snapshot for prompt injection.

        Returns the snapshot dict if available, None otherwise. The snapshot
        contains all user messages verbatim, which are critical for goal
        synthesis during compaction.
        """
        try:
            from backend.context.compactor.pre_condensation_snapshot import (
                load_snapshot,
            )
            return load_snapshot()
        except Exception:
            return None

    def _digest_events(self, events: list[Event]) -> str:
        """Group events by type and produce a compact digest.

        Instead of sending raw events (which can be 500k+ chars for 50 events
        at 10k each), this classifies events into groups and summarizes each.
        This reduces prompt size 5-10x and reduces recency bias by showing the
        big picture (e.g. "19 files created") rather than burying it in detail.
        """
        files_created: list[str] = []
        files_edited: list[str] = []
        commands_run: list[tuple[str, int | None]] = []
        agent_thoughts: list[str] = []
        code_nav: list[str] = []
        errors: list[str] = []
        other_count = 0

        for event in events:
            type_name = type(event).__name__

            if type_name == 'FileEditAction':
                path = getattr(event, 'path', '')
                cmd = getattr(event, 'command', '')
                if path:
                    if cmd == 'create_file':
                        files_created.append(path)
                    else:
                        files_edited.append(path)
            elif type_name == 'FileEditObservation':
                path = getattr(event, 'path', '')
                if path and path not in files_edited:
                    files_edited.append(path)
            elif type_name == 'CmdRunAction':
                cmd = getattr(event, 'command', '')
                if cmd:
                    commands_run.append((cmd, None))
            elif type_name == 'CmdOutputObservation':
                cmd = getattr(event, 'command', '')
                exit_code = getattr(event, 'exit_code', None)
                if cmd:
                    if exit_code and exit_code != 0:
                        content = str(event)[:200]
                        errors.append(f'{cmd} (exit={exit_code}): {content}')
                    commands_run.append((cmd, exit_code))
            elif type_name == 'ErrorObservation':
                content = str(event)[:200]
                errors.append(content)
            elif type_name == 'MessageAction':
                source = getattr(event, 'source', None)
                if source and 'user' in str(source).lower():
                    continue
                agent_thoughts.append(str(event))
            elif type_name in ('AgentThinkAction', 'SystemHintAction'):
                agent_thoughts.append(str(event)[:200])
            elif type_name in (
                'FileReadAction',
                'GlobAction',
                'GrepAction',
                'FindSymbolsAction',
                'LspQueryAction',
            ):
                path = getattr(event, 'path', '') or getattr(event, 'query', '') or getattr(event, 'pattern', '')
                code_nav.append(f'{type_name.replace("Action", "")}: {path}' if path else type_name)
            elif type_name in (
                'AgentCondensationObservation',
                'NullAction',
                'NullObservation',
            ):
                continue
            else:
                other_count += 1

        lines: list[str] = []

        if files_created:
            if len(files_created) <= 15:
                lines.append(f'Files created ({len(files_created)}): {", ".join(files_created)}')
            else:
                lines.append(
                    f'Files created ({len(files_created)}): {", ".join(files_created[:15])}, '
                    f'... and {len(files_created) - 15} more'
                )
        if files_edited:
            unique_edited = list(dict.fromkeys(files_edited))
            if len(unique_edited) <= 15:
                lines.append(f'Files edited ({len(unique_edited)} unique): {", ".join(unique_edited)}')
            else:
                lines.append(
                    f'Files edited ({len(unique_edited)} unique): {", ".join(unique_edited[:15])}, '
                    f'... and {len(unique_edited) - 15} more'
                )
        if commands_run:
            unique_cmds = list(dict.fromkeys(commands_run))
            cmd_strs = [
                f'{cmd} (exit={exit_code})' if exit_code is not None else cmd
                for cmd, exit_code in unique_cmds[:20]
            ]
            lines.append(f'Commands run ({len(unique_cmds)} unique): {"; ".join(cmd_strs)}')
        if errors:
            lines.append(f'Errors ({len(errors)}):')
            for err in errors[:10]:
                lines.append(f'  - {err}')
        if agent_thoughts:
            lines.append(f'Agent reasoning/thought steps: {len(agent_thoughts)}')
        if code_nav:
            unique_nav = list(dict.fromkeys(code_nav))
            lines.append(f'Code navigation ({len(unique_nav)}): {"; ".join(unique_nav[:20])}')
        if other_count:
            lines.append(f'Other events: {other_count}')

        return '\n'.join(lines) if lines else '(no events)'

    @staticmethod
    def _extract_section(text: str, header: str) -> str:
        """Extract the content of a markdown section from text.

        Returns the content between ``header`` and the next ``## `` header
        (or end of text). Returns empty string if the header is not found.
        """
        idx = text.find(header)
        if idx < 0:
            return ''
        start = idx + len(header)
        next_header = text.find('\n## ', start)
        if next_header < 0:
            return text[start:].strip()
        return text[start:next_header].strip()

    def _build_condensation_prompt(
        self, summary_event: AgentCondensationObservation, pruned_events: list,
        *, snapshot: dict[str, Any] | None = None, char_limit: int = 48000,
    ) -> str:
        """Build the prompt for LLM condensation.

        Events are pre-digested into a compact type-grouped summary to reduce
        prompt size and recency bias. The last few raw events are included
        for detailed context. The prompt enforces a priority-ordered structure
        with a hard character budget.

        All user messages from the snapshot are injected verbatim as ground
        truth for goal synthesis. The previous ``## USER GOAL`` section from
        the prior summary is injected so the LLM can refine it with new
        messages rather than re-deriving from scratch.
        """
        user_messages_section = ''
        previous_goal_section = ''
        has_user_messages = False

        if snapshot:
            messages = snapshot.get('user_messages')
            if isinstance(messages, list) and messages:
                parts = ['### USER MESSAGES (verbatim ground truth for goal synthesis)']
                for i, item in enumerate(messages, 1):
                    if not isinstance(item, dict):
                        continue
                    text = str(item.get('text', '')).strip()
                    if text:
                        parts.append(f'[{i}] {text}')
                if len(parts) > 1:
                    user_messages_section = '\n'.join(parts) + '\n\n'
                    has_user_messages = True

        self._has_user_messages = has_user_messages

        if summary_event and summary_event.message:
            prev_goal = self._extract_section(summary_event.message, '## USER GOAL')
            if prev_goal:
                previous_goal_section = (
                    '### PREVIOUS GOAL SYNTHESIS (refine with new messages)\n'
                    f'{prev_goal}\n\n'
                )

        base_prompt = (
            'You are maintaining the state summary of an interactive software '
            'agent. This summary is critical: it lets the agent resume work '
            'WITHOUT re-reading the full conversation history once it has been '
            'compacted for length.\n\n'
            f'{user_messages_section}{previous_goal_section}'
            'You will be given:\n'
            '- <PREVIOUS SUMMARY>: the prior compaction summary (preserve its '
            'narrative arc)\n'
            '- <EVENT DIGEST>: a compact grouped breakdown of what happened '
            '(files created/edited, commands run, errors)\n'
            '- <RECENT RAW EVENTS>: the last few raw events for detailed '
            'context\n\n'
            '### BUDGET CONSTRAINT\n'
            f'Your entire response MUST not exceed {char_limit} characters.\n'
            'To stay under this hard cap, use tight, hyper-dense Markdown '
            'structures (bullet points, key-value pairs, tables). Avoid '
            'conversational filler, narrative prose, or meta-commentary (e.g., '
            'do not say "In this session, the agent...").\n\n'
            'If you are running close to the character limit, compress '
            'lower-priority sections into dense, single-line bullets. Never '
            'truncate or drop higher-priority sections.\n\n'
            '### PRIORITY ORDER & STRUCTURE\n'
            'Format your response using the following headers in this exact '
            'order. If budget runs tight, compress from the bottom up:\n\n'
        )

        if has_user_messages:
            base_prompt += (
                '0. ## USER GOAL (Highest Priority — Never Drop)\n'
                "Synthesize the user's current goal from ALL their messages "
                'above AND the previous goal synthesis (if provided). Capture:\n'
                '- The original intent (what they asked for initially)\n'
                '- All constraints, acceptance criteria, and preferences stated\n'
                '- Any refinements, pivots, or scope changes\n'
                '- If the user abandoned a previous goal, state the CURRENT goal\n'
                'Reproduce specific constraints (e.g. "must run under X ms", '
                '"do not modify Y") verbatim — never paraphrase technical '
                'constraints.\n'
                'When the goal evolves, cite the user message number [N] that '
                'triggered the change. Use [DEPRIORITIZED] or [SUPERSEDED] '
                'markers for constraints that are no longer active, but ONLY '
                'when a user message explicitly authorized the change — never '
                'on your own inference that something "seems less relevant".\n\n'
            )

        base_prompt += (
            '1. ## UNRESOLVED & BLOCKING\n'
            'What is currently blocking, failing, untested, or incomplete. '
            'Preserve this verbatim. Never paraphrase, never compress, never '
            'drop. If a test was skipped, say exactly why. If a spec '
            'requirement was not met, say exactly which one and what the gap '
            'is. Flag any spec requirement that could not be verified on this '
            'platform, or any test that is structural rather than behavioral, '
            'with [UNVERIFIED] so the resuming agent knows to treat it as '
            'unproven.\n\n'
            '2. ## NEXT STEPS\n'
            'What remains to do, with concrete immediate action items for the '
            'resuming agent.\n\n'
            '3. ## FAILED APPROACHES\n'
            'Only list failures of the actual execution approach '
            '(e.g. "type inference hangs on tuple patterns", "test suite '
            'times out"), not tool-level errors like "old_string not found" '
            'or "undo not available".\n\n'
            '4. ## ACCOMPLISHED & ARCHITECTURE\n'
            'What was concretely built, fixed, or created across the entire '
            'session. Preserve the overarching historical narrative arc from '
            '<PREVIOUS SUMMARY> so early architectural changes are not wiped '
            'out by recent incremental bug fixes.\n\n'
            '5. ## DECISIONS & RATIONALE (Lowest Priority)\n'
            'Key technical choices made and WHY (the rationale, constraints, '
            'or trade-offs, not just the outcome).\n\n'
            '### ADHERENCE TO DETAIL\n'
            '- Preserve VERBATIM: exact file paths, test names, exact error '
            'messages, function signatures, key variable/data values, and '
            'precise technical specifications stated by the user.\n'
            '- If the user messages contain specific constraints (e.g., "must '
            'run under X ms", "do not modify Y", "use Z"), reproduce them '
            'faithfully in the USER GOAL section. Never dilute technical '
            'constraints into vague paraphrase.\n'
            '- Never mark a test as passing if it only checks file existence '
            'or symbol presence in a header. A test passes only if it '
            'executes the actual behavior the spec requires and produces a '
            'verified behavioral result.\n'
            '- If a previous summary exists, you MUST preserve its key '
            'narrative. Do not replace the full arc with only recent bug '
            'fixes or incremental work.\n\n'
            'Summarize the session now, ensuring a fresh agent can seamlessly '
            'resume work using only this state.\n'
        )

        # Add previous summary
        summary_event_content = self._truncate(summary_event.message or '')
        base_prompt += (
            f'<PREVIOUS SUMMARY>\n{summary_event_content}\n</PREVIOUS SUMMARY>\n\n'
        )

        # Add event digest (compact grouped summary)
        digest = self._digest_events(pruned_events)
        base_prompt += f'<EVENT DIGEST>\n{digest}\n</EVENT DIGEST>\n\n'

        # Add last few raw events for detailed context
        raw_event_budget = 5
        recent_raw = pruned_events[-raw_event_budget:] if len(pruned_events) > raw_event_budget else pruned_events
        if recent_raw:
            base_prompt += '<RECENT RAW EVENTS (for detail)>\n'
            for pruned_event in recent_raw:
                event_content = self._truncate(str(pruned_event))
                base_prompt += f'<EVENT id={pruned_event.id}>\n{event_content}\n</EVENT>\n'
            base_prompt += '</RECENT RAW EVENTS>\n'

        return base_prompt


# Lazy registration to avoid circular imports
def _register_config():
    """Register StructuredSummaryCompactorConfig with the StructuredSummaryCompactor factory.

    Defers import of StructuredSummaryCompactorConfig to avoid circular dependency between
    compactor implementations and their configuration classes. Called at module load time
    to enable from_config() factory method to instantiate compactors from config objects.
    """
    from backend.core.config.compactor_config import StructuredSummaryCompactorConfig

    StructuredSummaryCompactor.register_config(StructuredSummaryCompactorConfig)


_register_config()
