"""Unit tests for unified diff preview widget."""

from __future__ import annotations

from backend.cli.tui.widgets.unified_diff_view import (
    build_diff_view_rows,
    decode_diff_view_payload,
    encode_diff_view_payload,
)


def test_encode_decode_diff_view_payload():
    encoded = encode_diff_view_payload(
        path='demo.py',
        old_content='a\n',
        new_content='b\n',
    )
    assert encoded is not None
    payload = decode_diff_view_payload(encoded)
    assert payload is not None
    assert payload['path'] == 'demo.py'
    assert payload['old'] == 'a\n'
    assert payload['new'] == 'b\n'


def test_build_diff_rows_from_old_new():
    rows = build_diff_view_rows(
        old_content='alpha\nbeta\n',
        new_content='alpha\ngamma\nbeta\n',
    )
    kinds = [row.kind for row in rows]
    assert 'ctx' in kinds
    assert 'add' in kinds
    assert any(row.text == 'gamma' for row in rows)


def test_build_diff_rows_from_patch_pairs_replace_lines():
    patch = """--- demo.rs
+++ demo.rs
@@ -1,2 +1,2 @@
-old line
+new line
 context
"""
    rows = build_diff_view_rows(patch=patch)
    rem = [row for row in rows if row.kind == 'rem']
    add = [row for row in rows if row.kind == 'add']
    assert rem and add
    assert rem[0].pair_text == 'new line'
    assert add[0].pair_text == 'old line'
