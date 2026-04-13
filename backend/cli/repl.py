"""Async REPL — prompt_toolkit input loop integrated with the agent engine."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, cast

from rich.console import Console

from backend.cli.config_manager import get_current_model
from backend.cli.confirmation import build_confirmation_action, render_confirmation
from backend.cli.event_renderer import CLIEventRenderer
from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.settings_tui import open_settings
from backend.core.config import AppConfig, load_app_config
from backend.core.enums import AgentState, EventSource
from backend.ledger.action import MessageAction

logger = logging.getLogger(__name__)

if TYPE_CHECKING:

    from backend.ledger.stream import EventStream


def _prompt_toolkit_available() -> bool:
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# History file
# ---------------------------------------------------------------------------
_HISTORY_DIR = Path.home() / ".grinta"
_HISTORY_FILE = _HISTORY_DIR / "history.txt"


@dataclass(frozen=True)
class SlashCommandSpec:
    """Metadata used by help text and prompt-toolkit completion."""

    name: str
    description: str
    usage: str
    aliases: tuple[str, ...] = ()
    #: Grouping key for `/help` (see `_HELP_SECTIONS_ORDER`).
    help_section: str = "system"


_AUTONOMY_LEVEL_HINTS = {
    "supervised": "Always ask before actions",
    "balanced": "Ask only for high-risk actions",
    "full": "Run without confirmation prompts",
}
_SLASH_COMMANDS = (
    SlashCommandSpec(
        "/help",
        "Show commands and shortcuts",
        "/help",
        aliases=("/?",),
        help_section="system",
    ),
    SlashCommandSpec(
        "/settings",
        "Open settings (model, API key, MCP)",
        "/settings",
        help_section="model",
    ),
    SlashCommandSpec(
        "/sessions", "List past sessions", "/sessions", help_section="session"
    ),
    SlashCommandSpec(
        "/resume",
        "Resume a past session by index or ID",
        "/resume <N|id>",
        help_section="session",
    ),
    SlashCommandSpec(
        "/autonomy",
        "View or set autonomy (supervised/balanced/full)",
        "/autonomy [supervised|balanced|full]",
        help_section="model",
    ),
    SlashCommandSpec(
        "/model",
        "Show or switch the active model",
        "/model [provider/model]",
        help_section="model",
    ),
    SlashCommandSpec(
        "/compact",
        "Condense context to free token budget",
        "/compact",
        help_section="control",
    ),
    SlashCommandSpec(
        "/retry", "Re-send the last message", "/retry", help_section="control"
    ),
    SlashCommandSpec(
        "/status", "Show the current HUD snapshot", "/status", help_section="control"
    ),
    SlashCommandSpec(
        "/clear", "Clear the visible transcript", "/clear", help_section="control"
    ),
    SlashCommandSpec(
        "/exit", "Quit grinta", "/exit", aliases=("/quit",), help_section="system"
    ),
)

# Known models surfaced in `/model` tab-completion.
# provider/model pairs — provider shown as display_meta in the completer.
_KNOWN_MODELS: tuple[tuple[str, str], ...] = (
    ("openai/gpt-4.1", "OpenAI"),
    ("openai/gpt-4o", "OpenAI"),
    ("openai/o4-mini", "OpenAI"),
    ("anthropic/claude-opus-4-20250514", "Anthropic"),
    ("anthropic/claude-sonnet-4-20250514", "Anthropic"),
    ("anthropic/claude-haiku-4-20250514", "Anthropic"),
    ("google/gemini-2.5-pro", "Google"),
    ("google/gemini-2.5-flash", "Google"),
    ("groq/meta-llama/llama-4-scout", "Groq"),
    ("xai/grok-4.1-fast", "xAI"),
    ("deepseek/deepseek-chat", "DeepSeek"),
    ("openrouter/anthropic/claude-3.5-sonnet", "OpenRouter"),
)
_COMMAND_ALIASES = {
    alias: spec.name for spec in _SLASH_COMMANDS for alias in spec.aliases
}
_COMMAND_NAMES = tuple(
    name for spec in _SLASH_COMMANDS for name in (spec.name, *spec.aliases)
)


def _ensure_history() -> Path:
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if not _HISTORY_FILE.exists():
        _HISTORY_FILE.touch()
    return _HISTORY_FILE


def _canonical_command_name(command: str) -> str:
    """Normalize slash-command aliases to a single canonical name."""
    lowered = command.lower()
    return _COMMAND_ALIASES.get(lowered, lowered)


def _iter_command_completion_entries() -> list[tuple[str, str]]:
    """Return slash commands plus aliases for prompt-toolkit completion."""
    entries: list[tuple[str, str]] = []
    for spec in _SLASH_COMMANDS:
        entries.append((spec.name, spec.description))
        entries.extend((alias, f"Alias for {spec.name}") for alias in spec.aliases)
    return entries


_HELP_SECTIONS_ORDER: tuple[tuple[str, str], ...] = (
    ("session", "Session & history"),
    ("model", "Model & configuration"),
    ("control", "Context & control"),
    ("system", "System"),
)


def _build_help_markdown() -> str:
    """Build the slash-command help block from the shared command registry."""
    from collections import defaultdict

    by_section: dict[str, list[SlashCommandSpec]] = defaultdict(list)
    for spec in _SLASH_COMMANDS:
        by_section[spec.help_section].append(spec)

    lines: list[str] = []
    first_section = True
    for section_key, title in _HELP_SECTIONS_ORDER:
        specs = by_section.get(section_key)
        if not specs:
            continue
        if not first_section:
            lines.append("")
        first_section = False
        lines.append(f"**{title}**")
        lines.append("")
        for spec in specs:
            alias_text = (
                " _(aliases: "
                + ", ".join(f"`{alias}`" for alias in spec.aliases)
                + ")_"
                if spec.aliases
                else ""
            )
            lines.append(f"- `{spec.usage}` — {spec.description}{alias_text}")

    lines.extend(
        [
            "",
            "**Input tips**",
            "",
            "- `Tab` autocomplete slash commands and common arguments",
            "- `↑` / `↓` search prompt history",
            "- `Alt+Enter` insert a newline",
            "- `Ctrl+C` interrupt the current run",
        ]
    )
    return "\n".join(lines)


def _closest_command_names(command: str, *, limit: int = 2) -> list[str]:
    """Suggest the closest matching slash commands for typos."""
    matches = get_close_matches(command, _COMMAND_NAMES, n=limit, cutoff=0.5)
    suggestions: list[str] = []
    for match in matches:
        if match not in suggestions:
            suggestions.append(match)
    return suggestions


def _build_command_completer(
    load_session_suggestions: Callable[[], list[tuple[str, str]]] | None = None,
) -> Any:
    """Create the prompt-toolkit completer used by the interactive REPL."""
    from prompt_toolkit.completion import Completer, Completion

    session_loader = load_session_suggestions or (lambda: [])

    class SlashCommandCompleter(Completer):
        def get_completions(self, document, complete_event):  # type: ignore[override]
            del complete_event
            text_before_cursor = document.text_before_cursor.lstrip()
            if not text_before_cursor.startswith("/"):
                return

            has_trailing_space = document.text_before_cursor.endswith(" ")
            parts = text_before_cursor.split()
            if not parts:
                return

            command_token = parts[0].lower()
            if len(parts) == 1 and not has_trailing_space:
                prefix = command_token
                for name, description in _iter_command_completion_entries():
                    if name.startswith(prefix):
                        yield Completion(
                            name,
                            start_position=-len(prefix),
                            display_meta=description,
                        )
                return

            canonical_command = _canonical_command_name(command_token)
            argument_prefix = "" if has_trailing_space or len(parts) < 2 else parts[1]

            if canonical_command == "/autonomy":
                lowered_prefix = argument_prefix.lower()
                for level, description in _AUTONOMY_LEVEL_HINTS.items():
                    if level.startswith(lowered_prefix):
                        yield Completion(
                            level,
                            start_position=-len(argument_prefix),
                            display_meta=description,
                        )
                return

            if canonical_command == "/model":
                lowered_prefix = argument_prefix.lower()
                for model_id, provider in _KNOWN_MODELS:
                    if lowered_prefix and not model_id.startswith(lowered_prefix):
                        continue
                    yield Completion(
                        model_id,
                        start_position=-len(argument_prefix),
                        display_meta=provider,
                    )
                return

            if canonical_command == "/resume":
                lowered_prefix = argument_prefix.lower()
                seen: set[str] = set()
                for candidate, description in session_loader():
                    if candidate in seen:
                        continue
                    if lowered_prefix and not candidate.lower().startswith(
                        lowered_prefix
                    ):
                        continue
                    seen.add(candidate)
                    yield Completion(
                        candidate,
                        start_position=-len(argument_prefix),
                        display_meta=description,
                    )

    return SlashCommandCompleter()


# ---------------------------------------------------------------------------
# Key bindings for prompt_toolkit
# ---------------------------------------------------------------------------


def _build_bindings() -> Any:
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.keys import Keys

    kb = KeyBindings()

    @kb.add(Keys.Escape, Keys.Enter)
    def _newline(event):
        """Alt+Enter inserts a newline (multi-line input)."""
        event.current_buffer.insert_text("\n")

    return kb


def _supports_prompt_session(input_stream: Any, output_stream: Any) -> bool:
    """Use prompt_toolkit only when both streams are attached to a TTY."""
    input_is_tty = bool(getattr(input_stream, "isatty", lambda: False)())
    output_is_tty = bool(getattr(output_stream, "isatty", lambda: False)())
    return input_is_tty and output_is_tty and _prompt_toolkit_available()


# ---------------------------------------------------------------------------
# REPL class
# ---------------------------------------------------------------------------


class Repl:
    """Interactive REPL that drives an in-process agent session."""

    def __init__(self, config: AppConfig, console: Console) -> None:
        self._config = config
        self._console = console
        self._hud = HUDBar()
        self._reasoning = ReasoningDisplay()
        self._renderer: Any | None = None
        self._event_stream: EventStream | None = None
        self._controller: Any | None = None
        self._running = True
        # Bootstrap components (stored for session resume).
        self._agent: Any | None = None
        self._runtime: Any | None = None
        self._memory: Any | None = None
        self._llm_registry: Any | None = None
        self._conversation_stats: Any | None = None
        self._acquire_result: Any | None = None
        self._pending_resume: str | None = None
        self._next_action: Any | None = None
        self._last_user_message: str | None = None
        self._queued_input: list[str] = []
        #: Single-line bootstrap / idle status under the stats bar (prompt_toolkit only).
        self._footer_system_status: str = ""
        self._footer_system_kind: str = "system"
        self._pt_session: Any | None = None

    def _invalidate_pt(self) -> None:
        sess = self._pt_session
        if sess is None:
            return
        app = getattr(sess, "app", None)
        if app is not None:
            app.invalidate()

    def _set_footer_system_line(self, text: str, *, kind: str = "system") -> None:
        """One shared status line under the stats bar; replaces previous text."""
        self._footer_system_status = text
        self._footer_system_kind = kind
        self._invalidate_pt()

    def _append_footer_system_fragments(
        self,
        fragments: list[tuple[str, str]],
        add: Callable[[str, str], None],
    ) -> None:
        status = self._footer_system_status.strip()
        if not status:
            return
        warn = self._footer_system_kind.strip().lower() == "warning"
        body_cls = (
            "class:prompt.footer.warn_body" if warn else "class:prompt.footer.body"
        )
        label = "system"
        sep = ": "
        cols = shutil.get_terminal_size((110, 24)).columns
        reserve = 5 + len(label) + len(sep)
        max_w = max(16, cols - reserve)
        if len(status) > max_w:
            status = status[: max_w - 1] + "…"
        add("", "\n")
        if warn:
            add("class:prompt.footer.warn_bracket", "[")
            add("class:prompt.footer.warn_core", "!")
            add("class:prompt.footer.warn_bracket", "]  ")
            add("class:prompt.footer.warn_kicker", label)
            add("class:prompt.footer.warn_sep", sep)
        else:
            add("class:prompt.footer.badge_bracket", "[")
            add("class:prompt.footer.badge_core", "i")
            add("class:prompt.footer.badge_bracket", "]  ")
            add("class:prompt.footer.kicker", label)
            add("class:prompt.footer.sep", sep)
        add(body_cls, status)

    @property
    def pending_resume(self) -> str | None:
        return self._pending_resume

    def set_renderer(self, renderer: Any) -> None:
        self._renderer = renderer

    def set_controller(self, controller: Any) -> None:
        self._controller = controller

    def set_bootstrap_state(
        self,
        *,
        agent: Any | None = None,
        runtime: Any | None = None,
        memory: Any | None = None,
        llm_registry: Any | None = None,
        conversation_stats: Any | None = None,
        event_stream: Any | None = None,
        acquire_result: Any | None = None,
    ) -> None:
        if agent is not None:
            self._agent = agent
        if runtime is not None:
            self._runtime = runtime
        if memory is not None:
            self._memory = memory
        if llm_registry is not None:
            self._llm_registry = llm_registry
        if conversation_stats is not None:
            self._conversation_stats = conversation_stats
        if event_stream is not None:
            self._event_stream = event_stream
        if acquire_result is not None:
            self._acquire_result = acquire_result

    def queue_initial_input(self, text: str) -> None:
        if text:
            self._queued_input.append(text)

    def _current_prompt_state(self) -> AgentState | None:
        renderer = self._renderer
        state = (
            getattr(renderer, "current_state", None) if renderer is not None else None
        )
        if isinstance(state, AgentState):
            return state

        controller = self._controller
        if controller is not None:
            with contextlib.suppress(Exception):
                candidate = controller.get_agent_state()
                if isinstance(candidate, AgentState):
                    return candidate
        return None

    def _prompt_message(self) -> str:
        state = self._current_prompt_state()
        if state in {AgentState.ERROR, AgentState.REJECTED}:
            label = "retry "
        else:
            label = ""
        return f"{label}❯ "

    def _prompt_placeholder(self) -> Any:
        from prompt_toolkit.formatted_text import HTML

        return HTML(
            '<style fg="#5d7286"><i>Describe the task, or type /help</i></style>'
        )

    def _prompt_state_label(self) -> str:
        state = self._current_prompt_state()
        if state == AgentState.AWAITING_USER_CONFIRMATION:
            return "Needs approval"
        if state in {AgentState.ERROR, AgentState.REJECTED}:
            return "Needs attention"
        if state == AgentState.RUNNING:
            return "Running"
        if state == AgentState.FINISHED:
            return "Done"
        if state == AgentState.STOPPED:
            return "Stopped"
        return "Ready"

    def _prompt_autonomy_label(self) -> str:
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, "autonomy_controller", None)
            if ac is not None:
                level = str(getattr(ac, "autonomy_level", "balanced")).strip().lower()
                if level in _AUTONOMY_LEVEL_HINTS:
                    return f"autonomy:{level}"
        return "autonomy:balanced"

    def _prompt_panel_data(self) -> dict[str, str]:
        hud = self._hud.state
        provider, model = HUDBar.describe_model(hud.model)
        tokens = (
            HUDBar._format_tokens(hud.context_tokens) if hud.context_tokens > 0 else "0"
        )
        lim = HUDBar._format_tokens(hud.context_limit) if hud.context_limit else "?"
        if hud.context_tokens == 0 and hud.context_limit == 0:
            token_display = "0 tokens"
        elif hud.context_limit == 0:
            token_display = f"{tokens} tokens"
        else:
            token_display = f"{tokens}/{lim}"
        mcp_txt = HUDBar._format_mcp_servers_label(hud.mcp_servers)
        skills_txt = HUDBar._format_skills_label(self._hud.bundled_skill_count)
        return {
            "state_label": self._prompt_state_label(),
            "autonomy_label": self._prompt_autonomy_label(),
            "provider": provider,
            "model": model,
            "token_display": token_display,
            "cost": f"${hud.cost_usd:.4f}",
            "calls": f"{hud.llm_calls} calls",
            "mcp": mcp_txt,
            "skills": skills_txt,
            "ledger": hud.ledger_status,
        }

    def _prompt_state_style(self) -> str:
        state = self._current_prompt_state()
        if state == AgentState.AWAITING_USER_CONFIRMATION:
            return "class:prompt.badge.review"
        if state in {AgentState.ERROR, AgentState.REJECTED}:
            return "class:prompt.badge.error"
        if state == AgentState.RUNNING:
            return "class:prompt.badge.running"
        return "class:prompt.badge.ready"

    def _prompt_autonomy_style(self) -> str:
        label = self._prompt_autonomy_label()
        if "full" in label:
            return "class:prompt.autonomy.full"
        if "supervised" in label:
            return "class:prompt.autonomy.supervised"
        return "class:prompt.autonomy.balanced"

    @staticmethod
    def _prompt_ledger_style(ledger_status: str) -> str:
        if ledger_status in {"Healthy", "Ready", "Idle", "Starting"}:
            return "class:prompt.health.good"
        if ledger_status in {"Review", "Paused"}:
            return "class:prompt.health.warn"
        return "class:prompt.health.bad"

    def _prompt_toolbar_text(self) -> str:
        data = self._prompt_panel_data()
        state_label = data["state_label"]
        autonomy_label = data["autonomy_label"]
        controls = f"{state_label}  │  {autonomy_label}  │  Tab for commands"
        telemetry = (
            f"provider: {data['provider']}  │  model: {data['model']}  │  {data['token_display']}  │  {data['cost']}  │  "
            f"{data['calls']}  │  {data['mcp']}  │  {data['skills']}  │  {data['ledger']}"
        )
        return f" {controls}\n {telemetry} "

    def _prompt_stats_row1_fragments(
        self, data: dict[str, str], compact: bool
    ) -> list[tuple[str, str]]:
        frags: list[tuple[str, str]] = []
        frags.append(("class:prompt.brand", "GRINTA"))
        frags.append(("class:prompt.dim", "  "))
        frags.append((self._prompt_state_style(), f" {data['state_label'].upper()} "))
        frags.append(("class:prompt.dim", "  "))
        frags.append((self._prompt_autonomy_style(), data["autonomy_label"]))
        if not compact:
            frags.append(("class:prompt.dim", "  "))
            frags.append(("class:prompt.hint", "Tab for commands"))
        return frags

    def _prompt_stats_row2_fragments(
        self, data: dict[str, str], compact: bool, width: int = 120
    ) -> list[tuple[str, str]]:
        """Build row-2 fragments, wrapping to a second line when content exceeds width."""
        sep = "  \u2022  "

        # Required prefix: provider + model + tokens + cost
        base: list[tuple[str, str]] = [
            ("class:prompt.dim", "provider:"),
            ("class:prompt.sep", " "),
            ("class:prompt.model", data["provider"]),
            ("class:prompt.sep", sep),
            ("class:prompt.dim", "model:"),
            ("class:prompt.sep", " "),
            ("class:prompt.model", data["model"]),
            ("class:prompt.sep", sep),
            ("class:prompt.value", data["token_display"]),
            ("class:prompt.sep", sep),
            ("class:prompt.value", data["cost"]),
        ]

        # Optional fields in priority order.
        optionals: list[tuple[str, str]] = [
            (self._prompt_ledger_style(data["ledger"]), data["ledger"]),
            ("class:prompt.value", data["calls"]),
            ("class:prompt.value", data["mcp"]),
            ("class:prompt.value", data["skills"]),
        ]

        def _len(frags: list[tuple[str, str]]) -> int:
            return sum(len(t) for _, t in frags)

        # Build the full single-line version first.
        opt_frags: list[tuple[str, str]] = []
        for item_style, item_text in optionals:
            opt_frags.extend([("class:prompt.sep", sep), (item_style, item_text)])

        all_frags = list(base) + opt_frags
        if _len(all_frags) <= width:
            return all_frags

        # Overflow → wrap: required fields on line 1, optionals on line 2.
        result = list(base)
        result.append(("", "\n"))
        indent = " " * 10  # width of "provider: " to align the wrapped row
        result.append(("class:prompt.dim", indent))
        for idx, (item_style, item_text) in enumerate(optionals):
            if idx > 0:
                result.append(("class:prompt.sep", sep))
            result.append((item_style, item_text))

        return result

    def _prompt_bottom_toolbar(self) -> Any:
        """Two-line status under the input; no filled backgrounds (terminal default)."""
        width = shutil.get_terminal_size((110, 24)).columns
        data = self._prompt_panel_data()
        compact = width < 110

        # Keep HUD state/autonomy in sync so the Live-mode HUD matches.
        self._hud.update_agent_state(data["state_label"])
        level = data["autonomy_label"].replace("autonomy:", "")
        self._hud.update_autonomy(level)

        # Keep the compact line readable by folding provider/model into one token.
        model = (
            data["model"]
            if data["provider"] in {"(not set)", "(unknown)"}
            else f"{data['provider']}/{data['model']}"
        )

        fragments: list[tuple[str, str]] = []

        def add(style: str, text: str) -> None:
            fragments.append((style, text))

        if width < 72:
            line = (
                f"{data['state_label']} · {data['autonomy_label']} · "
                f"{model} · {data['token_display']} · {data['cost']}"
            )
            add("class:prompt.dim", line)
            self._append_footer_system_fragments(fragments, add)
            return fragments

        add("class:prompt.dim", "\u2500" * width)
        add("", "\n")
        fragments.extend(self._prompt_stats_row1_fragments(data, compact))
        add("", "\n")
        # Pass actual terminal width so row 2 never overflows.
        fragments.extend(self._prompt_stats_row2_fragments(data, compact, width=width))
        self._append_footer_system_fragments(fragments, add)
        return fragments

    def _prompt_panel_message(self) -> Any:
        return [
            ("class:prompt.arrow", self._prompt_message()),
        ]

    def _create_prompt_session(self) -> Any:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.shortcuts import CompleteStyle
        from prompt_toolkit.styles import Style

        from backend.cli.session_manager import get_session_suggestions

        prompt_style = Style.from_dict(
            {
                # Default prompt text; no bg so the terminal background shows through.
                "": "noreverse #e6eef7",
                # PT defaults bottom-toolbar to reverse — disable without adding a fill color.
                "bottom-toolbar": "noreverse",
                "bottom-toolbar.text": "noreverse",
                "prompt.border": "#4a7a9b",
                "prompt.frame.border": "bold #34d399",
                "prompt.brand": "bold #7dd3fc",
                "prompt.dim": "#5c7287",
                "prompt.model": "bold #dbe7f3",
                "prompt.value": "#b4c4d5",
                "prompt.sep": "#2f465b",
                "prompt.arrow": "bold #7dd3fc",
                "prompt.hint": "bold #f1bf63",
                "prompt.badge.ready": "#86efac bold",
                "prompt.badge.running": "#93c5fd bold",
                "prompt.badge.review": "#fcd34d bold",
                "prompt.badge.paused": "#fcd34d bold",
                "prompt.badge.error": "#fca5a5 bold",
                "prompt.autonomy.balanced": "#8bd8ff",
                "prompt.autonomy.full": "#f1bf63 bold",
                "prompt.autonomy.supervised": "#f0a3ff bold",
                "prompt.health.good": "#8fdfb1 bold",
                "prompt.health.warn": "#f1bf63 bold",
                "prompt.health.bad": "#ff9ea8 bold",
                "prompt.footer.badge_bracket": "#0e7490",
                "prompt.footer.badge_core": "bold #22d3ee",
                "prompt.footer.kicker": "bold #a5f3fc",
                "prompt.footer.sep": "#64748b",
                "prompt.footer.body": "#94a3b8",
                "prompt.footer.warn_bracket": "#a16207",
                "prompt.footer.warn_core": "bold #facc15",
                "prompt.footer.warn_kicker": "bold #fde68a",
                "prompt.footer.warn_sep": "#92400e",
                "prompt.footer.warn_body": "#fcd34d",
                "completion-menu": "bg:#0d1f30 #b8c7d8",
                "completion-menu.completion": "bg:#0d1f30 #b8c7d8",
                "completion-menu.completion.current": "bg:#1e4976 bold #ffffff",
                "completion-menu.meta": "bg:#0a1929 #5c7fa0",
                "completion-menu.meta.completion": "bg:#0a1929 #5c7fa0",
                "completion-menu.meta.completion.current": "bg:#163350 #93c5fd",
                "completion-menu.multi-column-meta": "bg:#0a1929 #5c7fa0",
                "scrollbar.background": "bg:#0d1f30",
                "scrollbar.button": "bg:#1e4976",
            }
        )

        return PromptSession(
            message=self._prompt_panel_message,
            bottom_toolbar=self._prompt_bottom_toolbar,
            history=FileHistory(str(_ensure_history())),
            key_bindings=_build_bindings(),
            completer=_build_command_completer(
                lambda: get_session_suggestions(self._config)
            ),
            auto_suggest=AutoSuggestFromHistory(),
            complete_while_typing=True,
            complete_style=CompleteStyle.MULTI_COLUMN,
            reserve_space_for_menu=8,
            enable_history_search=True,
            multiline=False,
            style=prompt_style,
            erase_when_done=True,
            placeholder=self._prompt_placeholder,
        )

    async def ensure_controller_loop(
        self,
        *,
        controller: Any,
        agent_task: asyncio.Task[Any] | None,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        agent: Any,
        runtime: Any,
        config: AppConfig,
        conversation_stats: Any,
        memory: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any] | None]:
        ensure_controller_loop = cast(Any, self._ensure_controller_loop)
        return await ensure_controller_loop(
            controller=controller,
            agent_task=agent_task,
            create_controller=create_controller,
            create_status_callback=create_status_callback,
            run_agent_until_done=run_agent_until_done,
            agent=agent,
            runtime=runtime,
            config=config,
            conversation_stats=conversation_stats,
            memory=memory,
            end_states=end_states,
        )

    async def cancel_agent(self, agent_task: asyncio.Task[Any] | None) -> None:
        await self._cancel_agent(agent_task)

    async def resume_session(
        self,
        target: str,
        config: AppConfig,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any]] | None:
        resume_session = cast(Any, self._resume_session)
        return await resume_session(
            target,
            config,
            create_controller,
            create_status_callback,
            run_agent_until_done,
            end_states,
        )

    def handle_autonomy_command(self, text: str) -> None:
        self._handle_autonomy_command(text)

    def handle_command(self, text: str) -> bool:
        return self._handle_command(text)

    async def _read_non_interactive_input(self) -> str:
        if self._queued_input:
            return self._queued_input.pop(0)
        self._console.print(">>> ", end="")
        return await asyncio.to_thread(sys.stdin.readline)

    # -- public entry point ------------------------------------------------

    async def run(self) -> None:
        """Boot the engine, subscribe to events, and loop on user input."""
        loop = asyncio.get_running_loop()
        agent_task: asyncio.Task | None = None
        bootstrap_task: asyncio.Task[None] | None = None

        # -- imports (always needed) ----------------------------------------
        from backend.core.bootstrap.agent_control_loop import run_agent_until_done
        from backend.core.bootstrap.main import (
            _create_early_status_callback,
            _initialize_session_components,
            _setup_mcp_tools,
            _setup_memory,
            _setup_runtime_for_controller,
        )
        from backend.core.bootstrap.setup import create_controller

        try:
            bootstrap_task: asyncio.Task[None] | None = None  # type: ignore
            config = self._config
            self._hud.update_model(get_current_model(config))

            # -- prompt session (fast, no I/O) --------------------------------
            session: Any | None = None
            if _supports_prompt_session(sys.stdin, sys.stdout):
                session = self._create_prompt_session()
            self._pt_session = session

            # -- renderer (no event-stream subscription yet) ------------------
            get_pt_session = (lambda: session) if session is not None else None
            self._renderer = CLIEventRenderer(
                self._console,
                self._hud,
                self._reasoning,
                loop=loop,
                max_budget=config.max_budget_per_task,
                get_prompt_session=get_pt_session,
                cli_tool_icons=config.cli_tool_icons,
            )
            renderer = self._renderer
            if renderer is None:
                raise RuntimeError("CLI renderer did not initialize.")

            # -- staged init runs in background while user sees the prompt -----
            chat_ready_done = asyncio.Event()
            engine_init_done = asyncio.Event()
            engine_init_exc: list[BaseException | None] = [None]

            def _invalidate_prompt_session() -> None:
                if session is None:
                    return
                app = getattr(session, "app", None)
                if app is not None:
                    app.invalidate()

            def _handle_bootstrap_failure(exc: BaseException) -> None:
                engine_init_exc[0] = exc
                self._set_footer_system_line("")
                exc_name = type(exc).__name__
                if "AuthenticationError" in exc_name or "api_key" in str(exc).lower():
                    renderer.add_system_message(
                        "No API key or model configured.\n"
                        "Run grinta again and complete onboarding, "
                        "or edit settings.json directly.\n"
                        f"{exc}",
                        title="error",
                    )
                else:
                    renderer.add_system_message(
                        f"Initialization failed: {exc}", title="error"
                    )
                self._running = False
                _invalidate_prompt_session()

            async def _engine_bootstrap() -> None:
                """Prepare chat first, then finish optional tool warmup in the background."""
                try:
                    try:
                        bootstrap_state = await asyncio.to_thread(
                            _initialize_session_components,
                            config,
                            None,
                        )
                        session_id = bootstrap_state[0]
                        llm_registry = bootstrap_state[1]
                        conversation_stats = bootstrap_state[2]
                        config_ = bootstrap_state[3]
                        agent = bootstrap_state[4]

                        self._agent = agent
                        self._llm_registry = llm_registry
                        self._conversation_stats = conversation_stats
                        self._config = config_
                    except Exception as exc:
                        _handle_bootstrap_failure(exc)
                        return
                    try:
                        runtime_state = await asyncio.to_thread(
                            _setup_runtime_for_controller,
                            config_,
                            llm_registry,
                            session_id,
                            True,
                            agent,
                            None,
                            inline_event_delivery=True,
                        )
                        runtime = runtime_state[0]
                        repo_directory = runtime_state[1]
                        acquire_result = runtime_state[2]

                        event_stream = runtime.event_stream
                        if event_stream is None:
                            raise RuntimeError(
                                "Runtime did not produce an event stream."
                            )

                        self._event_stream = event_stream
                        self._runtime = runtime
                        self._acquire_result = acquire_result

                        memory = await _setup_memory(
                            config_,
                            runtime,
                            session_id,
                            repo_directory,
                            None,
                            None,
                            agent,
                        )
                        self._memory = memory

                        renderer.subscribe(event_stream, event_stream.sid)
                        if agent.config.enable_mcp:
                            if session is not None:
                                self._set_footer_system_line(
                                    "Chat ready. MCP tools warming in background."
                                )
                            else:
                                renderer.add_system_message(
                                    "Chat ready. MCP tools warming in background.",
                                    title="system",
                                )
                        else:
                            self._hud.update_mcp_servers(0)
                            if session is not None:
                                self._set_footer_system_line("Ready.")
                            else:
                                renderer.add_system_message("Ready.", title="system")
                        self._hud.update_ledger("Healthy")
                        _invalidate_prompt_session()
                        chat_ready_done.set()
                    except Exception as exc:
                        _handle_bootstrap_failure(exc)
                        return

                    if not agent.config.enable_mcp:
                        return

                    try:
                        await _setup_mcp_tools(agent, runtime, memory)
                    except Exception as exc:
                        logger.warning(
                            "MCP warmup failed after chat became ready", exc_info=True
                        )
                        self._hud.update_mcp_servers(0)
                        msg = f"MCP warmup failed: {exc}"
                        if session is not None:
                            self._set_footer_system_line(msg, kind="warning")
                        else:
                            renderer.add_system_message(msg, title="warning")
                    else:
                        mcp_status = getattr(agent, "mcp_capability_status", None) or {}
                        try:
                            mcp_n = int(mcp_status.get("connected_client_count") or 0)
                        except (TypeError, ValueError):
                            mcp_n = 0
                        self._hud.update_mcp_servers(mcp_n)
                        if session is not None:
                            self._set_footer_system_line("MCP tools loaded.")
                        else:
                            renderer.add_system_message(
                                "MCP tools loaded.", title="system"
                            )
                finally:
                    chat_ready_done.set()
                    engine_init_done.set()

            # -- enter input loop ---------------------------------------------
            controller = None
            bootstrap_task = None
            end_states = [
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.ERROR,
                AgentState.STOPPED,
                AgentState.RATE_LIMITED,
            ]

            self._hud.update_ledger("Starting")
            if session is not None:
                self._set_footer_system_line("Initializing engine...")
            else:
                renderer.add_system_message("Initializing engine...", title="system")
            bootstrap_task = asyncio.create_task(
                _engine_bootstrap(), name="grinta-engine-bootstrap"
            )

            while self._running:
                try:
                    if session is None:
                        user_input = await self._read_non_interactive_input()
                        if user_input == "":
                            raise EOFError
                    else:
                        user_input = await session.prompt_async()
                except KeyboardInterrupt:
                    continue
                except EOFError:
                    self._console.print("EOF Error received in prompt loop.")
                    break
                except Exception as e:
                    self._console.print(f"CRASH: {e}")
                    import traceback

                    traceback.print_exc()
                    break

                if not self._running:
                    break  # type: ignore

                text = user_input.strip()
                if not text:
                    continue

                if text.startswith("/"):
                    parts_sl = text.strip().split()
                    if parts_sl:
                        sc = _canonical_command_name(parts_sl[0].lower())
                        if sc in ("/resume", "/compact", "/retry"):
                            await engine_init_done.wait()
                            if engine_init_exc[0] is not None:
                                continue
                    should_continue = self._handle_command(text)
                    if not should_continue:
                        break
                    if self._pending_resume is not None:
                        target = self._pending_resume
                        self._pending_resume = None
                        await self._cancel_agent(agent_task)
                        controller = None
                        agent_task = None
                        result = await self._resume_session(
                            target,
                            self._config,
                            create_controller,
                            _create_early_status_callback,
                            run_agent_until_done,
                            end_states,
                        )
                        if result is not None:
                            controller, agent_task = result
                        continue
                    if self._next_action is not None:
                        # /compact or /retry: fall through to agent dispatch below
                        pass
                    else:
                        continue

                await chat_ready_done.wait()
                if engine_init_exc[0] is not None:
                    continue

                config = self._config
                agent = self._agent
                llm_registry = self._llm_registry
                conversation_stats = self._conversation_stats
                runtime = self._runtime
                memory = self._memory
                event_stream = self._event_stream

                if (
                    agent is None
                    or llm_registry is None
                    or conversation_stats is None
                    or runtime is None
                    or memory is None
                    or event_stream is None
                ):
                    self._renderer.add_system_message(
                        "Initialization failed: engine components were not created.",
                        title="error",
                    )
                    break

                # -- user message: start Live for agent turn
                # Print the user message statically since prompt_toolkit erases it
                self._set_footer_system_line("")
                if self._next_action is not None:
                    initial_action = self._next_action
                    self._next_action = None
                    msg_content = getattr(initial_action, "content", None)
                    if msg_content is not None:
                        await self._renderer.add_user_message(str(msg_content))
                    else:
                        if self._renderer is not None:
                            self._renderer.add_system_message(
                                "Condensing context\u2026", title="grinta"
                            )
                else:
                    self._last_user_message = text
                    await self._renderer.add_user_message(text)
                    initial_action = MessageAction(content=text)
                self._renderer.start_live()
                self._renderer.begin_turn()

                controller, agent_task = await self._ensure_controller_loop(
                    controller=controller,
                    agent_task=agent_task,
                    create_controller=create_controller,
                    create_status_callback=_create_early_status_callback,
                    run_agent_until_done=run_agent_until_done,
                    agent=agent,
                    runtime=runtime,
                    config=config,
                    conversation_stats=conversation_stats,
                    memory=memory,
                    end_states=end_states,
                )

                event_stream.add_event(initial_action, EventSource.USER)
                try:
                    controller.step()
                except Exception:
                    logger.debug(
                        "controller.step() failed, agent loop will retry",
                        exc_info=True,
                    )

                try:
                    await self._wait_for_agent_idle(controller, agent_task)
                except (KeyboardInterrupt, asyncio.CancelledError):
                    await self._cancel_agent(agent_task)
                finally:
                    self._renderer.stop_live()
                    _invalidate_prompt_session()
        finally:
            self._pt_session = None
            if bootstrap_task is not None and not bootstrap_task.done():
                bootstrap_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await bootstrap_task
            controller = self._controller
            if controller is not None:
                with contextlib.suppress(Exception):
                    controller.save_state()
            self._reasoning.stop()
            if self._renderer is not None:
                self._renderer.stop_live()
            if agent_task and not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass
            if self._acquire_result is not None:
                from backend.execution import runtime_orchestrator

                runtime_orchestrator.release(self._acquire_result)
            event_stream = self._event_stream
            if event_stream is not None:
                close = getattr(event_stream, "close", None)
                if callable(close):
                    with contextlib.suppress(Exception):
                        close()

    async def _ensure_controller_loop(
        self,
        *,
        controller: Any,
        agent_task: asyncio.Task[Any] | None,
        create_controller: Any,
        create_status_callback: Any,
        run_agent_until_done: Any,
        agent: Any,
        runtime: Any,
        config: AppConfig,
        conversation_stats: Any,
        memory: Any,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any] | None]:
        if controller is None:
            controller, _ = create_controller(
                agent, runtime, config, conversation_stats
            )
            runtime.controller = controller
            early_cb = create_status_callback(controller)
            try:
                memory.status_callback = early_cb
            except Exception:
                logger.debug("Could not set memory status callback", exc_info=True)
            self._controller = controller

        current_state = controller.get_agent_state()
        if current_state in {
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.REJECTED,
            AgentState.STOPPED,
        }:
            await controller.set_agent_state_to(AgentState.RUNNING)

        if agent_task is None or agent_task.done():
            agent_task = asyncio.create_task(
                run_agent_until_done(controller, runtime, memory, end_states),
                name="grinta-agent-loop",
            )

        return controller, agent_task

    # -- wait for agent to be idle -----------------------------------------

    async def _wait_for_agent_idle(
        self, controller: Any, agent_task: asyncio.Task[Any] | None
    ) -> None:
        """Wait until agent is idle, handling confirmation prompts inline.

        Events are now processed directly in the EventStream delivery thread
        (no 3rd hop to the main loop), so the renderer state stays nearly in
        sync with the agent.  A brief yield after task completion is enough to
        let any in-flight deliveries finish.
        """
        idle_states = {
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
            AgentState.REJECTED,
            AgentState.RATE_LIMITED,  # Keep the loop attached during background retries
        }

        # Disabled by default to avoid aborting long-running sessions.
        # Set APP_AGENT_HARD_TIMEOUT_SECONDS / APP_AGENT_HARD_TIMEOUT_CMD_SECONDS
        # to a positive value to re-enable limits.
        _hard_timeout_raw = os.getenv("APP_AGENT_HARD_TIMEOUT_SECONDS", "0")
        try:
            _HARD_TIMEOUT = max(0, int(_hard_timeout_raw))
        except (ValueError, TypeError):
            _HARD_TIMEOUT = 0

        _cmd_hard_timeout_raw = os.getenv("APP_AGENT_HARD_TIMEOUT_CMD_SECONDS", "0")
        try:
            _CMD_HARD_TIMEOUT = max(0, int(_cmd_hard_timeout_raw))
        except (ValueError, TypeError):
            _CMD_HARD_TIMEOUT = 0

        # When both are enabled, command-specific timeout should never be lower.
        if _HARD_TIMEOUT > 0 and _CMD_HARD_TIMEOUT > 0:
            _CMD_HARD_TIMEOUT = max(_HARD_TIMEOUT, _CMD_HARD_TIMEOUT)
        _start = time.monotonic()

        while True:
            renderer = cast(Any, self._renderer)

            # Drain queued events and render — this is the ONLY place
            # where Live.update() happens during agent execution.
            if renderer is not None:
                renderer.drain_events()
                state = renderer.current_state or controller.get_agent_state()
            else:
                state = controller.get_agent_state()

            if state in idle_states:
                if renderer is not None:
                    await self._drain_renderer_until_settled(renderer)
                    state = renderer.current_state or controller.get_agent_state()
                if state == AgentState.AWAITING_USER_CONFIRMATION:
                    await self._handle_confirmation(controller)
                    continue
                if state not in idle_states:
                    continue
                break

            if state == AgentState.AWAITING_USER_CONFIRMATION:
                await self._handle_confirmation(controller)
                continue

            # Agent task finished — drain any remaining events, then break.
            if agent_task and agent_task.done():
                if renderer is not None:
                    await asyncio.sleep(0.05)
                    renderer.drain_events()
                break

            # Yield to the event loop.  wait_for_state_change will return
            # early when the delivery thread sets _state_event.
            if renderer is None:
                await asyncio.sleep(0.1)
            else:
                await renderer.wait_for_state_change(wait_timeout_sec=0.1)

            # Hard timeout — surface error and return to prompt instead of
            # hanging forever (e.g. LLM API unresponsive). Allow a longer
            # budget while a foreground command action is still pending.
            active_timeout = _HARD_TIMEOUT
            pending_action = getattr(controller, "_pending_action", None)
            if pending_action is not None:
                with contextlib.suppress(Exception):
                    from backend.ledger.action import CmdRunAction

                    if (
                        isinstance(pending_action, CmdRunAction)
                        and _CMD_HARD_TIMEOUT > 0
                    ):
                        active_timeout = _CMD_HARD_TIMEOUT

            if active_timeout > 0 and time.monotonic() - _start > active_timeout:
                logger.warning("Agent wait exceeded %ds hard timeout", active_timeout)
                if renderer is not None:
                    renderer.add_system_message(
                        f"Agent timed out after {active_timeout} seconds. Returning to prompt.",
                        title="⏱ Timeout",
                    )
                    renderer.drain_events()
                # Cancel the stale task so it does not linger into the next turn.
                if agent_task and not agent_task.done():
                    agent_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await agent_task
                break

    async def _drain_renderer_until_settled(
        self,
        renderer: Any,
        *,
        settle_delay: float = 0.03,
        max_passes: int = 3,
    ) -> None:
        """Drain queued CLI events until the delivery queue stays quiet briefly."""
        for _ in range(max_passes):
            renderer.drain_events()
            if getattr(renderer, "pending_event_count", 0) == 0:
                await asyncio.sleep(settle_delay)
                renderer.drain_events()
                if getattr(renderer, "pending_event_count", 0) == 0:
                    return
            else:
                await asyncio.sleep(settle_delay)

    # -- interrupt handler -------------------------------------------------

    async def _cancel_agent(self, agent_task: asyncio.Task[Any] | None) -> None:
        """Cancel a running agent task and return to the prompt."""
        if agent_task and not agent_task.done():
            agent_task.cancel()
            try:
                await agent_task
            except (asyncio.CancelledError, Exception):
                pass

        # Hard kill underlying shells/processes
        with contextlib.suppress(Exception):
            from backend.execution.action_execution_server import (
                client as runtime_client,
            )

            if runtime_client is not None:
                await runtime_client.hard_kill()

        # Stop orchestrator cleanly
        if self._controller is not None:
            with contextlib.suppress(Exception):
                await self._controller.stop()

        self._reasoning.stop()
        if self._renderer is not None:
            self._renderer.add_system_message(
                "Interrupted. Ready for input.", title="grinta"
            )

    # -- session resume ----------------------------------------------------

    async def _resume_session(
        self,
        target: str,
        config: AppConfig,
        create_controller,
        create_status_callback,
        run_agent_until_done,
        end_states: list[AgentState],
    ) -> tuple[Any, asyncio.Task[Any]] | None:
        """Resume a previous session by index or ID.

        Returns (controller, agent_task) on success, or None on failure.
        """
        from backend.cli.session_manager import get_session_id_by_index
        from backend.core.bootstrap.main import (
            _setup_memory_and_mcp,
            _setup_runtime_for_controller,
        )

        llm_registry = self._llm_registry
        agent = self._agent
        conversation_stats = self._conversation_stats
        if llm_registry is None or agent is None or conversation_stats is None:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    "Resume failed: session bootstrap state is incomplete.",
                    title="error",
                )
            return None

        # Resolve target to a session ID.
        if target.isdigit():
            resolved_id = get_session_id_by_index(int(target), config)
            if resolved_id is None:
                if self._renderer is not None:
                    self._renderer.add_system_message(
                        f"No session at index {target}.", title="warning"
                    )
                return None
        else:
            resolved_id = target

        if self._renderer is not None:
            self._renderer.add_system_message(
                f"Resuming session: {resolved_id}", title="grinta"
            )

        try:
            runtime_state = _setup_runtime_for_controller(
                config,
                llm_registry,
                resolved_id,
                True,
                agent,
                None,
                inline_event_delivery=True,
            )
            runtime = runtime_state[0]
            repo_directory = runtime_state[1]
            acquire_result = runtime_state[2]
        except Exception as exc:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    f"Resume failed: {exc}", title="error"
                )
            return None

        if self._acquire_result is not None:
            from backend.execution import runtime_orchestrator

            runtime_orchestrator.release(self._acquire_result)

        event_stream = runtime.event_stream
        if event_stream is None:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    "Resume failed: no event stream.", title="error"
                )
            return None

        self._event_stream = event_stream
        self._runtime = runtime
        self._acquire_result = acquire_result

        memory = await _setup_memory_and_mcp(
            config,
            runtime,
            resolved_id,
            repo_directory,
            None,
            None,
            agent,
        )
        self._memory = memory
        mcp_status = getattr(agent, "mcp_capability_status", None) or {}
        try:
            mcp_n = int(mcp_status.get("connected_client_count") or 0)
        except (TypeError, ValueError):
            mcp_n = 0
        self._hud.update_mcp_servers(mcp_n)

        # Subscribe renderer to the new event stream.
        if self._renderer is not None:
            renderer = cast(Any, self._renderer)
            renderer.reset_subscription()
            renderer.subscribe(event_stream, event_stream.sid)

        controller, _ = create_controller(
            agent,
            runtime,
            config,
            conversation_stats,
        )
        runtime.controller = controller
        self._controller = controller

        early_cb = create_status_callback(controller)
        try:
            memory.status_callback = early_cb
        except Exception:
            logger.debug("Could not set memory status callback", exc_info=True)

        agent_task = asyncio.create_task(
            run_agent_until_done(controller, runtime, memory, end_states),
            name="grinta-agent-loop",
        )

        if self._renderer is not None:
            self._renderer.add_system_message(
                f"Session {resolved_id} resumed. Send a message to continue.",
                title="grinta",
            )

        return controller, agent_task

    # -- confirmation handler ----------------------------------------------

    async def _handle_confirmation(self, controller) -> None:
        """Prompt user for Y/N on a pending action, then resume the engine."""
        pending = None
        try:
            pending = controller.get_pending_action()
        except Exception:
            logger.debug("get_pending_action() failed, trying fallback", exc_info=True)
            pending = getattr(controller, "_pending_action", None)

        if pending is not None:
            if self._renderer is not None:
                with self._renderer.suspend_live():
                    approved = render_confirmation(self._console, pending)
            else:
                approved = render_confirmation(self._console, pending)
        else:
            # Fallback: generic prompt if we can't get the pending action.
            from rich.prompt import Confirm

            if self._renderer is not None:
                with self._renderer.suspend_live():
                    approved = Confirm.ask(
                        "[bold yellow]The agent wants to execute an action. Approve?[/bold yellow]",
                        console=self._console,
                    )
            else:
                approved = Confirm.ask(
                    "[bold yellow]The agent wants to execute an action. Approve?[/bold yellow]",
                    console=self._console,
                )

        action = build_confirmation_action(approved)
        if self._event_stream:
            self._event_stream.add_event(action, EventSource.USER)

    # -- autonomy control --------------------------------------------------

    def _handle_autonomy_command(self, text: str) -> None:
        """View or change the autonomy level."""
        parts = text.strip().split()
        valid_levels = tuple(_AUTONOMY_LEVEL_HINTS)

        if len(parts) < 2:
            # Show current level
            level = self._get_current_autonomy()
            if self._renderer is not None:
                level_lines = "\n".join(
                    f"  {name:<10} — {_AUTONOMY_LEVEL_HINTS[name]}"
                    for name in valid_levels
                )
                self._renderer.add_system_message(
                    f"Autonomy: {level}\n"
                    f"{level_lines}\n"
                    f'Change with: /autonomy <{"|".join(valid_levels)}>',
                    title="autonomy",
                )
            return

        new_level = parts[1].lower()
        if new_level not in valid_levels:
            if self._renderer is not None:
                self._renderer.add_system_message(
                    f"Invalid level '{new_level}'. Use: {', '.join(valid_levels)}",
                    title="warning",
                )
            return

        controller = self._controller
        if controller is not None:
            ac = getattr(controller, "autonomy_controller", None)
            if ac is not None:
                ac.autonomy_level = new_level
                if self._renderer is not None:
                    self._renderer.add_system_message(
                        f"Autonomy set to: {new_level}", title="autonomy"
                    )
                return

        if self._renderer is not None:
            self._renderer.add_system_message(
                "No active controller. Send a message first to initialize, then set autonomy.",
                title="warning",
            )

    def _get_current_autonomy(self) -> str:
        controller = self._controller
        if controller is not None:
            ac = getattr(controller, "autonomy_controller", None)
            if ac is not None:
                return str(getattr(ac, "autonomy_level", "balanced"))
        return "balanced (default)"

    # -- slash commands ----------------------------------------------------

    def _handle_command(self, text: str) -> bool:
        """Handle a /command. Returns True to continue REPL, False to exit."""
        raw_cmd = text.lower().split()[0]
        cmd = _canonical_command_name(raw_cmd)

        if cmd in ("/exit", "/quit"):
            if self._renderer is not None:
                self._renderer.add_system_message("Goodbye.", title="grinta")
            return False

        if cmd == "/settings":
            if self._renderer is not None:
                with self._renderer.suspend_live():
                    open_settings(self._console)
            else:
                open_settings(self._console)
            self._config = load_app_config()
            self._hud.update_model(get_current_model(self._config))
            if self._renderer is not None:
                self._renderer.set_cli_tool_icons(self._config.cli_tool_icons)
            # Don't add_system_message — settings are navigational, not part of
            # the agentic conversation and should not appear in chat history.
            return True

        if cmd == "/clear":
            if self._renderer is not None:
                self._renderer.clear_history()
                self._renderer.add_system_message(
                    "Screen cleared. Type a task or press Tab after `/` for commands.",
                    title="grinta",
                )
            return True

        if cmd == "/status":
            if self._renderer is not None:
                self._renderer.add_system_message(
                    self._hud.plain_text(), title="status"
                )
            return True

        if cmd == "/sessions":
            from backend.cli.session_manager import list_sessions

            if self._renderer is not None:
                with self._renderer.suspend_live():
                    list_sessions(self._console, config=self._config)
            else:
                list_sessions(self._console, config=self._config)
            return True

        if cmd == "/resume":
            parts = text.strip().split()
            if len(parts) < 2:
                if self._renderer is not None:
                    self._renderer.add_system_message(
                        "Usage: /resume <N> or /resume <session_id>. Press Tab to autocomplete recent sessions.",
                        title="warning",
                    )
                return True
            self._pending_resume = parts[1]
            return True

        if cmd == "/autonomy":
            self._handle_autonomy_command(text)
            return True

        if cmd == "/help":
            if self._renderer is not None:
                self._renderer.add_markdown_block(
                    "Help",
                    _build_help_markdown(),
                )
            return True

        if cmd == "/model":
            from backend.cli.config_manager import update_model

            parts = text.strip().split(maxsplit=1)
            if len(parts) < 2:
                current = get_current_model(self._config)
                provider, model = HUDBar.describe_model(current)
                if self._renderer is not None:
                    self._renderer.add_system_message(
                        f"Current provider: {provider}  model: {model}  (use `/model <provider/model>` to switch)",
                        title="model",
                    )
            else:
                new_model = parts[1].strip()
                update_model(new_model)
                self._config = load_app_config()
                self._hud.update_model(get_current_model(self._config))
                provider, model = HUDBar.describe_model(get_current_model(self._config))
                if self._renderer is not None:
                    self._renderer.add_system_message(
                        f"Model switched to provider: {provider}  model: {model}. Changes apply to the next session.",
                        title="model",
                    )
            return True

        if cmd == "/compact":
            from backend.ledger.action.agent import CondensationRequestAction

            self._next_action = CondensationRequestAction()
            return True

        if cmd == "/retry":
            if self._last_user_message:
                self._next_action = MessageAction(content=self._last_user_message)
            else:
                if self._renderer is not None:
                    self._renderer.add_system_message(
                        "No previous message to retry.",
                        title="warning",
                    )
            return True

        if self._renderer is not None:
            suggestion_text = _closest_command_names(raw_cmd)
            suffix = ""
            if suggestion_text:
                rendered_suggestions = " or ".join(
                    f"`{item}`" for item in suggestion_text
                )
                suffix = f" Try {rendered_suggestions}."
            self._renderer.add_system_message(
                f"Unknown command: {raw_cmd}.{suffix} Press Tab after `/` for autocomplete.",
                title="warning",
            )
        return True
