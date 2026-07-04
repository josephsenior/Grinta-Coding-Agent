"""Pure-Python prompt builder — replaces Jinja2 template rendering.

Each template partial is a function that returns a string.  Static
sections are loaded from .md files on disk; dynamic sections are
assembled via f-strings and simple loops.

Public API
----------
build_system_prompt(**ctx)   → full system prompt string
measure_system_prompt_sections(**ctx) → token/char breakdown (for budgeting; run ``python -m backend.engine.prompts.prompt_builder``)
build_workspace_context(...) → additional_info block
build_playbook_info(...)     → playbook block
build_knowledge_base_info(.) → knowledge-base block
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.engine.prompts.section_renderers import (
    _count_section_tokens,
    _lsp_available,
    _render_permissions,
    _render_security,
    _resolve_terminal_command_tool,
)
from backend.engine.prompts.section_renderers import (
    _render_autonomy as _render_autonomy_impl,
)
from backend.engine.prompts.section_renderers import (
    _render_critical as _render_critical_impl,
)
from backend.engine.prompts.section_renderers import (
    _render_examples as _render_examples_impl,
)
from backend.engine.prompts.section_renderers import (
    _render_interaction_tail as _render_interaction_tail_impl,
)
from backend.engine.prompts.section_renderers import (
    _render_mcp_and_permissions as _render_mcp_and_permissions_impl,
)
from backend.engine.prompts.section_renderers import (
    _render_routing as _render_routing_impl,
)
from backend.engine.prompts.section_renderers import (
    _render_system_capabilities as _render_system_capabilities_impl,
)
from backend.engine.prompts.section_renderers import (
    _render_tool_reference as _render_tool_reference_impl,
)

# Per-model capability classification (capability adaptation, not provider tuning).
# Model-class fingerprints live in ``backend.inference.capabilities.provider_capabilities``;
# adding a new model is a one-line entry there — no edits needed in this file.
from backend.inference.capabilities.provider_capabilities import (
    model_is_small as _model_is_small,
)

if TYPE_CHECKING:
    from backend.utils.prompt import (
        ConversationInstructions,
        RepositoryInfo,
        RuntimeInfo,
    )


def _provider_parallel_tool_calls_supported(model_id: str) -> bool:
    """Return True when the active model supports parallel tool_calls.

    Checks the catalog first for ``supports_parallel_tool_calls``.
    Returns False as conservative fallback if unknown.
    """
    if not model_id:
        return False
    try:
        from backend.inference.catalog.catalog_loader import lookup as _catalog_lookup

        entry = _catalog_lookup(model_id)
        if entry is not None:
            return bool(getattr(entry, 'supports_parallel_tool_calls', False))
    except Exception:
        pass

    return False


_DIR = Path(__file__).parent
_log = logging.getLogger(__name__)

# Matches {key} placeholders — but NOT {{ or }} (Python format-string escapes).
_PLACEHOLDER_RE = re.compile(r'(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})')


class PromptRenderError(ValueError):
    """Raised when a prompt template is missing required substitution keys."""


def _validate_render_keys(
    template: str,
    substitution: dict[str, Any],
    *,
    partial_name: str = '',
) -> None:
    """Verify that every ``{key}`` placeholder in *template* has a matching entry in *substitution*.

    Raises :class:`PromptRenderError` on the first missing key so callers fail
    fast instead of propagating a ``KeyError`` deep inside `str.format`.

    Extra keys in *substitution* that are not referenced by the template are
    silently ignored by `str.format` and are logged at DEBUG level only.
    """
    required = set(_PLACEHOLDER_RE.findall(template))
    provided = set(substitution)
    missing = required - provided
    if missing:
        loc = f' in {partial_name!r}' if partial_name else ''
        raise PromptRenderError(
            f'Prompt template{loc} is missing substitution keys: {sorted(missing)}'
        )
    extra = provided - required
    if extra:
        _log.debug(
            'Prompt partial %r received unused substitution keys: %s',
            partial_name,
            sorted(extra),
        )


def _render_partial(partial_name: str, **kwargs: Any) -> str:
    """Load a prompt partial, validate all placeholders are satisfied, and render."""
    template = _load(partial_name)
    _validate_render_keys(template, kwargs, partial_name=partial_name)
    return template.format(**kwargs)


def _render_routing(
    is_windows: bool,
    config: Any = None,
    function_calling_mode: str | None = None,
    *,
    windows_with_bash: bool = False,
    shell_is_powershell: bool = False,
    semantic_recall_active: bool | None = None,
) -> str:
    return _render_routing_impl(
        _render_partial,
        is_windows,
        config,
        function_calling_mode,
        windows_with_bash=windows_with_bash,
        shell_is_powershell=shell_is_powershell,
        semantic_recall_active=semantic_recall_active,
    )


def _render_autonomy(
    config: Any,
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
    semantic_recall_active: bool | None = None,
) -> str:
    return _render_autonomy_impl(
        _render_partial,
        config,
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        shell_is_powershell=shell_is_powershell,
        semantic_recall_active=semantic_recall_active,
    )


def _render_tool_reference(
    config: Any = None,
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
) -> str:
    return _render_tool_reference_impl(
        _render_partial,
        config,
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        shell_is_powershell=shell_is_powershell,
    )


def _render_critical(
    terminal_command_tool: str,
    *,
    terminal_manager_available: bool,
    tracker_on: bool,
    criteria_on: bool = True,
    checkpoints_on: bool,
    meta_cognition_on: bool,
    mode: str = 'agent',
) -> str:
    return _render_critical_impl(
        _render_partial,
        terminal_command_tool,
        terminal_manager_available=terminal_manager_available,
        tracker_on=tracker_on,
        criteria_on=criteria_on,
        checkpoints_on=checkpoints_on,
        meta_cognition_on=meta_cognition_on,
        mode=mode,
    )


def _render_examples(
    *,
    terminal_command_tool: str,
    tracker_on: bool,
    criteria_on: bool = True,
    working_memory_on: bool,
    meta_cognition_on: bool,
    lsp_available: bool,
    checkpoints_on: bool,
    web_on: bool = True,
) -> str:
    return _render_examples_impl(
        _render_partial,
        terminal_command_tool=terminal_command_tool,
        tracker_on=tracker_on,
        criteria_on=criteria_on,
        working_memory_on=working_memory_on,
        meta_cognition_on=meta_cognition_on,
        lsp_available=lsp_available,
        checkpoints_on=checkpoints_on,
        web_on=web_on,
    )


def _render_mcp_and_permissions(
    mcp_tool_names: list[str],
    mcp_tool_descriptions: dict[str, str],
    mcp_server_hints: list[dict[str, str]],
    config: Any,
) -> str:
    return _render_mcp_and_permissions_impl(
        _render_partial,
        mcp_tool_names,
        mcp_tool_descriptions,
        mcp_server_hints,
        config,
    )


def _render_interaction_tail(config: Any) -> str:
    from backend.core.interaction_modes import normalize_interaction_mode

    mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
    return _render_interaction_tail_impl(_render_partial, config, mode)


@lru_cache(maxsize=32)
def _load(name: str) -> str:
    """Read a .md partial from the prompts directory and cache it."""
    return (_DIR / name).read_text(encoding='utf-8').strip()


def _shell_identity_sections(
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
) -> list[tuple[str, str]]:
    if windows_with_bash:
        return [
            (
                'shell_identity_git_bash_windows',
                '<SHELL_IDENTITY>\n'
                'Your terminal is **Git Bash** running on Windows. Use **bash syntax exclusively**.\n'
                '- Allowed tools: `ls`, `cat`, `grep`, `find`, `echo`, `cd`, `mkdir`, `rm`, `pwd`, `which`.\n'
                '  (Prefer native tools from the **TOOL_ROUTING_LADDER** first.)\n'
                '- FORBIDDEN: `Get-ChildItem`, `Get-Process`, `Get-Content`, `Select-String`, '
                '`$PSVersionTable`, `Write-Output`, `Set-Location`, or any other PowerShell cmdlet.\n'
                '- Windows-style paths (`C:\\Users\\...`) in the working directory are normal.\n'
                '- Use `which <tool>` to check if on PATH.\n'
                '- Use `python` (not `python3`) to invoke Python.\n'
                '</SHELL_IDENTITY>',
            ),
        ]
    if shell_is_powershell:
        return [
            (
                'shell_identity_powershell_windows',
                '<SHELL_IDENTITY>\n'
                'Your terminal is **PowerShell** on Windows.\n\n'
                'Use PowerShell-native syntax:\n'
                '- chain commands with `;`\n'
                '- use `Get-ChildItem` for listing\n'
                '- use `Get-Content` for reading shell output files when necessary\n'
                '- use `Select-String` for shell-level text filtering when native search tools are not appropriate\n'
                '- use `Test-Path`, `New-Item`, `Remove-Item`, `Set-Location`\n'
                '- use `Start-Process` / `Start-Job` for background process patterns\n'
                '- use `try/catch` or `-ErrorAction` for error handling\n\n'
                'Prefer Grinta’s native tools for repo intelligence and file edits.\n'
                'Do not write source files through shell when file tools are available.\n'
                '</SHELL_IDENTITY>',
            ),
        ]
    if not is_windows:
        return [
            (
                'shell_identity_unix',
                '<SHELL_IDENTITY>\n'
                'Your terminal is **Bash / Zsh** running on a Unix-like system. Use standard bash syntax.\n'
                'You may use shell tools (grep, cat, ls, find) if needed, but prefer native tools first.\n'
                '</SHELL_IDENTITY>',
            ),
        ]
    return []


def _mcp_or_permissions_sections_for_collect(
    *,
    render_mcp_inline: bool,
    config: Any,
    mcp_tool_names: list[str] | None,
    mcp_tool_descriptions: dict[str, str] | None,
    mcp_server_hints: list[dict[str, str]] | None,
) -> list[tuple[str, str]]:
    """Return permissions guidance only.

    MCP tools are never inlined into the system prompt. When connected they are
    delivered via :func:`build_mcp_user_addendum` as a second system message.
    The ``render_mcp_inline`` flag is retained for API compatibility only.
    """
    _ = (render_mcp_inline, mcp_tool_names, mcp_tool_descriptions, mcp_server_hints)
    if getattr(config, 'enable_permissions', False):
        perm = getattr(config, 'permissions', None)
        if perm is not None:
            return [('permissions_partial', _render_permissions(config, perm))]
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _collect_system_prompt_sections(
    *,
    active_llm_model: str = '',
    is_windows: bool = False,
    windows_with_bash: bool = False,
    cli_mode: bool = False,
    config: Any = None,
    mcp_tool_names: list[str] | None = None,
    mcp_tool_descriptions: dict[str, str] | None = None,
    mcp_server_hints: list[dict[str, str]] | None = None,
    terminal_tool_name: str | None = None,
    function_calling_mode: str | None = None,
    agent_identity: str = '',
    render_mcp_inline: bool = True,
    semantic_recall_active: bool | None = None,
) -> list[tuple[str, str]]:
    """Ordered (name, body) sections before joining with blank lines.

    MCP tools are never part of the system prompt. Connected MCP catalogues are
    delivered as a second system message via :func:`build_mcp_user_addendum`
    so the system prefix stays stable when MCP servers connect or disconnect.
    """
    model_id = active_llm_model or 'unknown'
    is_small_model = _model_is_small(model_id)

    resolved_terminal_tool = _resolve_terminal_command_tool(
        is_windows=is_windows,
        terminal_tool_name=terminal_tool_name,
    )
    shell_is_powershell = resolved_terminal_tool == 'execute_powershell'
    lsp_available = _lsp_available(config)

    identity_line = (
        agent_identity.strip()
        if agent_identity.strip()
        else 'You are Grinta, a careful Autonomous software engineer built by Youssef Mejdi.'
    )
    sections: list[tuple[str, str]] = [
        (
            'identity_header',
            f'{identity_line} '
            'Use clear engineering judgment, methodical reasoning, and tool execution to help with technical work.\n\n'
            '**Model identity:** The deployment calls you through an API using the configured '
            'model id below.\n'
            f'Configured model id: `{model_id}`\n\n'
            '<OPERATING_CONTRACT>\n'
            '- Write production-quality code by default.\n'
            '- State your approach before implementing.\n'
            '- Calibrate confidence to evidence . Be decisive when tool observations are sufficient; state uncertainty when something is unverified.\n'
            '- Keep scope anchored to the latest user request. You may act on adjacent issues that are clearly required for the requested change to be correct (for example, a bug in a helper you touched, or a broken call site your edit created).\n'
            '- Stop at the request boundary for pure style, refactors, or unrelated investigations — note them in the final summary instead of acting on them.\n'
            '- When the requested change is implemented and verification appropriate to the change is done, stop and give the final summary. If verification cannot run, state exactly why and stop.\n'
            '- Before final, silently check: latest request answered, no required work remains, verification status is clear, and no stale todo/in_progress task is left behind.\n'
            '</OPERATING_CONTRACT>',
        ),
    ]
    from backend.core.interaction_modes import (
        is_chat_mode,
        is_plan_mode,
        normalize_interaction_mode,
    )

    mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
    web_on = bool(getattr(config, 'enable_web', True))
    docs_on = bool(getattr(config, 'enable_docs', True))
    external_discovery_parts: list[str] = []
    if web_on:
        external_discovery_parts.append('`web_search` / `web_fetch`')
    if docs_on:
        external_discovery_parts.append('`docs_resolve` / `docs_query`')
    external_discovery_hint = (
        f' (including {" and ".join(external_discovery_parts)} when external context helps)'
        if external_discovery_parts
        else ''
    )
    if is_plan_mode(mode):
        plan_tools_line = (
            'Scope with `acceptance_criteria` and `task_tracker` — see `<ACCEPTANCE_CRITERIA>` and `<COMMON_PATTERNS>`. '
            'Do not audit in Plan mode (no executable evidence yet).\n'
            if bool(getattr(config, 'enable_acceptance_criteria_tool', True))
            and bool(getattr(config, 'enable_task_tracker_tool', True))
            else (
                'Scope with `acceptance_criteria` — see `<ACCEPTANCE_CRITERIA>`. '
                'Do not audit in Plan mode.\n'
                if bool(getattr(config, 'enable_acceptance_criteria_tool', True))
                else (
                    'Use `task_tracker` for a coarse plan — see `<TASK_TRACKING>`.\n'
                    if bool(getattr(config, 'enable_task_tracker_tool', True))
                    else ''
                )
            )
        )
        sections.append(
            (
                'simplified_plan_protocol',
                f'You are in Plan mode. Use discovery tools{external_discovery_hint} '
                'to inspect the codebase.\n\n'
                f'{plan_tools_line}'
                'Do **not** edit files or run shell commands in Plan mode.\n\n'
                'When you need input from the user to continue, see `<ASK_USER_TOOL>`.\n\n'
                'When planning is complete, write the plan as your final response. '
                'Plain text ends the run — no completion tool is required.',
            )
        )
    elif is_chat_mode(mode):
        sections.append(
            (
                'simplified_chat_protocol',
                f'You are in Chat mode. Use discovery tools{external_discovery_hint} '
                'to investigate when grounding helps.\n\n'
                'Do **not** edit files or run shell commands in Chat mode.\n\n'
                'When you need input from the user to continue, see `<ASK_USER_TOOL>`.\n\n'
                'Respond naturally in prose. Plain text ends the turn unless you used `ask_user`.',
            )
        )
    else:
        sections.append(
            (
                'simplified_agent_protocol',
                'Drive the request through your tools.\n\n'
                'When you need input from the user to continue, see `<ASK_USER_TOOL>`.\n\n'
                'When your work is complete, write a comprehensive final summary covering:\n'
                '- What you did\n'
                '- What changed\n'
                '- Verification run and result, or the concrete blocker if verification could not run\n'
                '- Any important notes or caveats for the user\n'
                '- Next steps for the user\n\n'
                'Writing that summary ends the run. You do not need to call any special tool to signal completion. Your final response IS the completion.',
            )
        )
    sections.extend(
        _shell_identity_sections(
            is_windows=is_windows,
            windows_with_bash=windows_with_bash,
            shell_is_powershell=shell_is_powershell,
        )
    )

    sections += [
        (
            'system_partial_00_routing',
            _render_routing(
                is_windows,
                config,
                function_calling_mode,
                windows_with_bash=windows_with_bash,
                shell_is_powershell=shell_is_powershell,
                semantic_recall_active=semantic_recall_active,
            ),
        ),
        (
            'security_risk_policy',
            _render_security(
                cli_mode,
                enable_web=web_on,
                enable_docs=docs_on,
                autonomy_level=getattr(config, 'autonomy_level', 'balanced'),
            ),
        ),
        (
            'system_partial_01_autonomy',
            _render_autonomy(
                config,
                is_windows=is_windows,
                windows_with_bash=windows_with_bash,
                shell_is_powershell=shell_is_powershell,
                semantic_recall_active=semantic_recall_active,
            ),
        ),
        (
            'system_partial_02_tools',
            _render_tool_reference(
                config,
                is_windows=is_windows,
                windows_with_bash=windows_with_bash,
                shell_is_powershell=shell_is_powershell,
            ),
        ),
        (
            'system_partial_03_capabilities',
            _render_system_capabilities_impl(
                config,
                function_calling_mode=function_calling_mode,
                parallel_tool_calls_provider_flag=_provider_parallel_tool_calls_supported(
                    model_id
                ),
                mode=mode,
                semantic_recall_active=semantic_recall_active,
            ),
        ),
    ]

    sections.extend(
        _mcp_or_permissions_sections_for_collect(
            render_mcp_inline=render_mcp_inline,
            config=config,
            mcp_tool_names=mcp_tool_names,
            mcp_tool_descriptions=mcp_tool_descriptions,
            mcp_server_hints=mcp_server_hints,
        )
    )
    sections.append(('system_partial_03_tail', _render_interaction_tail(config)))

    # Worked-examples partial — agent mode only; edit-heavy examples mislead Chat/Plan.
    if not is_small_model and not (is_chat_mode(mode) or is_plan_mode(mode)):
        sections.append(
            (
                'system_partial_05_examples',
                _render_examples(
                    terminal_command_tool=resolved_terminal_tool,
                    tracker_on=bool(getattr(config, 'enable_task_tracker_tool', True)),
                    criteria_on=bool(
                        getattr(config, 'enable_acceptance_criteria_tool', True)
                    ),
                    working_memory_on=bool(
                        getattr(config, 'enable_working_memory', True)
                    ),
                    meta_cognition_on=bool(
                        getattr(config, 'enable_meta_cognition', False)
                    ),
                    lsp_available=lsp_available,
                    checkpoints_on=bool(getattr(config, 'enable_checkpoints', True)),
                    web_on=bool(getattr(config, 'enable_web', True)),
                ),
            )
        )

    sections.append(
        (
            'system_partial_04_critical',
            _render_critical(
                resolved_terminal_tool,
                terminal_manager_available=bool(
                    getattr(config, 'enable_terminal', True)
                ),
                tracker_on=bool(getattr(config, 'enable_task_tracker_tool', True)),
                criteria_on=bool(
                    getattr(config, 'enable_acceptance_criteria_tool', True)
                ),
                checkpoints_on=bool(getattr(config, 'enable_checkpoints', True)),
                meta_cognition_on=bool(getattr(config, 'enable_meta_cognition', False)),
                mode=mode,
            ),
        ),
    )
    return sections


def build_mcp_user_addendum(
    mcp_tool_names: list[str] | None = None,
    mcp_tool_descriptions: dict[str, str] | None = None,
    mcp_server_hints: list[dict[str, str]] | None = None,
    config: Any = None,
) -> str:
    """Render the MCP tool catalogue as a per-turn system-message addendum.

    Returns an empty string when no MCP tools are connected. The system prompt
    intentionally omits MCP so this addendum can be injected as a second system
    message without invalidating provider prefix caches.
    """
    names = list(mcp_tool_names or [])
    if not names:
        return ''
    descriptions = dict(mcp_tool_descriptions or {})
    hints = list(mcp_server_hints or [])
    return _render_mcp_and_permissions(names, descriptions, hints, config)


def measure_system_prompt_sections(
    *,
    active_llm_model: str = '',
    is_windows: bool = False,
    windows_with_bash: bool = False,
    cli_mode: bool = False,
    config: Any = None,
    mcp_tool_names: list[str] | None = None,
    mcp_tool_descriptions: dict[str, str] | None = None,
    mcp_server_hints: list[dict[str, str]] | None = None,
    terminal_tool_name: str | None = None,
    function_calling_mode: str | None = None,
    agent_identity: str = '',
) -> dict[str, Any]:
    """Token/char budget per section (tiktoken when available). Sections sorted by tokens descending."""
    mid = active_llm_model or 'unknown'
    sections = _collect_system_prompt_sections(
        active_llm_model=active_llm_model,
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        cli_mode=cli_mode,
        config=config,
        mcp_tool_names=mcp_tool_names,
        mcp_tool_descriptions=mcp_tool_descriptions,
        mcp_server_hints=mcp_server_hints,
        terminal_tool_name=terminal_tool_name,
        function_calling_mode=function_calling_mode,
        agent_identity=agent_identity,
    )
    per: list[dict[str, Any]] = []
    for name, body in sections:
        tok, enc = _count_section_tokens(body, mid)
        per.append({'name': name, 'tokens': tok, 'chars': len(body), 'encoding': enc})
    per.sort(key=lambda r: r['tokens'], reverse=True)
    joined = '\n\n'.join(body for _, body in sections)
    tot, enc_tot = _count_section_tokens(joined, mid)
    return {
        'model_id': mid,
        'sections': per,
        'total_tokens': tot,
        'total_chars': len(joined),
        'total_encoding': enc_tot,
    }


def build_system_prompt(
    *,
    active_llm_model: str = '',
    is_windows: bool = False,
    windows_with_bash: bool = False,
    cli_mode: bool = False,
    config: Any = None,
    mcp_tool_names: list[str] | None = None,
    mcp_tool_descriptions: dict[str, str] | None = None,
    mcp_server_hints: list[dict[str, str]] | None = None,
    terminal_tool_name: str | None = None,
    function_calling_mode: str | None = None,
    agent_identity: str = '',
    render_mcp_inline: bool = True,
    semantic_recall_active: bool | None = None,
    **_extra: object,
) -> str:
    """Assemble the full system prompt from partials.

    Drop-in replacement for the old ``system_prompt`` rendering.

    MCP tools are not included in the system prompt. Deliver connected MCP
    catalogues separately via :func:`build_mcp_user_addendum`.
    """
    sections = _collect_system_prompt_sections(
        active_llm_model=active_llm_model,
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        cli_mode=cli_mode,
        config=config,
        mcp_tool_names=mcp_tool_names,
        mcp_tool_descriptions=mcp_tool_descriptions,
        mcp_server_hints=mcp_server_hints,
        terminal_tool_name=terminal_tool_name,
        function_calling_mode=function_calling_mode,
        agent_identity=agent_identity,
        render_mcp_inline=render_mcp_inline,
        semantic_recall_active=semantic_recall_active,
    )
    return '\n\n'.join(body for _, body in sections)


def _build_repository_info_block(repository_info: RepositoryInfo | None) -> str | None:
    if not repository_info:
        return None

    repo_name = getattr(repository_info, 'repo_name', None) or ''
    repo_dir = getattr(repository_info, 'repo_directory', None) or ''
    branch = getattr(repository_info, 'branch_name', None) or ''
    lines = [
        '<REPOSITORY_INFO>',
        f"At the user's request, repository {repo_name} has been cloned to {repo_dir} in the current working directory.",
    ]
    if branch:
        lines.append(f'The repository has been checked out to branch "{branch}".')
        lines.append('')
        lines.append(
            f'IMPORTANT: You should work within the current branch "{branch}" unless\n'
            '    1. the user explicitly instructs otherwise\n'
            '    2. if the current branch is "main", "master", or another default branch '
            'where direct pushes may be unsafe'
        )
    lines.append('</REPOSITORY_INFO>')
    return '\n'.join(lines)


def _build_repo_instructions_block(repo_instructions: str) -> str | None:
    if not repo_instructions:
        return None
    return f'<REPOSITORY_INSTRUCTIONS>\n{repo_instructions}\n</REPOSITORY_INSTRUCTIONS>'


def _runtime_hosts_lines(hosts: dict[object, object]) -> list[str]:
    if not hosts:
        return []
    lines = [
        'The user has access to the following hosts for accessing a web application, '
        'each of which has a corresponding port:'
    ]
    for host, port in hosts.items():
        lines.append(f'* {host} (port {port})')
    lines.append(
        'When starting a web server, use the corresponding ports. You should also '
        'set any options to allow iframes and CORS requests, and allow the server to '
        'be accessed from any host (e.g. 0.0.0.0).\n'
        'For example, if you are using vite.config.js, you should set server.host '
        'and server.allowedHosts to true'
    )
    return lines


def _runtime_secrets_lines(secrets: dict[object, object]) -> list[str]:
    if not secrets:
        return []
    lines = [
        '<CUSTOM_SECRETS>',
        'You have access to the following environment variables',
    ]
    for name, desc in secrets.items():
        lines.append(f'* $**{name}**: {desc}')
    lines.append('</CUSTOM_SECRETS>')
    return lines


def _build_runtime_information_block(
    runtime_info: RuntimeInfo | None,
    *,
    workspace_is_bare: bool = False,
) -> str | None:
    if not runtime_info:
        return None

    ri_lines: list[str] = ['<RUNTIME_INFORMATION>']
    wd = getattr(runtime_info, 'working_dir', '') or ''
    if wd:
        ri_lines.append(f'The current working directory is {wd}')
        ri_lines.append(
            'The open project lives in that directory. Use file and shell paths relative to '
            'it, or absolute paths on disk that stay under it.'
        )
        ri_lines.append(
            'There is no `/workspace` virtual path — tools and shell commands use real paths only.'
        )
        ri_lines.append(
            'This message does not list project files—do not assume paths like '
            '`tailwind.config.*` exist. Use `glob` to discover layout, '
            'then read with editor/view tools.'
        )

    hosts = getattr(runtime_info, 'available_hosts', None) or {}
    ri_lines.extend(_runtime_hosts_lines(hosts))

    extra_instr = getattr(runtime_info, 'additional_agent_instructions', '') or ''
    if extra_instr:
        ri_lines.append(extra_instr)

    secrets = getattr(runtime_info, 'custom_secrets_descriptions', None) or {}
    ri_lines.extend(_runtime_secrets_lines(secrets))

    date = getattr(runtime_info, 'date', '') or ''
    if date:
        ri_lines.append(f"Today's date is {date} (UTC).")

    if workspace_is_bare:
        ri_lines.append(
            'No cloned repository metadata or repository instructions were detected for '
            'this directory; treat it as a plain local workspace rather than a known '
            'project, and rely on discovery tools to learn what is here.'
        )

    ri_lines.append('</RUNTIME_INFORMATION>')
    return '\n'.join(ri_lines)


def _build_conversation_instructions_block(
    conversation_instructions: ConversationInstructions | None,
) -> str | None:
    conv = conversation_instructions
    if conv is None or not conv.content:
        return None
    return f'<CONVERSATION_INSTRUCTIONS>\n{conv.content}\n</CONVERSATION_INSTRUCTIONS>'


def build_workspace_context(
    repository_info: RepositoryInfo | None = None,
    runtime_info: RuntimeInfo | None = None,
    conversation_instructions: ConversationInstructions | None = None,
    repo_instructions: str = '',
) -> str:
    """Render the additional-info / workspace context block."""
    parts: list[str] = []

    for block in (
        _build_repository_info_block(repository_info),
        _build_repo_instructions_block(repo_instructions),
    ):
        if block:
            parts.append(block)

    has_repo = bool(
        repository_info
        and (
            getattr(repository_info, 'repo_name', '')
            or getattr(repository_info, 'repo_directory', '')
        )
    )
    workspace_is_bare = not has_repo and not (repo_instructions or '').strip()

    runtime_block = _build_runtime_information_block(
        runtime_info, workspace_is_bare=workspace_is_bare
    )
    if runtime_block:
        parts.append(runtime_block)

        conversation_block = _build_conversation_instructions_block(
            conversation_instructions
        )
        if conversation_block:
            parts.append(conversation_block)

    return '\n'.join(parts).strip()


def build_playbook_info(triggered_agents: list[Any]) -> str:
    """Render playbook info blocks for triggered agents."""
    blocks: list[str] = []
    for agent_info in triggered_agents:
        name = getattr(agent_info, 'name', '')
        trigger = getattr(agent_info, 'trigger', '')
        content = getattr(agent_info, 'content', '')
        intro = (
            f'The following information has been included from playbook "{name}" based on a keyword match for "{trigger}".\n'
            if name
            else f'The following information has been included based on a keyword match for "{trigger}".\n'
        )
        blocks.append(
            f'<EXTRA_INFO>\n'
            f'{intro}'
            f"It may or may not be relevant to the user's request.\n\n"
            f'{content}\n'
            f'</EXTRA_INFO>'
        )
    return '\n'.join(blocks).strip()


def build_knowledge_base_info(kb_results: list[Any]) -> str:
    """Render knowledge base search results."""
    blocks: list[str] = []
    for result in kb_results:
        filename = getattr(result, 'filename', '')
        score = getattr(result, 'relevance_score', 0.0)
        chunk = getattr(result, 'chunk_content', '')
        blocks.append(
            f'<KNOWLEDGE_BASE_INFO>\n'
            f'The following information was found in your knowledge base (Document: {filename}).\n'
            f'Relevance score: {score:.2f}\n\n'
            f'{chunk}\n'
            f'</KNOWLEDGE_BASE_INFO>'
        )
    return '\n'.join(blocks).strip()


def _cli_measure_default() -> None:
    """Print a default baseline budget (balanced config, no MCP tools)."""
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        autonomy_level='balanced',
        enable_lsp_query=False,
    )

    report = measure_system_prompt_sections(
        active_llm_model='gpt-4',
        is_windows=False,
        config=cfg,
        mcp_tool_names=[],
        mcp_tool_descriptions={},
        mcp_server_hints=[],
        function_calling_mode='native',
    )
    print(
        f'model_id={report["model_id"]} total_tokens≈{report["total_tokens"]} ({report["total_encoding"]}) chars={report["total_chars"]}'
    )
    print('section'.ljust(42), 'tokens', 'chars')
    for row in report['sections']:
        print(row['name'][:41].ljust(42), row['tokens'], row['chars'])


if __name__ == '__main__':
    _cli_measure_default()
