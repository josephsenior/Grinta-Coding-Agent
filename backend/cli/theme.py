"""Centralized visual theme tokens for Grinta CLI.

All color and style constants used across CLI components are defined here.
Import from this module instead of scattering raw hex values through files.

Naming conventions
------------------

* ``CLR_*_BODY`` — soft, low-saturation tone meant for body text inside a
  panel (kept legible against the terminal background without shouting).
* ``CLR_*_ICON`` — bright, bold companion tone used for inline status icons,
  badges, or single-character markers (``✓``, ``✗``, ``•``, ``ℹ``).

Always pair the body and icon tones from the same family to keep panels
visually coherent across components.
"""

from __future__ import annotations

import os


def _env_truthy(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def no_color_enabled() -> bool:
    """Respect NO_COLOR and a Grinta-specific override."""
    return _env_truthy('NO_COLOR') or _env_truthy('GRINTA_NO_COLOR')


def use_ascii_cli_symbols() -> bool:
    """When true, use ASCII-friendly markers instead of Unicode (``GRINTA_ASCII=1``)."""
    if _env_truthy('GRINTA_ASCII'):
        return True
    enc = (os.environ.get('PYTHONIOENCODING') or '').strip().lower()
    return enc == 'ascii'


def mark_ok() -> str:
    return '+' if use_ascii_cli_symbols() else MARK_OK


def mark_err() -> str:
    return 'x' if use_ascii_cli_symbols() else MARK_ERR


def mark_warn() -> str:
    return '!' if use_ascii_cli_symbols() else MARK_WARN


def mark_info() -> str:
    return '*' if use_ascii_cli_symbols() else MARK_INFO


def mark_prompt() -> str:
    return '>' if use_ascii_cli_symbols() else MARK_PROMPT


def splash_anim_disabled() -> bool:
    """Skip splash ``Live`` animation (``GRINTA_NO_SPLASH_ANIM=1``)."""
    return _env_truthy('GRINTA_NO_SPLASH_ANIM')

# ── Backgrounds ────────────────────────────────────────────────────────────────
HUD_BG = 'grey15'  # HUD footer background

# ── Separators & borders ───────────────────────────────────────────────────────
CLR_SEP = '#4a6b82'  # · bullet separator and lightweight dividers
CLR_CARD_BORDER = '#5a7f95'  # rounded card / panel border (blue-gray)

# ── HUD display text ──────────────────────────────────────────────────────────
CLR_HUD_MODEL = 'bold #dbe7f3'  # model name (bright)
CLR_HUD_DETAIL = '#b4c4d5'  # tokens, cost, calls (secondary)
CLR_META = '#6d8596'  # subdued metadata, timers, helper text
CLR_MUTED_TEXT = '#94a3b8'  # long-form secondary labels / values
CLR_BRAND = 'bold #7dd3fc'  # GRINTA wordmark / active spinner hue
CLR_BRAND_HUE = '#7dd3fc'  # brand cyan without bold modifier

# ── Status semantic colors (HUD ledger / footer badges) ──────────────────────
CLR_STATUS_OK = '#8fdfb1'  # Healthy / Ready (green)
CLR_STATUS_WARN = '#fcd34d'  # Review / Paused (yellow)
CLR_STATUS_ERR = '#fca5a5'  # Error (red-pink)

# ── Result tones (paired body/icon hues for activity rows + tone panels) ─────
# Body tones live inside panels and stay readable on dark terminals; icon
# tones are reserved for the leading glyph or badge so the eye can pick the
# state out at a glance without making whole sentences shout.
CLR_OK_BODY = '#86efac'  # success body text
CLR_OK_ICON = 'bold #10b981'  # success icon / accent
CLR_ERR_BODY = '#fca5a5'  # error body text
CLR_ERR_ICON = 'bold #ef4444'  # error icon / accent
CLR_WARN_BODY = '#fcd34d'  # warning body text
CLR_WARN_ICON = 'bold #f59e0b'  # warning icon / accent
CLR_INFO_BODY = '#93c5fd'  # info body text
CLR_INFO_ICON = 'bold #38bdf8'  # info icon / accent

# ── Shared UI markers (keep iconography consistent) ───────────────────────────
# One canonical set used across transcript cards and prompt affordances.
MARK_OK = '✓'
MARK_ERR = '✗'
MARK_WARN = '⚠'
MARK_INFO = '•'
MARK_PROMPT = '❯'

# ── Shared Rich style aliases (avoid scattered literals) ─────────────────────
STYLE_DIM = 'dim'
STYLE_DEFAULT = 'default'
STYLE_BOLD = 'bold'
STYLE_BOLD_DIM = 'bold #a8b8c8'
STYLE_ITALIC_DIM = 'dim italic'
STYLE_EMPTY = ''

# ── Activity card chrome ──────────────────────────────────────────────────────
CLR_CARD_TITLE = 'bold #a0b9cc'  # panel title text (gray-blue)

# ── Activity row text ─────────────────────────────────────────────────────────
CLR_VERB = 'bold #94a3b8'  # action verb (muted but distinct)
CLR_DETAIL = 'default'  # action detail (normal foreground)
CLR_SECONDARY = '#6d8596'  # secondary row (neutral)
CLR_SECONDARY_OK = 'dim green'  # secondary row (success)
CLR_SECONDARY_ERR = 'dim red'  # secondary row (error)

# ── Diff colors ───────────────────────────────────────────────────────────────
CLR_DIFF_ADD = 'green'  # added lines
CLR_DIFF_REM = 'red'  # removed lines
CLR_DIFF_ADD_DIM = 'dim green'  # apply_patch +N delta (secondary line)
CLR_DIFF_REM_DIM = 'dim red'  # apply_patch -N delta

# ── Inline Rich markup (prefer these over raw [red] / [green] in prose) ───────
MSG_STYLE_SUCCESS_MARK = 'bold #8fdfb1'  # short ✓ success flashes (onboarding)
MSG_STYLE_PROVIDER_HINT = 'cyan'  # provider name in onboarding lines

# ── System message tags (panels / notices) ────────────────────────────────────
STYLE_SYSTEM_TAG_WARNING = 'yellow'
STYLE_SYSTEM_TAG_AUTONOMY = 'magenta'
STYLE_SYSTEM_TAG_STATUS = 'blue'
STYLE_SYSTEM_TAG_SETTINGS = 'cyan'
STYLE_SYSTEM_TAG_SYSTEM = 'cyan'
STYLE_SYSTEM_TAG_TIMEOUT = 'yellow'
STYLE_SYSTEM_TAG_NOTE = 'cyan'

# ── Delegate worker row accents ────────────────────────────────────────────────
STYLE_DELEGATE_STARTING = 'cyan'
STYLE_DELEGATE_RUNNING = 'yellow'
STYLE_DELEGATE_DONE = 'green'
STYLE_DELEGATE_FAILED = 'red'

# ── Reasoning / thinking chrome ────────────────────────────────────────────────
CLR_SPINNER = '#7dd3fc'  # spinner icon
CLR_ACTION = 'bold #dbe7f3'  # current action label text
CLR_THINKING_BORDER = '#587487'  # reasoning / live panel border accent
CLR_THOUGHT_BODY = '#8b9eb5'  # thought lines (live panel)
CLR_REASONING_SNAP = 'italic #64748b dim'  # committed reasoning (transcript)
CLR_DRAFT_BORDER = '#6b8ea4'  # draft reply preview border accent
CLR_DECISION_BORDER = '#c4a35a'  # approval / question / options accent
CLR_USER_BORDER = 'dim cyan'  # user message panel border
CLR_STATE_RUNNING = '#93c5fd bold'  # running / active state badge
CLR_AUTONOMY_BALANCED = '#8bd8ff'  # balanced autonomy tag
CLR_AUTONOMY_FULL = '#f1bf63 bold'  # full autonomy tag
CLR_AUTONOMY_CONSERVATIVE = (
    '#f0a3ff bold'  # conservative autonomy (confirm every action)
)

# ── Section divider ────────────────────────────────────────────────────────────
CLR_SECTION_RULE = '#4a6b82'  # "Tools & commands" divider rule

# ── Confirmation UI ────────────────────────────────────────────────────────────
CLR_RISK_HIGH = 'bold red'
CLR_RISK_MEDIUM = 'yellow'
CLR_RISK_LOW = 'green'
CLR_RISK_ASK = 'yellow'

# ── Decision callouts (questions, options, escalations) ──────────────────────
# Question text and option labels live inside DECISION-bordered panels, so
# the body tones must harmonise with that amber accent rather than drift to
# raw ``yellow`` (which read as warnings) or stark white.
CLR_QUESTION_TEXT = '#e6c674'  # question / escalation prose body
CLR_OPTION_TEXT = '#e2e8f0'  # neutral option label body
CLR_OPTION_RECOMMENDED = '#f1bf63'  # recommended option marker

# ── Secondary panels (terminal output, recovery notice) ──────────────────────
CLR_OUTPUT_PANEL_BORDER = '#1e3a4a'  # nested terminal output panel
CLR_OUTPUT_PANEL_TITLE = 'dim #9ca3af'  # nested panel title (session id, lines)

# ── Reasoning / activity rule chrome ─────────────────────────────────────────
CLR_REASONING_COMMITTED = 'italic #7e99b5'  # snapshot block after spinner stops
CLR_TURN_RULE = 'dim #6d8596'  # "Activity" rule above first tool row
CLR_RECOVERY_HINT = 'cyan'  # "Next steps" headline body in recovery notice
CLR_RECOVERY_HINT_DIM = 'dim cyan'  # recovery body / numbered steps

# ── Splash branding ──────────────────────────────────────────────────────────
CLR_SPLASH_LOGO_ACCENT = 'red'  # logo block art (intentional brand mark)
CLR_SPLASH_FIGLET = 'bold red'  # large GRINTA wordmark on the splash

# ── prompt_toolkit (``Style.from_dict``) — keep in sync with Rich tokens above ---
PT_DEFAULT_FG = '#e6eef7'
PT_PLACEHOLDER_DIM = '#5d7286'
PT_FOOTER_BADGE_BRACKET = '#0e7490'
PT_FOOTER_BADGE_CORE = 'bold #22d3ee'
PT_FOOTER_KICKER = 'bold #a5f3fc'
PT_FOOTER_WARN_BRACKET = '#a16207'
PT_FOOTER_WARN_CORE = 'bold #facc15'
PT_FOOTER_WARN_KICKER = 'bold #fde68a'
PT_FOOTER_WARN_SEP = '#92400e'
PT_COMPLETION_MENU_BG = 'bg:#0d1f30 #b8c7d8'
PT_COMPLETION_MENU_CURRENT = 'bg:#1e4976 bold #ffffff'
PT_COMPLETION_META_BG = 'bg:#0a1929 #5c7fa0'
PT_COMPLETION_META_CURRENT = 'bg:#163350 #93c5fd'
PT_SCROLLBAR_BG = 'bg:#0d1f30'
PT_SCROLLBAR_BUTTON = 'bg:#1e4976'


def prompt_toolkit_style_dict() -> dict[str, str]:
    """Return ``Style.from_dict`` mapping; respects :func:`no_color_enabled`."""
    if no_color_enabled():
        return _prompt_toolkit_style_dict_no_color()
    return _prompt_toolkit_style_dict_color()


def _prompt_toolkit_style_dict_color() -> dict[str, str]:
    return {
        '': f'noreverse {PT_DEFAULT_FG}',
        'bottom-toolbar': 'noreverse',
        'bottom-toolbar.text': 'noreverse',
        'placeholder': f'italic {PT_PLACEHOLDER_DIM}',
        'prompt.border': CLR_THINKING_BORDER,
        'prompt.frame.border': f'bold {CLR_STATUS_OK}',
        'prompt.brand': CLR_BRAND,
        'prompt.dim': CLR_META,
        'prompt.model': CLR_HUD_MODEL,
        'prompt.value': CLR_HUD_DETAIL,
        'prompt.sep': CLR_SEP,
        'prompt.arrow': CLR_BRAND,
        'prompt.hint': CLR_AUTONOMY_FULL,
        'prompt.badge.ready': f'bold {CLR_STATUS_OK}',
        'prompt.badge.running': CLR_STATE_RUNNING,
        'prompt.badge.review': f'bold {CLR_STATUS_WARN}',
        'prompt.badge.paused': f'bold {CLR_STATUS_WARN}',
        'prompt.badge.error': f'bold {CLR_STATUS_ERR}',
        'prompt.autonomy.balanced': CLR_AUTONOMY_BALANCED,
        'prompt.autonomy.full': CLR_AUTONOMY_FULL,
        'prompt.autonomy.conservative': CLR_AUTONOMY_CONSERVATIVE,
        'prompt.health.good': f'bold {CLR_STATUS_OK}',
        'prompt.health.warn': f'bold {CLR_STATUS_WARN}',
        'prompt.health.bad': f'bold {CLR_STATUS_ERR}',
        'prompt.footer.badge_bracket': PT_FOOTER_BADGE_BRACKET,
        'prompt.footer.badge_core': PT_FOOTER_BADGE_CORE,
        'prompt.footer.kicker': PT_FOOTER_KICKER,
        'prompt.footer.sep': CLR_META,
        'prompt.footer.body': CLR_MUTED_TEXT,
        'prompt.footer.warn_bracket': PT_FOOTER_WARN_BRACKET,
        'prompt.footer.warn_core': PT_FOOTER_WARN_CORE,
        'prompt.footer.warn_kicker': PT_FOOTER_WARN_KICKER,
        'prompt.footer.warn_sep': PT_FOOTER_WARN_SEP,
        'prompt.footer.warn_body': CLR_STATUS_WARN,
        'completion-menu': PT_COMPLETION_MENU_BG,
        'completion-menu.completion': PT_COMPLETION_MENU_BG,
        'completion-menu.completion.current': PT_COMPLETION_MENU_CURRENT,
        'completion-menu.meta': PT_COMPLETION_META_BG,
        'completion-menu.meta.completion': PT_COMPLETION_META_BG,
        'completion-menu.meta.completion.current': PT_COMPLETION_META_CURRENT,
        'completion-menu.multi-column-meta': PT_COMPLETION_META_BG,
        'scrollbar.background': PT_SCROLLBAR_BG,
        'scrollbar.button': PT_SCROLLBAR_BUTTON,
    }


def _prompt_toolkit_style_dict_no_color() -> dict[str, str]:
    """ANSI-only styles when ``NO_COLOR`` is set (no hex in output)."""
    return {
        '': 'noreverse',
        'bottom-toolbar': 'noreverse',
        'bottom-toolbar.text': 'noreverse',
        'placeholder': 'italic dim',
        'prompt.border': 'bold',
        'prompt.frame.border': 'bold',
        'prompt.brand': 'bold',
        'prompt.dim': 'dim',
        'prompt.model': 'bold',
        'prompt.value': 'dim',
        'prompt.sep': 'dim',
        'prompt.arrow': 'bold',
        'prompt.hint': 'bold',
        'prompt.badge.ready': 'bold',
        'prompt.badge.running': 'bold',
        'prompt.badge.review': 'bold',
        'prompt.badge.paused': 'bold',
        'prompt.badge.error': 'bold',
        'prompt.autonomy.balanced': 'dim',
        'prompt.autonomy.full': 'bold',
        'prompt.autonomy.conservative': 'bold',
        'prompt.health.good': 'bold',
        'prompt.health.warn': 'bold',
        'prompt.health.bad': 'bold',
        'prompt.footer.badge_bracket': 'dim',
        'prompt.footer.badge_core': 'bold',
        'prompt.footer.kicker': 'bold',
        'prompt.footer.sep': 'dim',
        'prompt.footer.body': 'dim',
        'prompt.footer.warn_bracket': 'dim',
        'prompt.footer.warn_core': 'bold',
        'prompt.footer.warn_kicker': 'bold',
        'prompt.footer.warn_sep': 'dim',
        'prompt.footer.warn_body': 'bold',
        'completion-menu': 'noreverse',
        'completion-menu.completion': 'noreverse',
        'completion-menu.completion.current': 'bold underline',
        'completion-menu.meta': 'dim',
        'completion-menu.meta.completion': 'dim',
        'completion-menu.meta.completion.current': 'bold',
        'completion-menu.multi-column-meta': 'dim',
        'scrollbar.background': 'dim',
        'scrollbar.button': 'bold',
    }
