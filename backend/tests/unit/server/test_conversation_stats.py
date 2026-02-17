"""Tests for backend.server.services.conversation_stats module.

Targets the 17.9% (87 missed lines) coverage gap.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from backend.llm.metrics import Metrics
from backend.server.services.conversation_stats import ConversationStats


def _make_file_store(data: str | None = None, raise_fnf: bool = False):
    fs = MagicMock()
    if raise_fnf:
        fs.read.side_effect = FileNotFoundError
    else:
        fs.read.return_value = data
    return fs


def _encode_metrics(mapping: dict) -> str:
    return base64.b64encode(json.dumps(mapping).encode()).decode()


# ------------------------------------------------------------------
# Initialization
# ------------------------------------------------------------------
class TestConversationStatsInit:
    def test_init_no_file_store(self):
        cs = ConversationStats(
            file_store=None, conversation_id="c1", user_id=None
        )
        assert cs.conversation_id == "c1"
        assert cs.service_to_metrics == {}
        assert cs.restored_metrics == {}

    def test_init_with_file_store_no_saved(self):
        fs = _make_file_store(raise_fnf=True)
        cs = ConversationStats(file_store=fs, conversation_id="c2", user_id="u1")
        assert cs.restored_metrics == {}

    def test_init_restores_saved_metrics(self):
        saved = _encode_metrics({"svc1": {"accumulated_cost": 0.5, "model_name": "m"}})
        fs = _make_file_store(data=saved)
        cs = ConversationStats(file_store=fs, conversation_id="c3", user_id="u1")
        assert "svc1" in cs.restored_metrics
        assert isinstance(cs.restored_metrics["svc1"], Metrics)


# ------------------------------------------------------------------
# save_metrics
# ------------------------------------------------------------------
class TestSaveMetrics:
    def test_no_file_store_noop(self):
        cs = ConversationStats(file_store=None, conversation_id="c1", user_id=None)
        cs.save_metrics()  # should not raise

    def test_saves_service_metrics(self):
        fs = _make_file_store(raise_fnf=True)
        cs = ConversationStats(file_store=fs, conversation_id="c1", user_id="u1")
        m = Metrics()
        cs.service_to_metrics["svc1"] = m
        cs.save_metrics()
        fs.write.assert_called_once()
        # Verify written data is valid base64 JSON
        written = fs.write.call_args[0][1]
        decoded = json.loads(base64.b64decode(written).decode())
        assert "svc1" in decoded

    def test_combines_restored_and_service(self):
        saved = _encode_metrics({"old_svc": {"accumulated_cost": 1.0}})
        fs = _make_file_store(data=saved)
        cs = ConversationStats(file_store=fs, conversation_id="c1", user_id="u1")
        cs.service_to_metrics["new_svc"] = Metrics()
        cs.save_metrics()
        written = fs.write.call_args[0][1]
        decoded = json.loads(base64.b64decode(written).decode())
        assert "old_svc" in decoded
        assert "new_svc" in decoded

    def test_handles_duplicate_services(self):
        saved = _encode_metrics({"dup": {"accumulated_cost": 1.0}})
        fs = _make_file_store(data=saved)
        cs = ConversationStats(file_store=fs, conversation_id="c1", user_id="u1")
        cs.service_to_metrics["dup"] = Metrics()
        # Should not raise, service_to_metrics takes precedence
        cs.save_metrics()
        fs.write.assert_called_once()


# ------------------------------------------------------------------
# maybe_restore_metrics
# ------------------------------------------------------------------
class TestMaybeRestoreMetrics:
    def test_no_file_store(self):
        cs = ConversationStats(file_store=None, conversation_id="c1", user_id=None)
        cs.maybe_restore_metrics()  # no-op
        assert cs.restored_metrics == {}

    def test_no_conversation_id(self):
        fs = _make_file_store()
        cs = ConversationStats(file_store=fs, conversation_id="", user_id=None)
        cs.maybe_restore_metrics()
        assert cs.restored_metrics == {}

    def test_invalid_json(self):
        bad_data = base64.b64encode(b"not json").decode()
        fs = _make_file_store(data=bad_data)
        cs = ConversationStats(file_store=fs, conversation_id="c1", user_id="u1")
        # Init calls maybe_restore, should not raise
        assert cs.restored_metrics == {}

    def test_non_dict_loaded(self):
        data = base64.b64encode(json.dumps([1, 2, 3]).encode()).decode()
        fs = _make_file_store(data=data)
        cs = ConversationStats(file_store=fs, conversation_id="c1", user_id="u1")
        assert cs.restored_metrics == {}


# ------------------------------------------------------------------
# get_combined_metrics
# ------------------------------------------------------------------
class TestGetCombinedMetrics:
    def test_empty(self):
        cs = ConversationStats(file_store=None, conversation_id="c1", user_id=None)
        m = cs.get_combined_metrics()
        assert isinstance(m, Metrics)

    def test_merges_multiple(self):
        cs = ConversationStats(file_store=None, conversation_id="c1", user_id=None)
        m1 = Metrics()
        m2 = Metrics()
        cs.service_to_metrics = {"s1": m1, "s2": m2}
        combined = cs.get_combined_metrics()
        assert isinstance(combined, Metrics)


# ------------------------------------------------------------------
# get_metrics_for_service
# ------------------------------------------------------------------
class TestGetMetricsForService:
    def test_existing_service(self):
        cs = ConversationStats(file_store=None, conversation_id="c1", user_id=None)
        m = Metrics()
        cs.service_to_metrics["svc1"] = m
        assert cs.get_metrics_for_service("svc1") is m

    def test_missing_service_raises(self):
        cs = ConversationStats(file_store=None, conversation_id="c1", user_id=None)
        with pytest.raises(KeyError, match="does not exist"):
            cs.get_metrics_for_service("nonexistent")


# ------------------------------------------------------------------
# register_llm
# ------------------------------------------------------------------
class TestRegisterLLM:
    def test_registers_new_service(self):
        cs = ConversationStats(file_store=None, conversation_id="c1", user_id=None)
        llm = MagicMock()
        llm.metrics = Metrics()
        event = MagicMock()
        event.llm = llm
        event.service_id = "svc1"
        cs.register_llm(event)
        assert "svc1" in cs.service_to_metrics

    def test_registers_with_no_existing_metrics(self):
        cs = ConversationStats(file_store=None, conversation_id="c1", user_id=None)
        llm = MagicMock(spec=[])  # no metrics attr
        event = MagicMock()
        event.llm = llm
        event.service_id = "svc2"
        cs.register_llm(event)
        assert "svc2" in cs.service_to_metrics

    def test_restores_saved_metrics_on_register(self):
        saved = _encode_metrics({"svc1": {"accumulated_cost": 5.0}})
        fs = _make_file_store(data=saved)
        cs = ConversationStats(file_store=fs, conversation_id="c1", user_id="u1")
        llm = MagicMock()
        llm.metrics = Metrics()
        event = MagicMock()
        event.llm = llm
        event.service_id = "svc1"
        cs.register_llm(event)
        # The restored metric should be moved to the llm
        assert "svc1" not in cs.restored_metrics
        assert "svc1" in cs.service_to_metrics

    def test_missing_llm_skips(self):
        cs = ConversationStats(file_store=None, conversation_id="c1", user_id=None)
        event = MagicMock()
        event.llm = None
        event.service_id = "svc1"
        cs.register_llm(event)
        assert cs.service_to_metrics == {}

    def test_missing_service_id_skips(self):
        cs = ConversationStats(file_store=None, conversation_id="c1", user_id=None)
        event = MagicMock()
        event.llm = MagicMock()
        event.service_id = None
        cs.register_llm(event)
        assert cs.service_to_metrics == {}


# ------------------------------------------------------------------
# merge_and_save
# ------------------------------------------------------------------
class TestMergeAndSave:
    def test_merges_restored_metrics(self):
        fs = _make_file_store(raise_fnf=True)
        cs1 = ConversationStats(file_store=fs, conversation_id="c1", user_id="u1")
        cs2 = ConversationStats(file_store=None, conversation_id="c2", user_id=None)

        m1 = Metrics()
        m1.accumulated_cost = 1.0
        m2 = Metrics()
        m2.accumulated_cost = 2.0
        cs1.restored_metrics = {"a": m1}
        cs2.restored_metrics = {"b": m2}

        cs1.merge_and_save(cs2)
        assert "a" in cs1.restored_metrics
        assert "b" in cs1.restored_metrics
        fs.write.assert_called_once()

    def test_drops_zero_cost_entries(self):
        fs = _make_file_store(raise_fnf=True)
        cs1 = ConversationStats(file_store=fs, conversation_id="c1", user_id="u1")
        cs2 = ConversationStats(file_store=None, conversation_id="c2", user_id=None)

        m_zero = Metrics()
        m_zero.accumulated_cost = 0
        m_nonzero = Metrics()
        m_nonzero.accumulated_cost = 5.0
        cs1.restored_metrics = {"zero": m_zero, "good": m_nonzero}
        cs2.restored_metrics = {}

        cs1.merge_and_save(cs2)
        assert "zero" not in cs1.restored_metrics
        assert "good" in cs1.restored_metrics
