"""File extension to tree-sitter language mapping.

Tree-sitter provides robust parsing for all the languages listed here, so
the editor can dispatch on language name uniformly.
"""

from __future__ import annotations

# Language extension mapping - 45+ languages supported!
# Tree-sitter provides robust parsing for all these languages
LANGUAGE_EXTENSIONS = {
    # Core languages (most popular)
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'tsx',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
    '.c': 'c',
    '.cpp': 'cpp',
    '.cc': 'cpp',
    '.cxx': 'cpp',
    '.h': 'c',
    '.hpp': 'cpp',
    '.hxx': 'cpp',
    # JVM languages
    '.kt': 'kotlin',
    '.kts': 'kotlin',
    '.scala': 'scala',
    '.clj': 'clojure',
    '.cljs': 'clojure',
    '.cljc': 'clojure',
    # .NET languages
    '.cs': 'c_sharp',
    '.fs': 'f_sharp',
    '.fsx': 'f_sharp',
    # Scripting languages
    '.rb': 'ruby',
    '.php': 'php',
    '.pl': 'perl',
    '.pm': 'perl',
    '.lua': 'lua',
    '.r': 'r',
    '.R': 'r',
    # Web languages
    '.html': 'html',
    '.htm': 'html',
    '.css': 'css',
    '.scss': 'scss',
    '.sass': 'scss',
    '.less': 'css',
    '.vue': 'vue',
    '.svelte': 'svelte',
    # Functional languages
    '.hs': 'haskell',
    '.lhs': 'haskell',
    '.ex': 'elixir',
    '.exs': 'elixir',
    '.erl': 'erlang',
    '.hrl': 'erlang',
    '.ml': 'ocaml',
    '.mli': 'ocaml',
    '.elm': 'elm',
    # Modern systems languages
    '.zig': 'zig',
    '.nim': 'nim',
    '.nims': 'nim',
    '.v': 'v',
    '.d': 'd',
    # Mobile / app development
    '.swift': 'swift',
    '.m': 'objective_c',
    '.mm': 'objective_c',
    '.dart': 'dart',
    # Data/Config languages
    '.json': 'json',
    '.json5': 'json',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.toml': 'toml',
    '.xml': 'xml',
    # Shell/Scripting
    '.sh': 'bash',
    '.bash': 'bash',
    '.zsh': 'bash',
    '.fish': 'fish',
    # Query languages
    '.sql': 'sql',
    '.graphql': 'graphql',
    '.gql': 'graphql',
    # Other
    '.proto': 'proto',
    '.md': 'markdown',
    '.markdown': 'markdown',
    '.rst': 'rst',
    '.tex': 'latex',
    '.jl': 'julia',
    # Additional languages commonly supported by Tree-sitter but not yet mapped
    '.ps1': 'powershell',
    '.psm1': 'powershell',
    '.psd1': 'powershell',
    '.ini': 'ini',
    '.tf': 'hcl',
    '.mk': 'make',
    '.cmake': 'cmake',
    '.dockerfile': 'dockerfile',
}


# Per-language node-type tables for symbol search. Lookups fall back to a
# sensible default (function_definition/function_declaration, etc.) when the
# language is unknown.
FUNCTION_NODE_TYPES: dict[str, list[str]] = {
    'python': ['function_definition'],
    'javascript': ['function_declaration', 'function', 'method_definition'],
    'typescript': ['function_declaration', 'function', 'method_definition'],
    'go': ['function_declaration', 'method_declaration'],
    'rust': ['function_item'],
    'java': ['method_declaration', 'constructor_declaration'],
    'cpp': ['function_definition'],
    'c': ['function_definition'],
    'ruby': ['method', 'singleton_method'],
    'php': ['function_definition', 'method_declaration'],
}

CLASS_NODE_TYPES: dict[str, list[str]] = {
    'python': ['class_definition'],
    'javascript': ['class_declaration', 'class_definition'],
    'typescript': ['class_declaration', 'class_definition'],
    'go': ['type_declaration'],
    'rust': ['impl_item'],
    'java': ['class_declaration'],
    'cpp': ['class_specifier'],
    'c_sharp': ['class_declaration'],
    'ruby': ['class'],
    'php': ['class_declaration'],
}

METHOD_NODE_TYPES: dict[str, list[str]] = {
    'python': ['function_definition'],
    'javascript': ['method_definition'],
    'typescript': ['method_definition'],
    'java': ['method_declaration'],
    'cpp': ['function_definition'],
    'c_sharp': ['method_declaration'],
    'ruby': ['method'],
    'php': ['method_declaration'],
}


def get_function_node_types(language: str) -> list[str]:
    """Return the function/method node types for ``language`` (with default)."""
    return FUNCTION_NODE_TYPES.get(
        language, ['function_definition', 'function_declaration']
    )


def get_class_node_types(language: str) -> list[str]:
    """Return the class node types for ``language`` (with default)."""
    return CLASS_NODE_TYPES.get(language, ['class_declaration', 'class_definition'])


def get_method_node_types(language: str) -> list[str]:
    """Return the method node types for ``language`` (with default)."""
    return METHOD_NODE_TYPES.get(language, ['method_definition', 'method_declaration'])
