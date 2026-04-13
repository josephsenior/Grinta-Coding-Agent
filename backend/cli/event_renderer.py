"""Event stream → terminal renderer.

Subscribes to the backend EventStream and translates events into rich
terminal output.  Handles all three reasoning paths (LLM reasoning,
AgentThinkAction, tool __thought), command output, file edits, errors,
and confirmation flow.
"""

from __future__ import annotations

import asyncio
import logging
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
    ACTIVITY_PANEL_PADDING,
    CALLOUT_PANEL_PADDING,
    TRANSCRIPT_RIGHT_INSET,
    frame_live_body,
    frame_transcript_body,
    gap_below_live_section,
    spacer_live_section,
)
from backend.cli.tool_call_display import (
    format_tool_activity_rows,
    looks_like_streaming_tool_arguments,
    mcp_result_user_preview,
    redact_internal_result_markers,
    redact_streamed_tool_call_markers,
    redact_task_list_json_blobs,
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
from backend.ledger import EventStreamSubscriber
from backend.ledger.action import (
    Action,
    AgentThinkAction,
    BrowseInteractiveAction,
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

# Patterns for extracting / stripping <redacted_thinking> blocks from reasoning models.
_THINK_EXTRACT_RE = re.compile(
    r"<redacted_thinking>(.*?)(?:</redacted_thinking>|$)", re.DOTALL | re.IGNORECASE
)
_THINK_STRIP_RE = re.compile(
    r"<redacted_thinking>.*?(?:</redacted_thinking>|$)", re.DOTALL | re.IGNORECASE
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
# Strip structured JSON payloads embedded in think-action thoughts.
_THINK_RESULT_JSON_RE = re.compile(
    r"\n?\[(?:CHECKPOINT_RESULT|REVERT_RESULT|ROLLBACK|TASK_TRACKER)\]" r"\s*\{.*",
    re.DOTALL,
)
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


def _sync_reasoning_after_tool_line(
    reasoning: Any,
    tool_label: str,
    thought: str,
) -> None:
    """Live panel: spinner + optional dim thinking text (``action.thought`` is LLM tags only; often empty)."""
    t = (thought or "").strip()
    if not t:
        return
    reasoning.start()
    reasoning.update_action(tool_label)
    reasoning.update_thought(t)


def _normalize_reasoning_text(text: str) -> tuple[str | None, str | None]:
    """Split internal tagged thoughts into a user-facing action label and optional short text."""
    stripped = (text or "").strip()
    if not stripped or stripped == "Your thought has been logged.":
        return None, None

    # Strip structured JSON payloads from multi-line thoughts (e.g. checkpoint results).
    stripped = _THINK_RESULT_JSON_RE.sub("", stripped).strip()
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
    if not payload:
        return label, None
    if payload.startswith("{") or payload.startswith("["):
        return label, None

    payload_lines = [line.strip() for line in payload.splitlines() if line.strip()]
    if payload_lines and all(line[:1] in '{["' for line in payload_lines[:2]):
        return label, None

    return label, payload


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
            style=f"bold {TASK_STATUS_PANEL_STYLES.get(status, 'dim')}",
        )
        badge.append("]", style="dim")

        body = Text()
        if task_id and task_id != "?":
            body.append(f"{task_id}  ", style="dim")
        body.append(desc, style="default")
        table.add_row(badge, body)

    empty_state: Any = (
        table if task_list else Text("No tracked tasks yet.", style="dim")
    )
    return format_callout_panel(
        f"Tasks ({len(task_list)})",
        empty_state,
        accent_style="dim",
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
            style=f"bold {_DELEGATE_WORKER_STATUS_STYLES.get(status, 'dim')}",
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
        table if workers else Text("No delegated workers yet.", style="dim")
    )
    return format_callout_panel(
        f"Workers ({len(workers)})",
        empty_state,
        accent_style="dim",
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

# Subscriber ID for the CLI renderer.
_SUBSCRIBER = EventStreamSubscriber.CLI


@dataclass(frozen=True)
class ErrorGuidance:
    """Actionable recovery copy for a rendered error."""

    summary: str
    steps: tuple[str, ...]


@dataclass
class PendingActivityCard:
    """Buffered non-shell activity card, paired with a later observation."""

    title: str
    verb: str
    detail: str
    secondary: str | None = None
    kind: str = "generic"
    payload: dict[str, Any] | None = None


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
    summary = lines[0].strip() or "Unknown error"
    detail = "\n".join(line.rstrip() for line in lines[1:]).strip()
    if len(detail) > 2000:
        detail = detail[:2000] + "\n... (truncated)"
    return summary, detail


def _error_guidance(error_text: str) -> ErrorGuidance | None:
    """Return actionable recovery steps for common CLI error patterns."""
    lower = error_text.lower()
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
    if _contains_any(lower, ("timeout", "timed out")):
        return ErrorGuidance(
            summary="The provider did not answer before the CLI gave up waiting.",
            steps=(
                "Check your network connection and the provider status page.",
                "Retry with a shorter request or switch to a faster model in /settings.",
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
    return None


def _build_recovery_text(guidance: ErrorGuidance) -> Text:
    """Render a guidance block for the error panel."""
    recovery = Text()
    recovery.append("What you can try\n", style="yellow bold")
    recovery.append(guidance.summary, style="yellow")
    if guidance.steps:
        recovery.append("\n", style="yellow")
    for index, step in enumerate(guidance.steps, start=1):
        recovery.append(f"{index}. {step}", style="yellow")
        if index < len(guidance.steps):
            recovery.append("\n", style="yellow")
    return recovery


def _build_error_panel(
    error_text: str,
    *,
    title: str = "Error",
    accent_style: str = "red",
) -> Panel:
    """Render a structured error panel with recovery guidance when available."""
    summary, detail = _split_error_text(error_text)
    body_parts: list[Any] = [Text(summary, style=f"{accent_style} bold")]

    guidance = _error_guidance(error_text)
    # When we have actionable guidance (recognized error type), the raw provider
    # detail is noisy and redundant — suppress it so the panel stays clean.
    if guidance is None and detail:
        body_parts.append(Text(detail, style=f"{accent_style} dim"))

    if guidance is not None:
        body_parts.append(_build_recovery_text(guidance))

    panel_title = Text(title.strip() or "Error", style=f"{accent_style} bold")
    return Panel(
        Group(*body_parts),
        title=panel_title,
        border_style=accent_style,
        padding=CALLOUT_PANEL_PADDING,
    )


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
        self._budget_warned_80 = False
        self._budget_warned_100 = False
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
            border_style="dim cyan",
            padding=(0, 0),
            style="default",
        )
        framed = frame_transcript_body(panel)
        spacer = frame_transcript_body(Text(""))
        group = Group(spacer, framed, spacer)

        if self._live is not None:
            self._console.print(group)
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
        lower_title = title.strip().lower()
        if lower_title == "error":
            self._print_or_buffer(_build_error_panel(text, title="Error"))
            self._hud.update_ledger("Error")
            return
        if "timeout" in lower_title:
            self._print_or_buffer(
                _build_error_panel(text, title=title, accent_style="yellow")
            )
            self._hud.update_ledger("Error")
            return
        if lower_title == "warning":
            tag, color = _system_message_tag(title)
            warning = Text()
            warning.append(f"{tag} ", style=f"bold {color}")
            warning.append(f"{title}: ", style=f"bold {color}")
            warning.append(text, style=color)
            self._print_or_buffer(warning)
            return

        tag, color = _system_message_tag(title)
        message = Text()
        message.append(f"{tag} ", style=f"bold {color}")
        message.append(text, style="dim" if color == "cyan" else color)
        self._print_or_buffer(message)

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
        if self._streaming_accumulated:
            stream_max_lines = None
            if options.max_height:
                # Keep the streaming preview in a viewport so Live doesn't fall
                # back to bottom ellipsis clipping when drafts get long.
                stream_max_lines = max(8, min(24, options.max_height - 10))
            live_sections.append(
                self._render_streaming_preview(
                    max_width=options.max_width,
                    max_lines=stream_max_lines,
                )
            )
        reasoning_section: Any | None = None
        if self._reasoning.active:
            reasoning_section = self._reasoning.renderable(max_width=options.max_width)
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
        input_row.add_row(
            Spinner("dots", style="bold #7dd3fc"),
            Text("Agent working… ctrl+c to interrupt", style="italic #5d7286"),
        )
        items.append(input_row)

        # -- separator (mirrors _prompt_bottom_toolbar) ---------------------
        items.append(Text("─" * width, style="#5c7287"))

        state_label = hud.agent_state_label or "Running"
        autonomy = hud.autonomy_level or "balanced"

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
            line.append(state_label, style="dim")
            line.append(" · ", style="#2f465b")
            line.append(f"autonomy:{autonomy}", style="dim")
            line.append(" · ", style="#2f465b")
            line.append(model_short, style="dim")
            line.append(" · ", style="#2f465b")
            line.append(ctx, style="dim")
            line.append(" · ", style="#2f465b")
            line.append(f"${hud.cost_usd:.4f}", style="dim")
            items.append(line)
            return Group(*items)

        # -- row 1: brand + state badge + autonomy -------------------------
        row1 = Text()
        row1.append("GRINTA", style="bold #7dd3fc")
        row1.append("  ", style="")
        _BADGE_STYLES = {
            "Running": "#93c5fd bold",
            "Ready": "#86efac bold",
            "Done": "#86efac bold",
            "Finished": "#86efac bold",
            "Needs approval": "#fcd34d bold",
            "Needs attention": "#fca5a5 bold",
            "Stopped": "#fca5a5 bold",
        }
        row1.append(
            f" {state_label.upper()} ",
            style=_BADGE_STYLES.get(state_label, "#93c5fd bold"),
        )
        row1.append("  ", style="")
        auto_style = "#8bd8ff"
        if "full" in autonomy:
            auto_style = "#f1bf63 bold"
        elif "supervised" in autonomy:
            auto_style = "#f0a3ff bold"
        row1.append(f"autonomy:{autonomy}", style=auto_style)
        items.append(row1)

        # -- row 2: model · tokens · cost · calls · MCP · skills · ledger --
        SEP = ("  \u2022  ", "#2f465b")

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

        ledger_style = "#8fdfb1 bold"
        if hud.ledger_status in {"Review", "Paused"}:
            ledger_style = "#f1bf63 bold"
        elif hud.ledger_status not in {"Healthy", "Ready", "Idle", "Starting"}:
            ledger_style = "#ff9ea8 bold"

        # Build row 2 parts and wrap to a second line if they overflow.
        parts: list[tuple[str, str]] = [
            ("provider:", "#5c7287"),
            (" ", ""),
            (provider, "bold #dbe7f3"),
            SEP,
            ("model:", "#5c7287"),
            (" ", ""),
            (model, "bold #dbe7f3"),
            SEP,
            (token_display, "#b4c4d5"),
            SEP,
            (f"${hud.cost_usd:.4f}", "#b4c4d5"),
        ]
        optional_parts: list[tuple[str, str]] = [
            (hud.ledger_status, ledger_style),
            (f"{hud.llm_calls} calls", "#b4c4d5"),
            (mcp_label, "#b4c4d5"),
            (skills_label, "#b4c4d5"),
        ]
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
            # Split into two lines: required on line 1, optionals on line 2.
            row2a = Text()
            base_len = 11  # provider: + provider + sep + model: + model + sep + tokens + sep + cost
            for content, style in parts[:base_len]:
                row2a.append(content, style=style)
            items.append(row2a)
            row2b = Text()
            row2b.append(
                "          ", style=""
            )  # indent to align under the provider label
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
            cot = (getattr(action, "thought", None) or "").strip()
            if cot:
                self._ensure_reasoning()
                self._reasoning.update_thought(cot)
            self._stop_reasoning()
            self._clear_streaming_preview()
            display_content = redact_internal_result_markers(
                redact_streamed_tool_call_markers((action.content or "").strip())
            ).strip()
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
                # Strip leading [TAG] markers to get the human message.
                tag_m = _INTERNAL_THINK_TAG_RE.match(cleaned)
                human_msg = (tag_m.group("payload") or "").strip() if tag_m else cleaned
                if source_tool == "checkpoint":
                    verb, title = "Saved", "Checkpoint"
                    # Use the tag's human message or a user-friendly default.
                    detail = human_msg or "checkpoint"
                elif source_tool == "revert_to_checkpoint":
                    verb, title = "Reverted", "Checkpoint"
                    detail = human_msg or "workspace reverted"
                else:
                    verb = source_tool.replace("_", " ").title()
                    title = "Tool"
                    detail = human_msg or source_tool
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
                self._pending_shell_title = headline or "Shell"
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
            if cmd == "view_file":
                verb, detail = "Viewed", path
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
                title="File",
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
                title="File",
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
            self._print_activity("Recalled", detail, None, title="Memory")
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
                title="File",
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
                title="MCP",
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
            self._print_activity("Opened", detail, None, title="Browser")
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
                title="Code",
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
            self._flush_pending_tool_cards()
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
            self.refresh()
            return

        if isinstance(action, TerminalInputAction):
            self._flush_pending_tool_cards()
            inp = getattr(action, "input", "")
            inp_display = inp[:60] + "…" if len(inp) > 60 else inp
            self._print_activity("Sent input", inp_display, None, title="Terminal")
            self.refresh()
            return

        # -- Delegation -------------------------------------------------------
        if isinstance(action, DelegateTaskAction):
            self._clear_streaming_preview()
            self._flush_pending_tool_cards()
            self._reset_delegate_panel(batch_id=action.id if action.id > 0 else None)
            desc_display, secondary = _summarize_delegate_action(action)
            self._buffer_pending_activity(
                title="Agent",
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
            finish_text = redact_internal_result_markers(
                (action.message or "").strip()
            ).strip()
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
                    "Need your input",
                    Group(*escalate_parts),
                    accent_style="yellow",
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
                line = Text()
                line.append(f"{i}. ", style="bold #f1bf63")
                line.append(str(opt), style="#e2e8f0")
                clarify_parts.append(line)
            if clarify_parts:
                self._append_history(
                    format_callout_panel(
                        "Question",
                        Group(*clarify_parts),
                        accent_style="yellow",
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
                line = Text()
                line.append("• ", style="dim")
                line.append(str(concern), style="dim")
                uncertainty_parts.append(line)
            if info_needed:
                uncertainty_parts.append(Text(f"Need: {info_needed}", style="yellow"))
            if uncertainty_parts:
                self._append_history(
                    format_callout_panel(
                        "Needs context",
                        Group(*uncertainty_parts),
                        accent_style="yellow",
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
                line = Text()
                line.append(f"{i + 1}. ", style="bold #a78bfa")
                line.append(
                    f"{label}{marker}",
                    style="bold #f1bf63" if i == recommended else "bold #e2e8f0",
                )
                proposal_parts.append(line)
                if desc:
                    proposal_parts.append(Text(f"   {desc}", style="dim"))
            if proposal_parts:
                self._append_history(
                    format_callout_panel(
                        "Options",
                        Group(*proposal_parts),
                        accent_style="#7c3aed",
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
            self._reasoning.update_action(f"{headline}…")
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
        if action.thinking_accumulated:
            self._ensure_reasoning()
            self._reasoning.set_streaming_thought(action.thinking_accumulated)

        # Fallback: extract <redacted_thinking> tags embedded in content text
        # (backward compat for models that embed thinking in the main stream).
        think_match = _THINK_EXTRACT_RE.search(raw)
        if think_match:
            thinking_text = think_match.group(1)
            if thinking_text.strip():
                self._ensure_reasoning()
                self._reasoning.set_streaming_thought(thinking_text)
            # Strip thinking from the streaming preview.
            display_text = _THINK_STRIP_RE.sub("", raw).strip()
            self._streaming_accumulated = redact_internal_result_markers(
                redact_task_list_json_blobs(
                    redact_streamed_tool_call_markers(display_text)
                )
            )
        else:
            self._streaming_accumulated = redact_internal_result_markers(
                redact_task_list_json_blobs(redact_streamed_tool_call_markers(raw))
            )

        self._streaming_final = action.is_final
        if action.is_final:
            self._hud.state.llm_calls += 1
        self.refresh(force=action.is_final)

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
            else:
                raw_lines = (
                    [ln.strip() for ln in content.split("\n") if ln.strip()]
                    if content
                    else []
                )
                if not raw_lines:
                    msg = "done" if exit_code == 0 else None
                else:
                    msg = raw_lines[0][:220] if len(raw_lines[0]) > 2 else "done"
                    if len(raw_lines) > 1:
                        from backend.cli.transcript import _ACTIVITY_SECONDARY_INDENT

                        extra_lines = []
                        max_preview = 12
                        for ln in raw_lines[1:max_preview]:
                            t = Text(_ACTIVITY_SECONDARY_INDENT, style="")
                            t.append(f"  {ln[:200]}", style="dim")
                            extra_lines.append(t)
                        if len(raw_lines) > max_preview:
                            t = Text(_ACTIVITY_SECONDARY_INDENT, style="")
                            t.append(
                                f"  ... and {len(raw_lines) - max_preview} more entries",
                                style="dim italic",
                            )
                            extra_lines.append(t)

                result_kind = "ok" if exit_code == 0 else "neutral"

            self._emit_activity_turn_header()  # not a duplicate
            if is_internal:
                # Internal tool — compact activity row, no raw terminal block
                inner = format_activity_block(
                    verb,
                    label,
                    secondary=msg,
                    secondary_kind=result_kind,
                    extra_lines=extra_lines,
                    title=title or "Shell",
                )
            else:
                inner = format_activity_shell_block(
                    verb,
                    label,
                    result_message=msg,
                    result_kind=result_kind,
                    extra_lines=extra_lines,
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
            error_content = getattr(obs, "content", str(obs))
            self._append_history(
                _build_error_panel(error_content),
            )
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
            self._flush_pending_tool_cards()
            if getattr(obs, "status_type", "") == "delegate_progress":
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
            content = getattr(obs, "content", "")
            if content:
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
            self._stop_reasoning()
            self._flush_pending_tool_cards()
            content = getattr(obs, "content", "")
            if content.strip():
                display = content[:2000]
                self._append_history(
                    Syntax(display, "text", word_wrap=True, theme="ansi_dark")
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
            self._stop_reasoning()
            self._flush_pending_tool_cards()
            task_list = getattr(obs, "task_list", None)
            cmd = getattr(obs, "command", "")
            if task_list is not None and cmd == "update":
                self._set_task_panel(task_list)
            content = strip_tool_result_validation_annotations(
                (getattr(obs, "content", None) or "").strip()
            )
            body = ""
            if task_list is None or cmd != "update":
                body = content
            elif content.startswith("[TASK_TRACKER]"):
                # Suppress noop "plan unchanged" messages — they add noise.
                if "Update skipped" not in content:
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
            self._hud.update_agent_state("Rate Limited")
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
        if not display_content:
            return

        # Render assistant content directly (no "Assistant" header).
        # Keep a small top spacer for readability.
        self._append_history(Text(""))
        tool_lines = try_format_message_as_tool_json(
            display_content, use_icons=self._cli_tool_icons
        )
        if tool_lines is not None:
            _icon, friendly = tool_lines
            for line in friendly.split("\n"):
                self._append_history(Text(line, style="cyan"))
        else:
            self._append_history(Padding(Markdown(display_content), (0, 0, 1, 0)))
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
                verb, detail, secondary=stats, secondary_kind="neutral"
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
            inner = format_activity_block(verb, label, title=title or "Shell")
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
        if thought:
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
        self._print_or_buffer(format_reasoning_snapshot(thoughts))

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

        # Account for panel padding / gutters so wrapping approximates terminal width.
        wrap_width = max(20, (max_width or 120) - 8)
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
            body.append(Text("auto-scroll: showing latest content", style="dim italic"))
        if not self._streaming_final:
            body.append(Text("streaming…", style="dim"))
        return format_callout_panel(
            "Draft reply",
            Group(*body),
            accent_style="dim",
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
