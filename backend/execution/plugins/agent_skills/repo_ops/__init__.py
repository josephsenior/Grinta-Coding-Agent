"""Repository operations plugin (vacated in 0.56).

The legacy ``explore_tree_structure`` / ``read_symbol`` /
``search_code_snippets`` skills relied on a custom NetworkX-backed code graph
(``GraphRAG``). They were strict subsets of capabilities already provided by
``lsp`` (LSP), structure editing, ``grep`` / ``glob``
(ripgrep) and ``read_file``. The package is kept as a stub so legacy imports
do not crash; new code should target those four primitives.

Note: the transitive import-graph capability the old
``explore_tree_structure`` provided was reintroduced in
``analyze_project_structure`` as ``command='dependencies'`` — on-demand,
without a persistent index.
"""
