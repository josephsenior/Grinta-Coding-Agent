"""Historical: was used to add _cp. routing for test patch compatibility.

Phase 2 (flat architecture) eliminated the mixin modules and the _cp.
self-import pattern.  All functions are now imported directly into
``pipeline.py`` / ``compaction.py``, so test patches must target those
modules directly instead of the ``__init__`` namespace.
"""

from __future__ import annotations
