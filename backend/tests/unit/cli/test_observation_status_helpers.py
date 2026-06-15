"""Unit tests for observation status mixin helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.cli.event_rendering.observations.status import _ObsStatusMixin


class TestStatusStaticHelpers:
    def test_extract_order_and_detail(self) -> None:
        obs = SimpleNamespace(content='fallback detail')
        assert _ObsStatusMixin._extract_order({'order': 3}) == 3
        assert _ObsStatusMixin._extract_order({'order': 'bad'}) == 9999
        assert (
            _ObsStatusMixin._extract_detail(obs, {'detail': 'worker detail'})
            == 'worker detail'
        )
        assert _ObsStatusMixin._extract_detail(obs, {}) == 'fallback detail'

    def test_compute_worker_timing_marks_finished(self) -> None:
        started, finished = _ObsStatusMixin._compute_worker_timing(
            'done', {'started_at': 1.0, 'finished_at': None}, now=5.0
        )
        assert started == 1.0
        assert finished == 5.0

    def test_compute_worker_action_tracking_increments(self) -> None:
        action, count = _ObsStatusMixin._compute_worker_action_tracking(
            'running',
            'new step',
            {'last_action': 'old step', 'action_count': 2},
        )
        assert action == 'new step'
        assert count == 3

    def test_delegate_worker_record_builds_snapshot(self) -> None:
        obs = SimpleNamespace(content='worker output')
        extras = {
            'worker_status': 'running',
            'worker_label': 'worker-1',
            'task_description': 'scan repo',
            'order': 1,
        }
        record = _ObsStatusMixin._delegate_worker_record(
            obs, extras, 'worker-1', previous=None
        )
        assert record['label'] == 'worker-1'
        assert record['task'] == 'scan repo'
        assert record['status'] == 'running'

    def test_coerce_positive_int(self) -> None:
        assert _ObsStatusMixin._coerce_positive_int('3', default=1) == 3
        assert _ObsStatusMixin._coerce_positive_int('bad', default=2) == 2
        assert _ObsStatusMixin._coerce_positive_int('1', default=5, floor=4) == 4


class TestStatusInstanceHelpers:
    def setup_method(self) -> None:
        self.mixin = _ObsStatusMixin()
        self.mixin._delegate_workers = {}
        self.mixin._delegate_batch_id = 'batch-a'
        self.mixin._hud = SimpleNamespace(
            update_mcp_servers=lambda *_a, **_k: None,
            update_ledger=lambda *_a, **_k: None,
            update_agent_state=lambda *_a, **_k: None,
        )
        self.mixin._last_retry_status_signature = None
        self.mixin._set_delegate_panel = lambda: None

    def test_delegate_batch_mismatch(self) -> None:
        assert self.mixin._delegate_batch_mismatch('batch-b') is True
        assert self.mixin._delegate_batch_mismatch('batch-a') is False
        assert self.mixin._delegate_batch_mismatch(None) is False

    def test_maybe_update_mcp_status(self) -> None:
        calls: list[int] = []
        self.mixin._hud.update_mcp_servers = lambda n: calls.append(n)
        obs = SimpleNamespace(extras={'connected_client_count': 2})
        self.mixin._maybe_update_mcp_status('mcp_ready', obs)
        assert calls == [2]
        self.mixin._maybe_update_mcp_status('other', obs)
        assert calls == [2]

    def test_handle_retry_status_pending_and_resuming(self) -> None:
        ledger: list[str] = []
        states: list[str] = []
        self.mixin._hud.update_ledger = lambda value: ledger.append(value)
        self.mixin._hud.update_agent_state = lambda value: states.append(value)
        pending = SimpleNamespace(
            extras={'attempt': 2, 'max_attempts': 5, 'delay_seconds': 0.5}
        )
        self.mixin._handle_retry_status(pending, status_type='retry_pending')
        assert ledger == ['Backoff']
        assert states[0].startswith('Backoff 2/5')
        resuming = SimpleNamespace(extras={'attempt': 3, 'max_attempts': 5})
        self.mixin._handle_retry_status(resuming, status_type='retry_resuming')
        assert states[-1] == 'Retrying 3/5'

    def test_try_early_return_for_status_delegate_and_retry(self) -> None:
        obs = SimpleNamespace(
            extras={
                'batch_id': 'batch-a',
                'worker_id': 'w1',
                'worker_status': 'running',
                'worker_label': 'w1',
                'task_description': 'task',
            }
        )
        assert self.mixin._try_early_return_for_status(obs, 'delegate_progress') is True
        retry = SimpleNamespace(
            extras={'attempt': 1, 'max_attempts': 3, 'delay_seconds': 2}
        )
        assert self.mixin._try_early_return_for_status(retry, 'retry_pending') is True
        assert self.mixin._try_early_return_for_status(retry, 'retry_pending') is True
        assert self.mixin._try_early_return_for_status(retry, 'other') is False


class TestRenderStatusContent:
    def setup_method(self) -> None:
        self.mixin = _ObsStatusMixin()
        self.mixin._stream_fallback_count = 0
        self.mixin._pending_activity_card = None
        self.mixin._last_retry_status_signature = None
        self.history: list[object] = []
        self.mixin._append_history = self.history.append
        self.mixin._flush_pending_tool_cards = lambda: None

    def test_skips_empty_content(self) -> None:
        obs = SimpleNamespace(content='')
        self.mixin._render_status_content(
            obs, force_visible_status=False, retry_signature=None
        )
        assert self.history == []

    def test_stream_fallback_appends_panel(self) -> None:
        obs = SimpleNamespace(content='Stream timed out; retrying without streaming')
        self.mixin._render_status_content(
            obs, force_visible_status=False, retry_signature=None
        )
        assert self.mixin._stream_fallback_count == 1
        assert len(self.history) == 1

    def test_dedupes_retry_signature(self) -> None:
        obs = SimpleNamespace(content='retry notice')
        sig = ('retry_pending', '1')
        self.mixin._last_retry_status_signature = sig
        self.mixin._render_status_content(
            obs, force_visible_status=True, retry_signature=sig
        )
        assert self.history == []
        self.mixin._render_status_content(
            obs, force_visible_status=True, retry_signature=('retry_pending', '2')
        )
        assert len(self.history) == 1
