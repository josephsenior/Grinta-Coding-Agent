"""Centralized visual theme tokens for Grinta CLI.

All color and style constants used across CLI components are defined here.
Import from this module instead of scattering raw hex values through files.
"""

from __future__ import annotations

# ── Backgrounds ────────────────────────────────────────────────────────────────
HUD_BG = 'grey15'                       # HUD footer background

# ── Separators & borders ───────────────────────────────────────────────────────
CLR_SEP = '#3a5368'                     # · bullet separator and lightweight dividers
CLR_CARD_BORDER = '#435f73'            # rounded card / panel border (blue-gray)

# ── HUD display text ──────────────────────────────────────────────────────────
CLR_HUD_MODEL = 'bold #dbe7f3'          # model name (bright)
CLR_HUD_DETAIL = '#b4c4d5'             # tokens, cost, calls (secondary)
CLR_META = '#5d7286'                   # subdued metadata, timers, helper text
CLR_MUTED_TEXT = '#94a3b8'             # long-form secondary labels / values
CLR_BRAND = 'bold #7dd3fc'             # GRINTA wordmark / active spinner hue

# ── Status semantic colors ────────────────────────────────────────────────────
CLR_STATUS_OK = '#8fdfb1'              # Healthy / Ready (green)
CLR_STATUS_WARN = '#fcd34d'            # Review / Paused (yellow)
CLR_STATUS_ERR = '#fca5a5'             # Error (red-pink)

# ── Activity card chrome ──────────────────────────────────────────────────────
CLR_CARD_TITLE = 'bold #8fa5b6'        # panel title text (gray-blue)

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
CLR_THINKING_BORDER = '#587487'        # reasoning / live panel border accent
CLR_THOUGHT_BODY = '#8b9eb5'           # thought lines (live panel)
CLR_REASONING_SNAP = 'italic #64748b dim'  # committed reasoning (transcript)
CLR_DRAFT_BORDER = '#6b8ea4'           # draft reply preview border accent
CLR_DECISION_BORDER = '#c4a35a'        # approval / question / options accent
CLR_USER_BORDER = 'dim cyan'           # user message panel border
CLR_STATE_RUNNING = '#93c5fd bold'     # running / active state badge
CLR_AUTONOMY_BALANCED = '#8bd8ff'      # balanced autonomy tag
CLR_AUTONOMY_FULL = '#f1bf63 bold'     # full autonomy tag
CLR_AUTONOMY_SUPERVISED = '#f0a3ff bold'  # supervised autonomy tag

# ── Section divider ────────────────────────────────────────────────────────────
CLR_SECTION_RULE = '#4a6b82'           # "Tools & commands" divider rule

# ── Confirmation UI ────────────────────────────────────────────────────────────
CLR_RISK_HIGH = 'bold red'
CLR_RISK_MEDIUM = 'yellow'
CLR_RISK_LOW = 'green'
CLR_RISK_ASK = 'yellow'
