"""Centralized visual theme tokens for Grinta CLI.

All color and style constants used across CLI components are defined here.
Import from this module instead of scattering raw hex values through files.
"""

from __future__ import annotations

# ── Backgrounds ────────────────────────────────────────────────────────────────
HUD_BG = 'grey15'                       # HUD footer background

# ── Separators & borders ───────────────────────────────────────────────────────
CLR_SEP = '#3a5368'                     # · bullet separator and card borders

# ── HUD display text ──────────────────────────────────────────────────────────
CLR_HUD_MODEL = 'bold #dbe7f3'          # model name (bright)
CLR_HUD_DETAIL = '#b4c4d5'             # tokens, cost, calls (secondary)

# ── Status semantic colors ────────────────────────────────────────────────────
CLR_STATUS_OK = '#8fdfb1'              # Healthy / Ready (green)
CLR_STATUS_WARN = '#fcd34d'            # Review / Paused (yellow)
CLR_STATUS_ERR = '#fca5a5'             # Error (red-pink)

# ── Activity card chrome ──────────────────────────────────────────────────────
CLR_CARD_TITLE = 'bold #9ca3af'        # panel title text (gray)
CLR_CARD_BORDER = '#3a5368'            # panel border (blue-gray)

# ── Activity row text ─────────────────────────────────────────────────────────
CLR_VERB = 'dim'                        # action verb (muted)
CLR_DETAIL = 'default'                  # action detail (normal foreground)
CLR_SECONDARY = 'dim'                   # secondary row (neutral)
CLR_SECONDARY_OK = 'dim green'         # secondary row (success)
CLR_SECONDARY_ERR = 'dim red'          # secondary row (error)

# ── Diff colors ───────────────────────────────────────────────────────────────
CLR_DIFF_ADD = 'green'                 # added lines
CLR_DIFF_REM = 'red'                   # removed lines

# ── Reasoning / thinking chrome ────────────────────────────────────────────────
CLR_SPINNER = '#7dd3fc'                # spinner icon
CLR_ACTION = 'bold #dbe7f3'            # current action label text
CLR_META = '#5d7286'                   # elapsed time, cost hint
CLR_THINKING_BORDER = '#4a6b82'        # reasoning panel border accent
CLR_THOUGHT_BODY = '#8b9eb5 dim'       # thought lines (live panel)
CLR_REASONING_SNAP = 'italic #64748b dim'  # committed reasoning (transcript)

# ── Section divider ────────────────────────────────────────────────────────────
CLR_SECTION_RULE = '#4a6b82'           # "Tools & commands" divider rule

# ── Confirmation UI ────────────────────────────────────────────────────────────
CLR_RISK_HIGH = 'bold red'
CLR_RISK_MEDIUM = 'yellow'
CLR_RISK_LOW = 'green'
CLR_RISK_ASK = 'yellow'
