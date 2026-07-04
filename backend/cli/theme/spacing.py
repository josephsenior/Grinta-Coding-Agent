"""Spacing scale for the Grinta TUI.

Use these constants instead of hand-typed padding/margin values so that the
TUI has a single, consistent rhythm.

Convention: spaces around the value (e.g. ``"1 2"``) follow Textual's
shorthand for ``top right bottom left``. The four-point variants
(``SPACE_BLOCK_*``) collapse the four sides into one block.
"""

from __future__ import annotations

# 0 — flush
SPACE_0 = '0 0'
# 1 — tight (e.g. inline label gap)
SPACE_1 = '0 1'
# 2 — standard inline padding (e.g. card horizontal)
SPACE_2 = '1 2'
# 3 — comfortable padding (e.g. card vertical breathing)
SPACE_3 = '1 3'
# 4 — block padding (panels)
SPACE_BLOCK_2 = '2 2'
# 5 — spacious block (dialogs)
SPACE_BLOCK_3 = '2 3'
# 6 — transcript block (the heaviest unit; used between transcript cards)
TRANSCRIPT_BLOCK = '2 2 3 2'

# Margin scale (slightly different rhythm than padding)
MARGIN_TIGHT = '0 0 1 0'
MARGIN_BLOCK = '0 0 2 0'
MARGIN_TRANSCRIPT = '0 0 1 0'
