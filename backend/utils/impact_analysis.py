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
from typing import Literal, Any

from backend.core.logging.logger import app_logger as logger
from backend.utils.lsp.lsp_client import get_lsp_client
from backend.utils.treesitter.treesitter_editor import TreeSitterEditor

# Common code/text file extensions to walk as fallback.
_COMMON_EXTENSIONS = {
    '.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java', '.c', '.cpp',
    '.h', '.hpp', '.cs', '.rb', '.php', '.swift', '.kt', '.scala', '.sh',
    '.bat', '.ps1', '.sql', '.yaml', '.yml', '.json', '.md', '.txt', '.xml',
    '.html', '.css', '.toml', '.ini', '.cfg'
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
    engine: Literal["lsp", "ripgrep", "ast", "unknown"]
    confidence: Literal["high", "medium", "low"]

    total_references: int
    unique_files: int
    external_file_references: int
    production_references: int
    test_references: int

    locations: list[ReferenceLocation] = field(default_factory=list)
    truncated: bool = False

    risk: Literal["low", "medium", "high"] = "low"
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


def _grep_fallback_locations(
    symbol_name: str,
    definition_file: str,
    definition_line: int,
    search_root: str,
) -> list[ReferenceLocation]:
    """Find references using ripgrep or grep walking when LSP is unavailable."""
    locations: list[ReferenceLocation] = []
    rg = shutil.which('rg')
    
    if rg:
        cmd = [
            rg,
            '-n',
            '--no-heading',
            '--word-regexp',
            '--ignore-case',
            symbol_name,
            search_root,
        ]
        
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            for line in proc.stdout.splitlines():
                # Format: file_path:line_num:text
                parts = line.split(':', 2)
                if len(parts) >= 3:
                    file_path, line_str, text = parts
                    try:
                        line_num = int(line_str)
                    except ValueError:
                        continue
                    
                    # Normalize file path relative to search root / PROJECT_ROOT
                    rel_path = os.path.relpath(file_path, search_root).replace(os.sep, '/')
                    
                    # Exclude the definition line itself
                    if os.path.abspath(file_path) == os.path.abspath(definition_file) and line_num == definition_line:
                        continue
                        
                    # Skip comment lines
                    stripped = text.strip()
                    if stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('/*'):
                        continue
                        
                    locations.append(
                        ReferenceLocation(
                            file_path=rel_path,
                            line=line_num,
                            column=1,
                            text=text,
                            is_test=_is_test_file(rel_path),
                        )
                    )
        except Exception as exc:
            logger.debug('Ripgrep fallback failed: %s', exc)
    else:
        # Walk directories as secondary fallback
        from backend.engine.tools.ignore_filter import get_ignore_spec, prune_ignored_dirs, is_ignored_file
        
        spec = get_ignore_spec(search_root)
        sym_re = re.compile(r'\b' + re.escape(symbol_name) + r'\b', re.IGNORECASE)
        for root_dir, dirs, files in os.walk(search_root):
            prune_ignored_dirs(search_root, root_dir, dirs, spec)
            
            for file in files:
                if is_ignored_file(search_root, root_dir, file, spec):
                    continue
                if Path(file).suffix.lower() in _COMMON_EXTENSIONS:
                    fpath = os.path.join(root_dir, file)
                    rel_path = os.path.relpath(fpath, search_root).replace(os.sep, '/')
                    
                    # Exclude definition file on definition line
                    is_def_file = os.path.abspath(fpath) == os.path.abspath(definition_file)
                    
                    try:
                        with open(fpath, encoding='utf-8', errors='ignore') as fl:
                            for idx, line in enumerate(fl, 1):
                                if is_def_file and idx == definition_line:
                                    continue
                                if sym_re.search(line):
                                    stripped = line.strip()
                                    if stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('/*'):
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
            
    from backend.engine.tools.ignore_filter import get_ignore_spec, prune_ignored_dirs, is_ignored_file
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
        resolved_file = None
        
        # Determine if file_path is a directory or None
        if not file_path or file_path == '.' or os.path.isdir(file_path):
            resolved_file = _find_defining_file(symbol_name, search_root)
        else:
            resolved_file = os.path.abspath(file_path)

        locations: list[ReferenceLocation] = []
        engine: Literal["lsp", "ripgrep", "ast", "unknown"] = "unknown"
        confidence: Literal["high", "medium", "low"] = "low"
        def_file_rel = ""

        if resolved_file and os.path.exists(resolved_file):
            loc = editor.find_symbol(resolved_file, symbol_name)
            if not loc:
                logger.debug('Symbol %s not found in file %s', symbol_name, resolved_file)
                engine = "ripgrep"
                confidence = "low"
                def_file_rel = os.path.relpath(resolved_file, search_root).replace(os.sep, '/')
                locations = _grep_fallback_locations(symbol_name, resolved_file, 0, search_root)
            else:
                def_file = os.path.abspath(resolved_file)
                def_line = loc.line_start
                def_file_rel = os.path.relpath(def_file, search_root).replace(os.sep, '/')

                # 1. Try LSP
                lsp = get_lsp_client()
                lsp_result = None
                if lsp.available:
                    try:
                        lsp_result = lsp.query(
                            'find_references',
                            file=def_file,
                            line=def_line,
                            column=1,
                        )
                    except Exception as e:
                        logger.debug('LSP query failed: %s', e)
                        
                if lsp_result and lsp_result.locations:
                    engine = "lsp"
                    confidence = "high"
                    for ref in lsp_result.locations:
                        # Exclude the definition itself
                        if os.path.abspath(ref.file) == def_file and ref.line == def_line:
                            continue
                        
                        # Fetch text content for the reference line if possible
                        text_content = ''
                        try:
                            ref_abs_path = os.path.abspath(ref.file)
                            with open(ref_abs_path, encoding='utf-8', errors='ignore') as f:
                                lines = f.readlines()
                                if 1 <= ref.line <= len(lines):
                                    text_content = lines[ref.line - 1].rstrip()
                        except Exception:
                            pass
                        
                        rel_path = os.path.relpath(ref.file, search_root).replace(os.sep, '/')
                        locations.append(
                            ReferenceLocation(
                                file_path=rel_path,
                                line=ref.line,
                                column=ref.column,
                                text=text_content or ref.message or '',
                                is_test=_is_test_file(rel_path),
                            )
                        )
                else:
                    # 2. Fallback to Ripgrep/Grep
                    engine = "ripgrep"
                    confidence = "medium"
                    locations = _grep_fallback_locations(symbol_name, def_file, def_line, search_root)
        else:
            # No definition file found, run pure fallback
            engine = "ripgrep"
            confidence = "low"
            locations = _grep_fallback_locations(symbol_name, "", 0, search_root)

        # Deduplicate locations by (file_path, line)
        seen = set()
        deduped_locations: list[ReferenceLocation] = []
        for loc_obj in locations:
            key = (loc_obj.file_path, loc_obj.line)
            if key not in seen:
                seen.add(key)
                deduped_locations.append(loc_obj)
        locations = deduped_locations

        # Calculate counts
        unique_files = len({loc_obj.file_path for loc_obj in locations})
        
        external_file_refs = 0
        production_refs = 0
        test_refs = 0
        
        for loc_obj in locations:
            if def_file_rel and loc_obj.file_path != def_file_rel:
                external_file_refs += 1
            elif not def_file_rel:
                external_file_refs += 1
                
            if loc_obj.is_test:
                test_refs += 1
            else:
                production_refs += 1
                
        total_references = len(locations)
        
        # Risk assessment and reasoning
        reasons: list[str] = []
        risk: Literal["low", "medium", "high"] = "low"
        
        # Determine package crossing
        crosses_package = False
        if resolved_file and os.path.exists(resolved_file):
            def_dir = os.path.dirname(os.path.abspath(resolved_file))
            for loc_obj in locations:
                loc_abs = os.path.abspath(os.path.join(search_root, loc_obj.file_path))
                if os.path.dirname(loc_abs) != def_dir:
                    crosses_package = True
                    break
        else:
            # If no definition file, any reference crosses package
            if total_references > 0:
                crosses_package = True
        
        # Scoring risk rules:
        # High risk: refs > 15 OR unique files > 3 OR crosses package
        # Medium risk: refs > 5 OR unique files > 1 (cross-file)
        if total_references > 15 or unique_files > 3 or crosses_package:
            risk = "high"
        elif total_references > 5 or unique_files > 1:
            risk = "medium"
        else:
            risk = "low"

        if total_references > 15:
            reasons.append(f"High number of references ({total_references})")
        if unique_files > 3:
            reasons.append(f"Referenced across {unique_files} unique files")
        if crosses_package:
            reasons.append("Referenced outside its defining package")
            
        if risk != "high":
            if total_references > 5:
                reasons.append(f"Moderate number of references ({total_references})")
            elif unique_files > 1:
                reasons.append(f"Referenced across {unique_files} files")
                
        if total_references == 0:
            risk = "low"
            reasons.append("No references found outside the definition itself")
        else:
            if test_refs > 0 and production_refs > 0:
                reasons.append("Referenced by both production and test code")
            elif production_refs > 0:
                reasons.append("Referenced by production code")
            elif test_refs > 0:
                reasons.append("Referenced by test code only")

        # Exclude definition directory crossing if it's only in test files
        # Truncate locations if too large (e.g. > 50)
        truncated = False
        if len(locations) > 50:
            locations = locations[:50]
            truncated = True

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
        logger.error('Impact analysis failed for symbol %s: %s', symbol_name, e, exc_info=True)
        return None
