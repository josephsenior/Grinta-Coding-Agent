"""Tree-sitter tree-walking helpers used by the editor class.

Each helper is a module function. ``get_name_node`` is pure; the rest accept
the editor instance as the first positional argument so they can dispatch
through ``editor.get_name_node`` (a thin forwarder) when looking up definition
names. Keeping these as module functions lets the editor class stay small
while still allowing test monkey-patching of the public ``get_name_node`` hook.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from backend.utils.treesitter._tse_languages import (
    get_class_node_types,
    get_method_node_types,
)
from backend.utils.treesitter._tse_types import (
    AmbiguousSymbolError,
    SymbolLocation,
)

if TYPE_CHECKING:
    from tree_sitter import (
        Node as NodeType,
    )
    from tree_sitter import (
        Tree as TreeType,
    )
else:  # pragma: no cover
    NodeType = TreeType = Any


# Common body node names across languages. Used by ``get_function_body_node``.
_BODY_NODE_TYPES = ('block', 'body', 'compound_statement', 'expression_statement')

# Child node types whose presence between ``:`` and the block signals
# comments/decorators that should be replaced together with the body. We skip
# NEWLINE/INDENT/DEDENT (whitespace sentinels in the Python grammar).
_BODY_SKIP_CHILD_TYPES = frozenset({':', 'NEWLINE', 'INDENT', 'DEDENT', 'newline'})


def get_name_node(node: NodeType) -> NodeType | None:
    """Extract the name identifier node from a definition node.

    Walks the node's direct children looking for the conventional name fields
    used by Tree-sitter grammars (``identifier``, ``name``,
    ``property_identifier``, ``type_identifier``) and recurses through
    declarator wrappers (``function_declarator``, ``class_name``).
    """
    for child in node.children:
        if child.type in (
            'identifier',
            'name',
            'property_identifier',
            'type_identifier',
        ):
            return child
        if child.type in ('function_declarator', 'class_name'):
            return get_name_node(child)
    return None


def find_node_by_name(
    editor: Any,
    node: NodeType,
    file_bytes: bytes,
    target_name: str,
    node_types: list[str],
) -> NodeType | None:
    """Recursively find the first node matching ``target_name`` and ``node_types``."""
    if node.type in node_types:
        name_node = editor.get_name_node(node)
        if name_node:
            name_text = file_bytes[name_node.start_byte : name_node.end_byte].decode(
                'utf-8'
            )
            if name_text == target_name:
                return node
    for child in node.children:
        result = find_node_by_name(editor, child, file_bytes, target_name, node_types)
        if result:
            return result
    return None


def find_all_nodes_by_name(
    editor: Any,
    node: NodeType,
    file_bytes: bytes,
    target_name: str,
    node_types: list[str],
) -> list[NodeType]:
    """Recursively find ALL nodes matching ``target_name`` and ``node_types``.

    Unlike :func:`find_node_by_name`, this returns every match so the caller
    can detect ambiguity (multiple symbols with the same name).
    """
    matches: list[NodeType] = []
    if node.type in node_types:
        name_node = editor.get_name_node(node)
        if name_node:
            name_text = file_bytes[name_node.start_byte : name_node.end_byte].decode(
                'utf-8'
            )
            if name_text == target_name:
                matches.append(node)
    for child in node.children:
        matches.extend(
            find_all_nodes_by_name(editor, child, file_bytes, target_name, node_types)
        )
    return matches


def find_class_node(
    editor: Any,
    tree: TreeType,
    file_bytes: bytes,
    class_name: str,
    language: str,
) -> NodeType | None:
    """Find a class node by name within ``tree``."""
    return find_node_by_name(
        editor,
        tree.root_node,
        file_bytes,
        class_name,
        get_class_node_types(language),
    )


def find_method_node_in_class(
    editor: Any,
    class_node: NodeType,
    file_bytes: bytes,
    method_name: str,
    language: str,
) -> NodeType | None:
    """Find a method node within an already-located class node."""
    return find_node_by_name(
        editor,
        class_node,
        file_bytes,
        method_name,
        get_method_node_types(language),
    )


def find_method_in_class(
    editor: Any,
    tree: TreeType,
    file_bytes: bytes,
    class_name: str,
    method_name: str,
    file_path: str,
    language: str,
) -> SymbolLocation | None:
    """Find a method within a class and return a :class:`SymbolLocation`."""
    class_node = find_node_by_name(
        editor,
        tree.root_node,
        file_bytes,
        class_name,
        get_class_node_types(language),
    )
    if not class_node:
        return None

    method_node = find_node_by_name(
        editor,
        class_node,
        file_bytes,
        method_name,
        get_method_node_types(language),
    )
    if not method_node:
        return None

    return SymbolLocation(
        file_path=file_path,
        line_start=method_node.start_point[0] + 1,  # Tree-sitter is 0-indexed
        line_end=method_node.end_point[0] + 1,
        byte_start=method_node.start_byte,
        byte_end=method_node.end_byte,
        node_type=method_node.type,
        symbol_name=method_name,
        parent_name=class_name,
    )


def search_tree_for_symbol(
    editor: Any,
    tree: TreeType,
    file_bytes: bytes,
    symbol_name: str,
    file_path: str,
    language: str,
    symbol_type: str | None = None,
) -> SymbolLocation | None:
    """Search ``tree`` for ``symbol_name`` (function or class) by type filter."""
    if symbol_type == 'function':
        node_types = [
            'function_definition',
            'function_declaration',
            'method_definition',
        ]
    elif symbol_type == 'class':
        node_types = ['class_definition', 'class_declaration']
    else:
        # Search for both function- and class-shaped definitions.
        node_types = [
            'function_definition',
            'function_declaration',
            'method_definition',
            'class_definition',
            'class_declaration',
        ]

    all_nodes = find_all_nodes_by_name(
        editor, tree.root_node, file_bytes, symbol_name, node_types
    )
    if not all_nodes:
        return None

    if len(all_nodes) > 1:
        matches = [
            SymbolLocation(
                file_path=file_path,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                byte_start=node.start_byte,
                byte_end=node.end_byte,
                node_type=node.type,
                symbol_name=symbol_name,
                parent_name=None,
            )
            for node in all_nodes
        ]
        raise AmbiguousSymbolError(symbol_name, matches)

    found_node = all_nodes[0]
    return SymbolLocation(
        file_path=file_path,
        line_start=found_node.start_point[0] + 1,
        line_end=found_node.end_point[0] + 1,
        byte_start=found_node.start_byte,
        byte_end=found_node.end_byte,
        node_type=found_node.type,
        symbol_name=symbol_name,
        parent_name=None,
    )


def get_function_body_node(func_node: NodeType, language: str) -> NodeType | None:
    """Return the body node of ``func_node`` (language-agnostic).

    ``language`` is currently unused; kept in the signature to match the
    original method and to leave room for per-language overrides later.
    """
    for child in func_node.children:
        if child.type in _BODY_NODE_TYPES:
            return child
    return None


def has_syntax_errors(node: NodeType) -> bool:
    """Return ``True`` if ``node``'s subtree contains any ``ERROR``/``MISSING``."""
    if node.type == 'ERROR' or node.is_missing:
        return True
    for child in node.children:
        if has_syntax_errors(child):
            return True
    return False


def expand_body_range(func_node: NodeType, body_node: NodeType) -> SimpleNamespace:
    """Expand ``body_node`` to also include comments/decorators between ``:`` and the block.

    Tree-sitter places comments as siblings of the block, so the raw
    ``body_node.start_byte``/``body_node.end_byte`` may miss them. We walk
    siblings anchored at the first ``:`` to widen the range.
    """
    body_start = body_node.start_byte
    body_end = body_node.end_byte
    colon_end: int | None = None
    for child in func_node.children:
        if child.type == ':':
            colon_end = child.end_byte
            break
    if colon_end is not None:
        for child in func_node.children:
            if (
                child.start_byte >= colon_end
                and child.type not in _BODY_SKIP_CHILD_TYPES
            ):
                body_start = min(body_start, child.start_byte)
                body_end = max(body_end, child.end_byte)
    return SimpleNamespace(start_byte=body_start, end_byte=body_end)


def replace_node_content(
    original_code: str,
    node: NodeType,
    new_content: str,
    preserve_indentation: bool = True,
) -> str:
    """Replace ``node``'s byte range in ``original_code`` with ``new_content``.

    When ``preserve_indentation`` is set, the leading whitespace of the node's
    first line is applied to every non-first line of ``new_content`` so the
    replacement keeps the surrounding indent.
    """
    start_byte = node.start_byte
    end_byte = node.end_byte

    if preserve_indentation:
        start_line_begin = original_code.rfind('\n', 0, start_byte) + 1
        original_indent = original_code[start_line_begin:start_byte]

        new_content_lines = new_content.split('\n')
        indented_lines = [
            original_indent + line if i > 0 else line
            for i, line in enumerate(new_content_lines)
        ]
        new_content = '\n'.join(indented_lines)

    return original_code[:start_byte] + new_content + original_code[end_byte:]
