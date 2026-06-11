"""Regression tests for storage path consistency in the TUI bootstrap.

These tests verify that:
1. The TUI's `_bootstrap` creates a LocalFileStore (not InMemoryFileStore)
   and the EventStream uses the correct user_id so events are stored under
   the same path as conversation metadata.
2. There is no path mismatch where events go to ``sessions/<sid>/events/``
   while conversation metadata goes to ``users/<user_id>/conversations/<sid>/``.

Background
----------
Originally, ``_app_screen_lifecycle_mixin._bootstrap`` called
``get_file_store(config)`` (passing the config object as ``file_store_type``).
The function signature is ``get_file_store(file_store_type, local_data_root)``,
so the config object never equaled ``'local'`` and the function silently
returned an ``InMemoryFileStore`` (no persistence). On top of that, the
``EventStream`` was created without a ``user_id`` so events landed at
``sessions/<sid>/events/`` instead of ``users/tui/conversations/<sid>/events/``,
causing the agent to lose its memory after every restart.
"""

from __future__ import annotations

import os


def test_get_file_store_call_uses_config_file_store_attribute():
    """``get_file_store`` must be called with ``config.file_store`` and a path.

    The TUI bootstrap previously called ``get_file_store(config)``, which
    passed the config object as ``file_store_type`` and silently fell back
    to ``InMemoryFileStore`` (losing all events on restart). This test
    guards against that regression by inspecting the call site.
    """
    from backend.cli.tui import _app_screen_lifecycle_mixin as mixin

    source = mixin.__file__
    assert source is not None
    with open(source, encoding='utf-8') as fh:
        text = fh.read()

    # The literal buggy call must not appear anywhere in the bootstrap.
    assert 'get_file_store(config)' not in text, (
        'TUI bootstrap must not call get_file_store(config); it must '
        'pass file_store_type=config.file_store and a local_data_root '
        'so the LocalFileStore is used instead of the in-memory one.'
    )

    # The bootstrap must forward user_id='tui' to the EventStream so events
    # are stored under users/tui/conversations/<sid>/events/ (matching the
    # conversation metadata path) rather than sessions/<sid>/events/.
    assert "EventStream(sid=sid, file_store=file_store, user_id='tui')" in text, (
        'TUI bootstrap must initialize EventStream with user_id="tui" '
        'so events land in the same per-user conversation directory '
        'as conversation_stats.pkl.'
    )


def test_event_stream_and_conversation_share_storage_path(tmp_path):
    """End-to-end: events.db must land where the conversation expects it."""
    from backend.ledger.stream import EventStream
    from backend.persistence.local_file_store import LocalFileStore
    from backend.persistence.locations import (
        get_conversation_dir,
        get_conversation_events_dir,
    )

    fs = LocalFileStore(str(tmp_path))
    sid = 'sid-storage-path-test'
    user_id = 'tui'

    stream = EventStream(sid=sid, file_store=fs, user_id=user_id)
    try:
        conversation_dir = get_conversation_dir(sid, user_id)
        events_dir = get_conversation_events_dir(sid, user_id)
        expected_db = os.path.join(str(tmp_path), events_dir, 'events.db')

        assert fs.get_full_path(conversation_dir) is not None
        assert fs.get_full_path(events_dir) is not None

        # SQLite store must initialize at the user-scoped path, not at
        # the global ``sessions/<sid>/events/`` path.
        assert stream._sqlite_store is not None, (
            'EventStream must initialize a SQLite store when persistence is enabled.'
        )
        actual_db_path = os.path.normpath(os.fspath(stream._sqlite_store._db_path))
        expected_db_norm = os.path.normpath(expected_db)
        assert actual_db_path == expected_db_norm, (
            f'events.db must be at {expected_db_norm} (under users/tui/conversations/'
            f'<sid>/events/) but is at {actual_db_path}'
        )
        assert not os.path.exists(
            os.path.join(str(tmp_path), 'sessions', sid, 'events', 'events.db')
        ), 'events.db must NOT be created at the global sessions/<sid>/events/ path'
    finally:
        stream.close()
