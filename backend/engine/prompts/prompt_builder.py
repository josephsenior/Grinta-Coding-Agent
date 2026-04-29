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
    _code_intelligence_available,
    _count_section_tokens,
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
    _render_mcp_and_permissions as _render_mcp_and_permissions_impl,
)
from backend.engine.prompts.section_renderers import (
    _render_routing as _render_routing_impl,
)
from backend.engine.prompts.section_renderers import (
    _render_tool_reference as _render_tool_reference_impl,
)

# Per-model capability classification (capability adaptation, not provider tuning).
# Model-class fingerprints live in ``backend.inference.provider_capabilities``;
# adding a new model is a one-line entry there — no edits needed in this file.
from backend.inference.provider_capabilities import (
    model_has_inherent_reasoning as _model_has_inherent_reasoning,
)
from backend.inference.provider_capabilities import (
    model_is_small as _model_is_small,
)

if TYPE_CHECKING:
    from backend.utils.prompt import (
        ConversationInstructions,
        RepositoryInfo,
        RuntimeInfo,
    )

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
) -> str:
    return _render_routing_impl(_render_partial, is_windows, config, function_calling_mode)


def _render_autonomy(config: Any, is_windows: bool) -> str:
    return _render_autonomy_impl(_render_partial, config, is_windows)


def _render_tool_reference(is_windows: bool, config: Any = None) -> str:
    return _render_tool_reference_impl(_render_partial, is_windows, config)


def _render_critical(
    terminal_command_tool: str,
    *,
    enable_think: bool,
    terminal_manager_available: bool,
    meta_cognition_on: bool,
) -> str:
    return _render_critical_impl(
        _render_partial,
        terminal_command_tool,
        enable_think=enable_think,
        terminal_manager_available=terminal_manager_available,
        meta_cognition_on=meta_cognition_on,
    )


def _render_examples(
    *,
    tracker_on: bool,
    enable_think: bool,
    meta_cognition_on: bool,
    code_intelligence_available: bool,
    checkpoints_on: bool,
) -> str:
    return _render_examples_impl(
        _render_partial,
        tracker_on=tracker_on,
        enable_think=enable_think,
        meta_cognition_on=meta_cognition_on,
        code_intelligence_available=code_intelligence_available,
        checkpoints_on=checkpoints_on,
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
                'Your terminal is **PowerShell** on Windows. Use PowerShell syntax: chain with `;` (not `&&` / `||`); '
                'prefer `-ErrorAction SilentlyContinue` or `try/catch` instead of `|| true`; use `Start-Process` / '
                '`Start-Job` instead of a trailing `&`.\n\n'
                '**Directory/Content listing:** You may use `Get-ChildItem` (or `ls`, `dir`) and `Select-String` if needed, '
                'but prefer native tools from the **TOOL_ROUTING_LADDER** (`search_code`, editors, structure tools) first.\n\n'
                '**Do not use Unix-only habits here:** `find`, `cat`, `grep`, `head`, `tail`, `touch`, `rm -rf`, '
                '`pkill`, `timeout`, `which`, or `&&` / `||`.\n'
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
    """MCP catalogue inline, or permissions-only when MCP is delivered as user addendum."""
    if render_mcp_inline:
        return [
            (
                'mcp_permissions_partial_03_tail',
                _render_mcp_and_permissions(
                    mcp_tool_names or [],
                    mcp_tool_descriptions or {},
                    mcp_server_hints or [],
                    config,
                ),
            ),
        ]
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
) -> list[tuple[str, str]]:
    """Ordered (name, body) sections before joining with blank lines.

    When ``render_mcp_inline=False`` the MCP tool block is omitted from the
    system prompt so it can be delivered as a per-turn user-role addendum
    (see :func:`build_mcp_user_addendum`). This preserves provider prefix
    caches because the system prompt no longer mutates when MCP servers
    connect or disconnect mid-session.
    """
    model_id = active_llm_model or 'unknown'
    is_small_model = _model_is_small(model_id)
    has_inherent_reasoning = _model_has_inherent_reasoning(model_id)

    resolved_terminal_tool = _resolve_terminal_command_tool(
        is_windows=is_windows,
        terminal_tool_name=terminal_tool_name,
    )
    shell_is_powershell = resolved_terminal_tool == 'execute_powershell'
    code_intelligence_available = _code_intelligence_available(config)

    identity_line = (
        agent_identity.strip()
        if agent_identity.strip()
        else 'You are Grinta, an expert AI coding agent built by Youssef Mejdi.'
    )
    sections: list[tuple[str, str]] = [
        (
            'identity_header',
            f'{identity_line} '
            'You solve complex technical tasks through methodical reasoning and tool execution.\n\n'
            '**Model identity:** The deployment calls you through an API using the configured '
            'model id below.\n'
            f'Configured model id: `{model_id}`',
        ),
    ]
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
            _render_routing(is_windows, config, function_calling_mode),
        ),
        ('security_risk_policy', _render_security(cli_mode)),
        ('system_partial_01_autonomy', _render_autonomy(config, shell_is_powershell)),
        (
            'system_partial_02_tools',
            _render_tool_reference(shell_is_powershell, config),
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

    # ``think`` is opt-in via config, but if the model has inherent reasoning
    # (o1/o3/r1/grok-4/gemini-thinking) we suppress the scaffolding regardless.
    effective_enable_think = bool(getattr(config, 'enable_think', False)) and not has_inherent_reasoning

    # Worked-examples partial — capability-adapted: omit on small/local models
    # where prompt budget is tight, and where examples can crowd out tool docs.
    if not is_small_model:
        sections.append(
            (
                'system_partial_05_examples',
                _render_examples(
                    tracker_on=bool(getattr(config, 'enable_internal_task_tracker', False)),
                    enable_think=effective_enable_think,
                    meta_cognition_on=bool(getattr(config, 'enable_meta_cognition', False)),
                    code_intelligence_available=code_intelligence_available,
                    checkpoints_on=bool(getattr(config, 'enable_checkpoints', False)),
                ),
            )
        )

    sections.append(
        (
            'system_partial_04_critical',
            _render_critical(
                resolved_terminal_tool,
                enable_think=effective_enable_think,
                terminal_manager_available=bool(
                    getattr(config, 'enable_terminal', True)
                ),
                meta_cognition_on=bool(getattr(config, 'enable_meta_cognition', False)),
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
    """Render the MCP catalogue as a *per-turn* addendum.

    Emit this as a system-role message *appended* to the conversation each
    turn (after history compaction) so the static system prompt remains stable
    across MCP connect/disconnect events. This restores Claude / Gemini prefix
    caching that was previously broken by inlining the MCP tool list into the
    system prompt.

    Returns an empty string when no MCP tools are connected.
    """
    if not mcp_tool_names:
        return ''
    return _render_mcp_and_permissions(
        mcp_tool_names,
        mcp_tool_descriptions or {},
        mcp_server_hints or [],
        config,
    )


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
    **_extra: object,
) -> str:
    """Assemble the full system prompt from partials.

    Drop-in replacement for the old ``system_prompt`` rendering.

    Pass ``render_mcp_inline=False`` to omit the MCP catalogue from the system
    prompt; deliver it separately via :func:`build_mcp_user_addendum` so the
    system prompt stays stable across MCP connect/disconnect events.
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
    return (
        f'<REPOSITORY_INSTRUCTIONS>\n{repo_instructions}\n</REPOSITORY_INSTRUCTIONS>'
    )


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


def _build_runtime_information_block(runtime_info: RuntimeInfo | None) -> str | None:
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
            '`tailwind.config.*` exist. Use `search_code` to discover layout, '
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

    runtime_block = _build_runtime_information_block(runtime_info)
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
            f"<EXTRA_INFO>\n"
            f"{intro}"
            f"It may or may not be relevant to the user's request.\n\n"
            f"{content}\n"
            f"</EXTRA_INFO>"
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


def build_remember_prompt_template(events: str) -> str:
    """Render the remember-prompt template."""
    return (
        "You are tasked with generating a prompt that will be used by another AI to revise a special reference file. "
        "This file contains important information and learnings that are used to carry out certain tasks. "
        "The file can be extended over time to incorporate new knowledge and experiences.\n\n"
        "You have been provided with a subset of new events that may require changes to the special file. "
        "These events are:\n"
        "<events>\n"
        f"{events}\n"
        "</events>\n\n"
        "Your task is to analyze these events and determine what changes, if any, should be made to the special file. "
        "Then, you need to generate a prompt that will instruct another AI to make these revisions correctly and efficiently.\n\n"
        "When creating your prompt, follow these guidelines:\n"
        "1. Clearly specify which parts of the file need to be revised or if new sections should be added.\n"
        "2. Provide context for why these changes are necessary based on the new events.\n"
        "3. Be specific about the information that should be added or modified.\n"
        "4. Maintain the existing structure and formatting of the file.\n"
        "5. Ensure that the revisions are consistent with the current content and don't contradict existing information.\n\n"
        "Now, based on the new events provided, generate a prompt that will guide the AI in making the appropriate "
        "revisions to the special file. Your prompt should be clear, specific, and actionable. "
        "Include your prompt within <revision_prompt> tags.\n\n"
        "<revision_prompt>\n\n</revision_prompt>"
    )


def _cli_measure_default() -> None:
    """Print a default baseline budget (balanced config, no MCP tools)."""
    from types import SimpleNamespace

    cfg = SimpleNamespace(
        autonomy_level='balanced',
        enable_checkpoints=False,
        enable_lsp_query=False,
        enable_internal_task_tracker=False,
        enable_permissions=False,
        enable_meta_cognition=False,
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
