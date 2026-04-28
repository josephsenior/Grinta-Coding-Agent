"""Cross-layer contracts shared between engine, orchestration, and persistence.

Modules here define types that multiple layers depend on without each
layer reaching into the others. Engine code should import from
``backend.core.contracts.*`` rather than from ``backend.orchestration.*``
so the import graph stays one-directional (orchestration → engine, never
the reverse).
"""

from __future__ import annotations
