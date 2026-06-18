"""Slash-command registry data tables.

Pure data: the list of built-in + playbook ``SlashCommandSpec`` tuples,
the known-models table used for ``/model`` completion, and the derived
alias/name index for fuzzy matching.
"""

from __future__ import annotations

from backend.cli.repl.slash_registry_models import SlashCommandSpec

_AUTONOMY_LEVEL_HINTS = {
    'conservative': 'Always ask before actions',
    'balanced': 'Ask only for high-risk actions',
    'full': 'Run without confirmation prompts',
}


_PLAYBOOK_SLASH_COMMANDS: tuple[SlashCommandSpec, ...] = (
    SlashCommandSpec(
        '/add_repo_inst',
        'Scaffold repository playbook instructions',
        '/add_repo_inst',
        help_section='control',
    ),
    SlashCommandSpec(
        '/address_pr_comments',
        'Apply a PR-comment resolution workflow',
        '/address_pr_comments',
        help_section='control',
    ),
    SlashCommandSpec(
        '/api',
        'Use API implementation guidance',
        '/api',
        help_section='control',
    ),
    SlashCommandSpec(
        '/audit',
        'Run an audit-oriented review workflow',
        '/audit',
        help_section='control',
    ),
    SlashCommandSpec(
        '/ci',
        'Use CI triage and stabilization workflow',
        '/ci',
        help_section='control',
    ),
    SlashCommandSpec(
        '/codereview',
        'Apply pragmatic code-review checklist',
        '/codereview',
        help_section='control',
    ),
    SlashCommandSpec(
        '/codereview-roasted',
        'Apply strict code-review checklist',
        '/codereview-roasted',
        help_section='control',
    ),
    SlashCommandSpec(
        '/compress',
        'Use context compression workflow',
        '/compress',
        help_section='control',
    ),
    SlashCommandSpec(
        '/database',
        'Use database and schema guidance',
        '/database',
        help_section='control',
    ),
    SlashCommandSpec(
        '/debug',
        'Use systematic debugging workflow',
        '/debug',
        help_section='control',
    ),
    SlashCommandSpec(
        '/docs',
        'Use documentation authoring guidance',
        '/docs',
        help_section='control',
    ),
    SlashCommandSpec(
        '/feature',
        'Use structured feature delivery workflow',
        '/feature',
        help_section='control',
    ),
    SlashCommandSpec(
        '/hardened',
        'Use hardened execution workflow',
        '/hardened',
        help_section='control',
    ),
    SlashCommandSpec(
        '/orch-debug',
        'Debug orchestration-level issues',
        '/orch-debug',
        help_section='control',
    ),
    SlashCommandSpec(
        '/owasp',
        'Use OWASP-oriented security review guidance',
        '/owasp',
        help_section='control',
    ),
    SlashCommandSpec(
        '/perf',
        'Use performance and cost optimization workflow',
        '/perf',
        help_section='control',
    ),
    SlashCommandSpec(
        '/react',
        'Use React implementation guidance',
        '/react',
        help_section='control',
    ),
    SlashCommandSpec(
        '/recover',
        'Recover from failed or stuck runs',
        '/recover',
        help_section='control',
    ),
    SlashCommandSpec(
        '/refactor',
        'Use refactoring workflow guidance',
        '/refactor',
        help_section='control',
    ),
    SlashCommandSpec(
        '/release',
        'Use release readiness and rollout workflow',
        '/release',
        help_section='control',
    ),
    SlashCommandSpec(
        '/remember',
        'Capture durable lessons and memory signals',
        '/remember',
        help_section='control',
    ),
    SlashCommandSpec(
        '/security',
        'Use security hardening guidance',
        '/security',
        help_section='control',
    ),
    SlashCommandSpec(
        '/testing',
        'Use test planning and authoring workflow',
        '/testing',
        help_section='control',
    ),
    SlashCommandSpec(
        '/tool',
        'Use tool and MCP authoring workflow',
        '/tool',
        help_section='control',
    ),
    SlashCommandSpec(
        '/update_pr_description',
        'Refresh PR summary and test plan',
        '/update_pr_description',
        help_section='control',
    ),
    SlashCommandSpec(
        '/update_test',
        'Regenerate tests after implementation changes',
        '/update_test',
        help_section='control',
    ),
)
_SLASH_COMMANDS = (
    SlashCommandSpec(
        '/help',
        'Show commands and shortcuts',
        '/help [command|--all]',
        aliases=('/?',),
        help_section='system',
    ),
    SlashCommandSpec(
        '/settings',
        'Open settings (model, API key, MCP)',
        '/settings',
        help_section='model',
    ),
    SlashCommandSpec(
        '/sessions', 'List past sessions', '/sessions', help_section='session'
    ),
    SlashCommandSpec(
        '/resume',
        'Resume a past session by index or ID',
        '/resume <N|id>',
        help_section='session',
    ),
    SlashCommandSpec(
        '/autonomy',
        'View or set autonomy (conservative/balanced/full)',
        '/autonomy [conservative|balanced|full]',
        help_section='model',
    ),
    SlashCommandSpec(
        '/model',
        'Show or switch the active model',
        '/model [provider/model]',
        help_section='model',
    ),
    SlashCommandSpec(
        '/compact',
        'Condense context to free token budget',
        '/compact',
        help_section='control',
    ),
    SlashCommandSpec(
        '/retry', 'Re-send the last message', '/retry', help_section='control'
    ),
    SlashCommandSpec(
        '/status',
        'Show the current HUD snapshot (use `verbose` for diagnostics)',
        '/status [verbose]',
        help_section='control',
    ),
    SlashCommandSpec(
        '/cost',
        'Show running token & USD cost for this session',
        '/cost',
        help_section='control',
    ),
    SlashCommandSpec(
        '/health',
        'Run a fast self-check (debug adapters, ripgrep, git, model)',
        '/health',
        help_section='control',
    ),
    SlashCommandSpec(
        '/diff',
        'Show workspace git changes',
        '/diff [--stat|--name-only|--patch] [path]',
        help_section='control',
    ),
    SlashCommandSpec(
        '/checkpoint',
        'Save a manual checkpoint of the workspace',
        '/checkpoint [label]',
        help_section='control',
    ),
    SlashCommandSpec(
        '/copy',
        'Copy last assistant message to system clipboard',
        '/copy',
        help_section='control',
    ),
    SlashCommandSpec(
        '/search',
        'Search the session transcript for matching text',
        '/search <query>',
        help_section='control',
    ),
    SlashCommandSpec(
        '/clear', 'Clear the visible transcript', '/clear', help_section='control'
    ),
    SlashCommandSpec(
        '/exit', 'Quit grinta', '/exit', aliases=('/quit',), help_section='system'
    ),
    *_PLAYBOOK_SLASH_COMMANDS,
)


def _load_known_models() -> tuple[tuple[str, str], ...]:
    """Load provider/model completions from the catalog."""
    try:
        from backend.inference.catalog_loader import get_catalog, runtime_model_id

        return tuple(
            (f'{entry.provider}/{runtime_model_id(entry)}', entry.provider)
            for entry in get_catalog()
            if entry.featured
        )
    except Exception:
        return (
            ('openai/gpt-5.1', 'openai'),
            ('anthropic/claude-sonnet-4-6', 'anthropic'),
            ('google/gemini-3-flash', 'google'),
        )


# Known models surfaced in `/model` tab-completion.
# provider/model pairs — provider shown as display_meta in the completer.
_KNOWN_MODELS: tuple[tuple[str, str], ...] = _load_known_models()
_COMMAND_ALIASES = {
    alias: spec.name for spec in _SLASH_COMMANDS for alias in spec.aliases
}
_COMMAND_NAMES = tuple(
    name for spec in _SLASH_COMMANDS for name in (spec.name, *spec.aliases)
)


def iter_command_completion_entries() -> list[tuple[str, str]]:
    """Return slash commands plus aliases for prompt-toolkit completion."""
    entries: list[tuple[str, str]] = []
    for spec in _SLASH_COMMANDS:
        entries.append((spec.name, spec.description))
        entries.extend((alias, f'Alias for {spec.name}') for alias in spec.aliases)
    return entries
