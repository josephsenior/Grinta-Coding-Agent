"""Tree-sitter runtime detection and shared language/parser bindings.

Defines the module-level flags the editor relies on:

- ``TREE_SITTER_AVAILABLE``: ``True`` when both ``tree_sitter`` and
  ``tree_sitter_language_pack`` import successfully.
- ``_get_language`` / ``_get_parser``: bound to the language-pack factories when
  available, otherwise ``None``.
- ``_RuntimeParser``: the runtime-imported ``Parser`` class, or ``None`` when
  tree-sitter is missing.

The type aliases ``LanguageType``/``ParserType``/``NodeType``/``TreeType`` are
TYPE_CHECKING-only; the runtime path doesn't need them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from tree_sitter import (
        Language as LanguageType,
    )
    from tree_sitter import (
        Node as NodeType,
    )
    from tree_sitter import (
        Parser as ParserType,
    )
    from tree_sitter import (
        Tree as TreeType,
    )
else:  # pragma: no cover - runtime import with graceful fallback
    LanguageType = ParserType = NodeType = TreeType = Any

TREE_SITTER_AVAILABLE = False
_RuntimeParser: Any | None = None
_get_language: Callable[[str], Any] | None = None
_get_parser: Callable[[str], Any] | None = None
try:  # pragma: no cover - exercised in integration tests
    from tree_sitter import (  # type: ignore[no-redef]
        Parser as _RuntimeParserModule,
    )
    from tree_sitter_language_pack import (  # type: ignore[no-redef]
        get_language as _runtime_get_language,
    )
    from tree_sitter_language_pack import (
        get_parser as _runtime_get_parser,
    )

    _RuntimeParser = _RuntimeParserModule
    _get_language = cast(Callable[[str], Any], _runtime_get_language)
    _get_parser = cast(Callable[[str], Any], _runtime_get_parser)
    TREE_SITTER_AVAILABLE = True
except ImportError:  # pragma: no cover - handled in __init__
    TREE_SITTER_AVAILABLE = False
