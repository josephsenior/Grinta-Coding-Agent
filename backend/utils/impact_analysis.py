"""Reference Impact Analysis Engine.

Consolidates LSP-based reference lookup and ripgrep fallback search
to produce a structured ImpactReport.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from backend.core.logging.logger import app_logger as logger
from backend.utils.lsp.lsp_client import LspResult, get_lsp_client
from backend.utils.treesitter.treesitter_editor import TreeSitterEditor

# Common code/text file extensions to walk as fallback.
_COMMON_EXTENSIONS = {
    '.py',
    '.js',
    '.ts',
    '.tsx',
    '.jsx',
    '.go',
    '.rs',
    '.java',
    '.c',
    '.cpp',
    '.h',
    '.hpp',
    '.cs',
    '.rb',
    '.php',
    '.swift',
    '.kt',
    '.scala',
    '.sh',
    '.bat',
    '.ps1',
    '.sql',
    '.yaml',
    '.yml',
    '.json',
    '.md',
    '.txt',
    '.xml',
    '.html',
    '.css',
    '.toml',
    '.ini',
    '.cfg',
}


@dataclass
class ReferenceLocation:
    file_path: str
    line: int
    column: int
    text: str
    is_test: bool


@dataclass
class ImpactReport:
    symbol: str
    definition_file: str
    engine: Literal['lsp', 'ripgrep', 'ast', 'unknown']
    confidence: Literal['high', 'medium', 'low']

    total_references: int
    unique_files: int
    external_file_references: int
    production_references: int
    test_references: int

    locations: list[ReferenceLocation] = field(default_factory=list)
    truncated: bool = False

    risk: Literal['low', 'medium', 'high'] = 'low'
    reasons: list[str] = field(default_factory=list)


def _is_test_file(file_path: str) -> bool:
    """Classify if a file is a test file based on its name and path parts."""
    parts = Path(file_path).parts
    name = Path(file_path).name.lower()

    # Check if name contains test_ or _test
    if 'test_' in name or '_test' in name:
        return True

    # Check if any path segment matches test, tests, spec, or specs
    test_dirs = {'test', 'tests', 'spec', 'specs'}
    if any(p.lower() in test_dirs for p in parts):
        return True

    return False


def _rel_path(file_path: str, search_root: str) -> str:
    """Return a normalized path relative to search_root."""
    return os.path.relpath(file_path, search_root).replace(os.sep, '/')


def _is_comment_text(text: str) -> bool:
    """Classify a line as a comment based on common comment prefixes."""
    stripped = text.strip()
    return (
        stripped.startswith('#')
        or stripped.startswith('//')
        or stripped.startswith('/*')
    )


def _parse_rg_line(
    line: str,
    definition_file: str,
    definition_line: int,
    search_root: str,
) -> ReferenceLocation | None:
    """Parse a ripgrep output line into a ReferenceLocation when valid."""
    parts = line.split(':', 2)
    if len(parts) < 3:
        return None

    file_path, line_str, text = parts
    try:
        line_num = int(line_str)
    except ValueError:
        return None

    rel_path = _rel_path(file_path, search_root)

    if (
        os.path.abspath(file_path) == os.path.abspath(definition_file)
        and line_num == definition_line
    ):
        return None

    if _is_comment_text(text):
        return None

    return ReferenceLocation(
        file_path=rel_path,
        line=line_num,
        column=1,
        text=text,
        is_test=_is_test_file(rel_path),
    )


def _rg_reference_locations(
    rg: str,
    symbol_name: str,
    definition_file: str,
    definition_line: int,
    search_root: str,
) -> list[ReferenceLocation]:
    """Find references by invoking ripgrep."""
    cmd = [
        rg,
        '-n',
        '--no-heading',
        '--word-regexp',
        '--ignore-case',
        symbol_name,
        search_root,
    ]

    locations: list[ReferenceLocation] = []
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        for line in proc.stdout.splitlines():
            location = _parse_rg_line(
                line, definition_file, definition_line, search_root
            )
            if location is not None:
                locations.append(location)
    except Exception as exc:
        logger.debug('Ripgrep fallback failed: %s', exc)
    return locations


def _scan_file_locations(
    fpath: str,
    rel_path: str,
    is_def_file: bool,
    definition_line: int,
    sym_re: re.Pattern[str],
) -> list[ReferenceLocation]:
    """Scan a single file for symbol references."""
    locations: list[ReferenceLocation] = []
    try:
        with open(fpath, encoding='utf-8', errors='ignore') as fl:
            for idx, line in enumerate(fl, 1):
                if is_def_file and idx == definition_line:
                    continue
                if not sym_re.search(line):
                    continue
                if _is_comment_text(line):
                    continue
                locations.append(
                    ReferenceLocation(
                        file_path=rel_path,
                        line=idx,
                        column=1,
                        text=line.rstrip(),
                        is_test=_is_test_file(rel_path),
                    )
                )
    except Exception:
        pass
    return locations


def _walk_reference_locations(
    symbol_name: str,
    definition_file: str,
    definition_line: int,
    search_root: str,
) -> list[ReferenceLocation]:
    """Find references by walking the search root without ripgrep."""
    from backend.engine.tools.ignore_filter import (
        get_ignore_spec,
        is_ignored_file,
        prune_ignored_dirs,
    )

    spec = get_ignore_spec(search_root)
    sym_re = re.compile(r'\b' + re.escape(symbol_name) + r'\b', re.IGNORECASE)
    locations: list[ReferenceLocation] = []

    for root_dir, dirs, files in os.walk(search_root):
        prune_ignored_dirs(search_root, root_dir, dirs, spec)

        for file in files:
            if is_ignored_file(search_root, root_dir, file, spec):
                continue
            if Path(file).suffix.lower() not in _COMMON_EXTENSIONS:
                continue

            fpath = os.path.join(root_dir, file)
            rel_path = _rel_path(fpath, search_root)
            is_def_file = os.path.abspath(fpath) == os.path.abspath(definition_file)
            locations.extend(
                _scan_file_locations(
                    fpath, rel_path, is_def_file, definition_line, sym_re
                )
            )

    return locations


def _grep_fallback_locations(
    symbol_name: str,
    definition_file: str,
    definition_line: int,
    search_root: str,
) -> list[ReferenceLocation]:
    """Find references using ripgrep or grep walking when LSP is unavailable."""
    rg = shutil.which('rg')
    if rg:
        return _rg_reference_locations(
            rg, symbol_name, definition_file, definition_line, search_root
        )
    return _walk_reference_locations(
        symbol_name, definition_file, definition_line, search_root
    )


def _find_defining_file(symbol_name: str, search_root: str) -> str | None:
    """Find a file in the workspace that defines symbol_name (with def or class)."""
    rg = shutil.which('rg')
    pattern = rf'\b(def|class)\s+{re.escape(symbol_name)}\b'

    if rg:
        cmd = [
            rg,
            '--files-with-matches',
            '--multiline',
            pattern,
            search_root,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            lines = proc.stdout.splitlines()
            if lines:
                return os.path.abspath(lines[0])
        except Exception:
            pass

    from backend.engine.tools.ignore_filter import (
        get_ignore_spec,
        is_ignored_file,
        prune_ignored_dirs,
    )

    spec = get_ignore_spec(search_root)
    sym_re = re.compile(pattern)
    for root_dir, dirs, files in os.walk(search_root):
        prune_ignored_dirs(search_root, root_dir, dirs, spec)
        for file in files:
            if is_ignored_file(search_root, root_dir, file, spec):
                continue
            if Path(file).suffix.lower() in _COMMON_EXTENSIONS:
                fpath = os.path.join(root_dir, file)
                try:
                    with open(fpath, encoding='utf-8', errors='ignore') as fl:
                        content = fl.read()
                        if sym_re.search(content):
                            return os.path.abspath(fpath)
                except Exception:
                    pass
    return None


def _resolve_definition_file(
    file_path: str | None, symbol_name: str, search_root: str
) -> str | None:
    """Resolve the file expected to contain the symbol definition."""
    if not file_path or file_path == '.' or os.path.isdir(file_path):
        return _find_defining_file(symbol_name, search_root)
    return os.path.abspath(file_path)


def _read_reference_text(file_path: str, line: int) -> str:
    """Read the text of a referenced line, returning empty text on failure."""
    try:
        ref_abs_path = os.path.abspath(file_path)
        with open(ref_abs_path, encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            if 1 <= line <= len(lines):
                return lines[line - 1].rstrip()
    except Exception:
        pass
    return ''


def _query_lsp_references(def_file: str, def_line: int) -> LspResult | None:
    """Query the LSP client for references, returning None when unavailable."""
    lsp = get_lsp_client()
    if not lsp.available:
        return None
    try:
        return lsp.query(
            'find_references',
            file=def_file,
            line=def_line,
            column=1,
        )
    except Exception as e:
        logger.debug('LSP query failed: %s', e)
        return None


def _lsp_reference_locations(
    lsp_result: LspResult, def_file: str, def_line: int, search_root: str
) -> list[ReferenceLocation]:
    """Convert LSP reference results into ReferenceLocation entries."""
    locations: list[ReferenceLocation] = []
    for ref in lsp_result.locations:
        if os.path.abspath(ref.file) == def_file and ref.line == def_line:
            continue

        text_content = _read_reference_text(ref.file, ref.line)
        rel_path = _rel_path(ref.file, search_root)
        locations.append(
            ReferenceLocation(
                file_path=rel_path,
                line=ref.line,
                column=ref.column,
                text=text_content or ref.message or '',
                is_test=_is_test_file(rel_path),
            )
        )
    return locations


def _analyze_definition(
    editor: TreeSitterEditor,
    resolved_file: str,
    symbol_name: str,
    search_root: str,
) -> tuple[
    Literal['lsp', 'ripgrep', 'ast', 'unknown'],
    Literal['high', 'medium', 'low'],
    str,
    list[ReferenceLocation],
]:
    """Resolve references for a located definition, preferring LSP."""
    loc = editor.find_symbol(resolved_file, symbol_name)
    if not loc:
        logger.debug('Symbol %s not found in file %s', symbol_name, resolved_file)
        def_file_rel = _rel_path(resolved_file, search_root)
        return (
            'ripgrep',
            'low',
            def_file_rel,
            _grep_fallback_locations(symbol_name, resolved_file, 0, search_root),
        )

    def_file = os.path.abspath(resolved_file)
    def_line = loc.line_start
    def_file_rel = _rel_path(def_file, search_root)
    lsp_result = _query_lsp_references(def_file, def_line)

    if lsp_result and lsp_result.locations:
        return (
            'lsp',
            'high',
            def_file_rel,
            _lsp_reference_locations(lsp_result, def_file, def_line, search_root),
        )

    return (
        'ripgrep',
        'medium',
        def_file_rel,
        _grep_fallback_locations(symbol_name, def_file, def_line, search_root),
    )


def _dedupe_locations(
    locations: list[ReferenceLocation],
) -> list[ReferenceLocation]:
    """Remove duplicate locations by file path and line."""
    seen = set()
    deduped_locations: list[ReferenceLocation] = []
    for loc_obj in locations:
        key = (loc_obj.file_path, loc_obj.line)
        if key not in seen:
            seen.add(key)
            deduped_locations.append(loc_obj)
    return deduped_locations


def _count_references(
    locations: list[ReferenceLocation], def_file_rel: str
) -> tuple[int, int, int]:
    """Count external, production, and test references."""
    external_file_refs = 0
    production_refs = 0
    test_refs = 0

    for loc_obj in locations:
        if not def_file_rel or loc_obj.file_path != def_file_rel:
            external_file_refs += 1
        if loc_obj.is_test:
            test_refs += 1
        else:
            production_refs += 1

    return external_file_refs, production_refs, test_refs


def _crosses_package(
    resolved_file: str | None,
    search_root: str,
    locations: list[ReferenceLocation],
    total_references: int,
) -> bool:
    """Determine whether references reach outside the definition's directory."""
    if resolved_file and os.path.exists(resolved_file):
        def_dir = os.path.dirname(os.path.abspath(resolved_file))
        for loc_obj in locations:
            loc_abs = os.path.abspath(os.path.join(search_root, loc_obj.file_path))
            if os.path.dirname(loc_abs) != def_dir:
                return True
        return False
    return total_references > 0


def _risk_level(
    total_references: int, unique_files: int, crosses_package: bool
) -> Literal['low', 'medium', 'high']:
    """Score impact risk from reference counts and package crossing."""
    if total_references > 15 or unique_files > 3 or crosses_package:
        return 'high'
    if total_references > 5 or unique_files > 1:
        return 'medium'
    return 'low'


def _risk_reasons(
    risk: Literal['low', 'medium', 'high'],
    total_references: int,
    unique_files: int,
    crosses_package: bool,
) -> list[str]:
    """Build the reference-volume portion of the risk reasons."""
    reasons: list[str] = []
    if total_references > 15:
        reasons.append(f'High number of references ({total_references})')
    if unique_files > 3:
        reasons.append(f'Referenced across {unique_files} unique files')
    if crosses_package:
        reasons.append('Referenced outside its defining package')

    if risk != 'high':
        if total_references > 5:
            reasons.append(f'Moderate number of references ({total_references})')
        elif unique_files > 1:
            reasons.append(f'Referenced across {unique_files} files')

    return reasons


def _reference_kind_reasons(
    total_references: int, production_refs: int, test_refs: int
) -> list[str]:
    """Build reasons describing where references appear."""
    if total_references == 0:
        return ['No references found outside the definition itself']
    if test_refs > 0 and production_refs > 0:
        return ['Referenced by both production and test code']
    if production_refs > 0:
        return ['Referenced by production code']
    if test_refs > 0:
        return ['Referenced by test code only']
    return []


def _assess_risk(
    resolved_file: str | None,
    search_root: str,
    locations: list[ReferenceLocation],
    total_references: int,
    unique_files: int,
    production_refs: int,
    test_refs: int,
) -> tuple[Literal['low', 'medium', 'high'], list[str]]:
    """Assess impact risk and collect the reasons behind it."""
    crosses_package = _crosses_package(
        resolved_file, search_root, locations, total_references
    )
    risk = _risk_level(total_references, unique_files, crosses_package)
    if total_references == 0:
        risk = 'low'

    reasons = _risk_reasons(risk, total_references, unique_files, crosses_package)
    reasons.extend(
        _reference_kind_reasons(total_references, production_refs, test_refs)
    )
    return risk, reasons


def analyze_symbol_impact(
    file_path: str | None,
    symbol_name: str,
    threshold: int = 15,
) -> ImpactReport | None:
    """Perform structural impact analysis for a code symbol, returning an ImpactReport.

    Resolves definition via Tree-sitter, queries LSP references if available,
    and falls back to ripgrep otherwise. Excludes definition, classifies tests,
    and rates impact risk.
    """
    try:
        editor = TreeSitterEditor()
        search_root = os.environ.get('PROJECT_ROOT') or os.getcwd()
        resolved_file = _resolve_definition_file(file_path, symbol_name, search_root)

        if resolved_file and os.path.exists(resolved_file):
            engine, confidence, def_file_rel, locations = _analyze_definition(
                editor, resolved_file, symbol_name, search_root
            )
        else:
            engine = 'ripgrep'
            confidence = 'low'
            def_file_rel = ''
            locations = _grep_fallback_locations(symbol_name, '', 0, search_root)

        locations = _dedupe_locations(locations)
        unique_files = len({loc_obj.file_path for loc_obj in locations})
        external_file_refs, production_refs, test_refs = _count_references(
            locations, def_file_rel
        )
        total_references = len(locations)
        risk, reasons = _assess_risk(
            resolved_file,
            search_root,
            locations,
            total_references,
            unique_files,
            production_refs,
            test_refs,
        )

        truncated = len(locations) > 50
        if truncated:
            locations = locations[:50]

        return ImpactReport(
            symbol=symbol_name,
            definition_file=def_file_rel,
            engine=engine,
            confidence=confidence,
            total_references=total_references,
            unique_files=unique_files,
            external_file_references=external_file_refs,
            production_references=production_refs,
            test_references=test_refs,
            locations=locations,
            truncated=truncated,
            risk=risk,
            reasons=reasons,
        )
    except Exception as e:
        logger.error(
            'Impact analysis failed for symbol %s: %s', symbol_name, e, exc_info=True
        )
        return None
