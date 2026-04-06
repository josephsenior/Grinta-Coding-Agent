"""Tests for :mod:`backend.cli.layout_tokens`."""

from __future__ import annotations

from rich.padding import Padding
from rich.text import Text

from backend.cli.layout_tokens import (
    ACTIVITY_BLOCK_BOTTOM_PAD,
    CALLOUT_PANEL_PADDING,
    TRANSCRIPT_LEFT_INSET,
    TRANSCRIPT_RIGHT_INSET,
    frame_live_body,
    frame_transcript_body,
    gap_below_live_section,
    spacer_live_section,
)


def test_transcript_insets_are_symmetric() -> None:
    assert TRANSCRIPT_LEFT_INSET == TRANSCRIPT_RIGHT_INSET


def test_frame_transcript_body_is_padding_with_insets() -> None:
    inner = Text('x')
    framed = frame_transcript_body(inner)
    assert isinstance(framed, Padding)
    assert framed.renderable is inner
    assert framed.top == 0 and framed.bottom == 0
    assert framed.left == TRANSCRIPT_LEFT_INSET
    assert framed.right == TRANSCRIPT_RIGHT_INSET


def test_frame_live_body_matches_transcript_frame() -> None:
    t = Text('y')
    assert isinstance(frame_live_body(t), Padding)
    a = frame_transcript_body(t)
    b = frame_live_body(t)
    assert a.left == b.left and a.right == b.right


def test_gap_below_live_section_adds_bottom_pad() -> None:
    t = Text('z')
    g = gap_below_live_section(t)
    assert isinstance(g, Padding)
    assert g.bottom == 1
    assert g.renderable is t


def test_spacer_live_section_is_empty_text() -> None:
    s = spacer_live_section()
    assert s.plain == ''


def test_callout_padding_tuple() -> None:
    assert CALLOUT_PANEL_PADDING == (1, 1)


def test_activity_block_bottom_pad() -> None:
    assert ACTIVITY_BLOCK_BOTTOM_PAD == (0, 0, 1, 0)
