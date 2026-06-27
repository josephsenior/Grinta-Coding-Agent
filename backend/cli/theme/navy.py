"""Textual TUI navy palette tokens.

Import from this module instead of scattering raw hex values through files.
New tokens should be added here (or in ``tokens.py``) and referenced by name.
"""

from __future__ import annotations

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
NAVY_DIVIDER = '#1e293b'  # secondary structural divider (sidebar, detail header)

# Text hierarchy (blue-white spectrum: primary → secondary → muted → disabled)
NAVY_TEXT_PRIMARY = '#e9e9e9'  # readable body text (near-white)
NAVY_TEXT_SECONDARY = '#bbc8e8'  # panel titles, labels (light blue)
NAVY_TEXT_TERTIARY = '#c5c7d2'  # headers, secondary labels (cool gray)
NAVY_TEXT_MUTED = '#969aad'  # disabled, placeholder text
NAVY_TEXT_DIM = '#8f9fc1'  # help text, timestamps
NAVY_TEXT_BODY = '#c8d4e8'  # agent / scan-line body text (most common)
NAVY_TEXT_USER = '#f2f6ff'  # user message body text
NAVY_TEXT_LIVE = '#b8c4d8'  # live/streaming content idle
NAVY_TEXT_LIVE_ACTIVE = '#d5dee8'  # live/streaming content active frame

# Transcript block backgrounds (uniform-ish, subtle differentiation)
NAVY_BG_TRANSCRIPT_BLOCK = '#090d18'  # thinking / orient / scan-line bg
NAVY_BG_TRANSCRIPT_ACTIVE = '#0a101c'  # streaming-active variant
NAVY_BG_USER = '#151d32'  # user message card bg
NAVY_BG_NOTICE = '#12161f'  # transcript notice bg
NAVY_TEXT_NOTICE = '#7a8299'  # transcript notice text

# Accent — periwinkle blue (primary interactive highlight)
NAVY_BRAND = '#91abec'  # primary accent — periwinkle blue
NAVY_BRAND_DIM = '#6171a6'  # secondary accent (muted periwinkle)

# Focus / selection accent — teal (used for focused cards, suggestions, modal left-pipe)
NAVY_FOCUS_ACCENT = '#5eead4'  # focus, active highlight, modal left-pipe

# Status semantic colors
NAVY_READY = '#54efae'  # green — Ready / Success / Healthy
NAVY_RUNNING = '#f6a657'  # warm amber — Running / active work
NAVY_RUNNING_DIM = '#c9803f'  # dimmer amber — running pulse off-frame
NAVY_WAITING = '#f6ff8f'  # lime yellow — Review / Paused / Warning
NAVY_WAITING_DIM = '#b8bb62'  # dimmer lime — waiting-state pulse off-frame
NAVY_ERROR = '#fd8383'  # soft red — Error / Danger

# Status accents (for borders, badges, toast accents)
NAVY_GREEN_ACCENT = '#5bd088'  # success toast/border accent
NAVY_RED_ACCENT = '#f05757'  # error toast/border accent
NAVY_YELLOW_ACCENT = '#f0e357'  # warning toast/border accent
NAVY_PURPLE_ACCENT = '#b565f3'  # tertiary accent (purple)

# Domain accents — sidebar sections
NAVY_DOMAIN_MCP = '#eacb8a'  # MCP servers section (gold)
NAVY_DOMAIN_MCP_DIM = '#b89a6a'  # dimmed gold for inactive
NAVY_DOMAIN_SKILLS = '#c792ea'  # Skills section (purple)
NAVY_DOMAIN_SKILLS_DIM = '#a88fd4'  # dimmed purple for inactive

# HUD per-Select accents (one per HUD select widget for visual disambiguation)
NAVY_HUD_SELECT_MODE = '#1f6d64'  # mode select — teal-green
NAVY_HUD_SELECT_MODE_FOCUS = '#2a9d8f'  # mode select — focused
NAVY_HUD_SELECT_MODE_OVERLAY = '#1f6d64'  # mode select — dropdown overlay border
NAVY_HUD_SELECT_AUTONOMY = '#3a5a8c'  # autonomy select — blue
NAVY_HUD_SELECT_AUTONOMY_FOCUS = '#5a8acc'  # autonomy select — focused
NAVY_HUD_SELECT_AUTONOMY_OVERLAY = '#2a4a7a'  # autonomy select — dropdown border
NAVY_HUD_SELECT_REASONING = '#8a6a2a'  # reasoning select — gold
NAVY_HUD_SELECT_REASONING_FOCUS = '#b8923a'  # reasoning select — focused
NAVY_HUD_SELECT_REASONING_OVERLAY = '#6a5020'  # reasoning select — dropdown border

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
