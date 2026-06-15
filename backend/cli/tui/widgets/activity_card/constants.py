"""Internal diff-line encoding prefixes for ActivityCard expanded bodies."""

from __future__ import annotations

DIFF_ADD_PREFIX = '\x1fgrinta-diff-add\x1f'
DIFF_REM_PREFIX = '\x1fgrinta-diff-rem\x1f'
DIFF_CTX_PREFIX = '\x1fgrinta-diff-ctx\x1f'
DIFF_SPLIT_PREFIX = '\x1fgrinta-diff-split\x1f'
