"""Blast radius calculation utilities."""

import re
from backend.core.logger import app_logger as logger
from backend.utils.treesitter_editor import TreeSitterEditor
from backend.utils.lsp_client import get_lsp_client

def check_blast_radius(
    file_path: str, symbol_name: str, threshold: int = 10
) -> str | None:
    """Query LSP for references to the edited symbol and return a warning if it exceeds the threshold."""
    try:
        universal = TreeSitterEditor()
        loc = universal.find_symbol(file_path, symbol_name)
        if not loc:
            return None

        lsp = get_lsp_client()
        lsp_result = lsp.query(
            "find_references",
            file=file_path,
            line=loc.line_start,
            column=1,
        )
        refs = lsp_result.locations

        if len(refs) > threshold:
            warning = f"\n\n[WARNING: BLAST RADIUS EXCEEDS {threshold}] The symbol '{symbol_name}' is referenced in {len(refs)} other locations. Please consider if those call sites need updating."
            logger.info(
                "Blast radius warning added for %s (%d references)",
                symbol_name,
                len(refs),
            )
            return warning
    except Exception as e:
        logger.debug("Blast radius check failed for %s: %s", symbol_name, e)
    return None

def check_blast_radius_from_code(
    file_path: str, code_snippet: str, threshold: int = 10
) -> str | None:
    """Extract a primary symbol from the snippet and check its blast radius."""
    try:
        editor = TreeSitterEditor()
        lang = editor.detect_language(file_path)
        if not lang:
            return None
            
        parser = editor.get_parser(lang)
        if not parser:
            return None
            
        tree = parser.parse(code_snippet.encode("utf-8"))
        
        def _find_first_symbol(node):
            if any(k in node.type for k in ["function", "class", "method", "declaration", "declarator"]):
                name_node = editor._get_name_node(node)
                if name_node:
                    return ((name_node.text.decode("utf-8") if name_node.text else "") if name_node.text else "")
            for child in node.children:
                res = _find_first_symbol(child)
                if res:
                    return res
            return None

        symbol_name = _find_first_symbol(tree.root_node)
        if symbol_name:
            return check_blast_radius(file_path, symbol_name, threshold)
    except Exception:
        pass
    return None
