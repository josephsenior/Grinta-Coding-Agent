"""Blast radius calculation utilities.

Uses LSP ``find_references`` when available, otherwise falls back to a
ripgrep/grep cross-file search so blast-radius warnings still work on
machines without a language server installed.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from backend.core.logger import app_logger as logger
from backend.utils.lsp_client import get_lsp_client
from backend.utils.treesitter_editor import TreeSitterEditor

# Directories excluded from the grep fallback to avoid noise.
_GREP_EXCLUDED_DIRS = (
    'node_modules',
    '.git',
    '__pycache__',
    '.venv',
    'venv',
    '.tox',
    'dist',
    'build',
    '.mypy_cache',
    '.pytest_cache',
)


def _grep_cross_file_refs(
    symbol_name: str, search_root: str | None = None
) -> int:
    """Count cross-file occurrences of *symbol_name* using rg or grep.

    Returns the number of matching lines (a rough proxy for reference count).
    """
    root = search_root or os.environ.get('PROJECT_ROOT') or os.getcwd()
    # Prefer ripgrep for speed; fall back to grep -rn.
    rg = shutil.which('rg')
    if rg:
        cmd = [
            rg,
            '--count-matches',
            '--no-heading',
            '--word-regexp',
            '--ignore-case',
        ]
        for d in _GREP_EXCLUDED_DIRS:
            cmd += [f'--glob=!**/{d}/**']
        cmd += [symbol_name, root]
    else:
        cmd = ['grep', '-rwn', '-i', '--count']
        for d in _GREP_EXCLUDED_DIRS:
            cmd += [f'--exclude-dir={d}']
        cmd += [symbol_name, root]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=10,
            text=True,
        )
        total = 0
        for line in proc.stdout.splitlines():
            # rg --count-matches / grep --count output: path:count
            m = re.search(r':(\d+)$', line)
            if m:
                total += int(m.group(1))
        return total
    except Exception as exc:
        logger.debug('Grep-based blast radius search failed: %s', exc)
        return 0


def check_blast_radius(
    file_path: str, symbol_name: str, threshold: int = 10
) -> str | None:
    """Return a warning if *symbol_name* is referenced in more than *threshold* places.

    Strategy: try LSP ``find_references`` first (precise, cross-file).
    If LSP returns nothing (not installed / unavailable), fall back to a
    lightweight ripgrep/grep word-search across the project.
    """
    try:
        universal = TreeSitterEditor()
        loc = universal.find_symbol(file_path, symbol_name)
        if not loc:
            return None

        # 1. Try LSP (precise cross-file references) ──────────────────
        lsp = get_lsp_client()
        lsp_result = lsp.query(
            'find_references',
            file=file_path,
            line=loc.line_start,
            column=1,
        )
        refs = lsp_result.locations

        # 2. Fallback: grep-based cross-file search ───────────────────
        if not refs:
            ref_count = _grep_cross_file_refs(
                symbol_name,
                search_root=str(Path(file_path).parent),
            )
            if ref_count > threshold:
                warning = (
                    f"\n\n[WARNING: BLAST RADIUS EXCEEDS {threshold}] "
                    f"The symbol '{symbol_name}' appears in ~{ref_count} "
                    f"locations across the project. Please consider if "
                    f"those call sites need updating."
                )
                logger.info(
                    'Blast radius warning (grep fallback) for %s (~%d refs)',
                    symbol_name,
                    ref_count,
                )
                return warning
            return None

        if len(refs) > threshold:
            warning = f"\n\n[WARNING: BLAST RADIUS EXCEEDS {threshold}] The symbol '{symbol_name}' is referenced in {len(refs)} other locations. Please consider if those call sites need updating."
            logger.info(
                'Blast radius warning added for %s (%d references)',
                symbol_name,
                len(refs),
            )
            return warning
    except Exception as e:
        logger.debug('Blast radius check failed for %s: %s', symbol_name, e)
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

        tree = parser.parse(code_snippet.encode('utf-8'))

        def _find_first_symbol(node):
            if any(
                k in node.type
                for k in ['function', 'class', 'method', 'declaration', 'declarator']
            ):
                name_node = editor._get_name_node(node)
                if name_node:
                    return (
                        (name_node.text.decode('utf-8') if name_node.text else '')
                        if name_node.text
                        else ''
                    )
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
