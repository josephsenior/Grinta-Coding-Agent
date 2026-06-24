"""Unit tests for shared terminal sanitization."""

from __future__ import annotations

from backend.cli.terminal_sanitize import (
    looks_like_terminal_selection_noise,
    strip_leaked_terminal_artifacts,
)


def test_strip_mouse_reports_with_sgr_prefix() -> None:
    leaked = '[<35;73;29M[<35;73;30Mhello\x1b[<35;74;31M'
    assert strip_leaked_terminal_artifacts(leaked) == 'hello'


def test_strip_mouse_reports_without_esc_byte() -> None:
    leaked = 'PS> [444444;32;15M[555;31;16Mhello'
    assert strip_leaked_terminal_artifacts(leaked) == 'PS> hello'


def test_strip_screenshot_style_mouse_stream() -> None:
    leaked = 'PS C:\\Users\\test> [555;57;27M[555;57;26M[555;58;24M[555555;60;27Mpython'
    assert strip_leaked_terminal_artifacts(leaked) == 'PS C:\\Users\\test> python'


def test_strip_orphan_param_chunk_stream() -> None:
    leaked = '0;1;40;1_0;0;32;1_8;1;32;1_hello'
    assert strip_leaked_terminal_artifacts(leaked) == 'hello'


def test_strip_two_field_mouse_report() -> None:
    assert strip_leaked_terminal_artifacts('[222;1Mhello') == 'hello'


def test_sanitize_prompt_input_text() -> None:
    from backend.cli.terminal_sanitize import sanitize_prompt_input_text

    leaked = 'PS C:\\Users\\test> ' + '[555;76;29M[222;1;38M' * 5
    assert sanitize_prompt_input_text(leaked) == 'PS C:\\Users\\test> '
    assert sanitize_prompt_input_text('[555;76;29M' * 4) == ''


def test_looks_like_terminal_selection_noise() -> None:
    noise = '[555;57;27M' * 4
    assert looks_like_terminal_selection_noise(noise)
    assert not looks_like_terminal_selection_noise('hello world')


def test_split_trailing_incomplete_mouse_artifact() -> None:
    from backend.cli.terminal_sanitize import split_trailing_incomplete_mouse_artifact

    body, tail = split_trailing_incomplete_mouse_artifact('ok[555;117;')
    assert body == 'ok'
    assert tail == '[555;117;'
    assert split_trailing_incomplete_mouse_artifact('done[555;117;1M') == (
        'done[555;117;1M',
        '',
    )
