"""Observation processors."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from backend.core.message import ImageContent, Message, TextContent
from backend.ledger.observation import (
    AnalyzeProjectStructureObservation,
    BrowserScreenshotObservation,
    CmdOutputObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    FindSymbolsObservation,
    MCPObservation,
    Observation,
    ReadSymbolsObservation,
    TerminalObservation,
    UserRejectObservation,
)
from backend.ledger.observation.agent import AgentCondensationObservation
from backend.ledger.observation.memory_tools import (
    CheckpointObservation,
    MemoryPersistObservation,
    MemoryRecallObservation,
    ScratchpadNoteObservation,
    ScratchpadRecallObservation,
    WorkingMemoryObservation,
)
from backend.ledger.observation.search import GlobObservation, GrepObservation
from backend.ledger.serialization.event import truncate_content

if TYPE_CHECKING:
    pass


_OBSERVATION_DISPATCH: dict[type, Callable[..., Message]] = {}


def _register_observation_handler(obs_type: type):
    def decorator(handler):
        _OBSERVATION_DISPATCH[obs_type] = handler
        return handler

    return decorator


def convert_observation_to_message(
    event: Observation,
    max_message_chars: int | None = None,
    vision_is_active: bool = False,
    enable_som_visual_browsing: bool = False,
) -> Message:
    """Convert an Observation event into a Message for the LLM.

    Args:
        event: The observation event to convert
        max_message_chars: Maximum characters for text content
        vision_is_active: Whether vision is enabled in the LLM
        enable_som_visual_browsing: Whether SOM (Set of Marks) visual browsing is enabled

    Returns:
        Message: A formatted message ready for the LLM

    """
    if _is_tool_backed_think_observation(event):
        return _handle_tool_backed_think_observation(event, max_message_chars)

    handler = _OBSERVATION_DISPATCH.get(type(event))
    if handler is not None:
        if isinstance(event, (BrowserScreenshotObservation, FileReadObservation)):
            return handler(event, max_message_chars, vision_is_active)
        return handler(event, max_message_chars)

    return _handle_simple_observation(event, max_message_chars)


@_register_observation_handler(FileReadObservation)
def _handle_file_read_observation(
    obs: FileReadObservation,
    max_message_chars: int | None,
    vision_is_active: bool = False,
) -> Message:
    path = getattr(obs, 'path', 'unknown')
    content = obs.content or ''
    if (
        vision_is_active
        and _is_valid_image_url(content)
        and content.startswith('data:image/')
    ):
        cap = truncate_content(
            f'[FILE_READ path={path}]\nImage attached below.',
            max_message_chars,
        )
        return Message(
            role='user',
            vision_enabled=True,
            content=[
                TextContent(text=cap),
                ImageContent(image_urls=[content]),
            ],
        )
    text = truncate_content(content, max_message_chars, strategy='head_heavy')
    text = f'[FILE_READ path={path}]\n{text}'
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(GrepObservation)
def _handle_grep_observation(
    obs: GrepObservation, max_message_chars: int | None
) -> Message:
    header = (
        f'[GREP pattern={obs.pattern!r} path={obs.path!r} mode={obs.output_mode!r}]'
    )
    body = obs.error or obs.content
    text = truncate_content(
        f'{header}\n{body}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(GlobObservation)
def _handle_glob_observation(
    obs: GlobObservation, max_message_chars: int | None
) -> Message:
    header = f'[GLOB pattern={obs.pattern!r} path={obs.path!r}]'
    body = obs.error or obs.content
    text = truncate_content(
        f'{header}\n{body}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(FindSymbolsObservation)
def _handle_find_symbols_observation(
    obs: FindSymbolsObservation, max_message_chars: int | None
) -> Message:
    header = (
        f'[FIND_SYMBOLS query={obs.query!r} path={obs.path!r} '
        f'symbol_kind={obs.symbol_kind!r}]'
    )
    body = obs.error or obs.content
    text = truncate_content(
        f'{header}\n{body}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(ReadSymbolsObservation)
def _handle_read_symbols_observation(
    obs: ReadSymbolsObservation, max_message_chars: int | None
) -> Message:
    header = f'[READ_SYMBOLS path={obs.path!r} symbol_kind={obs.symbol_kind!r}]'
    body = obs.error or obs.content
    text = truncate_content(
        f'{header}\n{body}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(AnalyzeProjectStructureObservation)
def _handle_analyze_project_structure_observation(
    obs: AnalyzeProjectStructureObservation, max_message_chars: int | None
) -> Message:
    header = (
        f'[ANALYZE_PROJECT_STRUCTURE command={obs.command!r} path={obs.path!r} '
        f'symbol={obs.symbol!r} depth={obs.depth!r} direction={obs.direction!r}]'
    )
    body = obs.error or obs.content
    text = truncate_content(
        f'{header}\n{body}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(CheckpointObservation)
def _handle_checkpoint_observation(
    obs: CheckpointObservation, max_message_chars: int | None
) -> Message:
    header = f'[CHECKPOINT command={obs.command!r} status={obs.status!r} ok={obs.ok}]'
    text = truncate_content(
        f'{header}\n{obs.content}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(WorkingMemoryObservation)
def _handle_working_memory_observation(
    obs: WorkingMemoryObservation, max_message_chars: int | None
) -> Message:
    header = f'[WORKING_MEMORY command={obs.command!r} section={obs.section!r}]'
    text = truncate_content(
        f'{header}\n{obs.content}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(MemoryPersistObservation)
def _handle_memory_persist_observation(
    obs: MemoryPersistObservation, max_message_chars: int | None
) -> Message:
    header = f'[MEMORY_PERSIST key={obs.key!r} kind={obs.kind!r}]'
    text = truncate_content(
        f'{header}\n{obs.content}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(MemoryRecallObservation)
def _handle_memory_recall_observation(
    obs: MemoryRecallObservation, max_message_chars: int | None
) -> Message:
    header = f'[MEMORY_RECALL query={obs.query!r}]'
    text = truncate_content(
        f'{header}\n{obs.content}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(ScratchpadNoteObservation)
def _handle_scratchpad_note_observation(
    obs: ScratchpadNoteObservation, max_message_chars: int | None
) -> Message:
    header = f'[SCRATCHPAD_NOTE key={obs.key!r}]'
    text = truncate_content(
        f'{header}\n{obs.content}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(ScratchpadRecallObservation)
def _handle_scratchpad_recall_observation(
    obs: ScratchpadRecallObservation, max_message_chars: int | None
) -> Message:
    header = f'[SCRATCHPAD_RECALL key={obs.key!r} found={obs.found}]'
    text = truncate_content(
        f'{header}\n{obs.content}', max_message_chars, strategy='head_heavy'
    )
    return Message(role='user', content=[TextContent(text=text)])


def _is_tool_backed_think_observation(event: Observation) -> bool:
    tool_result = getattr(event, 'tool_result', None)
    return type(event).__name__ == 'AgentThinkObservation' and isinstance(
        tool_result, dict
    )


def _handle_tool_backed_think_observation(
    obs: Observation, max_message_chars: int | None
) -> Message:
    import json as _json

    tool_result = getattr(obs, 'tool_result', None)
    assert isinstance(tool_result, dict)
    payload = _json.dumps(tool_result, ensure_ascii=False)
    if getattr(obs, 'tool_call_metadata', None) is not None:
        text_content = payload
    else:
        text_content = 'Internal tool observation, not a user request.\n' + payload
    text = truncate_content(
        text_content,
        max_message_chars,
        strategy='balanced',
    )
    return Message(role='user', content=[TextContent(text=text)])


def _get_observation_content(obs: Observation) -> str:
    """Extract content string from observation."""
    if hasattr(obs, 'content') and isinstance(obs.content, str):
        return obs.content
    if hasattr(obs, 'message') and isinstance(obs.message, str):
        return obs.message
    return str(obs)


def _is_valid_image_url(url: object) -> bool:
    """Return True when the provided value looks like a usable image reference.

    This is intentionally permissive: URLs, data-URLs, and local/relative paths
    are all treated as valid as long as they are non-empty strings.
    """
    if not isinstance(url, str):
        return False
    return bool(url.strip())


def _handle_simple_observation(
    obs: Observation,
    max_message_chars: int | None,
    prefix: str = '',
    suffix: str = '',
) -> Message:
    """Handle simple/generic observations.

    Observations without tool_call_metadata are rendered as role='user' but
    prefixed with a clear marker to disambiguate them from real user input.
    This prevents the LLM from confusing tool output with user messages.
    """
    content_str = _get_observation_content(obs)
    text = truncate_content(content_str, max_message_chars)

    # Add disambiguation prefix for observations without metadata
    has_metadata = getattr(obs, 'tool_call_metadata', None) is not None
    if not has_metadata and not prefix:
        obs_type = type(obs).__name__
        text = f'[Observation: {obs_type}]\n{text}'

    if prefix:
        text = prefix + text
    if suffix:
        text += suffix
    return Message(role='user', content=[TextContent(text=text)])


_CONDENSATION_BANNER = (
    '\u26a1 CONTEXT CONDENSED — older conversation events were replaced by the summary below.\n'
    + '─' * 60
    + '\n'
)

_POST_CONDENSATION_RECOVERY = (
    '\n' + '─' * 60 + '\n'
    'Context was condensed. The canonical task state and restored context '
    'above are your source of truth — do not hallucinate next actions.\n'
    'Continue from the next_action field in the canonical state.\n'
    'Do NOT re-read files you already created — trust your prior writes.\n'
)

# Patterns that could be used to inject adversarial instructions via stored memory.
# Lines starting with any of these prefixes are stripped at injection time (not at
# storage time, so the raw data is never corrupted).
_PROMPT_INJECTION_PREFIXES: tuple[str, ...] = (
    'ignore ',
    'ignore\n',
    'ignore:',
    'system:',
    '<system>',
    '[inst]',
    '[/inst]',
    '### instruction',
    '###instruction',
    '<|im_start|>',
    '<|im_end|>',
    '<|system|>',
    'disregard ',
    'forget ',
    'new task:',
    'new instructions:',
)


def _sanitize_memory_content(text: str) -> str:
    """Strip lines that look like prompt-injection attempts.

    Only the line is removed; the surrounding content is preserved.
    Comparison is case-insensitive and strips leading whitespace per line.
    """
    clean_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip().lower()
        if any(stripped.startswith(prefix) for prefix in _PROMPT_INJECTION_PREFIXES):
            continue
        clean_lines.append(line)
    return '\n'.join(clean_lines)


def _load_scratchpad_snapshot() -> str:
    """Load scratchpad notes for injection into post-condensation context.

    Returns the formatted scratchpad content, or empty string if unavailable.
    This replaces the unreliable 'call recall(key=all)' instruction with
    a programmatic guarantee that scratchpad data survives condensation.
    """
    try:
        from backend.engine.tools.scratchpad import _load_notes

        notes = _load_notes()
        if not notes:
            return ''
        import json

        body = _sanitize_memory_content(json.dumps(notes, indent=2, ensure_ascii=False))
        return '\n' + '─' * 60 + f'\n📋 SCRATCHPAD (auto-restored):\n{body}\n'
    except Exception:
        return ''


def _load_working_memory_snapshot() -> str:
    """Load structured working memory for post-condensation recovery."""
    try:
        from backend.engine.tools.working_memory import (
            get_working_memory_prompt_block,
        )

        block = get_working_memory_prompt_block()
        if not block:
            return ''
        return '\n' + '─' * 60 + '\n' + f'{_sanitize_memory_content(block)}\n'
    except Exception:
        return ''


def _load_restored_context_snapshot() -> str:
    """Load durable pre-condensation snapshot for recovery injection."""
    try:
        from backend.context.compactor.pre_condensation_snapshot import (
            format_snapshot_for_injection,
            load_snapshot,
        )

        snapshot = load_snapshot()
        if not snapshot:
            return ''

        block = format_snapshot_for_injection(snapshot)
        return '\n' + '─' * 60 + '\n' + f'{_sanitize_memory_content(block)}\n'
    except Exception:
        return ''


def _is_working_set_observation(obs: AgentCondensationObservation) -> bool:
    if getattr(obs, 'is_working_set', False):
        return True
    content = (obs.content or '').lstrip()
    return content.startswith('<DURABLE_WORKING_SET>')


@_register_observation_handler(AgentCondensationObservation)
def _handle_condensation_observation(
    obs: AgentCondensationObservation, max_message_chars: int | None
) -> Message:
    """Handle AgentCondensationObservation with an explicit visibility banner."""
    if _is_working_set_observation(obs):
        text = truncate_content(obs.content or '', max_message_chars)
        return Message(role='system', content=[TextContent(text=text)])

    summary = obs.content or '(no summary provided)'
    restored_context = _load_restored_context_snapshot()
    working_memory = _load_working_memory_snapshot()

    banner = _CONDENSATION_BANNER if not getattr(obs, 'is_prewarmed', False) else ''

    text = truncate_content(
        banner
        + summary
        + restored_context
        + working_memory
        + _POST_CONDENSATION_RECOVERY,
        max_message_chars,
    )
    return Message(role='system', content=[TextContent(text=text)])


def _find_diff_hunk_boundaries(lines: list[str]) -> tuple[list[int], list[int]]:
    hunk_starts: list[int] = []
    hunk_ends: list[int] = []
    for i, line in enumerate(lines):
        if line.startswith('[begin of edit') or line.startswith('[begin of ATTEMPTED'):
            hunk_starts.append(i)
        elif line.startswith('[end of edit') or line.startswith('[end of ATTEMPTED'):
            hunk_ends.append(i)
    return hunk_starts, hunk_ends


def _truncate_hunk_section(section: list[str], half: int) -> list[str]:
    if len(section) <= half * 2:
        return section
    return section[:half] + ['  [... truncated ...]'] + section[-half:]


def _truncate_oversized_hunk(hunk_lines: list[str], lines_per_hunk: int) -> list[str]:
    header_lines = []
    body_lines = []
    for line in hunk_lines:
        if line.startswith('[begin of') or line.startswith('(content before'):
            header_lines.append(line)
        elif line.startswith('(content after') or line.startswith('[end of'):
            body_lines.append(line)
        else:
            body_lines.append(line)

    after_idx = None
    for i, line in enumerate(body_lines):
        if line.startswith('(content after'):
            after_idx = i
            break

    if after_idx is not None:
        before_section = body_lines[:after_idx]
        after_section = body_lines[after_idx:]
        half = lines_per_hunk // 4
        kept_before = _truncate_hunk_section(before_section, half)
        kept_after = _truncate_hunk_section(after_section, half)
        return header_lines + kept_before + kept_after
    else:
        half = lines_per_hunk // 2
        return _truncate_hunk_section(hunk_lines, half)


def _truncate_diff_smart(content: str, max_chars: int) -> str:
    """Truncate a file edit observation while preserving diff hunk structure.

    Unlike blind head/tail truncation, this function:
    1. Keeps the summary line and hash marker untruncated at the top
    2. Parses diff hunks and keeps all hunk headers intact
    3. Truncates only within oversized hunks (keeps first/last N lines)
    4. Always includes the truncation banner between preserved sections

    This prevents mid-hunk cuts that cause merged lines and indentation corruption.
    """
    if len(content) <= max_chars:
        return content

    lines = content.split('\n')
    result_lines: list[str] = []
    remaining = max_chars

    if lines:
        first_line = lines[0]
        result_lines.append(first_line)
        remaining -= len(first_line) + 1

    hunk_starts, hunk_ends = _find_diff_hunk_boundaries(lines)

    if not hunk_starts:
        return truncate_content(content, max_chars, strategy='head_heavy')

    budget_per_hunk = max(200, remaining // len(hunk_starts)) if hunk_starts else 200
    lines_per_hunk = max(10, budget_per_hunk // 80)

    for hunk_idx, (start, end) in enumerate(zip(hunk_starts, hunk_ends, strict=False)):
        hunk_lines = lines[start : end + 1]
        hunk_size = sum(len(line) + 1 for line in hunk_lines)

        if hunk_size <= budget_per_hunk:
            result_lines.extend(hunk_lines)
            remaining -= hunk_size
        else:
            truncated_hunk = _truncate_oversized_hunk(hunk_lines, lines_per_hunk)
            result_lines.extend(truncated_hunk)
            remaining -= budget_per_hunk

        if hunk_idx < len(hunk_starts) - 1:
            result_lines.append('-------------------------')
            remaining -= 26

    return '\n'.join(result_lines)


# Marker prefix emitted by the execution layer (file_operations.truncate_diff)
# when an edit diff is shortened at production time. Detected here so the agent
# is always told to re-read, even when the prompt layer itself does not truncate.
from backend.execution.aes.file_operations import DIFF_CODEC_MARKER_PREFIX as _DIFF_CODEC_MARKER_PREFIX


def _edit_observation_truncation_footer(path: str) -> str:
    """Agent-actionable footer telling it the edit result is incomplete."""
    return (
        f'[EDIT_OBSERVATION_TRUNCATED path={path}] The result above is incomplete. '
        'Re-read the file (or the edited range) to confirm the final on-disk '
        'contents before making further edits or reporting completion.'
    )


@_register_observation_handler(FileEditObservation)
def _handle_file_edit_observation(
    obs: FileEditObservation, max_message_chars: int | None
) -> Message:
    # Use content_with_hash() to include the SHA-256 verification token
    # so the LLM can self-correct if the observation looks truncated.
    content_str = obs.content_with_hash()
    path = getattr(obs, 'path', 'unknown')

    truncated = max_message_chars is not None and len(content_str) > max_message_chars
    if truncated and max_message_chars is not None:
        # Hunk-aware truncation that preserves diff structure (keeps hunk
        # headers, trims inside oversized hunks). Falls back to head-heavy
        # truncation internally when no diff hunks are present, so it is safe
        # for plain summaries, unified diffs, and multi-edit receipts alike.
        text = _truncate_diff_smart(content_str, max_message_chars)
    else:
        text = content_str

    # Warn the agent whenever the shown changes are incomplete — either because
    # we truncated here, or because the execution layer already shortened the
    # diff before it reached the prompt.
    if truncated or _DIFF_CODEC_MARKER_PREFIX in content_str:
        text = f'{text}\n{_edit_observation_truncation_footer(path)}'

    text = f'[FILE_EDIT path={path}]\n{text}'
    return Message(role='user', content=[TextContent(text=text)])


_ERROR_CLASSIFIERS: list[tuple[str, list[str]]] = [
    ('PYTHON_IMPORT_ERROR', ['ModuleNotFoundError', 'ImportError', 'No module named']),
    ('PYTHON_SYNTAX_ERROR', ['SyntaxError:', 'IndentationError:', 'TabError:']),
    ('PYTHON_TYPE_ERROR', ['TypeError:']),
    ('PYTHON_NAME_ERROR', ['NameError:', 'is not defined']),
    ('PYTHON_ATTRIBUTE_ERROR', ['AttributeError:', 'has no attribute']),
    ('PYTHON_VALUE_ERROR', ['ValueError:']),
    ('PYTHON_KEY_ERROR', ['KeyError:']),
    ('PYTHON_INDEX_ERROR', ['IndexError:']),
    ('FILE_NOT_FOUND', ['FileNotFoundError', 'No such file or directory', 'ENOENT']),
    ('PERMISSION_DENIED', ['PermissionError', 'Permission denied', 'EACCES']),
    ('TIMEOUT_ERROR', ['TimeoutError', 'timed out', 'ETIMEDOUT']),
    ('CONNECTION_ERROR', ['ConnectionError', 'ConnectionRefused', 'ECONNREFUSED']),
    ('RUNTIME_ERROR', ['RuntimeError:']),
    ('ASSERTION_ERROR', ['AssertionError:', 'assert ']),
    ('TEST_FAILURE', ['FAILED', 'failures=', 'tests failed', 'ERRORS']),
    ('COMMAND_NOT_FOUND', ['command not found', 'not recognized as']),
    ('NPM_ERROR', ['npm ERR!', 'npm error']),
    ('GIT_ERROR', ['fatal:', 'error: failed to']),
    ('MEMORY_ERROR', ['MemoryError', 'OutOfMemoryError', 'OOM']),
    ('DISK_ERROR', ['No space left on device', 'ENOSPC']),
]


@_register_observation_handler(BrowserScreenshotObservation)
def _handle_browser_screenshot_observation(
    obs: BrowserScreenshotObservation,
    max_message_chars: int | None,
    vision_is_active: bool,
) -> Message:
    """Attach JPEG as multimodal content when vision is enabled for the active LLM."""
    cap = obs.content
    if obs.inject_skipped_reason:
        cap = f'{cap}\n[{obs.inject_skipped_reason}]'
    cap = truncate_content(cap, max_message_chars, strategy='balanced')
    tag = '[BROWSER_SCREENSHOT]'
    if vision_is_active and getattr(obs, 'image_b64', ''):  # type: ignore[arg-type]
        data_url = f'data:{obs.image_mime};base64,{obs.image_b64}'
        return Message(
            role='user',
            vision_enabled=True,
            content=[
                TextContent(text=f'{tag}\n{cap}'),
                ImageContent(image_urls=[data_url]),
            ],
        )
    return Message(
        role='user',
        content=[TextContent(text=f'{tag}\n{cap}')],
    )


def _classify_cmd_error(content: str) -> str | None:
    """Classify a command output error by scanning content for known patterns.

    Returns the error type string (e.g. 'PYTHON_IMPORT_ERROR') or None.
    """
    for error_type, patterns in _ERROR_CLASSIFIERS:
        for pattern in patterns:
            if pattern in content:
                return error_type
    return None


@_register_observation_handler(CmdOutputObservation)
def _handle_cmd_output_observation(
    obs: CmdOutputObservation, max_message_chars: int | None
) -> Message:
    exit_code = getattr(obs, 'exit_code', None)
    exit_tag = f' exit={exit_code}' if exit_code is not None else ''

    error_type_tag = ''
    if exit_code is not None and exit_code != 0:
        classified = _classify_cmd_error(obs.content)
        if classified:
            error_type_tag = f' error_type={classified}'

    tag = f'[CMD_OUTPUT{exit_tag}{error_type_tag}]'
    # Use tail_heavy for errors (traceback at end), balanced otherwise
    cmd_strategy = getattr(obs, 'truncation_strategy', None)
    if not cmd_strategy:
        cmd_strategy = (
            'tail_heavy' if (exit_code is not None and exit_code != 0) else 'balanced'
        )
    if obs.tool_call_metadata is None:
        text = truncate_content(
            f'{tag}\nObserved result of command executed by user:\n{obs.to_agent_observation()}',
            max_message_chars,
            strategy=cmd_strategy,
        )
    else:
        text = truncate_content(
            f'{tag}\n{obs.to_agent_observation()}',
            max_message_chars,
            strategy=cmd_strategy,
        )
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(ErrorObservation)
def _handle_error_observation(
    obs: ErrorObservation, max_message_chars: int | None
) -> Message:
    """Format an error observation into a clean, structured message for the LLM.

    Uses structured fields (fallback_tool) instead of parsing mutated content.
    This ensures consistent formatting regardless of which middleware ran.
    """
    error_id = getattr(obs, 'error_id', 'UNKNOWN')
    content = _get_observation_content(obs)
    text = truncate_content(content, max_message_chars)

    parts: list[str] = [f'[ERROR type={error_id}]']
    parts.append(text)

    # Add fallback hint from structured field (set by CircuitBreakerMiddleware)
    fallback = getattr(obs, 'fallback_tool', None)
    if fallback:
        parts.append(f'\n[SUGGESTION] Consider using `{fallback}` instead.')

    parts.append('\n[Error occurred in processing last action]')

    return Message(role='user', content=[TextContent(text='\n'.join(parts))])


@_register_observation_handler(UserRejectObservation)
def _handle_user_reject_observation(
    obs: UserRejectObservation, max_message_chars: int | None
) -> Message:
    return _handle_simple_observation(
        obs,
        max_message_chars,
        prefix='OBSERVATION:\n',
        suffix='\n[Last action has been rejected by the user]',
    )


@_register_observation_handler(FileDownloadObservation)
def _handle_file_download_observation(
    obs: FileDownloadObservation, max_message_chars: int | None
) -> Message:
    return _handle_simple_observation(obs, max_message_chars)


@_register_observation_handler(TerminalObservation)
def _handle_terminal_observation(
    obs: TerminalObservation, max_message_chars: int | None
) -> Message:
    """Handle terminal session output, surfacing dropped chars from the PTY ring buffer."""
    content_str = _get_observation_content(obs)
    text = truncate_content(content_str, max_message_chars)

    dropped = getattr(obs, 'dropped_chars', None)
    if dropped and dropped > 0:
        text += (
            f'\n[WARNING: {dropped} chars were dropped from the terminal '
            'ring buffer (oldest output lost). Use terminal_read with a '
            'wider offset to capture earlier output if needed.]'
        )

    has_metadata = getattr(obs, 'tool_call_metadata', None) is not None
    if not has_metadata:
        text = f'[Observation: TerminalObservation]\n{text}'
    return Message(role='user', content=[TextContent(text=text)])


@_register_observation_handler(MCPObservation)
def _handle_mcp_observation(
    obs: MCPObservation, max_message_chars: int | None
) -> Message:
    tool_name = getattr(obs, 'name', 'unknown')
    text = truncate_content(
        f'[MCP_RESULT tool={tool_name}]\n{obs.content}',
        max_message_chars,
        strategy='balanced',
    )
    return Message(role='user', content=[TextContent(text=text)])
