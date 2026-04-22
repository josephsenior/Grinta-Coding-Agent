"""EventStream pre-dispatch hook ordering (inline delivery)."""

from __future__ import annotations

import tempfile

from backend.ledger import EventSource
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.stream import EventStream, EventStreamSubscriber
from backend.persistence.local_file_store import LocalFileStore


def test_prerunnable_hook_runs_before_inline_subscriber() -> None:
    order: list[str] = []

    def hook(a: CmdRunAction) -> None:
        order.append('hook')

    def on_event(_: object) -> None:
        order.append('sub')

    # Windows: SQLite may retain a handle briefly; allow rmtree to skip locked files.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        fs = LocalFileStore(tmpdir)
        stream = EventStream('prerun-test', fs, worker_count=0)
        try:
            stream.pre_runnable_action_dispatch = hook
            stream.subscribe(EventStreamSubscriber.TEST, on_event, 't')
            act = CmdRunAction(command='echo 1')
            stream.add_event(act, EventSource.AGENT)
            assert order == ['hook', 'sub']
        finally:
            stream.close()
