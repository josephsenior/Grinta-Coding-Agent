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

# ── Backgrounds ────────────────────────────────────────────────────────────────
HUD_BG = 'grey15'  # HUD footer background

# ── Separators & borders ───────────────────────────────────────────────────────
CLR_SEP = '#3a5368'  # · bullet separator and lightweight dividers
CLR_CARD_BORDER = '#435f73'  # rounded card / panel border (blue-gray)

# ── HUD display text ──────────────────────────────────────────────────────────
CLR_HUD_MODEL = 'bold #dbe7f3'  # model name (bright)
CLR_HUD_DETAIL = '#b4c4d5'  # tokens, cost, calls (secondary)
CLR_META = '#5d7286'  # subdued metadata, timers, helper text
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

# ── Activity card chrome ──────────────────────────────────────────────────────
CLR_CARD_TITLE = 'bold #8fa5b6'  # panel title text (gray-blue)

# ── Activity row text ─────────────────────────────────────────────────────────
CLR_VERB = 'dim'  # action verb (muted)
CLR_DETAIL = 'default'  # action detail (normal foreground)
CLR_SECONDARY = 'dim'  # secondary row (neutral)
CLR_SECONDARY_OK = 'dim green'  # secondary row (success)
CLR_SECONDARY_ERR = 'dim red'  # secondary row (error)

# ── Diff colors ───────────────────────────────────────────────────────────────
CLR_DIFF_ADD = 'green'  # added lines
CLR_DIFF_REM = 'red'  # removed lines

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
