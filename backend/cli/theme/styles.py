"""Rich and prompt_toolkit style builders."""

from __future__ import annotations

import backend.cli.theme.navy as navy
import backend.cli.theme.tokens as tokens
from backend.cli.theme.env import no_color_enabled


def grinta_rich_theme_styles() -> dict[str, str]:
    """Return Rich theme overrides used by CLI and TUI renderables."""
    if no_color_enabled():
        return {
            'markdown.strong': 'not bold',
            'markdown.code': 'not bold',
            'markdown.code_block': 'not bold',
            'markdown.item.bullet': 'not bold',
            'markdown.h1': 'not bold underline',
            'markdown.h3': 'not bold',
            'markdown.table.header': 'not bold',
            'repr.number': 'not bold',
            'repr.string': 'not bold',
            'repr.bool': 'not bold',
            'repr.none': 'dim',
            'repr.url': 'underline',
            'repr.uuid': 'dim',
        }

    return {
        'markdown.strong': 'not bold',
        'markdown.code': f'not bold {navy.NAVY_TEXT_PRIMARY} on #101829',
        'markdown.code_block': f'not bold {navy.NAVY_TEXT_PRIMARY} on #101829',
        'markdown.item.bullet': navy.NAVY_BRAND,
        'markdown.h1': f'not bold underline {navy.NAVY_TEXT_SECONDARY}',
        'markdown.h2': f'underline {navy.NAVY_BRAND}',
        'markdown.h3': f'not bold {navy.NAVY_BRAND}',
        'markdown.table.header': f'not bold {navy.NAVY_BRAND}',
        'repr.number': navy.NAVY_TEXT_PRIMARY,
        'repr.string': navy.NAVY_READY,
        'repr.bool': navy.NAVY_BRAND,
        'repr.none': navy.NAVY_TEXT_MUTED,
        'repr.url': navy.NAVY_BRAND,
        'repr.uuid': navy.NAVY_TEXT_MUTED,
    }


def prompt_toolkit_style_dict() -> dict[str, str]:
    """Return ``Style.from_dict`` mapping; respects :func:`no_color_enabled`."""
    if no_color_enabled():
        return _prompt_toolkit_style_dict_no_color()
    return _prompt_toolkit_style_dict_color()


def _prompt_toolkit_style_dict_color() -> dict[str, str]:
    return {
        '': f'noreverse {tokens.PT_DEFAULT_FG}',
        'bottom-toolbar': 'noreverse',
        'bottom-toolbar.text': 'noreverse',
        'placeholder': f'italic {tokens.PT_PLACEHOLDER_DIM}',
        'prompt.border': tokens.CLR_THINKING_BORDER,
        'prompt.frame.border': f'bold {tokens.CLR_STATUS_OK}',
        'prompt.brand': tokens.CLR_BRAND,
        'prompt.dim': tokens.CLR_META,
        'prompt.model': tokens.CLR_HUD_MODEL,
        'prompt.value': tokens.CLR_HUD_DETAIL,
        'prompt.sep': tokens.CLR_SEP,
        'prompt.arrow': tokens.CLR_BRAND,
        'prompt.hint': tokens.CLR_AUTONOMY_FULL,
        'prompt.badge.ready': f'bold {tokens.CLR_STATUS_OK}',
        'prompt.badge.running': tokens.CLR_STATE_RUNNING,
        'prompt.badge.review': f'bold {tokens.CLR_STATUS_WARN}',
        'prompt.badge.paused': f'bold {tokens.CLR_STATUS_WARN}',
        'prompt.badge.error': f'bold {tokens.CLR_STATUS_ERR}',
        'prompt.autonomy.balanced': tokens.CLR_AUTONOMY_BALANCED,
        'prompt.autonomy.full': tokens.CLR_AUTONOMY_FULL,
        'prompt.autonomy.conservative': tokens.CLR_AUTONOMY_CONSERVATIVE,
        'prompt.health.good': f'bold {tokens.CLR_STATUS_OK}',
        'prompt.health.warn': f'bold {tokens.CLR_STATUS_WARN}',
        'prompt.health.bad': f'bold {tokens.CLR_STATUS_ERR}',
        'prompt.footer.badge_bracket': tokens.PT_FOOTER_BADGE_BRACKET,
        'prompt.footer.badge_core': tokens.PT_FOOTER_BADGE_CORE,
        'prompt.footer.kicker': tokens.PT_FOOTER_KICKER,
        'prompt.footer.sep': tokens.CLR_META,
        'prompt.footer.body': tokens.CLR_MUTED_TEXT,
        'prompt.footer.warn_bracket': tokens.PT_FOOTER_WARN_BRACKET,
        'prompt.footer.warn_core': tokens.PT_FOOTER_WARN_CORE,
        'prompt.footer.warn_kicker': tokens.PT_FOOTER_WARN_KICKER,
        'prompt.footer.warn_sep': tokens.PT_FOOTER_WARN_SEP,
        'prompt.footer.warn_body': tokens.CLR_STATUS_WARN,
        'completion-menu': tokens.PT_COMPLETION_MENU_BG,
        'completion-menu.completion': tokens.PT_COMPLETION_MENU_BG,
        'completion-menu.completion.current': tokens.PT_COMPLETION_MENU_CURRENT,
        'completion-menu.meta': tokens.PT_COMPLETION_META_BG,
        'completion-menu.meta.completion': tokens.PT_COMPLETION_META_BG,
        'completion-menu.meta.completion.current': tokens.PT_COMPLETION_META_CURRENT,
        'completion-menu.multi-column-meta': tokens.PT_COMPLETION_META_BG,
        'scrollbar.background': tokens.PT_SCROLLBAR_BG,
        'scrollbar.button': tokens.PT_SCROLLBAR_BUTTON,
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
