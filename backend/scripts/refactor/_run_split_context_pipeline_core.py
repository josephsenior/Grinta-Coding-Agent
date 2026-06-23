"""Historical: was used to split monolithic core.py into mixin submodules.

Phase 1 (this script): Split ``context_pipeline_core.py`` into 6 mixin
modules (``core_base.py``, ``core_prepare.py``, etc.) composed by a
``core.py`` facade using multiple inheritance.

Phase 2 (manual): Flattened the mixin chain into a single
``ContextPipeline`` class in ``pipeline.py`` with compaction logic
delegated to ``_CompactionEngine`` (``compaction.py``).
All old mixin modules were removed.
"""

from __future__ import annotations
