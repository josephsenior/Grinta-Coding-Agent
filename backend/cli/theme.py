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

_THEME_PRESET: str | None = None


def _env_truthy(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def no_color_enabled() -> bool:
    """Respect NO_COLOR and a Grinta-specific override."""
    return _env_truthy('NO_COLOR') or _env_truthy('GRINTA_NO_COLOR')


def set_theme_preset(name: str) -> None:
    """Override the active theme preset (must be called before imports)."""
    global _THEME_PRESET
    _THEME_PRESET = name


def get_theme_preset() -> str:
    """Return the active theme preset name.

    Check order: explicit set → ``GRINTA_THEME`` env var → ``deep-system-instrumentation``.
    """
    if _THEME_PRESET is not None:
        return _THEME_PRESET
    raw = (os.environ.get('GRINTA_THEME') or '').strip().lower()
    if raw in _THEME_PRESETS:
        return raw
    return 'deep-system-instrumentation'


_THEME_PRESETS = frozenset(
    {
        'default',
        'dark',
        'light',
        'high-contrast',
        'ocean',
        'mono',
        'deep-system-instrumentation',
    }
)


def _apply_theme_overrides() -> None:
    """Mutate module-level color constants based on the active preset."""
    preset = get_theme_preset()
    if preset in ('default', 'dark'):
        return

    global CLR_CARD_BORDER, CLR_META, CLR_BRAND, CLR_BRAND_HUE
    global CLR_STATUS_OK, CLR_STATUS_WARN, CLR_STATUS_ERR
    global CLR_HUD_MODEL, CLR_HUD_DETAIL, CLR_OK_BODY, CLR_OK_ICON
    global CLR_ERR_BODY, CLR_ERR_ICON, CLR_WARN_BODY, CLR_WARN_ICON
    global CLR_INFO_BODY, CLR_INFO_ICON, CLR_SEP, CLR_CARD_TITLE
    global CLR_THINKING_BORDER, CLR_LIVE_PANEL_BORDER, CLR_THOUGHT_BODY
    global CLR_SECTION_RULE, CLR_RISK_HIGH, CLR_RISK_MEDIUM, CLR_RISK_LOW
    global CLR_SPLASH_FIGLET, CLR_SPLASH_LOGO_ACCENT
    global CLR_WORKER_SPINNER, CLR_WORKER_TIMER, CLR_WORKER_LABEL, CLR_WORKER_ACTION
    global CLR_WORKER_LABEL_DONE, CLR_WORKER_LABEL_FAILED, CLR_WORKER_BORDER
    global STYLE_BOLD_DIM, CLR_MUTED_TEXT, CLR_VERB, CLR_DETAIL
    global CLR_SECONDARY, CLR_SECONDARY_OK, CLR_SECONDARY_ERR
    global CLR_DIFF_ADD, CLR_DIFF_REM, CLR_DIFF_ADD_DIM, CLR_DIFF_REM_DIM
    global MSG_STYLE_SUCCESS_MARK, MSG_STYLE_PROVIDER_HINT
    global STYLE_SYSTEM_TAG_WARNING, STYLE_SYSTEM_TAG_AUTONOMY
    global STYLE_SYSTEM_TAG_STATUS, STYLE_SYSTEM_TAG_SETTINGS
    global STYLE_SYSTEM_TAG_SYSTEM, STYLE_SYSTEM_TAG_TIMEOUT
    global STYLE_SYSTEM_TAG_NOTE
    global STYLE_DELEGATE_STARTING, STYLE_DELEGATE_RUNNING
    global STYLE_DELEGATE_DONE, STYLE_DELEGATE_FAILED
    global CLR_SPINNER, CLR_ACTION, CLR_DRAFT_BORDER, CLR_DECISION_BORDER
    global CLR_USER_BORDER, CLR_USER_BG, CLR_STATE_RUNNING
    global CLR_AUTONOMY_BALANCED, CLR_AUTONOMY_FULL, CLR_AUTONOMY_CONSERVATIVE
    global CLR_QUESTION_TEXT, CLR_OPTION_TEXT, CLR_OPTION_RECOMMENDED
    global CLR_OUTPUT_PANEL_BORDER, CLR_OUTPUT_PANEL_TITLE
    global CLR_RECOVERY_HINT, CLR_RECOVERY_HINT_DIM
    global PT_DEFAULT_FG, PT_PLACEHOLDER_DIM
    global PT_FOOTER_BADGE_BRACKET, PT_FOOTER_BADGE_CORE, PT_FOOTER_KICKER
    global PT_FOOTER_WARN_BRACKET, PT_FOOTER_WARN_CORE, PT_FOOTER_WARN_KICKER
    global PT_FOOTER_WARN_SEP
    global PT_COMPLETION_MENU_BG, PT_COMPLETION_MENU_CURRENT
    global PT_COMPLETION_META_BG, PT_COMPLETION_META_CURRENT
    global PT_SCROLLBAR_BG, PT_SCROLLBAR_BUTTON

    if preset == 'light':
        CLR_CARD_BORDER = '#6b8ba0'
        CLR_META = '#5a7285'
        CLR_BRAND = 'bold #0369a1'
        CLR_BRAND_HUE = '#0369a1'
        CLR_STATUS_OK = '#15803d'
        CLR_STATUS_WARN = '#b45309'
        CLR_STATUS_ERR = '#b91c1c'
        CLR_HUD_MODEL = 'bold #0f172a'
        CLR_HUD_DETAIL = '#334155'
        CLR_OK_BODY = '#15803d'
        CLR_OK_ICON = 'bold #166534'
        CLR_ERR_BODY = '#b91c1c'
        CLR_ERR_ICON = 'bold #991b1b'
        CLR_WARN_BODY = '#b45309'
        CLR_WARN_ICON = 'bold #92400e'
        CLR_INFO_BODY = '#1d4ed8'
        CLR_INFO_ICON = 'bold #1e40af'
        CLR_SEP = '#64748b'
        CLR_CARD_TITLE = 'bold #1e293b'
        CLR_THINKING_BORDER = '#94a3b8'
        CLR_LIVE_PANEL_BORDER = '#cbd5e1'
        CLR_THOUGHT_BODY = '#64748b'
        CLR_SECTION_RULE = '#94a3b8'
        CLR_RISK_HIGH = 'bold #dc2626'
        CLR_RISK_MEDIUM = '#ca8a04'
        CLR_RISK_LOW = '#16a34a'
        CLR_SPLASH_FIGLET = 'bold #b91c1c'
        CLR_SPLASH_LOGO_ACCENT = '#b91c1c'
        STYLE_BOLD_DIM = 'bold #475569'
        CLR_USER_BG = 'on #f8fafc'

    elif preset == 'high-contrast':
        CLR_CARD_BORDER = 'white'
        CLR_META = 'white'
        CLR_BRAND = 'bold white'
        CLR_BRAND_HUE = 'white'
        CLR_STATUS_OK = 'bold green'
        CLR_STATUS_WARN = 'bold yellow'
        CLR_STATUS_ERR = 'bold red'
        CLR_HUD_MODEL = 'bold white'
        CLR_HUD_DETAIL = 'white'
        CLR_OK_BODY = 'green'
        CLR_OK_ICON = 'bold green'
        CLR_ERR_BODY = 'red'
        CLR_ERR_ICON = 'bold red'
        CLR_WARN_BODY = 'yellow'
        CLR_WARN_ICON = 'bold yellow'
        CLR_INFO_BODY = 'cyan'
        CLR_INFO_ICON = 'bold cyan'
        CLR_SEP = 'white'
        CLR_CARD_TITLE = 'bold white'
        CLR_THINKING_BORDER = 'white'
        CLR_LIVE_PANEL_BORDER = 'bright_black'
        CLR_THOUGHT_BODY = 'bright_black'
        CLR_SECTION_RULE = 'white'
        CLR_RISK_HIGH = 'bold red'
        CLR_RISK_MEDIUM = 'bold yellow'
        CLR_RISK_LOW = 'bold green'
        CLR_SPLASH_FIGLET = 'bold white'
        CLR_SPLASH_LOGO_ACCENT = 'white'
        STYLE_BOLD_DIM = 'bold white'
        CLR_USER_BG = ''

    elif preset == 'ocean':
        CLR_CARD_BORDER = '#4895d6'
        CLR_META = '#7eb8da'
        CLR_BRAND = 'bold #00b4d8'
        CLR_BRAND_HUE = '#00b4d8'
        CLR_STATUS_OK = '#2dd4bf'
        CLR_STATUS_WARN = '#fbbf24'
        CLR_STATUS_ERR = '#fb7185'
        CLR_HUD_MODEL = 'bold #e0f2fe'
        CLR_HUD_DETAIL = '#bae6fd'
        CLR_OK_BODY = '#5eead4'
        CLR_OK_ICON = 'bold #14b8a6'
        CLR_ERR_BODY = '#fda4af'
        CLR_ERR_ICON = 'bold #f43f5e'
        CLR_WARN_BODY = '#fde047'
        CLR_WARN_ICON = 'bold #eab308'
        CLR_INFO_BODY = '#7dd3fc'
        CLR_INFO_ICON = 'bold #0ea5e9'
        CLR_SEP = '#6b9fc4'
        CLR_CARD_TITLE = 'bold #bae6fd'
        CLR_THINKING_BORDER = '#3b82f6'
        CLR_LIVE_PANEL_BORDER = '#1e3a5f'
        CLR_THOUGHT_BODY = '#6096b4'
        CLR_SECTION_RULE = '#3b82f6'
        CLR_RISK_HIGH = 'bold #f43f5e'
        CLR_RISK_MEDIUM = '#eab308'
        CLR_RISK_LOW = '#22d3ee'
        CLR_SPLASH_FIGLET = 'bold #0ea5e9'
        CLR_SPLASH_LOGO_ACCENT = '#0ea5e9'
        STYLE_BOLD_DIM = 'bold #7dd3fc'
        CLR_USER_BG = 'on #0f1c2e'

    elif preset == 'mono':
        CLR_CARD_BORDER = 'bright_black'
        CLR_META = 'bright_black'
        CLR_BRAND = 'bold white'
        CLR_BRAND_HUE = 'white'
        CLR_STATUS_OK = 'green'
        CLR_STATUS_WARN = 'yellow'
        CLR_STATUS_ERR = 'red'
        CLR_HUD_MODEL = 'bold white'
        CLR_HUD_DETAIL = 'white'
        CLR_OK_BODY = 'green'
        CLR_OK_ICON = 'bold green'
        CLR_ERR_BODY = 'red'
        CLR_ERR_ICON = 'bold red'
        CLR_WARN_BODY = 'yellow'
        CLR_WARN_ICON = 'bold yellow'
        CLR_INFO_BODY = 'cyan'
        CLR_INFO_ICON = 'bold cyan'
        CLR_SEP = 'bright_black'
        CLR_CARD_TITLE = 'bold white'
        CLR_THINKING_BORDER = 'bright_black'
        CLR_LIVE_PANEL_BORDER = 'bright_black'
        CLR_THOUGHT_BODY = 'bright_black'
        CLR_SECTION_RULE = 'bright_black'
        CLR_RISK_HIGH = 'bold red'
        CLR_RISK_MEDIUM = 'bold yellow'
        CLR_RISK_LOW = 'bold green'
        CLR_SPLASH_FIGLET = 'bold white'
        CLR_SPLASH_LOGO_ACCENT = 'white'
        STYLE_BOLD_DIM = 'bold white'
        CLR_USER_BG = ''

    elif preset == 'deep-system-instrumentation':
        # "Deep System Instrumentation" — Dolphie-inspired aesthetic.
        # Deep navy backgrounds, periwinkle blue accents, blue-white text
        # hierarchy, muted semantic colors. Designed for long coding sessions.
        CLR_CARD_BORDER = '#1b233a'
        CLR_META = '#969aad'
        CLR_BRAND = 'bold #91abec'
        CLR_BRAND_HUE = '#91abec'
        CLR_STATUS_OK = '#54efae'
        CLR_STATUS_WARN = '#f6ff8f'
        CLR_STATUS_ERR = '#fd8383'
        CLR_HUD_MODEL = 'bold #e9e9e9'
        CLR_HUD_DETAIL = '#969aad'
        CLR_OK_BODY = '#54efae'
        CLR_OK_ICON = 'bold #54efae'
        CLR_ERR_BODY = '#fd8383'
        CLR_ERR_ICON = 'bold #fd8383'
        CLR_WARN_BODY = '#f6ff8f'
        CLR_WARN_ICON = 'bold #f6ff8f'
        CLR_INFO_BODY = '#91abec'
        CLR_INFO_ICON = 'bold #91abec'
        CLR_SEP = '#1b233a'
        CLR_CARD_TITLE = 'bold #91abec'
        CLR_THINKING_BORDER = '#1b233a'
        CLR_LIVE_PANEL_BORDER = '#1b233a'
        CLR_THOUGHT_BODY = '#8f9fc1'
        CLR_SECTION_RULE = '#32416a'
        CLR_RISK_HIGH = 'bold #fd8383'
        CLR_RISK_MEDIUM = '#f6ff8f'
        CLR_RISK_LOW = '#54efae'
        CLR_SPLASH_FIGLET = 'bold #91abec'
        CLR_SPLASH_LOGO_ACCENT = '#91abec'
        CLR_VERB = 'bold #91abec'
        CLR_DETAIL = '#e9e9e9'
        CLR_SECONDARY = '#969aad'
        CLR_SECONDARY_OK = 'dim #54efae'
        CLR_SECONDARY_ERR = 'dim #fd8383'
        CLR_DIFF_ADD = '#54efae'
        CLR_DIFF_REM = '#fd8383'
        CLR_DIFF_ADD_DIM = 'dim #54efae'
        CLR_DIFF_REM_DIM = 'dim #fd8383'
        MSG_STYLE_SUCCESS_MARK = 'bold #54efae'
        MSG_STYLE_PROVIDER_HINT = '#91abec'
        STYLE_SYSTEM_TAG_WARNING = '#f6ff8f'
        STYLE_SYSTEM_TAG_AUTONOMY = '#91abec'
        STYLE_SYSTEM_TAG_STATUS = '#54efae'
        STYLE_SYSTEM_TAG_SETTINGS = '#91abec'
        STYLE_SYSTEM_TAG_SYSTEM = '#91abec'
        STYLE_SYSTEM_TAG_TIMEOUT = '#f6ff8f'
        STYLE_SYSTEM_TAG_NOTE = '#91abec'
        STYLE_DELEGATE_STARTING = '#91abec'
        STYLE_DELEGATE_RUNNING = '#f6ff8f'
        STYLE_DELEGATE_DONE = '#54efae'
        STYLE_DELEGATE_FAILED = '#fd8383'
        CLR_WORKER_SPINNER = '#91abec'
        CLR_WORKER_TIMER = '#969aad'
        CLR_WORKER_LABEL = 'bold #e9e9e9'
        CLR_WORKER_ACTION = '#969aad'
        CLR_WORKER_LABEL_DONE = 'bold #54efae'
        CLR_WORKER_LABEL_FAILED = 'bold #fd8383'
        CLR_WORKER_BORDER = '#1b233a'
        CLR_SPINNER = '#91abec'
        CLR_ACTION = 'bold #e9e9e9'
        CLR_DRAFT_BORDER = '#91abec'
        CLR_DECISION_BORDER = '#f6ff8f'
        CLR_USER_BORDER = 'dim #91abec'
        CLR_USER_BG = 'on #131724'
        CLR_STATE_RUNNING = '#91abec bold'
        CLR_AUTONOMY_BALANCED = '#54efae'
        CLR_AUTONOMY_FULL = '#f6ff8f bold'
        CLR_AUTONOMY_CONSERVATIVE = '#91abec bold'
        CLR_QUESTION_TEXT = '#f6ff8f'
        CLR_OPTION_TEXT = '#e9e9e9'
        CLR_OPTION_RECOMMENDED = '#f6ff8f'
        CLR_OUTPUT_PANEL_BORDER = '#1b233a'
        CLR_OUTPUT_PANEL_TITLE = 'dim #969aad'
        CLR_RECOVERY_HINT = '#91abec'
        CLR_RECOVERY_HINT_DIM = 'dim #91abec'
        STYLE_BOLD_DIM = 'bold #969aad'
        CLR_MUTED_TEXT = '#1b233a'

        # prompt_toolkit overrides
        PT_DEFAULT_FG = '#e9e9e9'
        PT_PLACEHOLDER_DIM = '#1b233a'
        PT_FOOTER_BADGE_BRACKET = '#1b233a'
        PT_FOOTER_BADGE_CORE = 'bold #91abec'
        PT_FOOTER_KICKER = 'bold #91abec'
        PT_FOOTER_WARN_BRACKET = '#3d1f1f'
        PT_FOOTER_WARN_CORE = 'bold #f6ff8f'
        PT_FOOTER_WARN_KICKER = 'bold #f6ff8f'
        PT_FOOTER_WARN_SEP = '#3d1f1f'
        PT_COMPLETION_MENU_BG = 'bg:#060a14 #969aad'
        PT_COMPLETION_MENU_CURRENT = 'bg:#1b233a bold #91abec'
        PT_COMPLETION_META_BG = 'bg:#060a14 #969aad'
        PT_COMPLETION_META_CURRENT = 'bg:#1b233a #91abec'
        PT_SCROLLBAR_BG = 'bg:#060a14'
        PT_SCROLLBAR_BUTTON = 'bg:#1b233a'


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


def accessible_mode_enabled() -> bool:
    """When true, enable high-contrast/simplified UI for accessibility.

    Controlled by the ``GRINTA_ACCESSIBLE`` env var.

    Accessible mode disables animations, disables color (via ``NO_COLOR``),
    forces ASCII symbols, and uses simplified layouts suitable for screen
    readers and low-vision users.
    """
    return _env_truthy('GRINTA_ACCESSIBLE')


# ── "Deep System Instrumentation" Default Palette ──────────────────────────
# Inspired by command-center / mission-control TUIs — NASA, radar, HFT desks.
# Deep Navy (#0a0e14) background, Teal (#5fb3b3) accents, Muted Emerald
# (#99c794) for success, Soft Coral (#ec5f67) for errors.
# Designed for long coding sessions with minimal eye strain.

# ── Backgrounds ────────────────────────────────────────────────────────────────
HUD_BG = '#0f1525'  # HUD footer background (slightly lighter than main bg)

# ── Separators & borders ───────────────────────────────────────────────────────
CLR_SEP = '#1b233a'  # bullet separator and lightweight dividers
CLR_CARD_BORDER = '#1b233a'  # rounded card / panel border (navy)

# ── HUD display text ──────────────────────────────────────────────────────────
CLR_HUD_MODEL = 'bold #e9e9e9'  # model name (near-white)
CLR_HUD_DETAIL = '#969aad'  # tokens, cost, calls (cool gray)
CLR_META = '#969aad'  # subdued metadata, timers, helper text
CLR_MUTED_TEXT = '#1b233a'  # long-form secondary labels / values
# Brand — periwinkle blue for instrumentation feel.
CLR_BRAND = 'bold #91abec'  # GRINTA wordmark / active spinner hue
CLR_BRAND_HUE = '#91abec'  # brand blue without bold modifier

# ── Status semantic colors (HUD ledger / footer badges) ──────────────────────
CLR_STATUS_OK = '#54efae'  # Healthy / Ready (bright green)
CLR_STATUS_WARN = '#f6ff8f'  # Review / Paused (lime yellow)
CLR_STATUS_ERR = '#fd8383'  # Error (soft red)

# ── Result tones (paired body/icon hues for activity rows + tone panels) ─────
CLR_OK_BODY = '#54efae'  # success body text
CLR_OK_ICON = 'bold #54efae'  # success icon / accent
CLR_ERR_BODY = '#fd8383'  # error body text
CLR_ERR_ICON = 'bold #fd8383'  # error icon / accent
CLR_WARN_BODY = '#f6ff8f'  # warning body text
CLR_WARN_ICON = 'bold #f6ff8f'  # warning icon / accent
CLR_INFO_BODY = '#91abec'  # info body text
CLR_INFO_ICON = 'bold #91abec'  # info icon / accent

# ── Shell output chrome ────────────────────────────────────────────────────────
CLR_SHELL_OUTPUT = '#6b7280'  # shell command output text (dim gray)
CLR_SHELL_BORDER = '#374151'  # shell output left border line

# ── Shared UI markers (keep iconography consistent) ───────────────────────────
MARK_OK = '✓'
MARK_ERR = '✗'
MARK_WARN = '⚠'
MARK_INFO = '•'
MARK_PROMPT = '❯'

# ── Shared Rich style aliases (avoid scattered literals) ─────────────────────
STYLE_DIM = 'dim'
STYLE_DEFAULT = 'default'
STYLE_BOLD = 'bold'
STYLE_BOLD_DIM = 'bold #969aad'
STYLE_ITALIC_DIM = 'dim italic'
STYLE_EMPTY = ''

# ── Activity card chrome ──────────────────────────────────────────────────────
CLR_CARD_TITLE = 'bold #91abec'  # panel title text (periwinkle blue)

# ── Activity row text ─────────────────────────────────────────────────────────
CLR_VERB = 'bold #91abec'  # action verb (periwinkle blue)
CLR_DETAIL = '#e9e9e9'  # action detail (near-white)
CLR_SECONDARY = '#969aad'  # secondary row (cool gray)
CLR_SECONDARY_OK = 'dim #54efae'  # secondary row (success)
CLR_SECONDARY_ERR = 'dim #fd8383'  # secondary row (error)

# ── Diff colors ───────────────────────────────────────────────────────────────
CLR_DIFF_ADD = '#54efae'  # added lines (bright green)
CLR_DIFF_REM = '#fd8383'  # removed lines (soft red)
CLR_DIFF_ADD_DIM = 'dim #54efae'  # apply_patch +N delta (secondary line)
CLR_DIFF_REM_DIM = 'dim #fd8383'  # apply_patch -N delta

# ── Inline Rich markup (prefer these over raw [red] / [green] in prose) ───────
MSG_STYLE_SUCCESS_MARK = 'bold #54efae'  # short ✓ success flashes (onboarding)
MSG_STYLE_PROVIDER_HINT = '#91abec'  # provider name in onboarding lines

# ── System message tags (panels / notices) ────────────────────────────────────
STYLE_SYSTEM_TAG_WARNING = '#f6ff8f'
STYLE_SYSTEM_TAG_AUTONOMY = '#91abec'
STYLE_SYSTEM_TAG_STATUS = '#54efae'
STYLE_SYSTEM_TAG_SETTINGS = '#91abec'
STYLE_SYSTEM_TAG_SYSTEM = '#91abec'
STYLE_SYSTEM_TAG_TIMEOUT = '#f6ff8f'
STYLE_SYSTEM_TAG_NOTE = '#91abec'

# ── Delegate worker row accents ────────────────────────────────────────────────
STYLE_DELEGATE_STARTING = '#91abec'
STYLE_DELEGATE_RUNNING = '#f6ff8f'
STYLE_DELEGATE_DONE = '#54efae'
STYLE_DELEGATE_FAILED = '#fd8383'

# ── Worker live-panel chrome (spinner, timer, action text) ────────────────────
CLR_WORKER_SPINNER = '#91abec'  # spinner during delegation (matches brand blue)
CLR_WORKER_TIMER = '#969aad'  # worker elapsed timer
CLR_WORKER_LABEL = 'bold #e9e9e9'  # worker name/label
CLR_WORKER_ACTION = '#969aad'  # last action / reasoning line
CLR_WORKER_LABEL_DONE = 'bold #54efae'  # completed worker label
CLR_WORKER_LABEL_FAILED = 'bold #fd8383'  # failed worker label
CLR_WORKER_BORDER = '#1b233a'  # worker card border (navy)

# ── Reasoning / thinking chrome ────────────────────────────────────────────────
CLR_SPINNER = '#91abec'  # spinner icon (matches brand blue)
CLR_ACTION = 'bold #e9e9e9'  # current action label text
CLR_THINKING_BORDER = '#1b233a'  # reasoning / live panel border accent (navy)
CLR_LIVE_PANEL_BORDER = '#1b233a'  # Live Rich block border
CLR_THOUGHT_BODY = '#8f9fc1'  # Live Thinking + flushed reasoning snapshot (dim blue)
CLR_REASONING_SNAP = CLR_THOUGHT_BODY  # legacy alias; keep in sync
CLR_DRAFT_BORDER = '#91abec'  # draft reply preview border accent (brand blue)
CLR_DECISION_BORDER = '#f6ff8f'  # approval / question / options accent (lime yellow)
CLR_USER_BORDER = 'dim #91abec'  # user message panel border (brand blue dim)
CLR_USER_BG = 'on #131724'  # user message panel background
CLR_STATE_RUNNING = '#91abec bold'  # running / active state badge (brand blue)
CLR_AUTONOMY_BALANCED = '#54efae'  # balanced autonomy tag
CLR_AUTONOMY_FULL = '#f6ff8f bold'  # full autonomy tag (lime yellow)
CLR_AUTONOMY_CONSERVATIVE = '#91abec bold'  # conservative autonomy (blue)

# ── Section divider ────────────────────────────────────────────────────────────
CLR_SECTION_RULE = '#32416a'  # "Tools & commands" divider rule

# ── Confirmation UI ────────────────────────────────────────────────────────────
CLR_RISK_HIGH = 'bold #fd8383'
CLR_RISK_MEDIUM = '#f6ff8f'
CLR_RISK_LOW = '#54efae'
CLR_RISK_ASK = '#f6ff8f'

# ── Decision callouts (questions, options, escalations) ──────────────────────
CLR_QUESTION_TEXT = '#f6ff8f'  # question / escalation prose body
CLR_OPTION_TEXT = '#e9e9e9'  # neutral option label body
CLR_OPTION_RECOMMENDED = '#f6ff8f'  # recommended option marker

# ── Secondary panels (terminal output, recovery notice) ──────────────────────
CLR_OUTPUT_PANEL_BORDER = '#1b233a'  # nested terminal output panel
CLR_OUTPUT_PANEL_TITLE = 'dim #969aad'  # nested panel title (session id, lines)

# ── Reasoning / activity rule chrome ─────────────────────────────────────────
CLR_REASONING_COMMITTED = CLR_THOUGHT_BODY  # transcript snapshot (same as live body)
CLR_TURN_RULE = 'dim #969aad'  # "Activity" rule above first tool row
CLR_RECOVERY_HINT = '#91abec'  # "Next steps" headline body in recovery notice
CLR_RECOVERY_HINT_DIM = 'dim #91abec'  # recovery body / numbered steps

# ── Splash branding ──────────────────────────────────────────────────────────
CLR_SPLASH_LOGO_ACCENT = '#91abec'  # logo block art (brand blue)
CLR_SPLASH_FIGLET = 'bold #91abec'  # large GRINTA wordmark on the splash (blue)

# ── prompt_toolkit (``Style.from_dict``) — keep in sync with Rich tokens above ---
PT_DEFAULT_FG = '#e9e9e9'
PT_PLACEHOLDER_DIM = '#1b233a'
PT_FOOTER_BADGE_BRACKET = '#1b233a'
PT_FOOTER_BADGE_CORE = 'bold #91abec'
PT_FOOTER_KICKER = 'bold #91abec'
PT_FOOTER_WARN_BRACKET = '#3d1f1f'
PT_FOOTER_WARN_CORE = 'bold #f6ff8f'
PT_FOOTER_WARN_KICKER = 'bold #f6ff8f'
PT_FOOTER_WARN_SEP = '#3d1f1f'
PT_COMPLETION_MENU_BG = 'bg:#0f1525 #969aad'
PT_COMPLETION_MENU_CURRENT = 'bg:#1b233a bold #91abec'
PT_COMPLETION_META_BG = 'bg:#0a0e1b #969aad'
PT_COMPLETION_META_CURRENT = 'bg:#1b233a #91abec'
PT_SCROLLBAR_BG = 'bg:#0a0e1b'
PT_SCROLLBAR_BUTTON = 'bg:#1b233a'


# ── Navy TUI Palette ──────────────────────────────────────────────────────────
# Deep Navy theme for the Textual TUI — Dolphie-inspired aesthetic.
# Uniform deep navy background — all widgets share the same color.
# Designed for long coding sessions with minimal eye strain.

# Backgrounds (uniform — all surfaces share the same deep navy)
NAVY_BG = '#060a14'  # deepest background (screen root)
NAVY_SURFACE = '#060a14'  # panels, cards, containers — uniform with bg
NAVY_SURFACE_RISING = '#060a14'  # elevated surfaces — uniform with bg
NAVY_SURFACE_TOP = '#060a14'  # topbar, footerbar background — uniform with bg
NAVY_MODAL_BG = '#060a14'  # modal screen background — uniform with bg
NAVY_MODAL_OVERLAY = '#0d1015'  # semi-transparent modal overlay

# Borders (muted blue spectrum — subtle but visible)
NAVY_BORDER = '#1b233a'  # structural dividers / panel borders
NAVY_BORDER_BRIGHT = '#384673'  # active/focused borders, modal borders
NAVY_BORDER_INPUT = '#252e49'  # input field default border
NAVY_BORDER_INPUT_FOCUS = '#43548b'  # input field focused border
NAVY_BORDER_HIGHLIGHT = '#32416a'  # rules, dividers

# Text hierarchy (blue-white spectrum: primary → secondary → muted → disabled)
NAVY_TEXT_PRIMARY = '#e9e9e9'  # readable body text (near-white)
NAVY_TEXT_SECONDARY = '#bbc8e8'  # panel titles, labels (light blue)
NAVY_TEXT_TERTIARY = '#c5c7d2'  # headers, secondary labels (cool gray)
NAVY_TEXT_MUTED = '#969aad'  # disabled, placeholder text
NAVY_TEXT_DIM = '#8f9fc1'  # help text, timestamps

# Accent — periwinkle blue (primary interactive highlight)
NAVY_BRAND = '#91abec'  # primary accent — periwinkle blue
NAVY_BRAND_DIM = '#6171a6'  # secondary accent (muted periwinkle)

# Status semantic colors
NAVY_READY = '#54efae'  # green — Ready / Success / Healthy
NAVY_RUNNING = '#91abec'  # periwinkle — Running / Processing
NAVY_WAITING = '#f6ff8f'  # lime yellow — Review / Paused / Warning
NAVY_ERROR = '#fd8383'  # soft red — Error / Danger

# Status accents (for borders, badges, toast accents)
NAVY_GREEN_ACCENT = '#5bd088'  # success toast/border accent
NAVY_RED_ACCENT = '#f05757'  # error toast/border accent
NAVY_YELLOW_ACCENT = '#f0e357'  # warning toast/border accent
NAVY_PURPLE_ACCENT = '#b565f3'  # tertiary accent (purple)

# Scrollbar (3-state: default → hover → active)
NAVY_SCROLLBAR_TRACK = '#161e31'  # scrollbar track background
NAVY_SCROLLBAR_THUMB = '#33405d'  # scrollbar thumb default
NAVY_SCROLLBAR_HOVER = '#404f71'  # scrollbar thumb hover
NAVY_SCROLLBAR_ACTIVE = '#4f608a'  # scrollbar thumb active/drag

# Button (3D raised effect: lighter top, darker bottom)
NAVY_BUTTON_BG = '#282c42'  # default button background
NAVY_BUTTON_BG_HOVER = '#383e5c'  # button hover background
NAVY_BUTTON_BORDER_TOP = '#54597b'  # button top edge (lighter — 3D)
NAVY_BUTTON_BORDER_BOTTOM = '#171922'  # button bottom edge (darker — 3D)
NAVY_BUTTON_PRIMARY_BG = '#192c5b'  # primary button background
NAVY_BUTTON_PRIMARY_HOVER = '#203875'  # primary button hover
NAVY_BUTTON_PRIMARY_BORDER_TOP = '#425894'  # primary button top accent

# Interactive states
NAVY_OPTION_HIGHLIGHTED = '#22293e'  # keyboard-highlighted option bg
NAVY_OPTION_HIGHLIGHTED_TEXT = '#9babd4'  # highlighted option text
NAVY_OPTION_HOVER = '#35405f'  # mouse-hovered option bg
NAVY_OPTION_HOVER_TEXT = '#cbdbfe'  # hovered option text

# Sparkline (for future metric graphs)
NAVY_SPARKLINE_MAX = '#869fd9'  # sparkline peak
NAVY_SPARKLINE_MIN = '#384c7a'  # sparkline valley

# Loading indicator
NAVY_LOADING = '#8fb0ee'  # loading spinner color

# Progress bar
NAVY_PROGRESS_BAR = '#91abec'  # progress bar fill
NAVY_PROGRESS_BG = '#3a3f51'  # progress bar track
NAVY_PROGRESS_COMPLETE = '#54efae'  # completed progress bar

# Legacy aliases (keep backward compatibility during transition)
NAVY_READY_OLD = '#99c794'  # old green — used in theme.py presets
NAVY_RUNNING_OLD = '#5fb3b3'  # old teal


# Apply theme preset overrides after all constants are defined.
_apply_theme_overrides()


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
