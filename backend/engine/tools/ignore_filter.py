"""Robust file exclusion filtering using pathspec."""

import os
import pathspec

def get_ignore_spec(root: str) -> pathspec.PathSpec:
    """Build a pathspec from default ignores and project .gitignore."""
    # Always block these highly disruptive or purely generated dirs 
    # just in case .gitignore is missing or broken.
    lines = [
        '.git/',
        '.venv/',
        'venv/',
        'env/',
        '.mypy_cache/',
        '.pytest_cache/',
        '.ruff_cache/',
        '__pycache__/',
        'node_modules/',
        '.tmp_cli_manual/',
        'build/',
        'dist/',
        '*.pyc',
        '*.pyo',
        '*.pyd',
        '.DS_Store',
    ]
    
    gitignore_path = os.path.join(root, '.gitignore')
    if os.path.exists(gitignore_path):
        try:
            with open(gitignore_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines.extend(f.readlines())
        except OSError:
            pass
            
    # Also grab local git exclude
    git_exclude = os.path.join(root, '.git', 'info', 'exclude')
    if os.path.exists(git_exclude):
         try:
            with open(git_exclude, 'r', encoding='utf-8', errors='ignore') as f:
                lines.extend(f.readlines())
         except OSError:
            pass
            
    return pathspec.PathSpec.from_lines('gitwildmatch', lines)

def prune_ignored_dirs(root: str, current_root: str, dirs: list[str], spec: pathspec.PathSpec) -> None:
    """Modify dirs list in-place to remove ignored directories."""
    rel_root = os.path.relpath(current_root, root)
    if rel_root == '.':
        rel_root = ''
        
    kept_dirs = []
    for d in dirs:
        # pathspec expects paths relative to git root, with trailing slash for dirs
        rel_path = os.path.join(rel_root, d) if rel_root else d
        rel_path = rel_path.replace(os.sep, '/') + '/'
        
        if not spec.match_file(rel_path):
            kept_dirs.append(d)
            
    dirs[:] = kept_dirs

def is_ignored_file(root: str, current_root: str, filename: str, spec: pathspec.PathSpec) -> bool:
    """Check if a file matches the ignore spec."""
    rel_root = os.path.relpath(current_root, root)
    if rel_root == '.':
        rel_root = ''
        
    rel_path = os.path.join(rel_root, filename) if rel_root else filename
    rel_path = rel_path.replace(os.sep, '/')
    
    return spec.match_file(rel_path)
