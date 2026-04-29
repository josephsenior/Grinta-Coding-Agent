"""Thin synchronous wrapper around python-lsp-server (pylsp).

Starts pylsp as a subprocess communicating via JSON-RPC over stdin/stdout.
Gracefully degrades — all public methods return empty results when
``pylsp`` is not installed, so no hard runtime dependency is required.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.core.logger import app_logger as logger

# ── Soft pylsp detection — delegates to the unified runtime detector ──────
# ``_PYLSP_AVAILABLE`` is kept for backward-compatibility with tests that
# monkeypatch it directly. ``_detect_pylsp`` now consults the multi-language
# detector so other languages (gopls, typescript-language-server, …) are
# discovered through the same mechanism.
_PYLSP_AVAILABLE: bool | None = None  # None = not yet detected


# #region agent log
def _agent_debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    try:
        payload = {
            'sessionId': 'fee086',
            'runId': 'pre-fix',
            'hypothesisId': hypothesis_id,
            'location': location,
            'message': message,
            'data': data,
            'timestamp': int(time.time() * 1000),
        }
        log_path = Path(__file__).resolve().parents[2] / 'debug-fee086.log'
        with open(log_path, 'a', encoding='utf-8') as _f:
            _f.write(json.dumps(payload, ensure_ascii=True) + '\n')
    except Exception:
        pass


# #endregion


def _detect_pylsp() -> bool:
    """Return True when the Python language server is available locally."""
    global _PYLSP_AVAILABLE
    if _PYLSP_AVAILABLE is not None:
        return _PYLSP_AVAILABLE
    try:
        from backend.utils.runtime_detect import detect_lsp_servers

        servers = detect_lsp_servers()
        detected = servers.get('pylsp')
        _PYLSP_AVAILABLE = bool(detected and detected.available)
        if _PYLSP_AVAILABLE and detected is not None:
            # Validate the command actually runs; PATH/import probes can pass while
            # execution still fails in this process environment.
            try:
                probe_cmd = list(detected.resolved_command) + ['--version']
                subprocess.run(probe_cmd, capture_output=True, timeout=3)
            except Exception:
                _PYLSP_AVAILABLE = False
        # #region agent log
        _agent_debug_log(
            'H4_lsp_detection_path',
            'backend/utils/lsp_client.py:_detect_pylsp',
            'pylsp-detection-result',
            {'cached_value': _PYLSP_AVAILABLE, 'server_keys': sorted(servers.keys())[:4]},
        )
        # #endregion
    except Exception:
        _PYLSP_AVAILABLE = False
    return _PYLSP_AVAILABLE


def _detect_any_lsp_server() -> bool:
    """Return True when at least one supported LSP server is available."""
    try:
        from backend.utils.runtime_detect import has_any_lsp_server

        return has_any_lsp_server()
    except Exception:
        return False


# ── Data types ─────────────────────────────────────────────────────────────


@dataclass
class LspLocation:
    file: str
    line: int  # 1-based
    column: int  # 1-based

    def __str__(self) -> str:
        return f'{self.file}:{self.line}:{self.column}'


@dataclass
class LspSymbol:
    name: str
    kind: str
    line: int

    def __str__(self) -> str:
        return f'{self.kind} {self.name} (line {self.line})'


@dataclass
class LspResult:
    available: bool = True
    locations: list[LspLocation] = field(default_factory=list)
    symbols: list[LspSymbol] = field(default_factory=list)
    hover_text: str = ''
    error: str = ''

    def format_text(self, command: str) -> str:
        """Return a human-readable summary for the LLM."""
        if not self.available:
            return (
                'LSP is not available (pylsp not installed). '
                'Use search_code or explore_code instead.'
            )
        if self.error:
            return f'LSP error: {self.error}'
        if command in ('find_definition', 'find_references'):
            if not self.locations:
                return 'No results found.'
            lines = [f'Found {len(self.locations)} result(s):']
            for loc in self.locations[:20]:  # cap output
                lines.append(f'  - {loc}')
            return '\n'.join(lines)
        if command == 'hover':
            return self.hover_text or 'No hover information available.'
        if command == 'list_symbols':
            if not self.symbols:
                return 'No symbols found.'
            lines = [f'Symbols in file ({len(self.symbols)}):']
            for sym in self.symbols[:40]:
                lines.append(f'  - {sym}')
            return '\n'.join(lines)
        if command in ('diagnostics', 'get_diagnostics'):
            if not self.locations:
                return 'No diagnostics found. File looks clean.'
            lines = [f'Diagnostics ({len(self.locations)} issue(s)):']
            for loc in self.locations[:30]:
                lines.append(f'  - {loc}')
            return '\n'.join(lines)
        return str(self)


# ── Core client ────────────────────────────────────────────────────────────


class LspClient:
    """Single-use JSON-RPC client that spawns pylsp per-query.

    For simplicity we spawn a fresh process per call (no long-lived server
    state needed for navigation). This is fast enough for file-level queries.
    """

    _SYMBOL_KIND_MAP: dict[int, str] = {
        1: 'File',
        2: 'Module',
        3: 'Namespace',
        4: 'Package',
        5: 'Class',
        6: 'Method',
        7: 'Property',
        8: 'Field',
        9: 'Constructor',
        10: 'Enum',
        11: 'Interface',
        12: 'Function',
        13: 'Variable',
        14: 'Constant',
        15: 'String',
        16: 'Number',
        17: 'Boolean',
        18: 'Array',
        19: 'Object',
        20: 'Key',
        21: 'Null',
        22: 'EnumMember',
        23: 'Struct',
        24: 'Event',
        25: 'Operator',
        26: 'TypeParameter',
    }

    _SERVER_COMMANDS: dict[str, list[str]] = {
        '.py': ['python', '-m', 'pylsp'],
        '.ts': ['typescript-language-server', '--stdio'],
        '.js': ['typescript-language-server', '--stdio'],
        '.rs': ['rust-analyzer'],
        '.go': ['gopls'],
    }

    def _get_server_command(self, file_path: str) -> list[str] | None:
        """Get the LSP server command based on file extension.

        Prefers the unified runtime detector (which only returns commands
        for tools actually installed on the machine). Falls back to the
        legacy hard-coded mapping so existing test patches keep working.
        """
        ext = Path(file_path).suffix.lower()
        try:
            from backend.utils.runtime_detect import lsp_command_for_extension

            resolved = lsp_command_for_extension(ext)
            if resolved is not None:
                return list(resolved)
        except Exception:
            pass
        return self._SERVER_COMMANDS.get(ext)

    def query(
        self,
        command: str,
        file: str,
        line: int = 1,
        column: int = 1,
        symbol: str = '',
    ) -> LspResult:
        """Execute a single LSP query and return structured results."""
        # For non-python, we don't have AST fallbacks, so we check server availability
        cmd = self._get_server_command(file)
        if not cmd:
            return LspResult(
                available=False,
                error=f'No LSP server configured for {Path(file).suffix}',
            )

        # Special-case Python hover when pylsp is not available: degrade gracefully
        if command == 'hover' and Path(file).suffix.lower() == '.py':
            pylsp_available = _detect_pylsp()
            # #region agent log
            _agent_debug_log(
                'H5_hover_degrade_gate',
                'backend/utils/lsp_client.py:query',
                'hover-python-gate',
                {
                    'file': file,
                    'detected_pylsp': pylsp_available,
                    'cmd': cmd,
                },
            )
            # #endregion
            if not pylsp_available:
                return LspResult(available=False)

        try:
            return self._run_query(command, file, line, column, symbol)
        except Exception as exc:
            logger.warning('LspClient query failed: %s', exc)
            return LspResult(available=True, error=str(exc))

    def _run_query(
        self,
        command: str,
        file: str,
        line: int,
        column: int,
        symbol: str,
    ) -> LspResult:
        abs_path = str(Path(file).resolve())
        try:
            source = Path(abs_path).read_text(encoding='utf-8', errors='replace')
        except FileNotFoundError:
            return LspResult(available=True, error=f'File not found: {abs_path}')

        uri = Path(abs_path).as_uri()
        # LSP protocol uses 0-based lines and columns
        lsp_line = max(0, line - 1)
        lsp_col = max(0, column - 1)

        if command == 'list_symbols':
            return self._query_document_symbols(abs_path, uri, source, symbol)
        elif command == 'hover':
            return self._query_hover(abs_path, uri, source, lsp_line, lsp_col)
        elif command in ('diagnostics', 'get_diagnostics'):
            return self._query_diagnostics(abs_path, uri, source)
        elif command in ('find_definition', 'find_references'):
            return self._query_locations(
                command, abs_path, uri, source, lsp_line, lsp_col
            )
        else:
            return LspResult(available=True, error=f'Unknown command: {command}')

    def _rpc(self, messages: list[dict], server_cmd: list[str]) -> list[dict]:
        """Send LSP messages and collect responses using a subprocess."""
        payload = ''.join(
            f'Content-Length: {len(json.dumps(m))}\r\n\r\n{json.dumps(m)}'
            for m in messages
        )
        try:
            proc = subprocess.run(
                server_cmd,
                input=payload.encode(),
                capture_output=True,
                timeout=15,
            )
            return self._parse_lsp_responses(proc.stdout.decode(errors='replace'))
        except subprocess.TimeoutExpired:
            logger.warning('%s subprocess timed out', server_cmd[0])
            return []

    def _parse_lsp_responses(self, raw: str) -> list[dict]:
        """Parse LSP stream using Content-Length framing (LSP spec)."""
        responses: list[dict] = []
        buf = raw
        i = 0
        n = len(buf)
        while i < n:
            cl_pos = buf.find('Content-Length:', i)
            if cl_pos == -1:
                break
            line_end = buf.find('\r\n', cl_pos)
            if line_end == -1:
                break
            header_line = buf[cl_pos:line_end]
            lower = header_line.strip().lower()
            if not lower.startswith('content-length:'):
                i = cl_pos + 1
                continue
            try:
                length = int(header_line.split(':', 1)[1].strip())
            except ValueError:
                i = line_end + 2
                continue
            sep = buf.find('\r\n\r\n', line_end)
            if sep == -1:
                break
            body_start = sep + 4
            body_end = body_start + length
            if body_end > n:
                break
            chunk = buf[body_start:body_end]
            try:
                responses.append(json.loads(chunk))
            except Exception:
                pass
            i = body_end
        return responses

    def _build_init_msgs(self, uri: str, file_path: str) -> list[dict]:
        ext = Path(file_path).suffix.lower()
        lang_id = {
            '.py': 'python',
            '.ts': 'typescript',
            '.js': 'javascript',
            '.rs': 'rust',
            '.go': 'go',
        }.get(ext, 'plaintext')

        return [
            {
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'initialize',
                'params': {
                    'processId': None,
                    'rootUri': str(Path(file_path).parent.as_uri()),
                    'capabilities': {
                        'textDocument': {
                            'publishDiagnostics': {'relatedInformation': True}
                        }
                    },
                },
            },
            {'jsonrpc': '2.0', 'method': 'initialized', 'params': {}},
            {
                'jsonrpc': '2.0',
                'method': 'textDocument/didOpen',
                'params': {
                    'textDocument': {
                        'uri': uri,
                        'languageId': lang_id,
                        'version': 1,
                        'text': '',
                    }
                },
            },
        ]

    # ── Command implementations ─────────────────────────────────────────

    def _query_diagnostics(self, abs_path: str, uri: str, source: str) -> LspResult:
        """Query LSP for diagnostics (errors/warnings)."""
        server_cmd = self._get_server_command(abs_path)
        if not server_cmd:
            return LspResult(available=False)

        msgs = self._build_init_msgs(uri, abs_path)
        msgs[2]['params']['textDocument']['text'] = source

        # Some LSPs send diagnostics as notifications after didOpen
        # We also send a shutdown to ensure we get all responses
        msgs.append({'jsonrpc': '2.0', 'method': 'shutdown', 'id': 99, 'params': {}})

        responses = self._rpc(msgs, server_cmd)

        errors = []
        for resp in responses:
            if resp.get('method') == 'textDocument/publishDiagnostics':
                params = resp.get('params', {})
                if params.get('uri') == uri:
                    for diag in params.get('diagnostics', []):
                        start = diag.get('range', {}).get('start', {})
                        errors.append(
                            LspLocation(
                                file=abs_path,
                                line=start.get('line', 0) + 1,
                                column=start.get('character', 0) + 1,
                            )
                        )
                        # We hijack LspLocation for diagnostics temporarily
                        # In a real impl, we'd have a LspDiagnostic class

        return LspResult(available=True, locations=errors)

    def _query_document_symbols(
        self, abs_path: str, uri: str, source: str, symbol_filter: str
    ) -> LspResult:
        if abs_path.endswith('.py'):
            return _ast_list_symbols(abs_path, source, symbol_filter)

        # For other languages, could implement LSP documentSymbol query here
        return LspResult(
            available=True, error='list_symbols only supported for Python currently'
        )

    def _query_hover(
        self, abs_path: str, uri: str, source: str, lsp_line: int, lsp_col: int
    ) -> LspResult:
        if abs_path.endswith('.py'):
            return _ast_hover(abs_path, source, lsp_line + 1)

        server_cmd = self._get_server_command(abs_path)
        if not server_cmd:
            return LspResult(available=False)

        msgs = self._build_init_msgs(uri, abs_path)
        msgs[2]['params']['textDocument']['text'] = source
        msgs.append(
            {
                'jsonrpc': '2.0',
                'id': 10,
                'method': 'textDocument/hover',
                'params': {
                    'textDocument': {'uri': uri},
                    'position': {'line': lsp_line, 'character': lsp_col},
                },
            }
        )
        msgs.append({'jsonrpc': '2.0', 'method': 'shutdown', 'id': 11, 'params': {}})

        responses = self._rpc(msgs, server_cmd)
        for resp in responses:
            if resp.get('id') == 10 and 'result' in resp:
                result = resp['result']
                if result and 'contents' in result:
                    contents = result['contents']
                    if isinstance(contents, dict):
                        return LspResult(
                            available=True, hover_text=contents.get('value', '')
                        )
                    elif isinstance(contents, list):
                        return LspResult(
                            available=True,
                            hover_text='\n'.join([str(c) for c in contents]),
                        )
                    return LspResult(available=True, hover_text=str(contents))

        return LspResult(available=True, hover_text='No hover info')

    def _query_locations(
        self,
        command: str,
        abs_path: str,
        uri: str,
        source: str,
        lsp_line: int,
        lsp_col: int,
    ) -> LspResult:
        server_cmd = self._get_server_command(abs_path)
        if not server_cmd:
            return LspResult(available=False)

        # Attempt real LSP; fall back to AST grep on failure (for Python)
        try:
            msg_id = 10
            msgs = self._build_init_msgs(uri, abs_path)
            # Override textDocument text
            msgs[2]['params']['textDocument']['text'] = source
            lsp_method = (
                'textDocument/definition'
                if command == 'find_definition'
                else 'textDocument/references'
            )
            msg: dict[str, Any] = {
                'jsonrpc': '2.0',
                'id': msg_id,
                'method': lsp_method,
                'params': {
                    'textDocument': {'uri': uri},
                    'position': {'line': lsp_line, 'character': lsp_col},
                },
            }
            if command == 'find_references':
                msg['params']['context'] = {'includeDeclaration': True}
            msgs.append(msg)
            msgs.append(
                {'jsonrpc': '2.0', 'method': 'shutdown', 'id': msg_id + 1, 'params': {}}
            )

            responses = self._rpc(msgs, server_cmd)
            for resp in responses:
                if resp.get('id') == msg_id and 'result' in resp:
                    result = resp['result']
                    if not result:
                        return LspResult(available=True)
                    if isinstance(result, dict):
                        result = [result]
                    locations = []
                    for loc in result:
                        start = loc.get('range', {}).get('start', {})
                        path = loc.get('uri', '').replace('file://', '')
                        locations.append(
                            LspLocation(
                                file=path,
                                line=start.get('line', 0) + 1,
                                column=start.get('character', 0) + 1,
                            )
                        )
                    return LspResult(available=True, locations=locations)
        except Exception as e:
            logger.debug('LSP RPC failed: %s', e)

        if abs_path.endswith('.py'):
            return _ast_grep_symbol(abs_path, source, lsp_line + 1)

        return LspResult(
            available=True, error='LSP query failed and no fallback available'
        )


# ── AST-based fallbacks (no pylsp needed) ─────────────────────────────────


def _ast_list_symbols(abs_path: str, source: str, symbol_filter: str) -> LspResult:
    """Parse source with TreeSitter and return top-level definitions."""
    from backend.utils.treesitter_editor import TreeSitterEditor

    editor = TreeSitterEditor()
    lang = editor.detect_language(abs_path)
    if not lang:
        return LspResult(available=False, error='Unsupported language for fallback')

    parser = editor.get_parser(lang)
    if not parser:
        return LspResult(available=False, error='No parser for language')

    tree = parser.parse(source.encode('utf-8'))

    symbols: list[LspSymbol] = []

    def traverse(node):
        if any(
            k in node.type
            for k in ['function', 'class', 'method', 'declaration', 'declarator']
        ):
            name_node = editor.get_name_node(node)
            if name_node:
                name = (
                    (name_node.text.decode('utf-8') if name_node.text else '')
                    if name_node.text
                    else ''
                )
                kind = (
                    'Class'
                    if any(k in node.type for k in ['class', 'interface'])
                    else 'Function'
                )
                if not symbol_filter or symbol_filter.lower() in name.lower():
                    symbols.append(
                        LspSymbol(
                            name=name, kind=kind, line=name_node.start_point[0] + 1
                        )
                    )
        for child in node.children:
            traverse(child)

    traverse(tree.root_node)

    # Filter duplicates (e.g. from nested name nodes)
    unique_symbols = []
    seen = set()
    for s in symbols:
        if s.name not in seen:
            seen.add(s.name)
            unique_symbols.append(s)

    unique_symbols.sort(key=lambda s: s.line)
    return LspResult(available=True, symbols=unique_symbols)


def _ast_hover(abs_path: str, source: str, line: int) -> LspResult:
    """Extract symbol name at the given 1-based line using TreeSitter."""
    from backend.utils.treesitter_editor import TreeSitterEditor

    editor = TreeSitterEditor()
    lang = editor.detect_language(abs_path)
    if not lang:
        return LspResult(available=True, hover_text='(unsupported language)')

    parser = editor.get_parser(lang)
    if not parser:
        return LspResult(available=True, hover_text='(no parser)')

    tree = parser.parse(source.encode('utf-8'))
    best = ''

    def traverse(node):
        nonlocal best
        # node.start_point is 0-indexed
        if node.start_point[0] + 1 <= line <= node.end_point[0] + 1:
            if any(k in node.type for k in ['function', 'class', 'method']):
                name_node = editor.get_name_node(node)
                if name_node:
                    kind = (
                        'Class'
                        if 'class' in node.type
                        else ('Method' if 'method' in node.type else 'Function')
                    )
                    best = f'{kind} `{((name_node.text.decode("utf-8") if name_node.text else "") if name_node.text else "")}`'
            for child in node.children:
                traverse(child)

    traverse(tree.root_node)
    return LspResult(available=True, hover_text=best or 'No documentation found.')


def _ast_grep_symbol(abs_path: str, source: str, line: int) -> LspResult:
    """Find definition of whatever name appears at the given line (TreeSitter definition grep)."""
    lines = source.splitlines()
    if not lines or line < 1 or line > len(lines):
        return LspResult(available=True)

    target_line = lines[line - 1]
    import re

    tokens = set(re.findall(r'[A-Za-z_]\w*', target_line))
    if not tokens:
        return LspResult(available=True)

    from backend.utils.treesitter_editor import TreeSitterEditor

    editor = TreeSitterEditor()
    lang = editor.detect_language(abs_path)
    if not lang:
        return LspResult(available=True)

    parser = editor.get_parser(lang)
    if not parser:
        return LspResult(available=True)

    tree = parser.parse(source.encode('utf-8'))
    locations: list[LspLocation] = []

    def traverse(node):
        if any(
            k in node.type
            for k in ['function', 'class', 'method', 'declaration', 'declarator']
        ):
            name_node = editor.get_name_node(node)
            if name_node:
                name = (
                    (name_node.text.decode('utf-8') if name_node.text else '')
                    if name_node.text
                    else ''
                )
                if name in tokens:
                    locations.append(
                        LspLocation(
                            file=abs_path,
                            line=name_node.start_point[0] + 1,
                            column=name_node.start_point[1] + 1,
                        )
                    )
        for child in node.children:
            traverse(child)

    traverse(tree.root_node)
    return LspResult(available=True, locations=locations)


# Singleton instance
_LSP_CLIENT = LspClient()


def get_lsp_client() -> LspClient:
    return _LSP_CLIENT
