"""Deterministic first-pass codebase exploration for coding tasks."""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_SOURCE_EXTENSIONS = {
    '.c',
    '.cc',
    '.cpp',
    '.cs',
    '.css',
    '.go',
    '.h',
    '.hpp',
    '.html',
    '.java',
    '.js',
    '.jsx',
    '.json',
    '.kt',
    '.md',
    '.php',
    '.py',
    '.rb',
    '.rs',
    '.svelte',
    '.swift',
    '.toml',
    '.ts',
    '.tsx',
    '.vue',
    '.yaml',
    '.yml',
}

_IGNORE_PARTS = {
    '.git',
    '.grinta',
    '.mypy_cache',
    '.pytest_cache',
    '.ruff_cache',
    '.venv',
    '__pycache__',
    'build',
    'dist',
    'node_modules',
}

_STOP_WORDS = {
    'about',
    'add',
    'after',
    'also',
    'and',
    'are',
    'before',
    'build',
    'change',
    'code',
    'create',
    'delete',
    'edit',
    'file',
    'fix',
    'for',
    'from',
    'implement',
    'into',
    'make',
    'modify',
    'need',
    'please',
    'refactor',
    'remove',
    'rename',
    'that',
    'the',
    'this',
    'update',
    'with',
}

_PATH_RE = re.compile(
    r'(?P<path>(?:[\w.-]+[/\\])+[\w.-]+(?:\.[A-Za-z0-9_]+)?|[\w.-]+\.[A-Za-z0-9_]+)'
)
_TOKEN_RE = re.compile(r'[A-Za-z0-9_]+')


@dataclass(frozen=True)
class ContextCandidate:
    """Ranked file candidate with compact evidence."""

    path: str
    score: int
    reasons: tuple[str, ...]
    symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextExplorerResult:
    """Bounded deterministic exploration result."""

    workspace: str
    dirty_files: tuple[str, ...] = ()
    candidates: tuple[ContextCandidate, ...] = ()
    query_terms: tuple[str, ...] = ()


@dataclass
class _CandidateDraft:
    path: str
    score: int = 0
    reasons: set[str] = field(default_factory=set)
    symbols: list[str] = field(default_factory=list)

    def add(self, points: int, reason: str) -> None:
        self.score += points
        self.reasons.add(reason)


def _run(
    args: list[str],
    root: Path,
    *,
    timeout: float = 2.0,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _is_candidate_path(path: str) -> bool:
    parts = Path(path).parts
    if any(part in _IGNORE_PARTS for part in parts):
        return False
    return Path(path).suffix.lower() in _SOURCE_EXTENSIONS


def _normalize_rel_path(path: str) -> str:
    return path.strip().strip('"\'`').replace('\\', '/').lstrip('./')


def _git_files(root: Path, *, limit: int = 5000) -> list[str]:
    result = _run(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard'],
        root,
        timeout=2.0,
    )
    if result is None or result.returncode != 0:
        return []
    files = [_normalize_rel_path(line) for line in result.stdout.splitlines()]
    return [path for path in files if path and _is_candidate_path(path)][:limit]


def _walk_files(root: Path, *, limit: int = 3000) -> list[str]:
    files: list[str] = []
    try:
        iterator = root.rglob('*')
        for path in iterator:
            if len(files) >= limit:
                break
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            rel_text = _normalize_rel_path(str(rel))
            if path.is_file() and _is_candidate_path(rel_text):
                files.append(rel_text)
    except OSError:
        return files
    return files


def _repo_files(root: Path) -> list[str]:
    files = _git_files(root)
    if files:
        return files
    return _walk_files(root)


def git_status_lines(root: Path, *, limit: int = 18) -> list[str]:
    """Return compact git status lines for prompt display."""
    result = _run(['git', 'status', '--short'], root, timeout=1.5)
    if result is None or result.returncode != 0:
        return []
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return lines[:limit]


def _dirty_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for line in git_status_lines(root, limit=100):
        raw = line[3:].strip()
        if ' -> ' in raw:
            raw = raw.rsplit(' -> ', 1)[-1].strip()
        normalized = _normalize_rel_path(raw)
        if normalized and _is_candidate_path(normalized):
            paths.add(normalized)
    return paths


def _query_terms(task: str, *, limit: int = 10) -> list[str]:
    terms: list[str] = []
    for token in _identifier_tokens(task):
        lowered = token.lower()
        if len(lowered) < 3 or lowered in _STOP_WORDS:
            continue
        if lowered not in terms:
            terms.append(lowered)
        if len(terms) >= limit:
            break
    return terms


def _mentioned_paths(task: str) -> set[str]:
    mentions: set[str] = set()
    for match in _PATH_RE.finditer(task):
        path = _normalize_rel_path(match.group('path'))
        if path:
            mentions.add(path)
    return mentions


def _path_tokens(path: str) -> set[str]:
    return {token.lower() for token in _identifier_tokens(path) if len(token) >= 2}


def _identifier_tokens(text: str) -> list[str]:
    expanded = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    expanded = expanded.replace('_', ' ').replace('-', ' ').replace('/', ' ')
    return _TOKEN_RE.findall(expanded)


def _content_hits(root: Path, terms: list[str]) -> dict[str, set[str]]:
    hits: dict[str, set[str]] = {}
    for term in terms[:6]:
        if len(term) < 4:
            continue
        result = _run(
            [
                'rg',
                '--files-with-matches',
                '--ignore-case',
                '--fixed-strings',
                '--glob',
                '!**/.git/**',
                '--glob',
                '!**/.venv/**',
                '--glob',
                '!**/node_modules/**',
                term,
            ],
            root,
            timeout=1.5,
        )
        if result is None or result.returncode not in (0, 1):
            continue
        paths = [
            _normalize_rel_path(line)
            for line in result.stdout.splitlines()
            if line.strip()
        ]
        if len(paths) > 80:
            continue
        for path in paths:
            if _is_candidate_path(path):
                hits.setdefault(path, set()).add(term)
    return hits


def _collect_python_symbols(
    path: Path, terms: set[str], *, limit: int = 4
) -> list[str]:
    if path.suffix.lower() != '.py':
        return []
    try:
        if path.stat().st_size > 350_000:
            return []
        tree = ast.parse(path.read_text(encoding='utf-8', errors='ignore'))
    except (OSError, SyntaxError, ValueError):
        return []

    symbols: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name
        name_tokens = _path_tokens(name)
        if name.lower() in terms or bool(name_tokens & terms):
            symbols.append(name)
            if len(symbols) >= limit:
                break
    return symbols


def _draft_for(drafts: dict[str, _CandidateDraft], path: str) -> _CandidateDraft:
    normalized = _normalize_rel_path(path)
    draft = drafts.get(normalized)
    if draft is None:
        draft = _CandidateDraft(path=normalized)
        drafts[normalized] = draft
    return draft


def explore_context(
    task: str,
    root: Path,
    *,
    max_candidates: int = 6,
) -> ContextExplorerResult:
    """Rank likely files/symbols using cheap deterministic repo signals."""
    root = root.resolve()
    files = _repo_files(root)
    file_set = set(files)
    terms = _query_terms(task)
    term_set = set(terms)
    dirty = _dirty_paths(root)
    mentions = _mentioned_paths(task)
    drafts: dict[str, _CandidateDraft] = {}

    for mentioned in mentions:
        for path in files:
            if path == mentioned or path.endswith('/' + mentioned):
                _draft_for(drafts, path).add(90, 'mentioned in task')

    for path in sorted(dirty & file_set):
        _draft_for(drafts, path).add(24, 'dirty file')

    for path in files:
        overlap = _path_tokens(path) & term_set
        if not overlap:
            continue
        points = min(28, len(overlap) * 7)
        draft = _draft_for(drafts, path)
        draft.add(points, 'path matches ' + ', '.join(sorted(overlap)[:3]))
        stem = Path(path).stem.lower()
        if stem in term_set:
            draft.add(10, 'filename stem matches task')

    for path, matched_terms in _content_hits(root, terms).items():
        draft = _draft_for(drafts, path)
        draft.add(
            min(36, len(matched_terms) * 12),
            'content matches ' + ', '.join(sorted(matched_terms)[:3]),
        )

    top_drafts = sorted(
        drafts.values(),
        key=lambda item: (-item.score, item.path),
    )[: max(max_candidates * 3, max_candidates)]

    for draft in top_drafts:
        symbols = _collect_python_symbols(root / draft.path, term_set)
        if symbols:
            draft.symbols.extend(symbols)
            draft.add(8, 'matching symbols')

    candidates = tuple(
        ContextCandidate(
            path=draft.path,
            score=draft.score,
            reasons=tuple(sorted(draft.reasons)),
            symbols=tuple(draft.symbols[:4]),
        )
        for draft in sorted(top_drafts, key=lambda item: (-item.score, item.path))[
            :max_candidates
        ]
        if draft.score > 0
    )

    return ContextExplorerResult(
        workspace=str(root),
        dirty_files=tuple(sorted(dirty)[:18]),
        candidates=candidates,
        query_terms=tuple(terms),
    )


__all__ = [
    'ContextCandidate',
    'ContextExplorerResult',
    'explore_context',
    'git_status_lines',
]
