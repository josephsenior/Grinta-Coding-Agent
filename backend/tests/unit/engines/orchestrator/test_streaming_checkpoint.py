"""Comprehensive unit tests for StreamingCheckpoint and CheckpointRecord."""

from __future__ import annotations

import json


from backend.engines.orchestrator.streaming_checkpoint import (
    CheckpointRecord,
    StreamingCheckpoint,
)


# ---------------------------------------------------------------------------
# CheckpointRecord
# ---------------------------------------------------------------------------

class TestCheckpointRecord:
    def test_fields_stored(self):
        rec = CheckpointRecord(
            token="abc123",
            created_at=1.0,
            params_summary={"model": "gpt-4"},
            attempt=2,
        )
        assert rec.token == "abc123"
        assert rec.created_at == 1.0
        assert rec.params_summary == {"model": "gpt-4"}
        assert rec.attempt == 2

    def test_default_attempt_is_1(self):
        rec = CheckpointRecord(token="t", created_at=0.0)
        assert rec.attempt == 1

    def test_default_params_summary_is_empty(self):
        rec = CheckpointRecord(token="t", created_at=0.0)
        assert rec.params_summary == {}


# ---------------------------------------------------------------------------
# StreamingCheckpoint.__init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_creates_directory(self, tmp_path):
        subdir = tmp_path / "sub" / "ckpt"
        StreamingCheckpoint(str(subdir))
        assert subdir.exists()

    def test_no_active_on_init(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        assert ckpt.active_token is None

    def test_wal_path_correct(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        assert ckpt._wal_path.name == "streaming_wal.json"


# ---------------------------------------------------------------------------
# begin
# ---------------------------------------------------------------------------

class TestBegin:
    def test_returns_token_string(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        token = ckpt.begin({"model": "gpt-4"})
        assert isinstance(token, str)
        assert len(token) == 12

    def test_sets_active_token(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        token = ckpt.begin({})
        assert ckpt.active_token == token

    def test_creates_wal_file(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt.begin({"model": "gpt-4o"})
        assert ckpt._wal_path.exists()

    def test_wal_file_contains_token(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        token = ckpt.begin({"model": "x"})
        data = json.loads(ckpt._wal_path.read_text())
        assert data["token"] == token

    def test_attempt_number_stored(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt.begin({}, attempt=3)
        data = json.loads(ckpt._wal_path.read_text())
        assert data["attempt"] == 3

    def test_each_call_produces_unique_token(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        tokens = {ckpt.begin({}) for _ in range(5)}
        assert len(tokens) == 5  # all unique (wal file overwritten each time)


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------

class TestCommit:
    def test_removes_wal_file(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        token = ckpt.begin({})
        assert ckpt._wal_path.exists()
        ckpt.commit(token)
        assert not ckpt._wal_path.exists()

    def test_clears_active_token(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        token = ckpt.begin({})
        ckpt.commit(token)
        assert ckpt.active_token is None

    def test_commit_wrong_token_logs_but_still_removes(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt.begin({})
        # Commit with wrong token — should still clear the WAL
        ckpt.commit("wrong-token-xxx")
        assert not ckpt._wal_path.exists()
        assert ckpt.active_token is None

    def test_commit_without_begin_no_crash(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt.commit("nonexistent")  # Should not raise


# ---------------------------------------------------------------------------
# discard
# ---------------------------------------------------------------------------

class TestDiscard:
    def test_removes_wal_file(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt.begin({})
        ckpt.discard()
        assert not ckpt._wal_path.exists()

    def test_clears_active(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt.begin({})
        ckpt.discard()
        assert ckpt.active_token is None

    def test_discard_without_begin_no_crash(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt.discard()


# ---------------------------------------------------------------------------
# recover
# ---------------------------------------------------------------------------

class TestRecover:
    def test_no_wal_returns_none(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        assert ckpt.recover() is None

    def test_uncommitted_returns_record(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        token = ckpt.begin({"model": "gpt-4"})
        # Simulate restart: create a fresh instance pointing to same dir
        ckpt2 = StreamingCheckpoint(str(tmp_path))
        record = ckpt2.recover()
        assert record is not None
        assert record.token == token

    def test_recover_after_commit_returns_none(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        token = ckpt.begin({})
        ckpt.commit(token)
        ckpt2 = StreamingCheckpoint(str(tmp_path))
        assert ckpt2.recover() is None

    def test_recover_after_discard_returns_none(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt.begin({})
        ckpt.discard()
        assert ckpt.recover() is None

    def test_corrupt_wal_returns_none_not_raises(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt._wal_path.write_text("NOT JSON", encoding="utf-8")
        assert ckpt.recover() is None

    def test_recover_returns_correct_attempt(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt.begin({"model": "x"}, attempt=4)
        ckpt2 = StreamingCheckpoint(str(tmp_path))
        record = ckpt2.recover()
        assert record is not None
        assert record.attempt == 4

    def test_recover_clears_corrupt_wal(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt._wal_path.write_text("{bad: json}", encoding="utf-8")
        ckpt.recover()
        assert not ckpt._wal_path.exists()


# ---------------------------------------------------------------------------
# _summarise_params
# ---------------------------------------------------------------------------

class TestSummariseParams:
    def setup_method(self, tmp_path=None):
        import tempfile
        self._tmp = tempfile.mkdtemp()
        self.ckpt = StreamingCheckpoint(self._tmp)

    def test_extracts_model(self):
        summary = self.ckpt._summarise_params({"model": "claude-3", "messages": []})
        assert summary["model"] == "claude-3"

    def test_counts_messages(self):
        summary = self.ckpt._summarise_params(
            {"messages": [{"role": "user"}, {"role": "assistant"}]}
        )
        assert summary["message_count"] == 2

    def test_counts_tools(self):
        summary = self.ckpt._summarise_params(
            {"tools": ["a", "b", "c"]}
        )
        assert summary["tool_count"] == 3

    def test_empty_params_returns_empty_summary(self):
        summary = self.ckpt._summarise_params({})
        assert summary == {}

    def test_unknown_keys_ignored(self):
        summary = self.ckpt._summarise_params({"temperature": 0.7, "foo": "bar"})
        assert "temperature" not in summary
        assert "foo" not in summary


# ---------------------------------------------------------------------------
# active_token property
# ---------------------------------------------------------------------------

class TestActiveToken:
    def test_none_before_begin(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        assert ckpt.active_token is None

    def test_set_after_begin(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        token = ckpt.begin({})
        assert ckpt.active_token == token

    def test_none_after_commit(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        token = ckpt.begin({})
        ckpt.commit(token)
        assert ckpt.active_token is None

    def test_none_after_discard(self, tmp_path):
        ckpt = StreamingCheckpoint(str(tmp_path))
        ckpt.begin({})
        ckpt.discard()
        assert ckpt.active_token is None
