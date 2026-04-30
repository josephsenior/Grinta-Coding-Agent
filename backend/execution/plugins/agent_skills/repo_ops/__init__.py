"""Repository operations plugin (vacated in 0.56).

The legacy ``explore_tree_structure`` / ``read_symbol_definition`` /
``search_code_snippets`` skills relied on a custom NetworkX-backed code graph
(``GraphRAG``). They were strict subsets of capabilities already provided by
``lsp`` (LSP), ``symbol_editor`` (tree-sitter), ``search_code``
(ripgrep) and ``read_file``. The package is kept as a stub so legacy imports
do not crash; new code should target those four primitives.
"""
