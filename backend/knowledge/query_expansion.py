"""Query expansion with synonyms for improved RAG recall."""

from __future__ import annotations

import re
from typing import Any


class QueryExpander:
    """Expands queries with synonyms to improve recall."""

    SYNONYMS: dict[str, set[str]] = {
        'function': {'method', 'procedure', 'subroutine', 'func'},
        'class': {'object', 'type', 'interface', 'struct'},
        'variable': {'var', 'const', 'let', 'parameter', 'arg'},
        'file': {'document', 'source', 'module'},
        'error': {'exception', 'bug', 'issue', 'fault', 'failure'},
        'test': {'spec', 'unit', 'mock', 'assertion'},
        'config': {'configuration', 'settings', 'options'},
        'api': {'endpoint', 'route', 'service', 'interface'},
        'database': {'db', 'storage', 'data', 'query'},
        'auth': {'authentication', 'authorization', 'login', 'security'},
        'install': {'setup', 'init', 'configure', 'deploy'},
        'build': {'compile', 'package', 'bundle'},
        'run': {'execute', 'start', 'launch', 'invoke'},
        'debug': {'troubleshoot', 'diagnose', 'fix', 'inspect'},
        'refactor': {'restructure', 'reorganize', 'cleanup', 'improve'},
        'implement': {'add', 'create', 'build', 'develop'},
        'remove': {'delete', 'drop', 'clear', 'uninstall'},
        'update': {'modify', 'change', 'edit', 'upgrade'},
        'check': {'verify', 'validate', 'ensure', 'confirm'},
        'find': {'search', 'locate', 'discover', 'get'},
        'list': {'show', 'display', 'enumerate', 'get_all'},
        'create': {'make', 'add', 'new', 'generate'},
        'read': {'load', 'fetch', 'retrieve', 'open'},
        'write': {'save', 'store', 'persist', 'output'},
    }

    CODE_PATTERNS: dict[str, list[str]] = {
        'pytest': ['test_', 'Test', 'assert', 'fixture'],
        'unittest': ['test', 'assert', 'mock', 'TestCase'],
        'django': ['models', 'views', 'urls', 'settings', 'manage.py'],
        'flask': ['app', 'route', 'blueprint', 'request', 'response'],
        'fastapi': ['app', 'router', 'endpoint', 'FastAPI', 'Pydantic'],
        'react': ['component', 'useState', 'useEffect', 'props', 'jsx'],
        'vue': ['component', 'vue', 'ref', 'computed', 'template'],
        'angular': ['component', 'service', 'module', 'NgModule', 'injectable'],
        'node': ['require', 'module', 'exports', 'async', 'callback'],
        'rust': ['fn', 'impl', 'struct', 'enum', 'trait', 'pub'],
        'go': ['func', 'struct', 'interface', 'package', 'go'],
    }

    TERM_REPLACEMENTS: dict[str, str] = {
        'file': 'source code file',
        'function': 'function or method',
        'class': 'class or interface',
        'variable': 'variable or parameter',
        'return': 'returns or output',
        'import': 'import or require',
        'loop': 'iteration or loop',
        'condition': 'conditional or if statement',
    }

    def __init__(self, expand: bool = True, use_patterns: bool = True):
        self.expand = expand
        self.use_patterns = use_patterns

    def expand_query(self, query: str) -> list[str]:
        """Expand query with synonyms and return multiple query variations."""
        if not self.expand:
            return [query]

        queries = [query]
        words = re.findall(r'\b\w+\b', query.lower())

        for word in words:
            if word in self.SYNONYMS:
                for syn in self.SYNONYMS[word]:
                    expanded = re.sub(rf'\b{word}\b', syn, query, flags=re.IGNORECASE)
                    if expanded not in queries:
                        queries.append(expanded)

        return queries

    def get_code_context_boost(self, query: str) -> dict[str, float]:
        """Return keyword boosts based on detected code patterns."""
        boosts: dict[str, float] = {}
        query_lower = query.lower()

        for pattern_name, keywords in self.CODE_PATTERNS.items():
            matches = sum(1 for kw in keywords if kw.lower() in query_lower)
            if matches > 0:
                boosts[pattern_name] = matches * 0.1

        return boosts

    def contextualize(
        self, query: str, context: dict[str, Any] | None = None
    ) -> list[str]:
        """Generate contextual query variations."""
        queries = self.expand_query(query)

        boosts = self.get_code_context_boost(query)
        if boosts and context:
            context_type = context.get('file_type') or context.get('language')
            if context_type:
                for q in queries:
                    if context_type.lower() in q.lower():
                        continue

        return queries

    def format_for_search(self, query: str) -> str:
        """Format query for hybrid search - add weight hints."""
        expanded = self.expand_query(query)
        if len(expanded) == 1:
            return query

        weighted = ' OR '.join(f'"{q}"' for q in expanded[:3])
        return weighted
