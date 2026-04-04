"""Tests for backend.engine.streaming_checkpoint."""

from __future__ import annotations

import json

import pytest

from backend.engine.streaming_checkpoint import (
    StreamingCheckpoint,
)


@pytest.fixture
def ckpt(tmp_path):
    return StreamingCheckpoint(str(tmp_path))


# ── begin / commit lifecycle ─────────────────────────────────────────


class TestStreamingCheckpointLifecycle:
    def test_begin_creates_wal(self, ckpt: StreamingCheckpoint, tmp_path):
        token = ckpt.begin({'model': 'gpt-4', 'messages': [1, 2]})
        assert token
        wal = tmp_path / 'streaming_wal.json'
        assert wal.exists()
        data = json.loads(wal.read_text(encoding='utf-8'))
        assert data['token'] == token
        assert data['params_summary']['model'] == 'gpt-4'
        assert data['params_summary']['message_count'] == 2

    def test_commit_removes_wal(self, ckpt: StreamingCheckpoint, tmp_path):
        token = ckpt.begin({'model': 'x'})
        ckpt.commit(token)
        assert not (tmp_path / 'streaming_wal.json').exists()
        assert ckpt.active_token is None

    def test_discard(self, ckpt: StreamingCheckpoint, tmp_path):
        ckpt.begin({'model': 'x'})
        ckpt.discard()
        assert not (tmp_path / 'streaming_wal.json').exists()
        assert ckpt.active_token is None


# ── active_token ─────────────────────────────────────────────────────


class TestActiveToken:
    def test_none_initially(self, ckpt):
        assert ckpt.active_token is None

    def test_set_after_begin(self, ckpt):
        token = ckpt.begin({})
        assert ckpt.active_token == token

    def test_cleared_after_commit(self, ckpt):
        token = ckpt.begin({})
        ckpt.commit(token)
        assert ckpt.active_token is None


# ── recover ──────────────────────────────────────────────────────────


class TestRecover:
    def test_no_wal(self, ckpt):
        assert ckpt.recover() is None

    def test_recovers_uncommitted(self, tmp_path):
        ckpt1 = StreamingCheckpoint(str(tmp_path))
        token = ckpt1.begin({'model': 'test'})
        # Simulate crash — don't commit. Create new instance.
        ckpt2 = StreamingCheckpoint(str(tmp_path))
        record = ckpt2.recover()
        assert record is not None
        assert record.token == token
        assert record.params_summary['model'] == 'test'

    def test_corrupt_wal(self, tmp_path):
        wal = tmp_path / 'streaming_wal.json'
        wal.write_text('not valid json', encoding='utf-8')
        ckpt = StreamingCheckpoint(str(tmp_path))
        assert ckpt.recover() is None
        assert not wal.exists()


# ── _summarise_params ────────────────────────────────────────────────


class TestSummariseParams:
    def test_extracts_model_and_counts(self, ckpt):
        summary = ckpt._summarise_params(
            {'model': 'gpt-4', 'messages': [1, 2, 3], 'tools': [1]}
        )
        assert summary['model'] == 'gpt-4'
        assert summary['message_count'] == 3
        assert summary['tool_count'] == 1

    def test_empty_params(self, ckpt):
        summary = ckpt._summarise_params({})
        assert summary == {}


# ── attempt tracking ─────────────────────────────────────────────────


class TestAttemptTracking:
    def test_default_attempt(self, ckpt, tmp_path):
        ckpt.begin({})
        data = json.loads((tmp_path / 'streaming_wal.json').read_text(encoding='utf-8'))
        assert data['attempt'] == 1

    def test_custom_attempt(self, ckpt, tmp_path):
        ckpt.begin({}, attempt=3)
        data = json.loads((tmp_path / 'streaming_wal.json').read_text(encoding='utf-8'))
        assert data['attempt'] == 3
