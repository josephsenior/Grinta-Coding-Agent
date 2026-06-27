"""User-facing string constants for the TUI.

Centralizes the empty-state and loading-state copy so that "no X" messages
share one convention. The convention is one trailing period on full
sentences and no period on terse one-liners.

Add a string here rather than scattering an inline literal.
"""

from __future__ import annotations

# Sidebar / panel empty states
EMPTY_TASKS = 'No tasks yet.'
EMPTY_MCP = 'No MCP servers configured.'
EMPTY_SKILLS = 'No custom skills.'
EMPTY_SIDEBAR_FALLBACK = 'No items.'

# Sidebar loading / scanning states
LOADING_LSP = 'Scanning local PATH...'
LOADING_DAP = 'Scanning local PATH...'

# Sessions dialog empty / error states
SESSIONS_NONE_FOUND = 'No sessions found.'
SESSIONS_NONE_MATCHING = 'No sessions matching {query}.'
SESSIONS_NO_STORAGE = 'No session storage found.'
SESSIONS_NONE_SELECTED = 'No session selected.'
SESSIONS_NO_AT_INDEX = "No session at '{target}'."
SESSIONS_NO_MATCHES = 'No session matches: {target}.'

# Other panel empty states
EMPTY_DIFF = 'No diff available.'
EMPTY_SEARCH = 'No matches found.'
EMPTY_DETAIL = '(no output)'

# Sessions filter / list helpers
SESSIONS_SORT_OPTIONS = ('updated', 'created', 'events', 'cost', 'model')
SESSIONS_LIMIT_MIN = 1
SESSIONS_LIMIT_DEFAULT = 20

# Common input hints (centralized to keep capitalization consistent)
INPUT_HINT_CHAT = 'Ask about the codebase or architecture…'
INPUT_HINT_PLAN = 'Describe what Grinta should inspect and plan…'
INPUT_HINT_AGENT = 'Describe a task for Grinta to execute…'

# Welcome widget
WELCOME_SLOGAN = 'Pure Grit.'

# Communicate widget labels (kept consistent — "Needs X" / "Need X" is a
# known TUI drift, this module is the single source of truth).
COMMUNICATE_QUESTION = 'Question'
COMMUNICATE_NEEDS_CONTEXT = 'Needs Context'
COMMUNICATE_OPTIONS = 'Options'
COMMUNICATE_CONFIRM = 'Confirm'
COMMUNICATE_STATUS = 'Status'
COMMUNICATE_NEEDS_INPUT = 'Need Your Input'
COMMUNICATE_FALLBACK = 'The agent needs your input.'

# Confirmation widget wording
CONFIRM_AGENT_WANTS = 'Agent wants to {verb} {target}'
CONFIRM_RISK_SUFFIX = '({risk_label} risk)'

# Slash command result strings
SLASH_RESULT_TRANSCRIPT_CLEARED = (
    'Transcript cleared. Send a message, or type `/help` for commands.'
)
SLASH_RESULT_NO_PREVIOUS = 'No previous message to retry.'
SLASH_RESULT_NO_REPLY = 'No assistant reply available to copy yet.'
SLASH_RESULT_NOT_AVAILABLE_PIPED = (
    '`{name}` is not available in piped (non-interactive) mode. '
    'Run `grinta` in a TTY for the full slash surface.'
)
SLASH_RESULT_REQUIRES_TTY = (
    '`{name}` requires an interactive TTY session. '
    'Run `grinta` (no pipe) to use it.'
)
SLASH_RESULT_UNKNOWN = 'Unknown command: `{cmd}`.'
SLASH_RESULT_DID_YOU_MEAN = ' Did you mean {suggestions}?'
SLASH_RESULT_TYPE_HELP = ' Type `/help` to list available commands.'
SLASH_RESULT_TYPE_HELP_TUI = (
    'Type `/help` to list commands, or press Tab after `/` to autocomplete.'
)
