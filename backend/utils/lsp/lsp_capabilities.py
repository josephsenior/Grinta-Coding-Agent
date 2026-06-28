"""Shared LSP client capabilities and capability-gating tables.

Imported by both :mod:`lsp_session` (persistent-session path) and
:mod:`lsp_client` (one-shot fallback path) so the ``initialize`` payload
is identical regardless of which execution path runs.
"""

from __future__ import annotations

from typing import Any

# Sent as ``ClientCapabilities`` in the ``initialize`` request.
# Both the session-backed and one-shot paths must use this same dict so
# server behaviour does not depend on which execution path was taken.
CLIENT_CAPABILITIES: dict[str, Any] = {
    'textDocument': {
        'publishDiagnostics': {'relatedInformation': True},
        'documentSymbol': {'hierarchicalDocumentSymbolSupport': True},
        'hover': {'contentFormat': ['markdown', 'plaintext']},
        'definition': {'linkSupport': True},
        'references': {},
        'codeAction': {
            'codeActionLiteralSupport': {
                'codeActionKind': {
                    'valueSet': [
                        'quickfix',
                        'refactor',
                        'source',
                        'source.organizeImports',
                    ]
                }
            }
        },
    }
}

# Maps LSP method names to the server-capability key that gates them.
# When a server's ``initialize`` result does not advertise the key,
# :meth:`LspSession.supports` returns False and the query short-circuits.
METHOD_CAPABILITY_KEYS: dict[str, str] = {
    'textDocument/hover': 'hoverProvider',
    'textDocument/definition': 'definitionProvider',
    'textDocument/references': 'referencesProvider',
    'textDocument/documentSymbol': 'documentSymbolProvider',
    'textDocument/codeAction': 'codeActionProvider',
}
