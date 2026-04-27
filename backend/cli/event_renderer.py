"""Event stream → terminal renderer.

Subscribes to the backend EventStream and translates events into rich
terminal output.  Handles all three reasoning paths (LLM reasoning,
AgentThinkAction, tool __thought), command output, file edits, errors,
and confirmation flow.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import textwrap
import time
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from backend.cli.hud import HUDBar
from backend.cli.layout_tokens import (
    ACTIVITY_BLOCK_BOTTOM_PAD,
    ACTIVITY_CARD_TITLE_BROWSER,
    ACTIVITY_CARD_TITLE_CHECKPOINT,
    ACTIVITY_CARD_TITLE_CODE,
    ACTIVITY_CARD_TITLE_DELEGATION,
    ACTIVITY_CARD_TITLE_FILES,
    ACTIVITY_CARD_TITLE_MCP,
    ACTIVITY_CARD_TITLE_MEMORY,
    ACTIVITY_CARD_TITLE_SEARCH,
    ACTIVITY_CARD_TITLE_SHELL,
    ACTIVITY_CARD_TITLE_TERMINAL,
    ACTIVITY_CARD_TITLE_TOOL,
    ACTIVITY_PANEL_PADDING,
    CALLOUT_PANEL_PADDING,
    DECISION_PANEL_ACCENT_STYLE,
    DRAFT_PANEL_ACCENT_STYLE,
    LIVE_PANEL_ACCENT_STYLE,
    TRANSCRIPT_LEFT_INSET,
    TRANSCRIPT_RIGHT_INSET,
    frame_live_body,
    frame_transcript_body,
    gap_below_live_section,
    spacer_live_section,
)
from backend.cli.theme import (
    CLR_AUTONOMY_BALANCED,
    CLR_AUTONOMY_FULL,
    CLR_AUTONOMY_SUPERVISED,
    CLR_BRAND,
    CLR_HUD_DETAIL,
    CLR_HUD_MODEL,
    CLR_META,
    CLR_MUTED_TEXT,
    CLR_SEP,
    CLR_STATE_RUNNING,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
    CLR_USER_BORDER,
)
from backend.cli.tool_call_display import (
    format_tool_activity_rows,
    looks_like_streaming_tool_arguments,
    mcp_result_user_preview,
    redact_internal_result_markers,
    redact_streamed_tool_call_markers,
    redact_task_list_json_blobs,
    streaming_args_hint,
    tool_headline,
    try_format_message_as_tool_json,
)
from backend.cli.transcript import (
    format_activity_block,
    format_activity_delta_secondary,
    format_activity_result_secondary,
    format_activity_secondary,
    format_activity_shell_block,
    format_activity_turn_header,
    format_callout_panel,
    format_ground_truth_tool_line,
    format_reasoning_snapshot,
    strip_tool_result_validation_annotations,
)
from backend.core.enums import AgentState, EventSource
from backend.core.task_status import (
    TASK_STATUS_PANEL_STYLES,
    TASK_STATUS_TODO,
    normalize_task_status,
)
from backend.engine import prompt_role_debug as _prompt_role_debug
from backend.ledger import EventStreamSubscriber
from backend.ledger.action import (
    Action,
    AgentThinkAction,
    BrowseInteractiveAction,
    BrowserToolAction,
    ClarificationRequestAction,
    CmdRunAction,
    CondensationAction,
    DelegateTaskAction,
    EscalateToHumanAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    LspQueryAction,
    MCPAction,
    MessageAction,
    NullAction,
    PlaybookFinishAction,
    ProposalAction,
    RecallAction,
    SignalProgressAction,
    StreamingChunkAction,
    TaskTrackingAction,
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
    UncertaintyAction,
)
from backend.ledger.observation import (
    AgentCondensationObservation,
    AgentStateChangedObservation,
    AgentThinkObservation,
    CmdOutputObservation,
    DelegateTaskObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    LspQueryObservation,
    MCPObservation,
    NullObservation,
    Observation,
    RecallFailureObservation,
    RecallObservation,
    ServerReadyObservation,
    SignalProgressObservation,
    StatusObservation,
    SuccessObservation,
    TaskTrackingObservation,
    TerminalObservation,
    UserRejectObservation,
)

logger = logging.getLogger(__name__)


def _show_reasoning_text() -> bool:
    """Whether to render model reasoning text in CLI.

    Default is on for backward compatibility. Set APP_CLI_SHOW_REASONING_TEXT=0
    to disable user-visible reasoning text and prevent provider reasoning leakage.
    """
    raw = os.environ.get("APP_CLI_SHOW_REASONING_TEXT", "").strip().lower()
    return raw not in (
        "0",
        "false",
        "no",
        "off",
    )


# Patterns for extracting / stripping thinking blocks from reasoning models.
# Matches both <redacted_thinking> (Anthropic/MiniMax) and <think> (DeepSeek R1,
# QwQ, Ollama reasoning models, early OpenAI o-series) tags.
_THINK_EXTRACT_RE = re.compile(
    r"<(?:redacted_thinking|think)>(.*?)(?:</(?:redacted_thinking|think)>|$)",
    re.DOTALL | re.IGNORECASE,
)
_THINK_STRIP_RE = re.compile(
    r"<(?:redacted_thinking|think)>.*?(?:</(?:redacted_thinking|think)>|$)",
    re.DOTALL | re.IGNORECASE,
)
_INTERNAL_THINK_TAG_RE = re.compile(
    r"^\[(?P<tag>[A-Z0-9_]+)\](?:\s*(?P<payload>.*))?$",
    re.DOTALL,
)
_INTERNAL_THINK_LABELS = {
    "CHECKPOINT": "Saving checkpoint…",
    "CHECKPOINT_RESULT": "Checkpoint…",
    "EXPLORE_TREE_STRUCTURE": "Exploring code graph…",
    "PREVIEW": "Preparing preview…",
    "READ_SYMBOL_DEFINITION": "Reading symbol definitions…",
    "ROLLBACK": "Reverting…",
    "SCRATCHPAD": "Updating scratchpad…",
    "VERIFY_FILE_LINES": "Verifying file lines…",
    "VIEW_AND_REPLACE": "Preparing edit…",
    "WORKING_MEMORY": "Updating working memory…",
}
_VISIBLE_INTERNAL_BLOCK_TAG_RE = re.compile(
    r"</?(?:WORKING_MEMORY|TASK_TRACKING)>",
    re.IGNORECASE,
)
_VISIBLE_INTERNAL_SECTION_RE = re.compile(
    r"^\[(HYPOTHESIS|FINDINGS|DECISIONS|PLAN)\](?:\s*(.*))?$",
    re.IGNORECASE,
)
_VISIBLE_SUPPRESSED_LINE_RE = re.compile(
    r"^\[(?:ANALYZE_PROJECT_STRUCTURE|CHECKPOINT|CHECKPOINT_RESULT|"
    r"EXPLORE_TREE_STRUCTURE|PREVIEW|READ_SYMBOL_DEFINITION|"
    r"REVERT_RESULT|ROLLBACK|SCRATCHPAD|SEMANTIC_RECALL_RESULT|"
    r"TASK_TRACKER|VERIFY_FILE_LINES|WORKING_MEMORY)\]\b",
    re.IGNORECASE,
)
# Strip structured JSON payloads embedded in think-action thoughts.
_THINK_RESULT_JSON_RE = re.compile(
    r"\n?\[(?:CHECKPOINT_RESULT|REVERT_RESULT|ROLLBACK|TASK_TRACKER)\]\s*\{.*",
    re.DOTALL,
)
# Strip XML-like tags from tool outputs (e.g. <search_results>, <checkpoint>).
_TOOL_RESULT_TAG_RE = re.compile(r"</?[a-z_][a-z0-9_]*>", re.IGNORECASE)
_CMD_SUMMARY_NOISE_PATTERNS = (
    "a complete log of this run can be found in",
    "[below is the output of the previous command.]",
    "[the command completed with exit code",
    "[app: output truncated",
)
_CMD_SUMMARY_PRIORITY_PATTERNS = (
    re.compile(
        r"^\[(shell_mismatch|scaffold_setup_failed|missing_module|missing_tool|disk_full|permission_error|oom_killed|segfault|repeated_command_failure)\]",
        re.IGNORECASE,
    ),
    re.compile(r"could not read package\.json", re.IGNORECASE),
    re.compile(r"contains files that could conflict", re.IGNORECASE),
    re.compile(r"operation cancelled", re.IGNORECASE),
    re.compile(r"command not found|not recognized as", re.IGNORECASE),
    re.compile(r"module(?:notfounderror| not found)|importerror", re.IGNORECASE),
    re.compile(r"permission denied", re.IGNORECASE),
    re.compile(r"enoent|eacces|eperm|fatal:|exception|traceback|error", re.IGNORECASE),
)
_APPLY_PATCH_TITLE = "apply patch"
_APPLY_PATCH_STATS_RE = re.compile(r"\[APPLY_PATCH_STATS\]\s*\+(\d+)\s*-(\d+)")

# Exact command strings produced by `backend/execution/browser/grinta_browser.py`
# when it dispatches a `CmdOutputObservation` for a browser tool action.
# We use a whitelist (rather than `startswith('browser ')`) so that a user's
# shell command that happens to start with the word "browser" (e.g.
# ``browser-cli --help``) isn't silently dropped from the transcript.
_BROWSER_TOOL_COMMANDS = frozenset(
    {
        "browser start",
        "browser close",
        "browser navigate",
        "browser snapshot",
        "browser screenshot",
        "browser click",
        "browser type",
    }
)

# Prefix emitted by ``file_editor._view_directory`` when the editor is pointed
# at a directory rather than a regular file. Used by the File-read observation
# handler to switch the result label from "N lines" to "N entries".
_DIRECTORY_VIEW_PREFIX = "Directory contents of "


def _sync_reasoning_after_tool_line(
    reasoning: Any,
    tool_label: str,
    thought: str,
) -> None:
    """Live panel: spinner + optional dim thinking text (``action.thought`` is LLM tags only; often empty)."""
    label = (tool_label or "").strip()
    t = (thought or "").strip()
    # Always refresh the action line when we have a label.  Previously we no-op'd when
    # ``thought`` was empty, which left the streaming placeholder (e.g. ``Browser…``)
    # up even after the concrete tool action (with URL / path) was known.
    if not label and not t:
        return
    _prompt_role_debug.log_reasoning_transition("tool_line", label or t)
    reasoning.start()
    if label:
        _prompt_role_debug.log_reasoning_transition("update_action", label)
        reasoning.update_action(label)
    if t and _show_reasoning_text():
        _prompt_role_debug.log_reasoning_transition("update_thought", t)
        reasoning.update_thought(t)


def _normalize_reasoning_text(text: str) -> tuple[str | None, str | None]:
    """Split internal tagged thoughts into a user-facing action label and optional short text."""
    stripped = (text or "").strip()
    if not stripped or stripped == "Your thought has been logged.":
        return None, None

    # Strip structured JSON payloads from multi-line thoughts (e.g. checkpoint results).
    stripped = _THINK_RESULT_JSON_RE.sub("", stripped).strip()

    # Strip XML-like tags from tool outputs.
    stripped = _TOOL_RESULT_TAG_RE.sub("", stripped).strip()

    if not stripped:
        return None, None

    match = _INTERNAL_THINK_TAG_RE.match(stripped)
    if not match:
        return None, stripped

    tag = match.group("tag")
    payload = (match.group("payload") or "").strip()
    label = _INTERNAL_THINK_LABELS.get(
        tag,
        tag.replace("_", " ").capitalize() + "…",
    )
    del payload
    # Internal tagged thoughts are machine-state updates, not user-facing prose.
    # Keep the live action label but suppress the payload from transcript snapshots.
    return label, None


def _sanitize_visible_transcript_text(text: str) -> str:
    """Remove internal prompt scaffolding and protocol chatter from visible text."""
    stripped = redact_internal_result_markers(
        redact_task_list_json_blobs(
            redact_streamed_tool_call_markers((text or "").strip())
        )
    )
    if not stripped:
        return ""

    had_task_tracking_block = "<TASK_TRACKING>" in stripped.upper()
    stripped = _VISIBLE_INTERNAL_BLOCK_TAG_RE.sub("", stripped)
    lines_out: list[str] = []
    previous_blank = False
    for raw_line in stripped.splitlines():
        line = raw_line.rstrip()
        compact = line.strip()
        if not compact:
            if lines_out and not previous_blank:
                lines_out.append("")
            previous_blank = True
            continue

        if _VISIBLE_SUPPRESSED_LINE_RE.match(compact):
            continue

        lower_compact = compact.lower()
        if had_task_tracking_block and (
            lower_compact.startswith("task_tracker:")
            or lower_compact.startswith("**task_tracker**:")
            or lower_compact.startswith("allowed statuses:")
            or lower_compact.startswith("**syncing**:")
            or lower_compact.startswith("**completion (critical)**:")
        ):
            continue

        section_match = _VISIBLE_INTERNAL_SECTION_RE.match(compact)
        if section_match:
            section_name = section_match.group(1).strip().capitalize()
            remainder = (section_match.group(2) or "").strip()
            compact = (
                f"{section_name}: {remainder}" if remainder else f"{section_name}:"
            )

        lines_out.append(compact)
        previous_blank = False

    return "\n".join(lines_out).strip()


def _task_panel_signature(
    task_list: list[dict[str, Any]],
) -> tuple[tuple[str, str, str], ...]:
    """Build a stable signature for the visible task tracker state."""
    rows: list[tuple[str, str, str]] = []
    for item in task_list:
        try:
            status = normalize_task_status(item.get("status"), default=TASK_STATUS_TODO)
        except ValueError:
            status = TASK_STATUS_TODO
        desc = str(item.get("description") or "…")
        task_id = str(item.get("id") or "?")
        rows.append((task_id, status, desc))
    return tuple(rows)


_DELEGATE_WORKER_STATUS_STYLES = {
    "starting": "cyan",
    "running": "yellow",
    "done": "green",
    "failed": "red",
}


def _delegate_worker_panel_signature(
    workers: dict[str, dict[str, Any]],
) -> tuple[tuple[int, str, str, str, str], ...]:
    """Build a stable signature for the visible delegated-worker panel."""
    rows: list[tuple[int, str, str, str, str]] = []
    for worker_id, item in workers.items():
        order = item.get("order", 9999)
        if not isinstance(order, int):
            order = 9999
        rows.append(
            (
                order,
                str(item.get("label") or worker_id),
                str(item.get("status") or "running"),
                str(item.get("task") or "subtask"),
                str(item.get("detail") or ""),
            )
        )
    return tuple(sorted(rows, key=lambda row: (row[0], row[1], row[3], row[4])))


def _summarize_cmd_failure(content: str) -> str:
    """Pick the most actionable single-line failure summary for the CLI transcript."""
    lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
    if not lines:
        return ""

    filtered = [
        line
        for line in lines
        if not any(noise in line.lower() for noise in _CMD_SUMMARY_NOISE_PATTERNS)
    ]
    candidates = filtered or lines

    for pattern in _CMD_SUMMARY_PRIORITY_PATTERNS:
        for line in reversed(candidates):
            if pattern.search(line):
                return line[:160]

    return candidates[-1][:160]


def _is_apply_patch_activity(title: str | None, label: str | None) -> bool:
    """Return True when the internal shell card corresponds to apply_patch."""
    title_text = (title or "").strip().lower()
    label_text = (label or "").strip().lower()
    return (
        title_text == _APPLY_PATCH_TITLE
        or "applying patch" in label_text
        or "validating patch" in label_text
    )


def _extract_apply_patch_delta(content: str) -> tuple[int | None, int | None]:
    """Extract patch +/- line counts from stats marker or raw unified diff text."""
    match = _APPLY_PATCH_STATS_RE.search(content or "")
    if match:
        return int(match.group(1)), int(match.group(2))

    added = 0
    removed = 0
    saw_patch_lines = False
    for line in (content or "").splitlines():
        if line.startswith("diff --git "):
            continue
        if line.startswith("index "):
            continue
        if line.startswith("+++ "):
            continue
        if line.startswith("--- "):
            continue
        if line.startswith("@@ "):
            continue
        if line.startswith("Binary files "):
            continue
        if line.startswith("\\ No newline at end of file"):
            continue
        if line.startswith("+"):
            added += 1
            saw_patch_lines = True
        elif line.startswith("-"):
            removed += 1
            saw_patch_lines = True

    if not saw_patch_lines:
        return None, None
    return added, removed


def _compact_apply_patch_result(
    *,
    exit_code: int | None,
    label: str,
    content: str,
) -> tuple[str | None, str, list[Any] | None]:
    """Compact result text for apply_patch to reduce transcript clutter."""
    added, removed = _extract_apply_patch_delta(content)

    if exit_code == 0:
        line = format_activity_secondary("succeeded", kind="ok")
        if added is not None and removed is not None:
            line.append("  ", style="dim")
            line.append(f"+{added}", style="dim green")
            line.append("  ", style="dim")
            line.append(f"-{removed}", style="dim red")
        return None, "ok", [line]

    if exit_code is None:
        return "failed", "err", None

    marker = "[APPLY_PATCH_GUIDANCE]"
    if marker in content:
        detail = content.split(marker, 1)[1].strip().splitlines()[0]
        if detail:
            return f"failed · {_truncate_activity_detail(detail, 140)}", "err", None

    if summary := _summarize_cmd_failure(content):
        return f"failed · {summary}", "err", None

    return f"failed · exit {exit_code}", "err", None


def _truncate_activity_detail(text: str, limit: int) -> str:
    """Collapse whitespace and cap verbose tool details for compact activity cards."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 0)].rstrip() + "…"


def _summarize_delegate_action(action: DelegateTaskAction) -> tuple[str, str | None]:
    """Return a compact action label for single-worker and swarm delegations."""
    parallel_tasks = getattr(action, "parallel_tasks", []) or []
    run_in_background = bool(getattr(action, "run_in_background", False))

    if parallel_tasks:
        count = len(parallel_tasks)
        detail = f"{count} parallel task" + ("s" if count != 1 else "")
        previews = [
            _truncate_activity_detail(str(item.get("task_description") or ""), 36)
            for item in parallel_tasks
            if str(item.get("task_description") or "").strip()
        ]
        secondary_parts: list[str] = []
        if previews:
            preview = "; ".join(previews[:2])
            if len(previews) > 2:
                preview += f"; +{len(previews) - 2} more"
            secondary_parts.append(preview)
        if run_in_background:
            secondary_parts.append("background")
        return detail, " · ".join(secondary_parts) or None

    detail = (
        _truncate_activity_detail(getattr(action, "task_description", "") or "", 80)
        or "subtask"
    )

    secondary_parts = []
    files = getattr(action, "files", []) or []
    if files:
        secondary_parts.append(f"{len(files)} file" + ("s" if len(files) != 1 else ""))
    if run_in_background:
        secondary_parts.append("background")
    return detail, " · ".join(secondary_parts) or None


def _summarize_delegate_observation(
    obs: DelegateTaskObservation,
) -> tuple[str | None, str, list[Text]]:
    """Summarize delegated-worker results for compact in-card CLI rendering."""
    success = bool(getattr(obs, "success", True))
    error = str(getattr(obs, "error_message", "") or "").strip()
    raw_content = strip_tool_result_validation_annotations(
        str(getattr(obs, "content", "") or "").strip()
    )
    content = raw_content.split("[SHARED BLACKBOARD SNAPSHOT]", 1)[0].strip()
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    extra_lines: list[Text] = []

    worker_statuses: list[tuple[str, str]] = []
    for line in lines:
        match = re.match(r"^\[(OK|FAILED)\]\s*(.+)$", line)
        if match:
            worker_statuses.append((match.group(1), match.group(2)))

    if worker_statuses:
        total = len(worker_statuses)
        ok_count = sum(status == "OK" for status, _label in worker_statuses)
        failed_count = total - ok_count
        if failed_count == 0:
            result_message = f"all {total} workers completed"
            result_kind = "ok"
        else:
            result_message = f"{ok_count}/{total} workers completed"
            result_kind = "err"

        for status, label in worker_statuses[:3]:
            extra_lines.append(
                format_activity_result_secondary(
                    _truncate_activity_detail(label, 96),
                    kind="ok" if status == "OK" else "err",
                )
            )
        if total > 3:
            extra_lines.append(
                format_activity_result_secondary(
                    f"+{total - 3} more workers", kind="neutral"
                )
            )
        if failed_count and error:
            extra_lines.append(
                format_activity_result_secondary(
                    _truncate_activity_detail(error, 120),
                    kind="err",
                )
            )
        return result_message, result_kind, extra_lines

    if raw_content.startswith("Worker(s) started in background"):
        return _truncate_activity_detail(raw_content, 140), "neutral", extra_lines

    if not success:
        if error:
            return (
                f"delegation failed · {_truncate_activity_detail(error, 120)}",
                "err",
                extra_lines,
            )
        if lines:
            return (
                f"delegation failed · {_truncate_activity_detail(lines[0], 120)}",
                "err",
                extra_lines,
            )
        return "delegation failed", "err", extra_lines

    if not lines:
        if raw_content:
            return _truncate_activity_detail(raw_content, 140), "ok", extra_lines
        return "delegation completed", "ok", extra_lines

    return _truncate_activity_detail(lines[0], 140), "ok", extra_lines


def _build_task_panel(task_list: list[dict[str, Any]]) -> Any:
    """Render the current task list as a single reusable panel block."""
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column()
    table.add_column(ratio=1)

    for task_id, status, desc in _task_panel_signature(task_list):
        badge = Text()
        badge.append("[", style="dim")
        badge.append(
            status.upper(),
            style=f'bold {TASK_STATUS_PANEL_STYLES.get(status, "dim")}',
        )
        badge.append("]", style="dim")

        body = Text()
        if task_id and task_id != "?":
            body.append(f"{task_id}  ", style="dim")
        body.append(desc, style="default")
        table.add_row(badge, body)

    empty_state: Any = (
        table
        if task_list
        else Text(
            "No tasks in the tracker yet — the agent may add some as it works.",
            style="dim",
        )
    )
    return format_callout_panel(
        f"Tasks ({len(task_list)})",
        empty_state,
        accent_style=LIVE_PANEL_ACCENT_STYLE,
        padding=ACTIVITY_PANEL_PADDING,
    )


def _build_delegate_worker_panel(workers: dict[str, dict[str, Any]]) -> Any:
    """Render delegated worker progress as a compact reusable panel block."""
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column()
    table.add_column(ratio=1)

    for _order, label, status, task, detail in _delegate_worker_panel_signature(
        workers
    ):
        badge = Text()
        badge.append("[", style="dim")
        badge.append(
            status.upper(),
            style=f'bold {_DELEGATE_WORKER_STATUS_STYLES.get(status, "dim")}',
        )
        badge.append("]", style="dim")

        body = Text()
        if label:
            body.append(f"{label}  ", style="dim")
        body.append(task or "subtask", style="default")
        if detail and detail != task:
            body.append(f"\n{detail}", style="dim")
        table.add_row(badge, body)

    empty_state: Any = (
        table
        if workers
        else Text(
            "No parallel workers — subtasks appear here when the agent delegates.",
            style="dim",
        )
    )
    return format_callout_panel(
        f"Workers ({len(workers)})",
        empty_state,
        accent_style=LIVE_PANEL_ACCENT_STYLE,
        padding=ACTIVITY_PANEL_PADDING,
    )


if TYPE_CHECKING:
    from backend.cli.reasoning_display import ReasoningDisplay
    from backend.ledger.stream import EventStream

# Events to silently skip (mirrors gateway filtering).
_SKIP_ACTIONS = (NullAction,)
_SKIP_OBSERVATIONS = (NullObservation,)
_IDLE_STATES = {
    AgentState.AWAITING_USER_INPUT,
    AgentState.FINISHED,
    AgentState.ERROR,
    AgentState.STOPPED,
    AgentState.PAUSED,
    AgentState.REJECTED,
}

# Provider / network / quota issues: calm “notice” styling (cyan) instead of red.
_RECOVERABLE_NOTICE_FRAGMENTS = (
    "verification required",
    "blind retries are blocked",
    "fresh grounding action",
    "stuck loop detected",
    "no executable action",
    "no-progress loop",
    "intermediate control tool",
    "timeout",
    "timed out",
    "did not answer before",
    "automatic backoff and retry",
    "retrying without streaming",
    "stream timed out",
    "fallback completion timed out",
    "rate limit",
    "too many requests",
    "429",
    "quota",
    "billing",
    "insufficient_quota",
    "connection",
    "unreachable",
    "connect error",
    "dns",
    "ssl",
    "certificate",
    "econnrefused",
    "econnreset",
    "context length",
    "context window",
    "token limit",
    "max tokens",
    "too large to process",
)

# Auth, policy, and hard failures — keep scarlet “error” treatment.
_CRITICAL_ERROR_FRAGMENTS = (
    "syntax validation failed",
    "401",
    "unauthorized",
    "invalid api key",
    "authenticationerror",
    "api key rejected",
    "no api key or model configured",
    "permission denied",
    "access is denied",
    "403",
    "filenotfounderror",
)


def _use_recoverable_notice_style(error_text: str) -> bool:
    """True for timeouts and provider hiccups; False for auth/syntax/crash-like errors."""
    lower = error_text.lower()
    if _contains_any(lower, _CRITICAL_ERROR_FRAGMENTS):
        return False
    if _contains_any(lower, _RECOVERABLE_NOTICE_FRAGMENTS):
        return True
    return False


# Subscriber ID for the CLI renderer.
_SUBSCRIBER = EventStreamSubscriber.CLI


@dataclass(frozen=True)
class ErrorGuidance:
    """Actionable recovery copy for a rendered error."""

    summary: str
    steps: tuple[str, ...]
    # When True, "What you can try" lists only steps (summary is shown as the panel headline).
    omit_summary_in_recovery: bool = False


@dataclass
class PendingActivityCard:
    """Buffered non-shell activity card, paired with a later observation."""

    title: str
    verb: str
    detail: str
    secondary: str | None = None
    kind: str = "generic"
    payload: dict[str, Any] | None = None


def _reasoning_lines_skip_already_committed(
    prev: list[str] | None, new: list[str]
) -> list[str]:
    """Drop leading lines already printed in the previous reasoning snapshot.

    Models (especially Gemini with long CoT) often restate the same preamble on
    every segment; Grinta flushes thoughts at tool boundaries, so without this
    the transcript repeats goals and plan bullets while work is advancing.
    """
    if not new:
        return []
    if not prev:
        return new
    n = min(len(prev), len(new))
    i = 0
    while i < n and prev[i] == new[i]:
        i += 1
    return new[i:]


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    """Return True when any pattern appears in the target text."""
    return any(pattern in text for pattern in patterns)


def _split_error_text(error_text: str) -> tuple[str, str]:
    """Split error text into a short summary line and optional detail block."""
    # Clean up redundant internal engine scaffolding to prevent visual clutter for users
    cleaned = re.sub(
        r"<APP_RESULT_VALIDATION>.*?(?:</APP_RESULT_VALIDATION>|$)",
        "",
        error_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(r"\[TOOL_FALLBACK\].*?(?:\n|$)", "", cleaned)
    stripped = cleaned.strip()

    if not stripped:
        return "Unknown error", ""
    lines = stripped.splitlines()
    # Drop leading "ERROR:" scaffolding so the summary is a real message, not a banner line.
    idx = 0
    while idx < len(lines):
        head = lines[idx].strip()
        if head and head.upper() not in ("ERROR:", "ERROR"):
            break
        idx += 1
    if idx >= len(lines):
        return "Unknown error", ""
    summary = lines[idx].strip() or "Unknown error"
    detail = "\n".join(line.rstrip() for line in lines[idx + 1 :]).strip()
    if len(detail) > 2000:
        detail = detail[:2000] + "\n... (truncated)"
    return summary, detail


def _error_panel_text_wrap_width(console_width: int | None) -> int | None:
    """Character width for wrapped body lines inside a transcript error/notice panel."""
    if console_width is None:
        return None
    # Transcript inset + rounded border + CALLOUT_PANEL_PADDING (1, 2) horizontal.
    area = max(20, console_width - TRANSCRIPT_LEFT_INSET - TRANSCRIPT_RIGHT_INSET)
    inner = area - 2 - 4
    return max(16, inner)


def _pty_output_transcript_caption(
    *,
    session_id: str,
    n_lines: int,
    truncated: bool,
    has_output: bool,
    has_new_output: bool | None = None,
) -> str:
    """One line for the transcript: session and line count."""
    parts: list[str] = [f"{ACTIVITY_CARD_TITLE_TERMINAL.lower()} output"]
    if session_id:
        parts.append(session_id)
    if has_output and n_lines:
        parts.append(f'{n_lines} line{"s" if n_lines != 1 else ""}')
    if truncated:
        parts.append("truncated")
    if has_new_output is False:
        parts.append("no new bytes since last read")
    return " · ".join(parts)


def _strip_pty_echo(text: str, sent_cmd: str) -> str:
    """Remove PTY character-echo lines from a terminal delta.

    When text is injected into a PTY the shell echoes each keystroke at the
    current cursor position.  The resulting line in the buffer looks like
    ``[cursor-noise]<sent_cmd>`` — e.g. ``Get-ChildItem old.txtGet-ChildItem -Name``.
    Stripping it keeps the displayed output clean.
    """
    cmd = sent_cmd.strip().rstrip("\r\n")
    if not cmd or not text:
        return text
    lines = text.split("\n")
    filtered = [ln for ln in lines if not ln.rstrip().endswith(cmd)]
    # Only apply if at least one line was removed to avoid silently blanking output.
    if len(filtered) < len(lines):
        result = "\n".join(filtered).strip()
        return result if result else text
    return text


def _wrap_panel_text_block(text: str, *, wrap_width: int | None) -> str:
    """Hard-wrap lines so long API / exception strings stay inside the panel."""
    if wrap_width is None or not text:
        return text
    lines_out: list[str] = []
    for raw in text.splitlines():
        if not raw:
            lines_out.append("")
            continue
        chunk = textwrap.wrap(
            raw,
            width=wrap_width,
            replace_whitespace=False,
            drop_whitespace=False,
        )
        lines_out.extend(chunk or [""])
    return "\n".join(lines_out)


def _error_panel_outer_width(console_width: int | None) -> int | None:
    """Width of the Panel box aligned with the framed transcript column."""
    if console_width is None:
        return None
    return max(20, console_width - TRANSCRIPT_LEFT_INSET - TRANSCRIPT_RIGHT_INSET)


def _error_guidance(error_text: str) -> ErrorGuidance | None:
    """Return actionable recovery steps for common CLI error patterns."""
    lower = error_text.lower()
    if "syntax validation failed" in lower:
        return ErrorGuidance(
            summary="Edit was not saved: the file fails a syntax check (invalid structure).",
            steps=(
                "Fix the broken brackets, quotes, or keywords in that file (the agent still sees the full tool error in context).",
                "Prefer small patches or a minimal valid stub, then iterate.",
                "Re-read the file before applying the next edit.",
            ),
            omit_summary_in_recovery=True,
        )
    if "no api key or model configured" in lower or (
        "initialization failed" in lower
        and _contains_any(
            lower,
            (
                "authenticationerror",
                "invalid api key",
                "api_key",
                "unauthorized",
                "401",
            ),
        )
    ):
        return ErrorGuidance(
            summary="The engine could not finish startup with the current credentials.",
            steps=(
                "Restart grinta and complete onboarding so it can prompt for a model and API key.",
                "Or update settings.json with a valid provider, model, and API key before retrying.",
                "Rerun the same task after saving the new settings.",
            ),
        )
    if _contains_any(
        lower,
        (
            "resume failed",
            "no event stream",
            "session bootstrap state is incomplete",
        ),
    ):
        return ErrorGuidance(
            summary="This saved session could not be reopened cleanly.",
            steps=(
                "Run /sessions and try a different session if the current one is stale or incomplete.",
                "If the session files were removed, start a new task in the current project.",
            ),
        )
    if "pending action timed out" in lower:
        return ErrorGuidance(
            summary="A tool action ran longer than the pending-action guard window.",
            steps=(
                "The command may still be running. Verify current process/output state before retrying.",
                "For setup/install tasks, run shorter sequential commands instead of one long chained command.",
                "Increase pending_action_timeout in settings.json if your environment is consistently slow.",
            ),
        )
    if _contains_any(
        lower,
        (
            "call_async_from_sync",
            "browser_tool",
        ),
    ) and _contains_any(lower, ("timeout", "timed out")):
        return ErrorGuidance(
            summary="The local runtime sync bridge timed out waiting for an async tool to finish.",
            steps=(
                "This is usually the in-process executor thread (e.g. native browser / browser-use), not the LLM provider.",
                "Close stray Chromium or Chrome processes, restart the CLI, and retry.",
                "Set GRINTA_BROWSER_TRACE=1 to print browser stage lines to stderr; optional env vars: CALL_ASYNC_LOOP_SHUTDOWN_WAIT_SEC (task cancel wait, default 2s), CALL_ASYNC_LOOP_FINALIZE_WAIT_SEC (asyncgen/executor shutdown cap, default 3s).",
                "If the action may still be running in the background, check processes before retrying.",
            ),
        )
    if _contains_any(
        lower,
        (
            "browser screenshot timed out",
            "browser screenshot failed",
            "browser snapshot timed out",
            "snapshot timed out",
            "screenshot timed out",
            "tried compositor and window capture",
            "navigation to ",
        ),
    ) and _contains_any(
        lower,
        ("timed out", "timeout", "compositor", "window capture"),
    ):
        return ErrorGuidance(
            summary="The browser tool did not finish in time.",
            steps=(
                "A JavaScript alert/confirm/prompt dialog on the page may be "
                "blocking rendering; we now auto-dismiss these before "
                "screenshots, but it can still happen on other commands. "
                "Try ``browser snapshot`` to probe DOM state without rendering.",
                "Re-run ``browser navigate`` to the same URL to reset the tab, "
                "or close stray Chrome/Chromium windows and retry.",
                "Set GRINTA_BROWSER_TRACE=1 before launching to see stage "
                "timings on stderr.",
            ),
        )
    if "fallback completion timed out" in lower:
        return ErrorGuidance(
            summary="The non-streaming retry also hit the wait limit.",
            steps=(
                "Check your network and the provider status page, then try again.",
                "Pick another model in /settings if this endpoint is often slow.",
                "Optional: raise APP_LLM_FALLBACK_TIMEOUT_SECONDS for a longer "
                "non-streaming cap (many setups use 60s by default).",
            ),
        )
    if _contains_any(
        lower,
        (
            "automatic backoff and retry will run",
            "waiting before retrying — no action needed",
            "waiting before retrying - no action needed",
        ),
    ):
        return ErrorGuidance(
            summary="Autonomous recovery is in progress.",
            steps=(
                "No action needed. Grinta already scheduled a retry.",
                "Watch the Backoff / Auto Retry status in the footer for attempt progress.",
                "If automatic retries exhaust, the prompt will return automatically.",
            ),
        )
    if "intermediate control tool" in lower:
        return ErrorGuidance(
            summary="This was an internal control step, not a user-facing reply.",
            steps=(
                "No action is required from you.",
                "Grinta should continue the same turn and either execute the next step or finish normally.",
            ),
        )
    if _contains_any(lower, ("no executable action", "no-progress loop")):
        return ErrorGuidance(
            summary="Grinta paused to avoid a no-progress loop.",
            steps=(
                "No action is required unless you want the task to continue immediately.",
                "Reply with a clearer next step or ask the agent to retry if you want it to resume.",
            ),
        )
    if _contains_any(lower, ("timeout", "timed out")):
        return ErrorGuidance(
            summary="The model didn't finish within Grinta's wait window.",
            steps=(
                "Confirm your network and the provider status page, then retry.",
                "Shorter prompts or a faster model in /settings usually help.",
                "If chunks pause too long mid-stream, raise APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS "
                "(default 90s) or APP_LLM_FIRST_CHUNK_TIMEOUT_SECONDS.",
                "If streaming often stalls, Grinta may retry non-streaming automatically—"
                "watch for the cyan “Still working” note in the transcript.",
            ),
        )
    if _contains_any(
        lower,
        (
            "401",
            "unauthorized",
            "invalid api key",
            "authenticationerror",
            "api key rejected",
        ),
    ):
        return ErrorGuidance(
            summary="The provider rejected the configured credentials.",
            steps=(
                "Open /settings, press k, and update the API key.",
                "Press m in /settings to confirm the selected model belongs to that provider.",
                "Send the request again after saving the updated settings.",
            ),
        )
    if _contains_any(
        lower,
        (
            "429",
            "rate limit",
            "too many requests",
            "insufficient_quota",
            "quota",
            "billing",
        ),
    ):
        return ErrorGuidance(
            summary="The provider is rejecting more requests because of rate or billing limits.",
            steps=(
                "Wait a moment and retry.",
                "Switch to another model in /settings if you need to keep working right now.",
                "Check the provider dashboard for quota, spend, or billing problems.",
            ),
        )
    if _contains_any(
        lower,
        (
            "404",
            "model not found",
            "does not exist",
            "unknown model",
        ),
    ):
        return ErrorGuidance(
            summary="The configured model name is not available from the selected provider.",
            steps=(
                "Open /settings, press m, and pick a supported model.",
                "If you entered the model manually, include the correct provider prefix.",
            ),
        )
    if _contains_any(
        lower,
        (
            "connection",
            "connect error",
            "unreachable",
            "dns",
            "ssl",
            "certificate",
        ),
    ):
        return ErrorGuidance(
            summary="Grinta could not reach the model provider.",
            steps=(
                "Check your internet connection, VPN, proxy, or firewall rules.",
                "Retry after the connection is stable.",
            ),
        )
    if "context" in lower and _contains_any(
        lower,
        ("length", "window", "limit", "too many tokens"),
    ):
        return ErrorGuidance(
            summary="The request is larger than the model can accept.",
            steps=(
                "Retry with a shorter prompt or less pasted context.",
                "If you need the larger context, switch models in /settings.",
            ),
        )
    if "budget" in lower:
        return ErrorGuidance(
            summary="The task budget blocked another model call.",
            steps=(
                "Open /settings, press b, and raise the budget.",
                "Use 0 if you want to remove the per-task budget limit.",
                "Retry the request after saving the new budget.",
            ),
        )
    if _contains_any(lower, ("file not found", "no such file", "path does not exist")):
        return ErrorGuidance(
            summary="The requested file or path was not available in the current project.",
            steps=(
                "Double-check the path and make sure the file still exists.",
                "If you moved the project, reopen grinta from the correct directory and retry.",
            ),
        )
    if _contains_any(
        lower, ("permission denied", "access is denied", "forbidden", "403")
    ):
        return ErrorGuidance(
            summary="The current account or filesystem permissions are blocking the action.",
            steps=(
                "Verify the API key has access to the selected model or endpoint.",
                "If this is a local file action, reopen grinta from a writable directory and retry.",
            ),
        )
    if "initialization failed" in lower:
        return ErrorGuidance(
            summary="Startup did not complete successfully.",
            steps=(
                "Restart grinta to try the bootstrap flow again.",
                "If it fails again, use the detail above to inspect the specific exception.",
            ),
        )
    if _contains_any(
        lower,
        (
            "verification required",
            "blind retries are blocked",
            "fresh grounding action",
        ),
    ):
        return ErrorGuidance(
            summary="Grinta blocked another blind write because recent edits were followed by failing feedback.",
            steps=(
                "Read the affected file or rerun the focused failing check to get fresh evidence.",
                "After one grounding step, the agent can edit or finish again.",
            ),
        )
    if _contains_any(
        lower,
        (
            "stuck loop detected",
            "stuck recovery:",
            "mandatory recovery:",
        ),
    ):
        return ErrorGuidance(
            summary="The model repeated the same action without new output.",
            steps=(
                "It is being nudged to read fresh state or run a different step.",
                "You can wait, or add a short message to redirect it.",
            ),
        )
    return None


def _build_recovery_text(
    guidance: ErrorGuidance,
    *,
    for_notice: bool = False,
    wrap_width: int | None = None,
) -> Text:
    """Render a guidance block for the error / notice panel."""
    recovery = Text()
    if for_notice:
        recovery.append("Next steps\n", style="bold dim cyan")
        sum_style = "cyan"
        step_style = "dim cyan"
    else:
        recovery.append("What you can try\n", style="yellow bold")
        sum_style = "yellow"
        step_style = "yellow"
    # Cyan notice panels already use ``guidance.summary`` as the headline body.
    if guidance.summary and not guidance.omit_summary_in_recovery and not for_notice:
        sum_block = _wrap_panel_text_block(
            guidance.summary,
            wrap_width=wrap_width,
        )
        recovery.append(sum_block, style=sum_style)
        if guidance.steps:
            recovery.append("\n", style=sum_style)
    for index, step in enumerate(guidance.steps, start=1):
        line = f"{index}. {step}"
        line = _wrap_panel_text_block(line, wrap_width=wrap_width)
        recovery.append(line, style=step_style)
        if index < len(guidance.steps):
            recovery.append("\n", style=step_style)
    return recovery


def _notice_panel_title(error_text: str) -> str:
    """Short cyan banner title for recoverable (notice-style) issues."""
    lower = error_text.lower()
    if "verification required" in lower:
        return "Need fresh evidence"
    if _contains_any(
        lower,
        (
            "automatic backoff and retry",
            "waiting before retrying — no action needed",
            "waiting before retrying - no action needed",
            "autonomous recovery",
        ),
    ):
        return "Autonomous recovery"
    if _contains_any(lower, ("no executable action", "no-progress loop")):
        return "Paused safely"
    if "intermediate control tool" in lower:
        return "Continuing work"
    if "fallback completion timed out" in lower:
        return "Still no reply"
    if _contains_any(
        lower,
        ("rate limit", "too many requests", "429", "quota", "billing"),
    ):
        return "Rate or quota limit"
    if _contains_any(
        lower,
        ("connection", "unreachable", "connect error", "dns", "ssl", "certificate"),
    ):
        return "Connection issue"
    if "stuck loop" in lower:
        return "Stuck pattern"
    if _contains_any(lower, ("timeout", "timed out", "did not answer")):
        return "Request timed out"
    return "Heads-up"


def _build_llm_stream_fallback_panel() -> Panel:
    """Compact callout when streaming stalls and the engine retries without streaming."""
    body = Group(
        Text(
            "The first streamed tokens took longer than expected, so Grinta is "
            "retrying the same completion in one shot (non-streaming).",
            style=LIVE_PANEL_ACCENT_STYLE,
        ),
        Text(
            "You do not need to do anything—this is common on busy endpoints.",
            style=f"dim {CLR_META}",
        ),
    )
    return Panel(
        body,
        title=Text("ℹ  Still Working", style=f"bold {LIVE_PANEL_ACCENT_STYLE}"),
        title_align="left",
        border_style=LIVE_PANEL_ACCENT_STYLE,
        box=box.ROUNDED,
        padding=(0, 1),
    )


def _build_error_panel(
    error_text: str,
    *,
    title: str = "Error",
    accent_style: str = "red",
    force_notice: bool | None = None,
    content_width: int | None = None,
) -> Panel:
    """Render a structured panel with recovery guidance when available.

    Recoverable provider/network issues use a compact cyan “notice” treatment;
    auth, validation, and similar failures keep the red error styling.
    """
    wrap_w = _error_panel_text_wrap_width(content_width)
    summary, detail = _split_error_text(error_text)
    guidance = _error_guidance(error_text)
    use_notice = (
        force_notice
        if force_notice is not None
        else _use_recoverable_notice_style(error_text)
    )
    accent = LIVE_PANEL_ACCENT_STYLE if use_notice else accent_style
    border = LIVE_PANEL_ACCENT_STYLE if use_notice else accent_style
    headline_style = (
        f"bold {LIVE_PANEL_ACCENT_STYLE}" if use_notice else f"{accent_style} bold"
    )
    detail_style = f"dim {CLR_META}" if use_notice else f"{accent_style} dim"

    if guidance is not None and "syntax validation failed" in error_text.lower():
        headline = guidance.summary
    elif use_notice and guidance is not None:
        # Friendlier line than raw provider exception scaffolding.
        headline = guidance.summary
    else:
        headline = summary
    headline = _wrap_panel_text_block(headline, wrap_width=wrap_w)
    body_parts: list[Any] = [Text(headline, style=headline_style)]
    if guidance is None and detail:
        body_parts.append(
            Text(_wrap_panel_text_block(detail, wrap_width=wrap_w), style=detail_style)
        )

    if guidance is not None:
        body_parts.append(Text(""))  # air gap before steps
        body_parts.append(
            _build_recovery_text(guidance, for_notice=use_notice, wrap_width=wrap_w)
        )

    if use_notice:
        panel_label = _notice_panel_title(error_text)
        panel_title = Text(f"ℹ  {panel_label}", style=f"bold {accent}")
    else:
        panel_title = Text(title.strip() or "Error", style=f"{accent_style} bold")
    notice_pad = (0, 1) if use_notice else CALLOUT_PANEL_PADDING
    panel_kw: dict[str, Any] = {
        "title": panel_title,
        "title_align": "left",
        "border_style": border,
        "box": box.ROUNDED,
        "padding": notice_pad,
    }
    outer = _error_panel_outer_width(content_width)
    if outer is not None:
        panel_kw["width"] = outer
    return Panel(Group(*body_parts), **panel_kw)


def _system_message_tag(title: str) -> tuple[str, str]:
    """ASCII bracket tag + color (no Unicode icons)."""
    normalized = title.strip().lower()
    if normalized == "warning":
        return "[!]", "yellow"
    if normalized == "autonomy":
        return "[auto]", "magenta"
    if normalized == "status":
        return "[*]", "blue"
    if normalized == "settings":
        return "[cfg]", "cyan"
    if "timeout" in normalized:
        return "[time]", "yellow"
    if normalized in ("system", "grinta"):
        return "[grinta]", "cyan"
    label = (title.strip() or "note").replace("\n", " ")
    if len(label) > 24:
        label = label[:21] + "..."
    return f"[{label}]", "cyan"


def _normalize_system_title(title: str) -> str:
    """Normalize arbitrary titles to stable, user-facing label casing."""
    raw = (title or "").strip()
    if not raw:
        return "Info"
    lowered = raw.lower()
    canonical = {
        "grinta": "System",
        "system": "System",
        "warning": "Warning",
        "status": "Status",
        "error": "Error",
        "autonomy": "Autonomy",
        "model": "Model",
        "clipboard": "Clipboard",
    }
    if lowered in canonical:
        return canonical[lowered]
    if "timeout" in lowered:
        return "Timeout"
    return raw[:1].upper() + raw[1:]


def _build_system_notice_panel(
    text: str,
    *,
    title: str,
    tone: str = "info",
) -> Panel:
    """Unified panel chrome for non-error system messages."""
    normalized_title = _normalize_system_title(title)
    tones: dict[str, tuple[str, str]] = {
        "warning": ("#f59e0b", "yellow"),
        "success": ("#10b981", "#86efac"),
        "info": ("#38bdf8", "#93c5fd"),
    }
    border_style, body_style = tones.get(tone, tones["info"])
    panel_title = Text(normalized_title, style=f"bold {border_style}")
    body = Text((text or "").strip(), style=body_style)
    return Panel(
        body,
        title=panel_title,
        title_align="left",
        border_style=border_style,
        box=box.ROUNDED,
        padding=(0, 1),
    )


class CLIEventRenderer:
    """Bridges EventStream → live rich layout.

    Activity rows (verb + detail, optional dim stats) are built by
    :func:`backend.cli.transcript.format_activity_block` and related helpers.
    — one line per tool event, no deduplication. Model thoughts use :class:`~backend.cli.reasoning_display.ReasoningDisplay`
    (plain dim text), separate from ground truth.

    Operates in two modes:

    * **Live mode** (during an agent turn): a Rich ``Live`` display shows the
      task strip, streaming preview, reasoning line, and HUD.  Finalized
      transcript lines are ``console.print``ed immediately so they stay in
      scrollback and are not clipped to the terminal height.
    * **Static mode** (idle / prompt): no ``Live`` display.  Output is printed
      once via ``console.print()`` so prompt_toolkit can own the terminal for
      user input without any contention.
    """

    def __init__(
        self,
        console: Console,
        hud: HUDBar,
        reasoning: ReasoningDisplay,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        max_budget: float | None = None,
        get_prompt_session: Callable[[], Any | None] | None = None,
        cli_tool_icons: bool = True,
    ) -> None:
        self._console = console
        self._hud = hud
        self._reasoning = reasoning
        self._cli_tool_icons = bool(cli_tool_icons)
        self._loop = loop or asyncio.get_event_loop()
        self._get_prompt_session = get_prompt_session
        self._live: Live | None = None
        self._streaming_accumulated = ""
        self._streaming_final = False
        self._current_state: AgentState | None = None
        self._state_event = asyncio.Event()
        self._subscribed = False
        self._max_budget = max_budget
        self._pending_events: deque[Any] = deque()
        self._last_assistant_message_text: str = ""
        self._budget_warned_80 = False
        self._budget_warned_100 = False
        #: Running count of stream-fallback retries this session ("Still Working" panels).
        self._stream_fallback_count: int = 0
        # Per-turn metric snapshots (used to compute deltas at turn completion)
        self._turn_start_cost: float = 0.0
        self._turn_start_tokens: int = 0
        self._turn_start_calls: int = 0
        self._task_panel: Any | None = None
        self._task_panel_signature: tuple[tuple[str, str, str], ...] | None = None
        self._last_printed_task_panel_signature: (
            tuple[tuple[str, str, str], ...] | None
        ) = None
        self._delegate_workers: dict[str, dict[str, Any]] = {}
        self._delegate_batch_id: int | None = None
        self._delegate_panel: Any | None = None
        self._delegate_panel_signature: (
            tuple[tuple[int, str, str, str, str], ...] | None
        ) = None
        self._last_printed_delegate_panel_signature: (
            tuple[tuple[int, str, str, str, str], ...] | None
        ) = None
        #: Last shell command label; paired with :class:`CmdOutputObservation` for one dim result row.
        self._pending_shell_command: str | None = None
        #: Raw input most recently sent via TerminalInputAction (used to strip PTY echo).
        self._last_terminal_input_sent: str = ""
        #: Buffered (verb, label) from CmdRunAction — printed as a combined card on CmdOutputObservation.
        self._pending_shell_action: tuple[str, str] | None = None
        #: Headline for internal shell-backed tool actions (e.g. Analyze project, Search code).
        self._pending_shell_title: str | None = None
        #: True when the buffered shell action is from an internal tool (display_label set).
        #: CmdOutputObservation renders only a brief result line instead of a terminal block.
        self._pending_shell_is_internal: bool = False
        #: Buffered non-shell tool card — printed as a combined card on the matching observation.
        self._pending_activity_card: PendingActivityCard | None = None
        #: First tool/shell row each turn prints a small section marker for scanability.
        self._activity_turn_header_emitted: bool = False
        #: Monotonic timestamp of the last Live refresh (for throttling).
        self._last_refresh_time: float = 0.0
        #: Last reasoning lines committed to transcript (for prefix de-dup per turn).
        self._last_committed_reasoning_lines: list[str] | None = None

    @property
    def current_state(self) -> AgentState | None:
        return self._current_state

    @property
    def streaming_preview(self) -> str:
        return self._streaming_accumulated

    @property
    def budget_warned_80(self) -> bool:
        return self._budget_warned_80

    @property
    def budget_warned_100(self) -> bool:
        return self._budget_warned_100

    @property
    def pending_event_count(self) -> int:
        return len(self._pending_events)

    @property
    def last_assistant_message_text(self) -> str:
        """Most recent committed assistant message rendered in transcript."""
        return self._last_assistant_message_text

    def set_cli_tool_icons(self, enabled: bool) -> None:
        """Toggle emoji tool headlines (e.g. after /settings)."""
        self._cli_tool_icons = bool(enabled)

    # -- Live lifecycle (per agent turn) -----------------------------------

    def start_live(self) -> None:
        """Create and start a Rich Live display for the current agent turn."""
        if self._live is not None:
            return
        live = Live(
            self,
            console=self._console,
            auto_refresh=False,
            transient=True,  # erases on stop — we print final output ourselves
            # ``visible`` causes Rich to re-print overflow content on every
            # refresh when the Live body is taller than the terminal, which
            # makes streaming panels (Draft reply, Thinking) render dozens of
            # duplicate copies per turn. ``crop`` redraws in place; panels
            # that could exceed height (streaming preview, reasoning thoughts)
            # are responsible for clamping themselves to ``options.max_height``.
            vertical_overflow="crop",
        )
        live.start()
        self._live = live
        self.refresh(force=True)

    def stop_live(self) -> None:
        """Stop the Rich Live display."""
        # Flush any remaining thinking before the Live panel disappears.
        self._flush_thinking_block()
        live = self._live
        if live is None:
            try:
                self._console.show_cursor(True)
            except Exception:
                pass
            return
        self._live = None
        if (
            self._task_panel is not None
            and self._task_panel_signature != self._last_printed_task_panel_signature
        ):
            self._console.print(self._task_panel)
            self._last_printed_task_panel_signature = self._task_panel_signature
        if (
            self._delegate_panel is not None
            and self._delegate_panel_signature
            != self._last_printed_delegate_panel_signature
        ):
            self._console.print(self._delegate_panel)
            self._last_printed_delegate_panel_signature = self._delegate_panel_signature
        try:
            live.stop()
        except Exception:
            logger.debug("Live.stop() failed", exc_info=True)
        # Rich usually restores the cursor, but prompt_toolkit may still think the
        # screen layout is pre-Live; force-visible cursor before the next prompt.
        try:
            self._console.show_cursor(True)
        except Exception:
            pass

    # Minimum seconds between non-forced Live refreshes (~20 fps).
    _REFRESH_MIN_INTERVAL: float = 0.05

    def refresh(self, *, force: bool = False) -> None:
        """Redraw the Live display if active.

        When *force* is False the call is throttled so rapid-fire streaming
        tokens do not saturate the terminal with redraws.
        """
        if self._live is None:
            return
        now = time.monotonic()
        if not force and (now - self._last_refresh_time) < self._REFRESH_MIN_INTERVAL:
            return
        self._last_refresh_time = now
        self._live.update(self, refresh=True)

    async def handle_event(self, event: Any) -> None:
        self._process_event_data(event)
        self.refresh(force=True)

    def reset_subscription(self) -> None:
        self._subscribed = False

    @contextmanager
    def suspend_live(self):
        """Stop/start Live around a block (fallback for non-interactive input)."""
        live = self._live
        if live is None:
            yield
            return
        try:
            live.stop()
        except Exception:
            logger.debug("Live.stop() failed during suspend", exc_info=True)
        try:
            yield
        finally:
            try:
                live.start()
            except Exception:
                logger.debug("Live.start() failed during resume", exc_info=True)
            self.refresh()

    def begin_turn(self) -> None:
        """Snapshot metrics and mark the agent as running."""
        self._pending_shell_command = None
        self._pending_shell_action = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False
        self._pending_activity_card = None
        self._activity_turn_header_emitted = False
        self._last_committed_reasoning_lines = None
        self._current_state = AgentState.RUNNING
        self._hud.update_ledger("Healthy")
        self._hud.update_agent_state("Running")
        self._state_event.clear()
        self._turn_start_cost = self._hud.state.cost_usd
        self._turn_start_tokens = self._hud.state.context_tokens
        self._turn_start_calls = self._hud.state.llm_calls
        self._reasoning.set_cost_baseline(self._hud.state.cost_usd)
        self.refresh()

    async def wait_for_state_change(
        self, wait_timeout_sec: float = 0.25
    ) -> AgentState | None:
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=wait_timeout_sec)
        except asyncio.TimeoutError:
            return self._current_state
        self._state_event.clear()
        return self._current_state

    def clear_history(self) -> None:
        self._pending_shell_command = None
        self._pending_shell_action = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False
        self._pending_activity_card = None
        self._activity_turn_header_emitted = False
        self._task_panel = None
        self._task_panel_signature = None
        self._last_printed_task_panel_signature = None
        self._delegate_workers = {}
        self._delegate_batch_id = None
        self._delegate_panel = None
        self._delegate_panel_signature = None
        self._last_printed_delegate_panel_signature = None
        self._last_committed_reasoning_lines = None
        self._clear_streaming_preview()
        self._reasoning.stop()
        self.refresh()

    async def add_user_message(self, text: str) -> None:
        """Print a user turn — rounded panel, high-contrast label."""
        body = Text((text or "").rstrip(), style="default")
        panel = Panel(
            Padding(body, CALLOUT_PANEL_PADDING),
            title=Text("You", style="bold dim"),
            title_align="left",
            box=box.ROUNDED,
            border_style=CLR_USER_BORDER,
            padding=(0, 0),
            style="default",
        )
        framed = frame_transcript_body(panel)
        spacer = frame_transcript_body(Text(""))
        group = Group(spacer, framed, spacer)

        if self._live is not None:
            # Same path as committed transcript lines during a turn: print into
            # scrollback while Live is active, then refresh so the layout stays
            # coherent (printing before Live started could be erased on refresh).
            self._console.print(group)
            self.refresh(force=True)
            return

        sess: Any | None = None
        if self._get_prompt_session is not None:
            try:
                sess = self._get_prompt_session()
            except Exception:
                sess = None
        app = getattr(sess, "app", None) if sess is not None else None
        if app is not None and getattr(app, "is_running", False):
            await self._safe_print_above_prompt(group)
            return

        self._console.print(group)

    def add_system_message(self, text: str, *, title: str = "Info") -> None:
        normalized_title = _normalize_system_title(title)
        lower_title = normalized_title.lower()
        if lower_title == "error":
            use_notice = _use_recoverable_notice_style(text)
            self._print_or_buffer(
                frame_transcript_body(
                    _build_error_panel(
                        text,
                        title="Error",
                        force_notice=use_notice,
                        content_width=self._console.width,
                    )
                )
            )
            if use_notice:
                self._hud.update_ledger("Idle")
                self._hud.update_agent_state("Ready")
            else:
                self._hud.update_ledger("Error")
            return
        if "timeout" in lower_title:
            self._print_or_buffer(
                frame_transcript_body(
                    _build_error_panel(
                        text,
                        title=normalized_title,
                        force_notice=True,
                        content_width=self._console.width,
                    )
                )
            )
            self._hud.update_ledger("Idle")
            self._hud.update_agent_state("Ready")
            return
        tone = "warning" if lower_title == "warning" else "info"
        panel = _build_system_notice_panel(
            text,
            title=normalized_title,
            tone=tone,
        )
        self._print_or_buffer(frame_transcript_body(panel))

    def add_markdown_block(self, title: str, text: str) -> None:
        from rich.rule import Rule

        self._print_or_buffer(Text(""))
        self._print_or_buffer(
            Padding(Rule(title, style="dim"), (1, 0, 1, 0), expand=False)
        )
        self._print_or_buffer(Padding(Markdown(text), (0, 0, 1, 0), expand=False))
        self._print_or_buffer(Text(""))

    # -- subscription ------------------------------------------------------

    def subscribe(self, event_stream: EventStream, sid: str) -> None:
        if self._subscribed:
            return
        event_stream.subscribe(_SUBSCRIBER, self._on_event_threadsafe, sid)
        self._subscribed = True

    def _on_event_threadsafe(self, event: Any) -> None:
        """Called from the EventStream's delivery thread pool.

        Appends the event to a thread-safe deque for later processing.
        NO terminal writes happen here — all rendering is done by
        ``drain_events()`` on the main thread.  This avoids two threads
        (delivery pool + Live auto-refresh timer) fighting over stdout.
        """
        self._pending_events.append(event)
        # Wake the main-thread waiter so it drains promptly.
        try:
            self._loop.call_soon_threadsafe(self._state_event.set)
        except RuntimeError:
            pass

    def drain_events(self) -> None:
        """Process all queued events and refresh.

        MUST be called from
        the main thread (the one that owns the Live display).

        Always refreshes even when no events were queued so that
        time-based widgets (e.g. the Thinking… timer) stay up to date.
        """
        while self._pending_events:
            event = self._pending_events.popleft()
            self._process_event_data(event)
        self.refresh(force=True)

    def _process_event_data(self, event: Any) -> None:
        """Update internal state for one event.  Does NOT call refresh()."""
        # Update HUD metrics first so token/cost/call counters advance even if
        # the event itself is later skipped from visual rendering.
        self._update_metrics(event)

        if isinstance(event, _SKIP_ACTIONS) or isinstance(event, _SKIP_OBSERVATIONS):
            return

        source = getattr(event, "source", None)

        if isinstance(event, Action) and source == EventSource.AGENT:
            self._handle_agent_action(event)
            return

        if isinstance(event, Observation):
            self._handle_observation(event)
            return

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        # During Live: task strip, streaming preview, reasoning, and a fake
        # prompt bar at the bottom so the input area appears to stay visible.
        # Committed transcript lines are printed via console.print immediately
        # so Rich does not clip tall turns (Live vertical_overflow ellipsis).
        body_items: list[Any] = []
        live_sections: list[Any] = []
        if self._task_panel is not None:
            live_sections.append(self._task_panel)
        if self._delegate_panel is not None:
            live_sections.append(self._delegate_panel)
        # Split the available vertical budget between the streaming preview
        # and the reasoning panel so neither one grows unbounded and pushes
        # its sibling off-screen (which, with ``vertical_overflow='crop'``,
        # would hide the streamed content entirely).
        #
        # The reserve below accounts for the fake-prompt block at the bottom
        # of the Live display: input row (1) + separator (1) + branded row
        # (1) + stats row (1-2) + padding (~1) = ~6 rows. Previously we
        # reserved 10 rows, which — combined with a very defensive
        # ``max(4, …)`` floor — left as few as 4 physical rows for reasoning
        # content and made long thoughts appear truncated to ~2 lines.
        stream_max_lines: int | None = None
        reasoning_max_lines: int | None = None
        if options.max_height:
            available = max(12, options.max_height - 6)
            thought_rows = self._reasoning.live_panel_shows_thought_rows()
            if self._streaming_accumulated and self._reasoning.active:
                if thought_rows:
                    reasoning_share = max(10, available * 3 // 5)
                    stream_max_lines = max(6, min(16, available - reasoning_share - 1))
                    reasoning_max_lines = max(
                        10, min(reasoning_share, available - stream_max_lines - 1)
                    )
                else:
                    # Header-only Thinking panel: give the draft-reply preview
                    # the bulk of the Live viewport.
                    reasoning_max_lines = 6
                    stream_max_lines = max(10, min(28, available - 5))
            elif self._streaming_accumulated:
                stream_max_lines = max(10, min(28, available))
            elif self._reasoning.active:
                reasoning_max_lines = max(12, min(32, available)) if thought_rows else 6

        if self._streaming_accumulated:
            live_sections.append(
                self._render_streaming_preview(
                    max_width=options.max_width,
                    max_lines=stream_max_lines,
                )
            )
        reasoning_section: Any | None = None
        if self._reasoning.active:
            reasoning_section = self._reasoning.renderable(
                max_width=options.max_width,
                max_lines=reasoning_max_lines,
            )
            live_sections.append(reasoning_section)

        for index, section in enumerate(live_sections):
            if section is reasoning_section:
                framed = Padding(
                    section,
                    pad=(0, TRANSCRIPT_RIGHT_INSET, 0, 0),
                    expand=False,
                )
            else:
                framed = frame_live_body(section)
            if index < len(live_sections) - 1:
                body_items.append(gap_below_live_section(framed))
            else:
                body_items.append(framed)

        if live_sections:
            body_items.append(spacer_live_section())
        # Render a fake prompt bar at the bottom so the input area, stats, and
        # HUD remain visually present while the agent works.
        body_items.append(self._render_fake_prompt(options.max_width))

        yield Group(*body_items)

    # -- fake prompt (matches prompt_toolkit bottom toolbar) ----------------

    def _render_fake_prompt(self, width: int) -> Any:
        """Render a prompt look-alike anchored at the bottom of the Live display.

        Visually matches the prompt_toolkit bottom_toolbar so the transition
        between Live (agent executing) and prompt_toolkit (user input) is
        seamless — the input area and stats bar never appear to disappear.
        """
        from rich.spinner import Spinner

        hud = self._hud.state
        items: list[Any] = []
        provider, model = HUDBar.describe_model(hud.model)

        # -- fake input line (replaces the real ❯ prompt) -------------------
        input_row = Table.grid()
        input_row.add_column(width=3)
        input_row.add_column()
        state_l = (hud.agent_state_label or "Running").strip()
        if state_l.lower() == "running":
            subline = "Agent working · ctrl+c to interrupt"
            spin_style = CLR_BRAND
            text_style = f"italic {CLR_META}"
        else:
            subline = f"{state_l} · ctrl+c if you need to interrupt"
            spin_style = f"dim {CLR_META}"
            text_style = f"italic {CLR_META}"
        input_row.add_row(
            Spinner("dots", style=spin_style),
            Text(subline, style=text_style),
        )
        items.append(input_row)

        # -- separator (mirrors _prompt_bottom_toolbar) ---------------------
        items.append(Text("─" * width, style=CLR_SEP))

        state_label = hud.agent_state_label or "Running"
        autonomy = hud.autonomy_level or "balanced"

        # Tight bullet separator — the old "  •  " (5 chars) made the row
        # feel crowded; " · " keeps the visual rhythm while reclaiming
        # ~2 chars per delimiter for denser information without clutter.
        SEP = (" · ", CLR_SEP)

        if width < 72:
            # Compact single-line mode for very narrow terminals.
            model_short = (
                model
                if provider in {"(not set)", "(unknown)"}
                else f"{provider}/{model}"
            )
            ctx = (
                HUDBar._format_tokens(hud.context_tokens)
                if hud.context_tokens > 0
                else "0"
            )
            line = Text()
            ws_compact = (hud.workspace_path or "").strip()
            if ws_compact:
                line.append(
                    HUDBar.ellipsize_path(ws_compact, 22),
                    style=f"dim {CLR_MUTED_TEXT}",
                )
                line.append(SEP[0], style=SEP[1])
            line.append(state_label, style="dim")
            line.append(SEP[0], style=SEP[1])
            line.append(f"autonomy:{autonomy}", style="dim")
            line.append(SEP[0], style=SEP[1])
            line.append(model_short, style="dim")
            line.append(SEP[0], style=SEP[1])
            line.append(ctx, style="dim")
            line.append(SEP[0], style=SEP[1])
            line.append(f"${hud.cost_usd:.4f}", style="dim")
            items.append(line)
            return Group(*items)

        # -- row 1: brand + state badge + autonomy -------------------------
        row1 = Text()
        row1.append("GRINTA", style=CLR_BRAND)
        row1.append("  ", style="")
        _BADGE_STYLES = {
            "Running": CLR_STATE_RUNNING,
            "Ready": CLR_STATUS_OK + " bold",
            "Done": CLR_STATUS_OK + " bold",
            "Finished": CLR_STATUS_OK + " bold",
            "Needs approval": CLR_STATUS_WARN + " bold",
            "Needs attention": CLR_STATUS_ERR + " bold",
            "Stopped": CLR_STATUS_ERR + " bold",
        }
        row1.append(
            f" {state_label.upper()} ",
            style=_BADGE_STYLES.get(state_label, CLR_STATUS_OK + " bold"),
        )
        row1.append("  ", style="")
        auto_style = CLR_AUTONOMY_BALANCED
        if "full" in autonomy:
            auto_style = CLR_AUTONOMY_FULL
        elif "supervised" in autonomy:
            auto_style = CLR_AUTONOMY_SUPERVISED
        row1.append(f"autonomy:{autonomy}", style=auto_style)
        items.append(row1)

        ws_full = (hud.workspace_path or "").strip()
        if ws_full:
            row_ws = Text()
            row_ws.append("workspace ", style=f"dim {CLR_META}")
            row_ws.append(
                HUDBar.ellipsize_path(ws_full, max(28, width - 14)),
                style=CLR_MUTED_TEXT,
            )
            items.append(row_ws)

        # -- row 2: model · tokens · cost · ledger (+ optionals) -----------
        ctx = (
            HUDBar._format_tokens(hud.context_tokens) if hud.context_tokens > 0 else "0"
        )
        lim = HUDBar._format_tokens(hud.context_limit) if hud.context_limit else "?"
        if hud.context_tokens == 0 and hud.context_limit == 0:
            token_display = "0 tokens"
        elif hud.context_limit == 0:
            token_display = f"{ctx} tokens"
        else:
            token_display = f"{ctx}/{lim}"

        mcp_label = HUDBar._format_mcp_servers_label(hud.mcp_servers)
        skills_label = HUDBar._format_skills_label(self._hud.bundled_skill_count)

        ledger_style = CLR_STATUS_OK + " bold"
        if hud.ledger_status in {"Review", "Paused"}:
            ledger_style = CLR_STATUS_WARN + " bold"
        elif hud.ledger_status not in {"Healthy", "Ready", "Idle", "Starting"}:
            ledger_style = CLR_STATUS_ERR + " bold"

        # "provider/model" combined — the explicit "provider:" and "model:"
        # labels were redundant visual weight. Provider is already implied
        # by the prefix of the model slug.
        if provider in {"(not set)", "(unknown)"}:
            model_display = model
        else:
            model_display = f"{provider}/{model}"

        primary_parts: list[tuple[str, str]] = [
            (model_display, CLR_HUD_MODEL),
            SEP,
            (token_display, CLR_HUD_DETAIL),
            SEP,
            (f"${hud.cost_usd:.4f}", CLR_HUD_DETAIL),
            SEP,
            (hud.ledger_status, ledger_style),
        ]
        optional_parts: list[tuple[str, str]] = [
            (f"{hud.llm_calls} calls", CLR_HUD_DETAIL),
            (mcp_label, CLR_HUD_DETAIL),
            (skills_label, CLR_HUD_DETAIL),
        ]
        parts: list[tuple[str, str]] = list(primary_parts)
        for content, style in optional_parts:
            parts.append(SEP)
            parts.append((content, style))

        total_len = sum(len(c) for c, _ in parts)
        if total_len <= width:
            row2 = Text()
            for content, style in parts:
                row2.append(content, style=style)
            items.append(row2)
        else:
            # Split: essentials on line 1, optionals on line 2.
            row2a = Text()
            for content, style in primary_parts:
                row2a.append(content, style=style)
            items.append(row2a)
            row2b = Text()
            first = True
            for content, style in optional_parts:
                if not first:
                    row2b.append(SEP[0], style=SEP[1])
                row2b.append(content, style=style)
                first = False
            items.append(row2b)

        return Group(*items)

    # -- action handlers ---------------------------------------------------

    def _handle_agent_action(self, action: Action) -> None:
        if isinstance(action, StreamingChunkAction):
            self._handle_streaming_chunk(action)
            return

        if isinstance(action, MessageAction):
            self._flush_pending_tool_cards()
            # Suppress mid-task internal messages that were intercepted by the
            # event router (e.g. verbose model text between checkpoint and next
            # tool call). Still clear the streaming preview and stop reasoning
            # so Live panel doesn't linger.
            if getattr(action, "suppress_cli", False):
                self._stop_reasoning()
                self._clear_streaming_preview()
                self.refresh()
                return
            cot = (getattr(action, "thought", None) or "").strip()
            if cot and _show_reasoning_text():
                cleaned_cot = _sanitize_visible_transcript_text(cot)
                if cleaned_cot:
                    self._ensure_reasoning()
                    self._reasoning.update_thought(cleaned_cot)
            self._stop_reasoning()
            self._clear_streaming_preview()
            display_content = _sanitize_visible_transcript_text(action.content or "")
            if display_content:
                file_urls = getattr(action, "file_urls", None) or []
                image_urls = getattr(action, "image_urls", None) or []
                attachments: list[Any] = []
                if file_urls:
                    attachments.append(
                        format_activity_secondary(
                            f"files attached · {len(file_urls)} file(s)",
                            kind="neutral",
                        )
                    )
                if image_urls:
                    attachments.append(
                        format_activity_secondary(
                            f"images attached · {len(image_urls)} image(s)",
                            kind="neutral",
                        )
                    )
                self._append_assistant_message(display_content, attachments=attachments)
            else:
                self.refresh()
            return

        if not isinstance(action, AgentThinkAction):
            self._clear_streaming_preview()

        if isinstance(action, AgentThinkAction):
            if getattr(action, "suppress_cli", False):
                self.refresh()
                return
            source_tool = getattr(action, "source_tool", "") or ""
            thought = getattr(action, "thought", "") or getattr(action, "content", "")
            if source_tool:
                # Tool-sourced think actions get a proper activity row instead of
                # generic reasoning text.  Strip internal JSON payloads from the
                # human-readable summary.
                cleaned = _THINK_RESULT_JSON_RE.sub("", thought).strip()

                # Strip XML-like tags (e.g. <search_results>) and leading [TAG] markers to get the human message.
                tag_m = _INTERNAL_THINK_TAG_RE.match(cleaned)
                human_msg = (tag_m.group("payload") or "").strip() if tag_m else cleaned
                human_msg = _TOOL_RESULT_TAG_RE.sub("", human_msg).strip()

                if source_tool == "checkpoint":
                    verb, title = "Saved", ACTIVITY_CARD_TITLE_CHECKPOINT
                    # Use the tag's human message or a user-friendly default.
                    detail = human_msg or "checkpoint"
                elif source_tool == "revert_to_checkpoint":
                    verb, title = "Reverted", ACTIVITY_CARD_TITLE_CHECKPOINT
                    detail = human_msg or "workspace reverted"
                elif source_tool == "search_code":
                    verb, title = "Search Code", ACTIVITY_CARD_TITLE_SEARCH
                    lines = [
                        ln
                        for ln in (human_msg or "").splitlines()
                        if ln.strip() and not ln.startswith("Error running ripgrep:")
                    ]
                    if (
                        not lines
                        or any("No matches found." in ln for ln in lines[:5])
                        or any("No matching files found" in ln for ln in lines[:5])
                    ):
                        detail = "No matches found."
                    else:
                        match_count = sum(
                            1 for line in lines if re.match(r"^.*:\d+:", line)
                        ) or len(lines)
                        detail = f"Found {match_count} match lines."
                else:
                    verb = source_tool.replace("_", " ").title()
                    title = ACTIVITY_CARD_TITLE_TOOL
                    detail = str(human_msg)[:150] or source_tool
                self._emit_activity_turn_header()
                kind = "err" if "Failure" in (human_msg or "") else "ok"
                self._print_or_buffer(
                    Padding(
                        format_activity_block(
                            verb,
                            detail,
                            secondary=None,
                            secondary_kind=kind,
                            title=title,
                        ),
                        pad=ACTIVITY_BLOCK_BOTTOM_PAD,
                    )
                )
                self.refresh()
                return
            self._apply_reasoning_text(thought)
            self.refresh()
            return

        if isinstance(action, CmdRunAction):
            self._clear_streaming_preview()
            self._flush_pending_activity_card()
            if getattr(action, "hidden", False):
                self.refresh()
                return
            # Flush any previous buffered command that never received an observation
            if self._pending_shell_action is not None:
                self._flush_pending_shell_action()
            display_label = (getattr(action, "display_label", "") or "").strip()
            if display_label:
                # Internal tool command — buffer with friendly label; CmdOutputObservation
                # will render a compact result row (no raw terminal block).  Do NOT forward
                # the thought to the reasoning display — the display_label already acts as
                # the activity label and showing the thought too creates a duplicate.
                meta = getattr(action, "tool_call_metadata", None)
                function_name = getattr(meta, "function_name", "") or ""
                _icon, headline = tool_headline(
                    function_name, use_icons=self._cli_tool_icons
                )
                self._pending_shell_command = None
                self._pending_shell_action = ("Ran", display_label)
                self._pending_shell_title = headline or ACTIVITY_CARD_TITLE_SHELL
                self._pending_shell_is_internal = True
                self.refresh()
                return
            self._pending_shell_is_internal = False
            self._pending_shell_title = None
            cmd_display = (action.command or "").strip()
            if len(cmd_display) > 12_000:
                cmd_display = cmd_display[:11_997] + "…"
            self._pending_shell_command = cmd_display
            label = f"$ {cmd_display}" if cmd_display else "$ (empty)"
            # Buffer — combined card (command + result) is printed in CmdOutputObservation
            self._pending_shell_action = ("Ran", label)
            thought = getattr(action, "thought", "") or ""
            _sync_reasoning_after_tool_line(self._reasoning, label, thought)
            self.refresh()
            return

        if isinstance(action, FileEditAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            cmd = getattr(action, "command", "")
            path = action.path
            insert_line = getattr(action, "insert_line", None)
            start = getattr(action, "start", 1)
            end = getattr(action, "end", -1)
            stats: str | None = None
            if cmd == "read_file":
                verb, detail = "Read", path
            elif cmd == "create_file":
                verb, detail = "Created", path
            elif cmd == "insert_text":
                verb, detail = "Inserted", path
                stats = f"line {insert_line}" if insert_line is not None else None
            elif cmd == "undo_last_edit":
                verb, detail = "Reverted", path
            elif not cmd:
                end_str = f"L{end}" if end != -1 else "end"
                verb, detail = "Edited", f"{path} · L{start}:{end_str}"
            elif cmd == "write":
                verb, detail = "Wrote", path
            else:
                verb = "Edited"
                detail = path
            self._buffer_pending_activity(
                title=ACTIVITY_CARD_TITLE_FILES,
                verb=verb,
                detail=detail,
                secondary=stats,
                kind="file_edit",
            )
            thought = getattr(action, "thought", "") or ""
            _sync_reasoning_after_tool_line(
                self._reasoning, f"{verb} {detail}", thought
            )
            self.refresh()
            return

        if isinstance(action, FileWriteAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            content = getattr(action, "content", "") or ""
            n_lines = len(content.splitlines()) if content else 0
            self._buffer_pending_activity(
                title=ACTIVITY_CARD_TITLE_FILES,
                verb="Created",
                detail=action.path,
                kind="file_write",
                payload={"line_count": n_lines},
            )
            thought = getattr(action, "thought", "") or ""
            _sync_reasoning_after_tool_line(
                self._reasoning, f"Created {action.path}", thought
            )
            self.refresh()
            return

        if isinstance(action, RecallAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            query = getattr(action, "query", "")
            detail = query or "workspace context"
            if len(detail) > 100:
                detail = detail[:97] + "…"
            self._print_activity(
                "Recalled", detail, None, title=ACTIVITY_CARD_TITLE_MEMORY
            )
            self.refresh()
            return

        # -- File read --------------------------------------------------------
        if isinstance(action, FileReadAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            path = getattr(action, "path", "")
            view_range = getattr(action, "view_range", None)
            start = getattr(action, "start", 0)
            end = getattr(action, "end", -1)
            if view_range and len(view_range) == 2:
                detail = f"{path} · L{view_range[0]}:L{view_range[1]}"
            elif start not in (0, 1) or end != -1:
                end_str = str(end) if end != -1 else "end"
                detail = f"{path} · L{start}:{end_str}"
            else:
                detail = path
            self._buffer_pending_activity(
                title=ACTIVITY_CARD_TITLE_FILES,
                verb="Viewed",
                detail=detail,
                kind="file_read",
            )
            thought = getattr(action, "thought", "") or ""
            _sync_reasoning_after_tool_line(self._reasoning, f"Viewed {path}", thought)
            self.refresh()
            return

        # -- MCP tool call ----------------------------------------------------
        if isinstance(action, MCPAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            name = getattr(action, "name", "tool")
            raw_args = getattr(action, "arguments", None) or {}
            args_dict = raw_args if isinstance(raw_args, dict) else {}
            verb, detail, stats = format_tool_activity_rows(name, args_dict)
            self._buffer_pending_activity(
                title=ACTIVITY_CARD_TITLE_MCP,
                verb=verb,
                detail=detail,
                secondary=stats,
                kind="mcp",
            )
            thought = getattr(action, "thought", "") or ""
            _sync_reasoning_after_tool_line(
                self._reasoning, f"{verb} {detail}", thought
            )
            self.refresh()
            return

        # -- Native browser (browser-use) --------------------------------------
        if isinstance(action, BrowserToolAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            cmd = getattr(action, "command", "") or "browser"
            params = getattr(action, "params", None) or {}
            url = params.get("url") if isinstance(params, dict) else None
            detail = str(url)[:80] if url else str(cmd)
            self._print_activity(
                str(cmd), detail, None, title=ACTIVITY_CARD_TITLE_BROWSER
            )
            thought = getattr(action, "thought", "") or ""
            _sync_reasoning_after_tool_line(self._reasoning, detail, thought)
            self.refresh()
            return

        # -- Browser ----------------------------------------------------------
        if isinstance(action, BrowseInteractiveAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            browser_actions = getattr(action, "browser_actions", "") or ""
            url_match = re.search(r'https?://[^\s\'")\]]+', browser_actions)
            if url_match:
                url = url_match.group(0)[:80]
                detail = url
            else:
                detail = "interactive session"
            self._print_activity(
                "Opened", detail, None, title=ACTIVITY_CARD_TITLE_BROWSER
            )
            thought = getattr(action, "thought", "") or ""
            _sync_reasoning_after_tool_line(self._reasoning, detail, thought)
            self.refresh()
            return

        # -- Code navigation --------------------------------------------------
        if isinstance(action, LspQueryAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            cmd = getattr(action, "command", "query")
            file = getattr(action, "file", "")
            symbol = getattr(action, "symbol", "")
            detail = symbol or file
            stats = str(cmd) if cmd else None
            self._buffer_pending_activity(
                title=ACTIVITY_CARD_TITLE_CODE,
                verb="Analyzed",
                detail=detail,
                secondary=stats,
                kind="lsp",
            )
            self.refresh()
            return

        # -- Task tracking ----------------------------------------------------
        if isinstance(action, TaskTrackingAction):
            self._clear_streaming_preview()
            command = str(getattr(action, "command", "") or "").strip().lower()
            task_list = getattr(action, "task_list", None)
            if command == "update" and isinstance(task_list, list):
                self._set_task_panel(task_list)
            self.refresh()
            return

        # -- Context condensation ---------------------------------------------
        if isinstance(action, CondensationAction):
            self._ensure_reasoning()
            self._reasoning.update_action("Compressing context…")
            self.refresh()
            return

        # -- Progress signal --------------------------------------------------
        if isinstance(action, SignalProgressAction):
            note = getattr(action, "progress_note", "")
            if note:
                self._ensure_reasoning()
                self._reasoning.update_action(note)
            self.refresh()
            return

        # -- Terminal session -------------------------------------------------
        if isinstance(action, TerminalRunAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            cmd = (getattr(action, "command", "") or "").strip()
            if len(cmd) > 12_000:
                cmd = cmd[:11_997] + "…"
            self._pending_shell_command = cmd
            label = cmd if cmd else "(empty)"
            self._print_activity(
                "Launch",
                f"$ {label}",
                None,
                title=ACTIVITY_CARD_TITLE_TERMINAL,
                shell_rail=True,
            )
            self._ensure_reasoning()
            pty_line = f"{ACTIVITY_CARD_TITLE_TERMINAL} · {label}"
            thought = getattr(action, "thought", "") or ""
            _sync_reasoning_after_tool_line(self._reasoning, pty_line, thought)
            self.refresh()
            return

        if isinstance(action, TerminalInputAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            sess = (getattr(action, "session_id", "") or "").strip()
            inp = getattr(action, "input", "") or ""
            ctrl = getattr(action, "control", None)
            is_ctl = bool(getattr(action, "is_control", False))
            if ctrl and str(ctrl).strip():
                inp_display = f"ctrl {ctrl}"[:60]
                self._last_terminal_input_sent = ""
            elif is_ctl and inp:
                inp_display = inp[:60] + ("…" if len(inp) > 60 else "")
                self._last_terminal_input_sent = ""
            else:
                inp_display = inp[:60] + ("…" if len(inp) > 60 else "")
                self._last_terminal_input_sent = inp.strip().rstrip("\r\n")
            cmd_detail = f"[{sess}]  $ {inp_display}" if sess else f"$ {inp_display}"
            self._print_activity(
                "Run", cmd_detail, None, title=ACTIVITY_CARD_TITLE_TERMINAL
            )
            self._ensure_reasoning()
            if sess and inp_display:
                line = f"{ACTIVITY_CARD_TITLE_TERMINAL} input · {sess} · {inp_display}"
            elif sess:
                line = f"{ACTIVITY_CARD_TITLE_TERMINAL} input · {sess}"
            else:
                line = f'{ACTIVITY_CARD_TITLE_TERMINAL} input · {inp_display or "…"}'
            thought = getattr(action, "thought", "") or ""
            _sync_reasoning_after_tool_line(self._reasoning, line, thought)
            self.refresh()
            return

        if isinstance(action, TerminalReadAction):
            # Read is a polling operation — don't clutter the transcript with a
            # full card; just keep the reasoning panel up-to-date.
            self._clear_streaming_preview()
            sess = (getattr(action, "session_id", "") or "").strip()
            self._ensure_reasoning()
            line = (
                f"{ACTIVITY_CARD_TITLE_TERMINAL} read · {sess}"
                if sess
                else f"{ACTIVITY_CARD_TITLE_TERMINAL} read · …"
            )
            thought = getattr(action, "thought", "") or ""
            _sync_reasoning_after_tool_line(self._reasoning, line, thought)
            self.refresh()
            return

        # -- Delegation -------------------------------------------------------
        if isinstance(action, DelegateTaskAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            self._reset_delegate_panel(batch_id=action.id if action.id > 0 else None)
            desc_display, secondary = _summarize_delegate_action(action)
            self._buffer_pending_activity(
                title=ACTIVITY_CARD_TITLE_DELEGATION,
                verb="Delegated",
                detail=desc_display,
                secondary=secondary,
                kind="delegate",
            )
            self.refresh()
            return

        # -- Playbook finish --------------------------------------------------
        if isinstance(action, PlaybookFinishAction):
            self._flush_pending_tool_cards()
            self._stop_reasoning()
            self._clear_streaming_preview()
            finish_text = _sanitize_visible_transcript_text(action.message or "")
            if finish_text:
                self._append_assistant_message(finish_text)
            self.refresh()
            return

        # -- Escalation to human ----------------------------------------------
        if isinstance(action, EscalateToHumanAction):
            self._flush_pending_tool_cards()
            self._stop_reasoning()
            self._clear_streaming_preview()
            reason = getattr(action, "reason", "")
            help_needed = getattr(action, "specific_help_needed", "")
            escalate_parts: list[Any] = []
            if reason:
                escalate_parts.append(Text(reason, style="yellow"))
            if help_needed:
                escalate_parts.append(
                    Text(f"Help needed: {help_needed}", style="yellow")
                )
            if not escalate_parts:
                escalate_parts.append(
                    Text("The agent needs your input to continue.", style="yellow")
                )
            self._append_history(
                format_callout_panel(
                    "Need Your Input",
                    Group(*escalate_parts),
                    accent_style=DECISION_PANEL_ACCENT_STYLE,
                )
            )
            self.refresh()
            return

        # -- Clarification request --------------------------------------------
        if isinstance(action, ClarificationRequestAction):
            self._flush_pending_tool_cards()
            self._stop_reasoning()
            self._clear_streaming_preview()
            question = getattr(action, "question", "")
            options = getattr(action, "options", []) or []
            clarify_parts: list[Any] = []
            if question:
                clarify_parts.append(Text(question, style="yellow"))
            for i, opt in enumerate(options, 1):
                option_line = Text()
                option_line.append(f"{i}. ", style="bold #f1bf63")
                option_line.append(str(opt), style="#e2e8f0")
                clarify_parts.append(option_line)
            if clarify_parts:
                self._append_history(
                    format_callout_panel(
                        "Question",
                        Group(*clarify_parts),
                        accent_style=DECISION_PANEL_ACCENT_STYLE,
                    )
                )
            self.refresh()
            return

        # -- Uncertainty signal -----------------------------------------------
        if isinstance(action, UncertaintyAction):
            self._flush_pending_tool_cards()
            concerns = getattr(action, "specific_concerns", []) or []
            info_needed = getattr(action, "requested_information", "")
            uncertainty_parts: list[Any] = []
            for concern in concerns[:5]:
                concern_line = Text()
                concern_line.append("• ", style="dim")
                concern_line.append(str(concern), style="dim")
                uncertainty_parts.append(concern_line)
            if info_needed:
                uncertainty_parts.append(Text(f"Need: {info_needed}", style="yellow"))
            if uncertainty_parts:
                self._append_history(
                    format_callout_panel(
                        "Needs Context",
                        Group(*uncertainty_parts),
                        accent_style=DECISION_PANEL_ACCENT_STYLE,
                    )
                )
            self.refresh()
            return

        # -- Proposal with options --------------------------------------------
        if isinstance(action, ProposalAction):
            self._flush_pending_tool_cards()
            self._stop_reasoning()
            self._clear_streaming_preview()
            options = getattr(action, "options", []) or []
            recommended = getattr(action, "recommended", 0)
            rationale = getattr(action, "rationale", "")
            proposal_parts: list[Any] = []
            if rationale:
                proposal_parts.append(Text(rationale, style="dim"))
            for i, opt in enumerate(options):
                label = opt.get("name", opt.get("title", f"Option {i + 1}"))
                desc = opt.get("description", "")
                marker = " (recommended)" if i == recommended else ""
                proposal_line = Text()
                proposal_line.append(
                    f"{i + 1}. ",
                    style=f"bold {DECISION_PANEL_ACCENT_STYLE}",
                )
                proposal_line.append(
                    f"{label}{marker}",
                    style="bold #f1bf63" if i == recommended else "bold #e2e8f0",
                )
                proposal_parts.append(proposal_line)
                if desc:
                    proposal_parts.append(Text(f"   {desc}", style="dim"))
            if proposal_parts:
                self._append_history(
                    format_callout_panel(
                        "Options",
                        Group(*proposal_parts),
                        accent_style=DECISION_PANEL_ACCENT_STYLE,
                    )
                )
            self.refresh()
            return

        self.refresh()

    def _handle_streaming_chunk(self, action: StreamingChunkAction) -> None:
        raw = action.accumulated

        # Tool call argument streaming: spinner + headline only. Do not put partial
        # JSON / command hints into the thinking buffer — those were flushed as dim
        # lines and looked like duplicate ``$ cmd`` reasoning (not LLM thinking).
        if action.is_tool_call:
            tool_name = action.tool_call_name or "tool"
            _icon, headline = tool_headline(tool_name, use_icons=self._cli_tool_icons)
            self._ensure_reasoning()
            raw = (action.accumulated or "").strip()
            hint = streaming_args_hint(tool_name, raw)
            if hint:
                self._reasoning.update_action(f"{headline}: {hint}")
            else:
                self._reasoning.update_action(f"{headline}…")
            # Clear any text content that arrived before the tool call started
            # (e.g. a preamble "[" or task-list header). Keeping it would leave
            # a stale "Draft Reply … Still streaming…" panel alongside the
            # Thinking spinner for the entire duration of the tool call stream.
            self._streaming_accumulated = ""
            self.refresh()
            return

        # Route <redacted_thinking> content to the reasoning display so the user sees
        # the model's chain-of-thought in real time.
        if looks_like_streaming_tool_arguments(raw):
            self._ensure_reasoning()
            self._reasoning.update_action("Tool…")
            self._streaming_accumulated = ""
            self.refresh()
            return

        # First-class thinking field: if the provider streamed reasoning tokens
        # via the dedicated thinking channel, display them immediately.
        if action.thinking_accumulated and _show_reasoning_text():
            cleaned_thinking = _sanitize_visible_transcript_text(
                action.thinking_accumulated
            )
            if cleaned_thinking:
                self._ensure_reasoning()
                self._reasoning.set_streaming_thought(cleaned_thinking)

        # Fallback: extract <redacted_thinking> tags embedded in content text
        # (backward compat for models that embed thinking in the main stream).
        think_match = _THINK_EXTRACT_RE.search(raw)
        if think_match:
            thinking_text = _sanitize_visible_transcript_text(think_match.group(1))
            if thinking_text and _show_reasoning_text():
                self._ensure_reasoning()
                self._reasoning.set_streaming_thought(thinking_text)
            # Strip thinking from the streaming preview.
            display_text = _THINK_STRIP_RE.sub("", raw).strip()
            self._streaming_accumulated = _sanitize_visible_transcript_text(
                display_text
            )
        else:
            self._streaming_accumulated = _sanitize_visible_transcript_text(raw)

        self._streaming_final = action.is_final
        if action.is_final:
            self._hud.state.llm_calls += 1
        # Always force redraw on streaming updates; throttling here made token
        # output feel delayed vs. the model (refresh() only coalesces to ~20fps).
        self.refresh(force=True)

    # -- observation handlers ----------------------------------------------

    def _handle_observation(self, obs: Observation) -> None:
        if isinstance(obs, AgentStateChangedObservation):
            self._handle_state_change(obs)
            return

        if isinstance(obs, AgentThinkObservation):
            if getattr(obs, "suppress_cli", False):
                self.refresh()
                return
            thought = getattr(obs, "thought", "") or getattr(obs, "content", "")
            self._apply_reasoning_text(thought)
            self.refresh()
            return

        if isinstance(obs, CmdOutputObservation):
            self._stop_reasoning()
            self._flush_pending_activity_card()
            if getattr(obs, "hidden", False):
                self._pending_shell_action = None
                self._pending_shell_command = None
                return
            # Browser tool completions reuse CmdOutputObservation (command
            # strings like ``browser navigate``/``browser screenshot``). The
            # corresponding ``Browser`` card was already printed when the
            # action was dispatched; rendering another ``Terminal / Ran /
            # $ (command) / ✓ done`` block creates spurious ghost rows in
            # the transcript. Treat those as already-displayed.
            _obs_cmd = (getattr(obs, "command", "") or "").strip().lower()
            if _obs_cmd in _BROWSER_TOOL_COMMANDS:
                self._pending_shell_action = None
                self._pending_shell_command = None
                self._pending_shell_title = None
                self._pending_shell_is_internal = False
                return
            exit_code = getattr(obs, "exit_code", None)
            if exit_code is None:
                meta = getattr(obs, "metadata", None)
                exit_code = getattr(meta, "exit_code", None) if meta else None
            raw = (getattr(obs, "content", "") or "").strip()
            content = strip_tool_result_validation_annotations(raw)
            # Retrieve buffered action (verb + label) set by CmdRunAction
            pending = self._pending_shell_action
            title = self._pending_shell_title
            is_internal = self._pending_shell_is_internal
            self._pending_shell_action = None
            self._pending_shell_command = None
            self._pending_shell_title = None
            self._pending_shell_is_internal = False
            verb = pending[0] if pending else "Ran"
            label = pending[1] if pending else "$ (command)"

            # Always initialize; some branches omit previews.
            extra_lines = None

            is_apply_patch_internal = is_internal and _is_apply_patch_activity(
                title,
                label,
            )

            if is_apply_patch_internal:
                msg, result_kind, extra_lines = _compact_apply_patch_result(
                    exit_code=exit_code,
                    label=label,
                    content=content,
                )

            # CmdOutputObservation defaults to exit_code=-1 when unknown.
            # Treat any non-zero exit code as an error line (including -1 unknown).
            elif exit_code is not None and exit_code != 0:
                err_line = _summarize_cmd_failure(content)
                msg = f"exit {exit_code}"
                if err_line:
                    msg += f" · {err_line}"
                result_kind = "err"
                # Hide raw stdout on failures: the summary line already carries
                # the important bit and the full body is reachable via logs.
                extra_lines = None
            else:
                raw_lines = (
                    [ln.strip() for ln in content.split("\n") if ln.strip()]
                    if content
                    else []
                )
                if not raw_lines:
                    msg = "done" if exit_code == 0 else None
                else:
                    msg = "done"
                result_kind = "ok" if exit_code == 0 else "neutral"
                # Plain shell successes: suppress the verbose stdout to reduce
                # transcript clutter; curated summaries (apply_patch +/− delta)
                # set their own ``extra_lines`` above and are preserved.
                extra_lines = None

            inner = format_activity_shell_block(
                verb,
                label,
                result_message=msg,
                result_kind=result_kind,
                extra_lines=extra_lines,
                # ``title`` was captured from the tool-call metadata when
                # CmdRunAction was buffered; use it so internal tool
                # invocations (apply_patch, analyze_project_structure, …)
                # render under their friendly headline instead of the
                # generic ``Terminal`` card.
                title=title if is_internal else None,
            )
            self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))
            return

        if isinstance(obs, (FileEditObservation, FileWriteObservation)):
            self._stop_reasoning()
            path = getattr(obs, "path", "")
            if isinstance(obs, FileEditObservation):
                from backend.cli.diff_renderer import DiffPanel

                pending = self._take_pending_activity_card("file_edit")  # type: ignore
                self._emit_activity_turn_header()
                self._print_or_buffer(
                    Padding(
                        DiffPanel(
                            obs,
                            verb=pending.verb if pending else None,  # type: ignore
                            detail=pending.detail if pending else path,  # type: ignore
                            secondary=pending.secondary if pending else None,  # type: ignore
                        ),
                        pad=ACTIVITY_BLOCK_BOTTOM_PAD,
                    )
                )
            else:
                pending = self._take_pending_activity_card("file_write")  # type: ignore
                extra_lines: list[Any] = []  # type: ignore
                line_count = 0
                if pending and pending.payload:  # type: ignore
                    raw_line_count = pending.payload.get("line_count", 0)  # type: ignore
                    line_count = (
                        raw_line_count if isinstance(raw_line_count, int) else 0
                    )
                delta = format_activity_delta_secondary(added=line_count)
                # Keep explicit line-count delta, but suppress default "created"
                # summary because a dedicated create-file UI component exists.
                if delta is not None:
                    extra_lines.append(delta)  # type: ignore

                if pending is not None:
                    self._render_pending_activity_card(pending, extra_lines=extra_lines)  # type: ignore
                # If no pending card, skip emitting the default 'created' line.
            return

        if isinstance(obs, ErrorObservation):
            self._stop_reasoning()
            self._flush_pending_tool_cards()
            self._clear_streaming_preview()
            error_content = getattr(obs, "content", str(obs))
            use_notice = _use_recoverable_notice_style(error_content)
            self._append_history(
                _build_error_panel(
                    error_content,
                    force_notice=use_notice,
                    content_width=self._console.width,
                ),
            )
            # Do not force HUD to Ready/Idle here for recoverable notices — the
            # agent may still be RUNNING (e.g. before RecoveryService transitions
            # state), which made the status bar lie and hid why the prompt was
            # blocked.  Ledger/agent HUD is driven by AgentStateChangedObservation.
            if not use_notice:
                self._hud.update_ledger("Error")
            return

        if isinstance(obs, UserRejectObservation):
            self._flush_pending_tool_cards()
            content = getattr(obs, "content", "")
            self._append_history(
                format_callout_panel(
                    "Rejected",
                    Text(content or "Action rejected.", style="yellow"),
                    accent_style="yellow",
                )
            )
            return

        if isinstance(obs, RecallObservation):
            self._flush_pending_tool_cards()
            # Show brief recall summary — full content goes to the agent
            recall_type = getattr(obs, "recall_type", None)
            label = str(recall_type.value) if recall_type else "context"
            # The next agent step will call the LLM — show activity indicator
            self._ensure_reasoning()
            self._reasoning.update_action(f"Recalled {label}…")
            self.refresh()
            return

        if isinstance(obs, StatusObservation):
            status_type = str(getattr(obs, "status_type", "") or "")
            force_visible_status = False
            if status_type == "delegate_progress":
                extras = getattr(obs, "extras", None) or {}
                batch_id = extras.get("batch_id")
                if (
                    batch_id is not None
                    and self._delegate_batch_id is not None
                    and batch_id != self._delegate_batch_id
                ):
                    return
                worker_id = str(extras.get("worker_id") or "").strip()
                if worker_id:
                    order = extras.get("order", 9999)
                    if not isinstance(order, int):
                        order = 9999
                    self._delegate_workers[worker_id] = {
                        "label": str(extras.get("worker_label") or worker_id),
                        "status": str(extras.get("worker_status") or "running"),
                        "task": str(extras.get("task_description") or "subtask"),
                        "detail": str(
                            extras.get("detail") or getattr(obs, "content", "") or ""
                        ),
                        "order": order,
                    }
                    self._set_delegate_panel()
                    return
            elif status_type == "retry_pending":
                extras = getattr(obs, "extras", None) or {}
                try:
                    attempt = max(1, int(extras.get("attempt") or 1))
                except (TypeError, ValueError):
                    attempt = 1
                try:
                    max_attempts = max(
                        attempt, int(extras.get("max_attempts") or attempt)
                    )
                except (TypeError, ValueError):
                    max_attempts = attempt
                self._hud.update_ledger("Backoff")
                self._hud.update_agent_state(f"Auto Retry {attempt}/{max_attempts}")
                force_visible_status = True
            elif status_type == "retry_resuming":
                extras = getattr(obs, "extras", None) or {}
                try:
                    attempt = max(1, int(extras.get("attempt") or 1))
                except (TypeError, ValueError):
                    attempt = 1
                try:
                    max_attempts = max(
                        attempt, int(extras.get("max_attempts") or attempt)
                    )
                except (TypeError, ValueError):
                    max_attempts = attempt
                self._hud.update_ledger("Backoff")
                self._hud.update_agent_state(f"Retrying {attempt}/{max_attempts}")
                force_visible_status = True
            content = getattr(obs, "content", "")
            if content:
                lower_c = content.lower()
                if (
                    "stream timed out" in lower_c
                    or "retrying without streaming" in lower_c
                ):
                    self._stream_fallback_count += 1
                    logger.warning(
                        "stream_fallback_retry: count=%d content=%r",
                        self._stream_fallback_count,
                        content[:120],
                    )
                    self._append_history(_build_llm_stream_fallback_panel())
                elif (
                    self._pending_activity_card is not None and not force_visible_status
                ):
                    return
                else:
                    self._flush_pending_tool_cards()
                    self._append_history(
                        format_activity_result_secondary(
                            f"status · {content}", kind="neutral"
                        )
                    )
            return

        # -- File read result -------------------------------------------------
        if isinstance(obs, FileReadObservation):
            self._stop_reasoning()
            content = getattr(obs, "content", "") or ""
            n_lines = len(content.splitlines()) if content else 0
            pending = self._take_pending_activity_card("file_read")  # type: ignore
            # ``text_editor view`` on a directory returns a header line
            # (``Directory contents of <path>:``) followed by one entry per
            # line. Labelling that output as "N lines" is misleading — the
            # number the user cares about is *entries*. We subtract 1 for the
            # header so the count matches what they see in the listing.
            if content.startswith(_DIRECTORY_VIEW_PREFIX):
                n_entries = max(0, n_lines - 1)
                if n_entries == 1:
                    result_message = "1 entry"
                elif n_entries:
                    result_message = f"{n_entries:,} entries"
                else:
                    result_message = "empty directory"
            else:
                result_message = f"{n_lines:,} lines" if n_lines else "empty file"
            if pending is not None:
                self._render_pending_activity_card(
                    pending,  # type: ignore
                    result_message=result_message,
                    result_kind="neutral",
                )
            elif n_lines:
                self._append_history(
                    format_activity_result_secondary(result_message, kind="neutral")
                )
            return

        # -- MCP tool result --------------------------------------------------
        if isinstance(obs, MCPObservation):
            self._stop_reasoning()
            content = getattr(obs, "content", "")
            friendly = mcp_result_user_preview(content)
            pending = self._take_pending_activity_card("mcp")  # type: ignore
            if pending is not None:
                self._render_pending_activity_card(
                    pending,  # type: ignore
                    result_message=friendly or None,
                    result_kind="neutral",
                )
            elif friendly:
                self._append_history(
                    format_activity_result_secondary(friendly, kind="neutral")
                )
            return

        # -- Terminal output --------------------------------------------------
        if isinstance(obs, TerminalObservation):
            raw = getattr(obs, "content", "") or ""
            display = strip_tool_result_validation_annotations(raw)
            content = display.strip()
            session_id = (getattr(obs, "session_id", "") or "").strip()
            has_new = getattr(obs, "has_new_output", None)
            # Suppress entirely when there's nothing new — these are just polling
            # reads and the "no new text" caption is noise for the human user.
            if has_new is False and not content:
                self._last_terminal_input_sent = ""
                return
            self._stop_reasoning()
            self._flush_pending_tool_cards()
            # Strip PTY character-echo lines produced when the agent injects input.
            if content and self._last_terminal_input_sent:
                content = _strip_pty_echo(content, self._last_terminal_input_sent)
                self._last_terminal_input_sent = ""
            n_lines = (
                len([ln for ln in content.splitlines() if ln.strip()]) if content else 0
            )
            cap = 2000
            truncated = len(display) > cap
            body = (content[:cap] + "…" if truncated else content) if content else ""
            if not content and not session_id and not raw.strip():
                return
            if content:
                title_parts: list[str] = []
                if session_id:
                    title_parts.append(session_id)
                if n_lines:
                    title_parts.append(f'{n_lines} line{"s" if n_lines != 1 else ""}')
                if truncated:
                    title_parts.append("truncated")
                panel_title = Text(
                    "  ·  ".join(title_parts) if title_parts else "output",
                    style="dim #9ca3af",
                )
                self._append_history(
                    Padding(
                        Panel(
                            Syntax(body, "text", word_wrap=True, theme="ansi_dark"),
                            title=panel_title,
                            title_align="left",
                            border_style="#1e3a4a",
                            box=box.ROUNDED,
                            padding=(0, 1),
                        ),
                        pad=(0, 0, 1, 0),
                    )
                )
            else:
                caption = _pty_output_transcript_caption(
                    session_id=session_id,
                    n_lines=n_lines,
                    truncated=truncated,
                    has_output=bool(content),
                    has_new_output=has_new,
                )
                self._append_history(
                    format_activity_result_secondary(caption, kind="neutral")
                )
            return

        # -- LSP / code navigation result -------------------------------------
        if isinstance(obs, LspQueryObservation):
            self._stop_reasoning()
            available = getattr(obs, "available", True)
            content = getattr(obs, "content", "") or ""
            pending = self._take_pending_activity_card("lsp")  # type: ignore
            result_message: str | None = None  # type: ignore
            if not available:
                result_message = "code navigation unavailable"
            elif content.strip():
                lines = [line for line in content.split("\n") if line.strip()]
                n = len(lines)
                if n:
                    preview = lines[0][:80]
                    suffix = f" · {n} lines" if n > 1 else ""
                    result_message = f"{preview}{suffix}"
            if pending is not None:
                self._render_pending_activity_card(
                    pending,  # type: ignore
                    result_message=result_message,
                    result_kind="neutral",
                )
            elif result_message:
                self._append_history(
                    format_activity_result_secondary(result_message, kind="neutral")
                )
            return

        # -- Server ready -----------------------------------------------------
        if isinstance(obs, ServerReadyObservation):
            self._flush_pending_tool_cards()
            url = getattr(obs, "url", "")
            port = getattr(obs, "port", "")
            label = url or f"port {port}"
            self._append_history(
                format_activity_result_secondary(
                    f"server ready · {label}",
                    kind="ok",
                ),
            )
            return

        # -- Success ----------------------------------------------------------
        if isinstance(obs, SuccessObservation):
            self._flush_pending_tool_cards()
            content = getattr(obs, "content", "")
            if content:
                self._append_history(
                    format_activity_result_secondary(content, kind="ok"),
                )
            return

        # -- Recall failure ---------------------------------------------------
        if isinstance(obs, RecallFailureObservation):
            self._flush_pending_tool_cards()
            error_msg = getattr(obs, "error_message", "")
            recall_type = getattr(obs, "recall_type", None)
            label = str(recall_type.value) if recall_type else "recall"
            if error_msg:
                self._append_history(
                    format_activity_result_secondary(
                        f"{label} failed · {error_msg}",
                        kind="err",
                    )
                )
            return

        # -- File download ----------------------------------------------------
        if isinstance(obs, FileDownloadObservation):
            self._flush_pending_tool_cards()
            path = getattr(obs, "file_path", "")
            self._append_history(
                format_activity_result_secondary(
                    f"downloaded · {path}", kind="neutral"
                ),
            )
            return

        # -- Delegation result ------------------------------------------------
        if isinstance(obs, DelegateTaskObservation):
            self._stop_reasoning()
            pending = self._take_pending_activity_card("delegate")  # type: ignore
            result_message, result_kind, extra_lines = _summarize_delegate_observation(  # type: ignore
                obs
            )
            if pending is not None:
                self._render_pending_activity_card(
                    pending,  # type: ignore
                    result_message=result_message,
                    result_kind=result_kind,
                    extra_lines=extra_lines,
                )
            else:
                if result_message is not None:
                    self._append_history(
                        format_activity_result_secondary(
                            result_message,
                            kind=result_kind,
                        ),
                    )
                for line in extra_lines:
                    self._append_history(line)
            return

        # -- Task tracking result ---------------------------------------------
        if isinstance(obs, TaskTrackingObservation):
            task_list = getattr(obs, "task_list", None)
            cmd = getattr(obs, "command", "")
            if task_list is not None and cmd == "update":
                self._set_task_panel(task_list)
            content = _sanitize_visible_transcript_text(
                strip_tool_result_validation_annotations(
                    (getattr(obs, "content", None) or "").strip()
                )
            )
            body = ""
            if task_list is None or cmd != "update":
                body = content
            if body:
                for line in body.splitlines():  # type: ignore
                    self._append_history(
                        format_activity_result_secondary(line, kind="neutral")  # type: ignore
                    )
            self.refresh()
            return

        # -- Context condensation result --------------------------------------
        if isinstance(obs, AgentCondensationObservation):
            return

        # -- Progress signal --------------------------------------------------
        if isinstance(obs, SignalProgressObservation):
            note = getattr(obs, "progress_note", "")
            if note:
                self._ensure_reasoning()
                self._reasoning.update_action(note)
            return

        self.refresh()

    # -- state transitions -------------------------------------------------

    def _handle_state_change(self, obs: AgentStateChangedObservation) -> None:
        state = obs.agent_state
        if isinstance(state, str):
            try:
                state = AgentState(state)
            except ValueError:
                logger.debug("Ignoring unknown agent state: %s", state)
                return
        previous_state = self._current_state
        self._current_state = state
        # Signal waiters on the main event loop (asyncio.Event is not thread-safe).
        try:
            self._loop.call_soon_threadsafe(self._state_event.set)
        except RuntimeError:
            pass

        # Update HUD ledger indicator on terminal states.
        if state in (AgentState.ERROR, AgentState.REJECTED):
            self._hud.update_ledger("Error")
            self._hud.update_agent_state("Needs attention")
        elif state == AgentState.AWAITING_USER_CONFIRMATION:
            self._hud.update_ledger("Review")
            self._hud.update_agent_state("Needs approval")
        elif state == AgentState.AWAITING_USER_INPUT:
            self._hud.update_ledger("Ready")
            self._hud.update_agent_state("Ready")
        elif state == AgentState.RATE_LIMITED:
            self._hud.update_ledger("Backoff")
            current_label = (self._hud.state.agent_state_label or "").strip()
            if not current_label.startswith(("Auto Retry", "Retrying")):
                self._hud.update_agent_state("Waiting on recovery")
        elif state == AgentState.PAUSED:
            # PAUSED is treated as STOPPED in CLI — collapse to same UX
            state = AgentState.STOPPED
            self._current_state = state
            self._hud.update_ledger("Idle")
            self._hud.update_agent_state("Stopped")
        elif state in (AgentState.FINISHED, AgentState.STOPPED):
            self._hud.update_ledger("Idle")
            label = "Done" if state == AgentState.FINISHED else "Stopped"
            self._hud.update_agent_state(label)
        elif state == AgentState.RUNNING:
            self._hud.update_ledger("Healthy")
            self._hud.update_agent_state("Running")

        if state == AgentState.AWAITING_USER_CONFIRMATION:
            self._flush_pending_tool_cards()
            self._stop_reasoning()
            self._clear_streaming_preview()
            if previous_state != state:
                self._append_history(
                    Text(
                        "  approval required — review the pending action.",
                        style="yellow",
                    )
                )
            self.refresh()
            return

        if state == AgentState.AWAITING_USER_INPUT:
            self._flush_pending_tool_cards()
            self._stop_reasoning()
            self._clear_streaming_preview()
            self.refresh()
            return

        if state == AgentState.FINISHED:
            self._flush_pending_tool_cards()
            self._stop_reasoning()
            self._clear_streaming_preview()
            return

        if state == AgentState.ERROR:
            self._flush_pending_tool_cards()
            self._stop_reasoning()
            self._clear_streaming_preview()
            self._append_history(
                Text("  error — send a follow-up to retry.", style="red dim"),
            )
            return

        # REJECTED collapses to ERROR in CLI
        if state == AgentState.REJECTED:
            self._flush_pending_tool_cards()
            self._stop_reasoning()
            self._clear_streaming_preview()
            self._append_history(
                Text("  error — send a follow-up to retry.", style="red dim")
            )
            return

        # STOPPED (and collapsed PAUSED)
        if state == AgentState.STOPPED:
            self._stop_reasoning()
            self._clear_streaming_preview()
            return

        if state in _IDLE_STATES:
            self._stop_reasoning()

        self.refresh()

    # -- helpers -----------------------------------------------------------

    def _turn_stats_text(self) -> str:
        """Format per-turn token/cost delta as a short summary string."""
        cost_delta = self._hud.state.cost_usd - self._turn_start_cost
        tokens_delta = self._hud.state.context_tokens - self._turn_start_tokens
        calls_delta = self._hud.state.llm_calls - self._turn_start_calls
        parts: list[str] = []
        if tokens_delta > 0:
            parts.append(HUDBar._format_tokens(tokens_delta) + " tokens")
        if cost_delta > 0.0:
            parts.append(f"${cost_delta:.4f}")
        if calls_delta > 0:
            parts.append(f'{calls_delta} LLM call{"s" if calls_delta != 1 else ""}')
        return "  [" + " · ".join(parts) + "]" if parts else ""

    def _ensure_reasoning(self) -> None:
        if not self._reasoning.active:
            self._reasoning.start()

    def _append_history(self, renderable: Any) -> None:
        """Add a renderable: buffer during Live, print otherwise."""
        self._print_or_buffer(renderable)

    def _print_or_buffer(self, renderable: Any) -> None:
        """Print transcript output, or schedule above the prompt when idle with PT.

        While Rich ``Live`` is active (agent turn), print each committed line
        through the same console so it lands in normal scrollback and the Live
        region only holds streaming, reasoning, tasks, and HUD — avoiding
        terminal-height clipping.

        When a prompt_toolkit session is active (user at the input prompt), Rich
        ``console.print`` writes at the wrong cursor and corrupts the multiline
        prompt.  In that case schedule ``run_in_terminal`` so output scrolls above
        the prompt.
        """
        framed = frame_transcript_body(renderable)
        if self._live is not None:
            self._console.print(framed)
            self.refresh(force=True)
            return

        sess: Any | None = None
        if self._get_prompt_session is not None:
            try:
                sess = self._get_prompt_session()
            except Exception:
                sess = None
        app = getattr(sess, "app", None) if sess is not None else None
        if app is not None and getattr(app, "is_running", False):
            try:
                task = self._loop.create_task(self._safe_print_above_prompt(framed))

                def _log_fail(t: asyncio.Task) -> None:
                    try:
                        t.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.debug(
                            "Safe console print above prompt failed",
                            exc_info=True,
                        )

                task.add_done_callback(_log_fail)
            except RuntimeError:
                self._console.print(framed)
            return

        self._console.print(framed)

    async def _safe_print_above_prompt(self, renderable: Any) -> None:
        from prompt_toolkit.application import run_in_terminal

        def _sync_print() -> None:
            self._console.print(renderable)

        await run_in_terminal(_sync_print)

    def _append_assistant_message(
        self, display_content: str, *, attachments: list[Any] | None = None
    ) -> None:
        """Render a committed assistant message block in the transcript."""
        display_content = _sanitize_visible_transcript_text(display_content)
        if not display_content:
            return
        self._last_assistant_message_text = display_content

        # Render assistant content directly (no "Assistant" header).
        # Keep a small top spacer for readability.
        self._append_history(Text(""))
        tool_lines = try_format_message_as_tool_json(
            display_content, use_icons=self._cli_tool_icons
        )
        if tool_lines is not None:
            _icon, friendly = tool_lines
            for line in friendly.split("\n"):
                self._append_history(Text(line, style=LIVE_PANEL_ACCENT_STYLE))
        else:
            # Condense embedded search tool output or ripgrep-style match lines
            s = display_content.strip()

            # If tool JSON didn't match, check for explicit <search_results> tags
            if "<search_results>" in s:
                m = re.search(
                    r"<search_results>\s*(?P<payload>.*?)\s*</search_results>", s, re.S
                )
                payload = m.group("payload") if m else s
                lines = [
                    ln
                    for ln in payload.splitlines()
                    if ln.strip() and not ln.startswith("Error running ripgrep:")
                ]
                if (
                    not lines
                    or any("No matches found." in ln for ln in lines[:5])
                    or any("No matching files found" in ln for ln in lines[:5])
                ):
                    summary = "No matches found."
                else:
                    match_count = sum(
                        1 for line in lines if re.match(r"^.*:\\d+:", line)
                    ) or len(lines)
                    summary = (
                        f'Found {match_count} match{"es" if match_count != 1 else ""}.'
                    )
                self._append_history(Text(summary, style=LIVE_PANEL_ACCENT_STYLE))
            else:
                # Also detect plain ripgrep-like output without XML tags and condense it
                plain_lines = [ln for ln in s.splitlines() if ln.strip()]
                if plain_lines and any(
                    re.match(r"^.*:\\d+:", ln) for ln in plain_lines[:5]
                ):
                    match_count = sum(
                        1 for line in plain_lines if re.match(r"^.*:\\d+:", line)
                    ) or len(plain_lines)
                    summary = (
                        f'Found {match_count} match{"es" if match_count != 1 else ""}.'
                    )
                    self._append_history(Text(summary, style=LIVE_PANEL_ACCENT_STYLE))
                else:
                    self._append_history(
                        Padding(Markdown(display_content), (0, 0, 1, 0))
                    )
        for attachment in attachments or []:
            self._append_history(attachment)
        self._append_history(Text(""))

    def _emit_activity_turn_header(self) -> None:
        if self._activity_turn_header_emitted:
            return
        self._activity_turn_header_emitted = True
        self._print_or_buffer(Padding(format_activity_turn_header(), pad=(0, 0, 1, 0)))

    def _print_activity(
        self,
        verb: str,
        detail: str,
        stats: str | None = None,
        *,
        shell_rail: bool = False,
        title: str | None = None,
    ) -> None:
        """Primary activity row plus optional dim stats (tool / file / shell)."""
        self._emit_activity_turn_header()  # not a duplicate
        if shell_rail:
            inner = format_activity_shell_block(
                verb,
                detail,
                secondary=stats,
                secondary_kind="neutral",
                title=title,
            )
        else:
            inner = format_activity_block(
                verb, detail, secondary=stats, secondary_kind="neutral", title=title
            )
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))

    def _buffer_pending_activity(
        self,
        *,
        title: str,
        verb: str,
        detail: str,
        secondary: str | None = None,
        kind: str = "generic",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._flush_pending_activity_card()
        self._pending_activity_card = PendingActivityCard(
            title=title,
            verb=verb,
            detail=detail,
            secondary=secondary,
            kind=kind,
            payload=payload or {},
        )

    def _take_pending_activity_card(
        self, *expected_kinds: str
    ) -> PendingActivityCard | None:
        pending = self._pending_activity_card
        if pending is None:
            return None
        if expected_kinds and pending.kind not in expected_kinds:
            return None
        self._pending_activity_card = None
        return pending

    def _render_pending_activity_card(
        self,
        pending: PendingActivityCard,
        *,
        result_message: str | None = None,
        result_kind: str = "neutral",
        extra_lines: list[Any] | None = None,
    ) -> None:
        self._emit_activity_turn_header()
        inner = format_activity_block(
            pending.verb,
            pending.detail,
            secondary=pending.secondary,
            secondary_kind="neutral",
            result_message=result_message,
            result_kind=result_kind,
            extra_lines=extra_lines,
            title=pending.title,
        )
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))

    def _flush_pending_activity_card(self) -> None:
        pending = self._pending_activity_card
        if pending is None:
            return
        self._pending_activity_card = None
        self._render_pending_activity_card(pending)

    def _flush_pending_tool_cards(self) -> None:
        self._flush_pending_activity_card()
        self._flush_pending_shell_action()

    def _flush_pending_shell_action(self) -> None:
        """Print buffered command card without a result (fallback for orphaned CmdRunActions)."""
        if self._pending_shell_action is None:
            return
        verb, label = self._pending_shell_action
        title = self._pending_shell_title
        is_internal = self._pending_shell_is_internal
        self._pending_shell_action = None
        self._pending_shell_command = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False
        self._emit_activity_turn_header()  # not a duplicate
        if is_internal:
            inner = format_activity_block(
                verb, label, title=title or ACTIVITY_CARD_TITLE_SHELL
            )
        else:
            inner = format_activity_shell_block(verb, label)
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))

    def _print_tool_call(self, label: str) -> None:
        """Emit one legacy ground-truth tool row (``> label``)."""
        self._emit_activity_turn_header()
        self._print_or_buffer(
            Padding(
                format_ground_truth_tool_line(label),
                pad=ACTIVITY_BLOCK_BOTTOM_PAD,
            )
        )

    def _apply_reasoning_text(self, text: str) -> None:
        """Update the reasoning display while keeping tagged tool payloads out of the transcript."""
        action_label, thought = _normalize_reasoning_text(text)
        if action_label is None and thought is None:
            return
        self._ensure_reasoning()
        if action_label:
            self._reasoning.update_action(action_label)
        if thought and _show_reasoning_text():
            self._reasoning.update_thought(thought)

    def _set_task_panel(self, task_list: list[dict[str, Any]]) -> None:
        """Replace the visible task tracker panel with the latest known state."""
        self._task_panel = _build_task_panel(task_list)
        self._task_panel_signature = _task_panel_signature(task_list)
        if (
            self._live is None
            and self._task_panel_signature != self._last_printed_task_panel_signature
        ):
            self._print_or_buffer(self._task_panel)
            self._last_printed_task_panel_signature = self._task_panel_signature

    def _set_delegate_panel(self) -> None:
        """Replace the visible delegated-worker panel with the latest known state."""
        self._delegate_panel = _build_delegate_worker_panel(self._delegate_workers)
        self._delegate_panel_signature = _delegate_worker_panel_signature(
            self._delegate_workers
        )
        if (
            self._live is None
            and self._delegate_panel_signature
            != self._last_printed_delegate_panel_signature
        ):
            self._print_or_buffer(self._delegate_panel)
            self._last_printed_delegate_panel_signature = self._delegate_panel_signature

    def _reset_delegate_panel(self, *, batch_id: int | None) -> None:
        """Start a fresh delegated-worker panel for a new delegation batch."""
        self._delegate_workers = {}
        self._delegate_batch_id = batch_id
        self._delegate_panel = None
        self._delegate_panel_signature = None
        self._last_printed_delegate_panel_signature = None

    def _flush_thinking_block(self) -> None:
        """Print accumulated thoughts as a persistent dim block before they are cleared.

        Called just before _reasoning.stop() so the thought lines are still available.
        Does nothing when no thoughts were collected this turn.
        """
        thoughts = self._reasoning.snapshot_thoughts()
        if not thoughts:
            return
        fresh = _reasoning_lines_skip_already_committed(
            self._last_committed_reasoning_lines,
            thoughts,
        )
        self._last_committed_reasoning_lines = list(thoughts)
        if not fresh:
            return
        self._print_or_buffer(format_reasoning_snapshot(fresh))

    def _stop_reasoning(self) -> None:
        """Flush any accumulated thoughts to static output, then stop the spinner.

        Always use this instead of calling _reasoning.stop() directly so that
        thoughts are never silently discarded mid-turn or at turn end.
        """
        self._flush_thinking_block()
        self._reasoning.stop()

    def _clear_streaming_preview(self) -> None:
        self._streaming_accumulated = ""
        self._streaming_final = False
        self.refresh()

    @staticmethod
    def _tail_preview_text(
        content: str, *, max_width: int | None, max_lines: int
    ) -> str:
        """Return a bottom-follow viewport of *content* constrained by wrapped lines."""
        if max_lines <= 0 or not content:
            return content

        # Account for panel padding / gutters so wrapping approximates terminal
        # width. 10 = 2 border chars + 4 padding chars (left+right) + 4-char
        # safety margin to leave room for Rich's trailing space on ANSI rows.
        wrap_width = max(20, (max_width or 120) - 10)
        wrapped: list[str] = []
        for raw in content.splitlines() or [""]:
            if not raw:
                wrapped.append("")
                continue
            wrapped.extend(
                textwrap.wrap(
                    raw,
                    width=wrap_width,
                    replace_whitespace=False,
                    drop_whitespace=False,
                )
                or [""]
            )

        if len(wrapped) <= max_lines:
            return content

        tail = wrapped[-max_lines:]
        return "\n".join(tail)

    def _render_streaming_preview(
        self,
        *,
        max_width: int | None = None,
        max_lines: int | None = None,
    ) -> Any:
        full = self._streaming_accumulated or ""
        clipped = full
        if max_lines is not None:
            clipped = self._tail_preview_text(
                full,
                max_width=max_width,
                max_lines=max_lines,
            )

        body: list[Any] = [Markdown(clipped)]
        if clipped != full:
            body.append(
                Text(
                    "Tail preview — full reply will appear in chat when streaming finishes",
                    style="dim italic",
                )
            )
        if not self._streaming_final:
            body.append(Text("Still streaming…", style="dim"))
        return format_callout_panel(
            "Draft Reply",
            Group(*body),
            accent_style=DRAFT_PANEL_ACCENT_STYLE,
            padding=ACTIVITY_PANEL_PADDING,
        )

    @staticmethod
    def _format_command_display(command: str, *, limit: int = 96) -> str:
        display = " ".join(command.split())
        if not display:
            return "(empty command)"
        if len(display) > limit:
            return display[: limit - 1] + "…"
        return display

    def _update_metrics(self, event: Any) -> None:
        llm_metrics = getattr(event, "llm_metrics", None)
        if llm_metrics is not None:
            self._hud.update_from_llm_metrics(llm_metrics)
            self._reasoning.update_cost(self._hud.state.cost_usd)
            self._check_budget()

    def _check_budget(self) -> None:
        if not self._max_budget or self._max_budget <= 0:
            return
        cost = self._hud.state.cost_usd
        if cost >= self._max_budget and not self._budget_warned_100:
            self._budget_warned_100 = True
            self._print_or_buffer(
                Panel(
                    Text(
                        f"Budget limit reached: ${cost:.4f} / ${self._max_budget:.4f}",
                        style="red bold",
                    ),
                    title="[red bold]Budget Exceeded[/red bold]",
                    border_style="red",
                    padding=(1, 2),
                )
            )
        elif cost >= self._max_budget * 0.8 and not self._budget_warned_80:
            self._budget_warned_80 = True
            self._print_or_buffer(
                Panel(
                    Text(
                        f"Approaching budget: ${cost:.4f} / ${self._max_budget:.4f} (80%)",
                        style="yellow",
                    ),
                    title="[yellow]Budget Warning[/yellow]",
                    border_style="yellow",
                    padding=(1, 2),
                )
            )
