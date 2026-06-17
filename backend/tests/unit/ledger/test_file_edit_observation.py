"""Tests for FileEditObservation display semantics."""

from __future__ import annotations

from backend.ledger.observation.files import (
    FileEditObservation,
    file_edit_observation_is_new_file,
    resolve_file_edit_outcome,
)


class TestResolveFileEditOutcome:
    def test_replace_string_is_edited(self) -> None:
        assert resolve_file_edit_outcome('replace_string', None) == 'edited'

    def test_create_file_without_old_content_is_created(self) -> None:
        assert resolve_file_edit_outcome('create_file', None) == 'created'

    def test_create_file_overwrite_is_edited(self) -> None:
        assert resolve_file_edit_outcome('create_file', 'before') == 'edited'

    def test_multi_edit_is_edited(self) -> None:
        assert resolve_file_edit_outcome('multi_edit', None) == 'edited'


class TestFileEditObservationIsNewFile:
    def test_outcome_created(self) -> None:
        observation = FileEditObservation(
            content='done',
            path='demo.txt',
            outcome='created',
        )
        assert file_edit_observation_is_new_file(observation) is True
        assert observation.is_new_file is True

    def test_outcome_edited(self) -> None:
        observation = FileEditObservation(
            content='done',
            path='demo.txt',
            outcome='edited',
        )
        assert file_edit_observation_is_new_file(observation) is False

    def test_missing_outcome_defaults_to_not_new_file(self) -> None:
        observation = FileEditObservation(content='done', path='demo.txt')
        assert file_edit_observation_is_new_file(observation) is False
        assert observation.is_new_file is False
