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
    leaked = (
        'PS C:\\Users\\test> '
        '[555;57;27M[555;57;26M[555;58;24M[555555;60;27Mpython'
    )
    assert strip_leaked_terminal_artifacts(leaked) == 'PS C:\\Users\\test> python'


def test_strip_orphan_param_chunk_stream() -> None:
    leaked = '0;1;40;1_0;0;32;1_8;1;32;1_hello'
    assert strip_leaked_terminal_artifacts(leaked) == 'hello'


def test_looks_like_terminal_selection_noise() -> None:
    noise = '[555;57;27M' * 4
    assert looks_like_terminal_selection_noise(noise)
    assert not looks_like_terminal_selection_noise('hello world')
