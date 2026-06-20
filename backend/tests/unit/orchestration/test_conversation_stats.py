from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from backend.inference.metrics import Metrics
from backend.orchestration.telemetry.conversation_stats import ConversationStats
from backend.persistence.file_store.files import FileStore


class _FileStore(FileStore):
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def write(self, path: str, contents: str | bytes) -> None:
        self.data[path] = (
            contents if isinstance(contents, str) else contents.decode('utf-8')
        )

    def read(self, path: str) -> str:
        if path not in self.data:
            raise FileNotFoundError(path)
        return self.data[path]

    def delete(self, path: str) -> None:
        self.data.pop(path, None)

    def list(self, path: str) -> list[str]:
        return [k for k in self.data if k.startswith(path)]


def _encode_metrics(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode('utf-8')).decode('utf-8')


def test_maybe_restore_metrics_ignores_missing_file() -> None:
    fs = _FileStore()
    stats = ConversationStats(fs, conversation_id='c1', user_id='u1')
    assert stats.restored_metrics == {}


def test_maybe_restore_metrics_restores_dict_payload() -> None:
    fs = _FileStore()
    m = Metrics()
    m.add_cost(0.2)
    fs.data['x'] = _encode_metrics({'svc': m.get()})

    stats = ConversationStats(fs, conversation_id='c1', user_id='u1')
    stats.metrics_path = 'x'
    stats.maybe_restore_metrics()

    assert 'svc' in stats.restored_metrics
    assert isinstance(stats.restored_metrics['svc'], Metrics)
    assert stats.restored_metrics['svc'].accumulated_cost == pytest.approx(0.2)


def test_save_metrics_serializes_combined_metrics() -> None:
    fs = _FileStore()
    stats = ConversationStats(fs, conversation_id='c2', user_id='u2')
    stats.metrics_path = 'save-path'
    m1 = Metrics()
    m1.add_cost(0.3)
    m2 = Metrics()
    m2.add_cost(0.5)
    stats.restored_metrics = {'a': m1}
    stats.service_to_metrics = {'b': m2}

    stats.save_metrics()

    encoded = fs.data['save-path']
    decoded = json.loads(base64.b64decode(encoded).decode('utf-8'))
    assert set(decoded.keys()) == {'a', 'b'}
    assert decoded['a']['accumulated_cost'] == pytest.approx(0.3)
    assert decoded['b']['accumulated_cost'] == pytest.approx(0.5)


def test_get_combined_metrics_merges_service_totals() -> None:
    fs = _FileStore()
    stats = ConversationStats(fs, conversation_id='c3', user_id='u3')
    a = Metrics()
    b = Metrics()
    a.add_cost(1.0)
    b.add_cost(2.5)
    stats.service_to_metrics = {'a': a, 'b': b}

    total = stats.get_combined_metrics()
    assert total.accumulated_cost == pytest.approx(3.5)


def test_get_metrics_for_service_raises_for_missing() -> None:
    stats = ConversationStats(_FileStore(), conversation_id='c4', user_id='u4')
    with pytest.raises(KeyError):
        stats.get_metrics_for_service('missing')


def test_register_llm_with_restored_metrics_reuses_restored_snapshot() -> None:
    stats = ConversationStats(_FileStore(), conversation_id='c5', user_id='u5')
    restored = Metrics()
    restored.add_cost(1.7)
    stats.restored_metrics = {'svc-x': restored}
    llm = SimpleNamespace(metrics=None)

    stats.register_llm(SimpleNamespace(llm=llm, service_id='svc-x'))  # type: ignore[arg-type]

    assert llm.metrics.accumulated_cost == pytest.approx(1.7)
    assert 'svc-x' in stats.service_to_metrics
    assert 'svc-x' not in stats.restored_metrics


def test_register_llm_without_metrics_creates_metrics() -> None:
    stats = ConversationStats(_FileStore(), conversation_id='c6', user_id='u6')
    llm = SimpleNamespace(metrics=None)
    stats.register_llm(SimpleNamespace(llm=llm, service_id='svc-y'))  # type: ignore[arg-type]
    assert isinstance(llm.metrics, Metrics)
    assert 'svc-y' in stats.service_to_metrics


def test_register_llm_skips_invalid_event() -> None:
    stats = ConversationStats(_FileStore(), conversation_id='c7', user_id='u7')
    stats.register_llm(SimpleNamespace(llm=None, service_id='svc-z'))  # type: ignore[arg-type]
    stats.register_llm(
        SimpleNamespace(llm=SimpleNamespace(metrics=None), service_id=None)  # type: ignore[arg-type]
    )
    assert stats.service_to_metrics == {}


def test_merge_and_save_drops_zero_cost_and_persists() -> None:
    fs = _FileStore()
    s1 = ConversationStats(fs, conversation_id='c8', user_id='u8')
    s2 = ConversationStats(fs, conversation_id='c9', user_id='u8')
    s1.metrics_path = 'merged'
    zero = Metrics()
    nonzero = Metrics()
    nonzero.add_cost(0.9)
    s1.restored_metrics = {'drop': zero}
    s2.restored_metrics = {'keep': nonzero}

    s1.merge_and_save(s2)

    payload = json.loads(base64.b64decode(fs.data['merged']).decode('utf-8'))
    assert set(payload.keys()) == {'keep'}
    assert payload['keep']['accumulated_cost'] == pytest.approx(0.9)
