"""Observation processors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.message import ImageContent, Message, TextContent
from backend.ledger.observation import (
    BrowserScreenshotObservation,
    CmdOutputObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    MCPObservation,
    Observation,
    UserRejectObservation,
)
from backend.ledger.observation.agent import AgentCondensationObservation
from backend.ledger.serialization.event import truncate_content

if TYPE_CHECKING:
    pass


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
    if isinstance(event, FileReadObservation):
        return _handle_file_read_observation(event, max_message_chars)
    if isinstance(event, FileEditObservation):
        return _handle_file_edit_observation(event, max_message_chars)
    if isinstance(event, BrowserScreenshotObservation):
        return _handle_browser_screenshot_observation(
            event, max_message_chars, vision_is_active
        )
    if isinstance(event, CmdOutputObservation):
        return _handle_cmd_output_observation(event, max_message_chars)
    if isinstance(event, ErrorObservation):
        return _handle_error_observation(event, max_message_chars)
    if isinstance(event, UserRejectObservation):
        return _handle_user_reject_observation(event, max_message_chars)
    if isinstance(event, FileDownloadObservation):
        return _handle_file_download_observation(event, max_message_chars)
    if isinstance(event, MCPObservation):
        return _handle_mcp_observation(event, max_message_chars)
    if isinstance(event, AgentCondensationObservation):
        return _handle_condensation_observation(event, max_message_chars)

    # Fallback for generic/simple observations
    return _handle_simple_observation(event, max_message_chars)


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
    """Handle simple/generic observations."""
    content_str = _get_observation_content(obs)
    text = truncate_content(content_str, max_message_chars)
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
    'Context was condensed. Continue working from where you left off.\n'
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
        from backend.engine.tools.note import _load_notes

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
    """Load and consume the pre-condensation snapshot for one-time recovery."""
    try:
        from backend.context.pre_condensation_snapshot import (
            delete_snapshot,
            format_snapshot_for_injection,
            load_snapshot,
        )

        snapshot = load_snapshot()
        if not snapshot:
            return ''

        block = format_snapshot_for_injection(snapshot)
        delete_snapshot()
        return '\n' + '─' * 60 + '\n' + f'{_sanitize_memory_content(block)}\n'
    except Exception:
        return ''


def _handle_condensation_observation(
    obs: AgentCondensationObservation, max_message_chars: int | None
) -> Message:
    """Handle AgentCondensationObservation with an explicit visibility banner."""
    summary = obs.content or '(no summary provided)'
    restored_context = _load_restored_context_snapshot()
    scratchpad = _load_scratchpad_snapshot()
    working_memory = _load_working_memory_snapshot()

    # Auto-sync scratchpad to working_memory after condensation
    try:
        from backend.engine.tools.note import _load_notes
        from backend.engine.tools.working_memory import (
            sync_scratchpad_to_working_memory,
        )

        notes = _load_notes()
        if notes:
            sync_scratchpad_to_working_memory(notes)
    except Exception:
        pass

    banner = _CONDENSATION_BANNER if not getattr(obs, 'is_prewarmed', False) else ''

    text = truncate_content(
        banner
        + summary
        + restored_context
        + scratchpad
        + working_memory
        + _POST_CONDENSATION_RECOVERY,
        max_message_chars,
    )
    return Message(role='user', content=[TextContent(text=text)])


def _handle_file_read_observation(
    obs: FileReadObservation, max_message_chars: int | None
) -> Message:
    path = getattr(obs, 'path', 'unknown')
    text = truncate_content(obs.content, max_message_chars, strategy='head_heavy')
    text = f'[FILE_READ path={path}]\n{text}'
    return Message(role='user', content=[TextContent(text=text)])


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

    # Always keep the first line (summary/hash) — it's critical
    if lines:
        first_line = lines[0]
        result_lines.append(first_line)
        remaining -= len(first_line) + 1  # +1 for newline

    # Find diff hunk boundaries
    hunk_starts: list[int] = []
    hunk_ends: list[int] = []
    for i, line in enumerate(lines):
        if line.startswith('[begin of edit') or line.startswith('[begin of ATTEMPTED'):
            hunk_starts.append(i)
        elif line.startswith('[end of edit') or line.startswith('[end of ATTEMPTED'):
            hunk_ends.append(i)

    if not hunk_starts:
        # No structured hunks found — fall back to head_heavy truncation
        return truncate_content(content, max_chars, strategy='head_heavy')

    # Budget per hunk: divide remaining budget across hunks
    budget_per_hunk = max(200, remaining // len(hunk_starts)) if hunk_starts else 200
    lines_per_hunk = max(10, budget_per_hunk // 80)  # ~80 chars per line avg

    for hunk_idx, (start, end) in enumerate(zip(hunk_starts, hunk_ends, strict=False)):
        hunk_lines = lines[start : end + 1]
        hunk_size = sum(len(line) + 1 for line in hunk_lines)

        if hunk_size <= budget_per_hunk:
            # Entire hunk fits — keep it all
            result_lines.extend(hunk_lines)
            remaining -= hunk_size
        else:
            # Hunk is too large — keep header, first N lines, last N lines
            header_lines = []
            body_lines = []
            for line in hunk_lines:
                if line.startswith('[begin of') or line.startswith('(content before'):
                    header_lines.append(line)
                elif line.startswith('(content after') or line.startswith('[end of'):
                    body_lines.append(line)
                else:
                    body_lines.append(line)

            # Split body into before/after sections around the "(content after" marker
            after_idx = None
            for i, line in enumerate(body_lines):
                if line.startswith('(content after'):
                    after_idx = i
                    break

            if after_idx is not None:
                before_section = body_lines[:after_idx]
                after_section = body_lines[after_idx:]

                # Keep first/last N lines of each section
                half = lines_per_hunk // 4
                kept_before = (
                    before_section[:half]
                    + (
                        ['  [... truncated ...]']
                        if len(before_section) > half * 2
                        else []
                    )
                    + before_section[-half:]
                    if len(before_section) > half * 2
                    else before_section
                )
                kept_after = (
                    after_section[:half]
                    + (
                        ['  [... truncated ...]']
                        if len(after_section) > half * 2
                        else []
                    )
                    + after_section[-half:]
                    if len(after_section) > half * 2
                    else after_section
                )

                result_lines.extend(header_lines)
                result_lines.extend(kept_before)
                result_lines.extend(kept_after)
            else:
                # No clear before/after split — keep first/last N lines
                half = lines_per_hunk // 2
                kept = (
                    hunk_lines[:half]
                    + (['  [... truncated ...]'] if len(hunk_lines) > half * 2 else [])
                    + hunk_lines[-half:]
                    if len(hunk_lines) > half * 2
                    else hunk_lines
                )
                result_lines.extend(kept)

            remaining -= budget_per_hunk

        # Add separator between hunks
        if hunk_idx < len(hunk_starts) - 1:
            result_lines.append('-------------------------')
            remaining -= 26

    return '\n'.join(result_lines)


def _handle_file_edit_observation(
    obs: FileEditObservation, max_message_chars: int | None
) -> Message:
    # Use content_with_hash() to include the SHA-256 verification token
    # so the LLM can self-correct if the observation looks truncated.
    content_str = obs.content_with_hash()
    path = getattr(obs, 'path', 'unknown')

    # For edit_mode=range edits (detected by hash presence), skip truncation.
    # Range edits produce diffs proportional to the change, not the file size.
    # Truncation here causes mid-hunk cuts, merged lines, and file corruption.
    if max_message_chars and len(content_str) > max_message_chars:
        if obs.new_content_hash:
            # Hash-verified range edit — use smart truncation that preserves
            # hunk structure, keeping all hunk headers and first/last lines.
            text = _truncate_diff_smart(content_str, max_message_chars)
        else:
            # For non-range edits, use head_heavy strategy (88% head / 12% tail)
            # to keep the beginning of edits intact where most changes occur.
            text = truncate_content(
                content_str, max_message_chars, strategy='head_heavy'
            )
    else:
        text = content_str

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


def _handle_user_reject_observation(
    obs: UserRejectObservation, max_message_chars: int | None
) -> Message:
    return _handle_simple_observation(
        obs,
        max_message_chars,
        prefix='OBSERVATION:\n',
        suffix='\n[Last action has been rejected by the user]',
    )


def _handle_file_download_observation(
    obs: FileDownloadObservation, max_message_chars: int | None
) -> Message:
    return _handle_simple_observation(obs, max_message_chars)


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
