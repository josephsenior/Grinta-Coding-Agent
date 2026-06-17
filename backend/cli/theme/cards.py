"""Shared TUI card, diff, and terminal palette tokens."""

from __future__ import annotations

from backend.cli.theme.navy import (
    NAVY_BG,
    NAVY_BORDER,
    NAVY_BORDER_HIGHLIGHT,
    NAVY_BRAND,
    NAVY_ERROR,
    NAVY_READY,
    NAVY_SCROLLBAR_THUMB,
    NAVY_SCROLLBAR_TRACK,
    NAVY_TEXT_DIM,
    NAVY_TEXT_MUTED,
    NAVY_TEXT_PRIMARY,
    NAVY_TEXT_SECONDARY,
)

# ── Unified diff palette ─────────────────────────────────────────────────────

DIFF_GUTTER = '#5a6478'
DIFF_GUTTER_ADD = '#6f9f82'
DIFF_GUTTER_REM = '#b87a7a'
DIFF_LINE_CTX = '#c8ceda'
DIFF_LINE_ADD = '#b8f0c8'
DIFF_LINE_REM = '#ffc0c0'
DIFF_BG_CTX = 'transparent'
# Softened ~10% toward NAVY_BG for long always-visible diffs
DIFF_BG_ADD = '#122a22'
DIFF_BG_REM = '#2a1a1a'
DIFF_INLINE_ADD = NAVY_READY
DIFF_INLINE_REM = NAVY_ERROR
DIFF_HDR = NAVY_BRAND
DIFF_HDR_BG = '#0a1224'
DIFF_TRUNCATED_FG = NAVY_TEXT_MUTED
DIFF_LINE_ADD_TEXT = '#7de6a1'
DIFF_LINE_REM_TEXT = '#ff9a9a'
DIFF_SPLIT_DIVIDER = '#26324f'

# ── File change card ───────────────────────────────────────────────────────────

CARD_FILE_BG = '#08101d'
CARD_FILE_BORDER = NAVY_BORDER
CARD_FILE_CREATE_ACCENT = NAVY_READY
CARD_FILE_EDIT_ACCENT = NAVY_BRAND
CARD_FILE_DELTA_PILL_BG = '#0a1224'

# ── Activity / terminal cards ──────────────────────────────────────────────────

CARD_SURFACE_BG = '#08101d'
CARD_TERMINAL_BG = '#050913'
CARD_TERMINAL_BORDER = '#24385c'
CARD_TERMINAL_RUNNING_ACCENT = '#5eead4'
CARD_SCROLL_MAX_HEIGHT = 24

TERM_TITLEBAR_BG = '#141c2e'
TERM_TITLEBAR_FG = NAVY_TEXT_DIM
TERM_PROMPT_BG = '#0a0e14'
TERM_OUTPUT_BG = '#080c12'
TERM_OUTPUT_FG = '#cbd5e1'
TERM_FOOTER_BG = '#0d1219'
TERM_FOOTER_FG = '#54597b'
TERM_FOOTER_OK = NAVY_READY
TERM_FOOTER_ERR = NAVY_ERROR
TERM_FOOTER_NEUTRAL = NAVY_TEXT_DIM
TERM_RUNNING_CURSOR = '#5eead4'
TERM_SHELL_PROMPT = NAVY_READY
TERM_PTY_PROMPT = '#5eead4'
TERM_PWSH_PROMPT = '#7dd3fc'
TERM_DEBUGGER_PROMPT = '#5eead4'
TERM_COMMAND_FG = '#e2e8f0'
TERM_SCROLLBAR_THUMB = NAVY_SCROLLBAR_THUMB
TERM_SCROLLBAR_TRACK = NAVY_BG
TERM_HIDDEN_LINES_FG = '#54597b'

# ── Transcript vertical rhythm ─────────────────────────────────────────────────

TRANSCRIPT_BLOCK_MARGIN = 2
TRANSCRIPT_PADDING_VERTICAL = 2



def file_change_kind_class(outcome: str | None) -> str:
    """Return CSS class suffix for file change cards: -create, -edit, or ''."""
    if not outcome:
        return ''
    tokens = outcome.replace(',', ' ').replace('·', ' ').split()
    has_add = any(t.startswith('+') and t[1:].isdigit() for t in tokens)
    has_rem = any(t.startswith('-') and t[1:].isdigit() for t in tokens)
    if has_add and not has_rem:
        return '-create'
    if has_add or has_rem:
        return '-edit'
    return ''


def footer_color_for_exit_code(exit_code: int | None) -> str:
    if exit_code == 0:
        return TERM_FOOTER_OK
    if exit_code is not None:
        return TERM_FOOTER_ERR
    return TERM_FOOTER_NEUTRAL
