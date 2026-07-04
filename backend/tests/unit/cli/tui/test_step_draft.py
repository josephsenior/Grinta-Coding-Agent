"""Assistant step draft state tests."""

from backend.cli.tui.renderer.step_draft import AssistantStepDraft


def test_accept_stream_preview_blocks_stale_partial_after_commit() -> None:
    draft = AssistantStepDraft()
    draft.note_content_committed('Full committed answer.')
    assert draft.accept_stream_preview(
        is_final=False,
        incoming='Full committed',
    ) is False


def test_accept_stream_preview_allows_new_leg_after_commit() -> None:
    draft = AssistantStepDraft()
    draft.note_content_committed('Full committed answer.')
    assert draft.accept_stream_preview(
        is_final=False,
        incoming='Next step with different content.',
    ) is True
    assert draft.content_committed is False


def test_should_commit_content_dedupes_transcript_only() -> None:
    draft = AssistantStepDraft()
    draft.note_content_committed('Preamble text.', transcript_only=True)
    assert draft.should_commit_content('Preamble text.', transcript_only=True) is False
    assert draft.should_commit_content('Different preamble.', transcript_only=True) is True
