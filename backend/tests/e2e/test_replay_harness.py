"""Mocked-LLM record/replay harness for trajectory regression.

This is a lightweight scaffold so trajectory regressions can be caught in CI
without burning real tokens. The harness:

1. Records LLM request/response pairs to ``backend/tests/fixtures/replays/``.
2. On replay, intercepts the LLM client and returns the recorded response
   for an identical request hash. Unknown requests fail loudly.

Mode is controlled by the ``GRINTA_LLM_REPLAY_MODE`` env var:
- unset / ``replay`` (default in CI): replay only, fail on missing fixture.
- ``record``: hit the real provider and write fixtures.
- ``passthrough``: forward to provider without recording (debugging).

A full implementation would hook ``backend.inference.llm.LLM.completion`` —
this scaffold provides the directory layout, the canonicalisation helper, and
a single smoke test, so future contributors have a clear extension point.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

REPLAY_DIR = Path(__file__).parent.parent / 'fixtures' / 'replays'


def _canonical_request(request: dict) -> str:
    """Stable hash of an LLM request for cache-key purposes."""
    canonical = json.dumps(request, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]


def _replay_path(request_hash: str) -> Path:
    return REPLAY_DIR / f'{request_hash}.json'


def replay_or_raise(request: dict) -> dict:
    """Return the recorded response for ``request`` or raise."""
    rh = _canonical_request(request)
    path = _replay_path(rh)
    if not path.exists():
        raise FileNotFoundError(
            f'No replay fixture for request hash {rh}. '
            f'Re-run with GRINTA_LLM_REPLAY_MODE=record to capture it.'
        )
    return json.loads(path.read_text(encoding='utf-8'))


def record(request: dict, response: dict) -> Path:
    """Persist ``response`` keyed by the canonical hash of ``request``."""
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    rh = _canonical_request(request)
    path = _replay_path(rh)
    path.write_text(
        json.dumps({'request': request, 'response': response}, indent=2),
        encoding='utf-8',
    )
    return path


@pytest.mark.integration
def test_canonicalisation_is_stable() -> None:
    """The hash of a request must not depend on dict iteration order."""
    a = {'model': 'm', 'messages': [{'role': 'user', 'content': 'hi'}], 'temperature': 0}
    b = {'temperature': 0, 'messages': [{'role': 'user', 'content': 'hi'}], 'model': 'm'}
    assert _canonical_request(a) == _canonical_request(b)


@pytest.mark.integration
def test_record_then_replay_roundtrip(tmp_path, monkeypatch) -> None:
    """Recording a fixture lets the next replay return the same payload."""
    monkeypatch.setattr('backend.tests.e2e.test_replay_harness.REPLAY_DIR', tmp_path)

    req = {'model': 'm', 'messages': [{'role': 'user', 'content': 'roundtrip'}]}
    resp = {'choices': [{'message': {'role': 'assistant', 'content': 'ok'}}]}
    record(req, resp)

    out = replay_or_raise(req)
    assert out['response'] == resp


def _replay_mode() -> str:
    return os.environ.get('GRINTA_LLM_REPLAY_MODE', 'replay').lower()
