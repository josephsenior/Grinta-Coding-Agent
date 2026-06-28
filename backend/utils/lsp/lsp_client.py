"""Language-server client — persistent sessions with one-shot fallback.

Uses an ``LspSession`` pool keyed by workspace + server so slow JVM servers
(jdtls, metals, …) amortize cold start. Set ``GRINTA_DISABLE_LSP_SESSION=1`` to
force the legacy spawn-per-query path. No tree-sitter or AST fallbacks.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from backend.core.logging.logger import app_logger as logger
from backend.execution.utils.files.bounded_io import (
    BoundedResult,
    async_bounded_subprocess_exec,
)
from backend.utils.async_helpers.async_utils import call_async_from_sync
from backend.utils.http.stdio_json_rpc import parse_content_length_json_messages
from backend.utils.lsp.lsp_project_routing import LspFileContext, lsp_context_for_file
from backend.utils.lsp.lsp_session import LspSession, get_lsp_session_pool
from backend.utils.lsp.lsp_timeouts import (
    effective_query_timeout,
    init_timeout_for_server,
)

_UNAVAILABLE_HINT = (
    'No language server is installed for this file type. '
    'Use find_symbols or grep for structure search.'
)


def _snippet_from_stderr(stderr: str) -> str:
    """Extract a short, non-empty tail from *stderr* for error surfacing."""
    if not stderr:
        return ''
    text = stderr.strip()
    if not text:
        return ''
    return text[-500:]


def _run_lsp_subprocess(
    args: list[str],
    *,
    process_timeout: float,
    stdin_data: bytes | str | None = None,
) -> BoundedResult:
    return call_async_from_sync(
        async_bounded_subprocess_exec,
        process_timeout + 5.0,
        args,
        process_timeout=process_timeout,
        max_bytes_per_stream=4 * 1024 * 1024,
        stdin_data=stdin_data,
    )


# ── One-shot JSON-RPC request ids ──────────────────────────────────────────
# Each one-shot query batch sends initialize (id=1) + didOpen + query +
# shutdown in a single stdin payload to a short-lived subprocess.  Ids must
# be unique within each batch and must not collide with the initialize id.
_ONESHOT_ID_INIT = 1
_ONESHOT_ID_HOVER = 10
_ONESHOT_ID_HOVER_SHUTDOWN = 11
_ONESHOT_ID_DOCUMENT_SYMBOL = 20
_ONESHOT_ID_DOCUMENT_SYMBOL_SHUTDOWN = 21
_ONESHOT_ID_CODE_ACTION = 30
_ONESHOT_ID_CODE_ACTION_SHUTDOWN = 31
_ONESHOT_ID_DIAGNOSTICS_SHUTDOWN = 99


@dataclass
class LspLocation:
    file: str
    line: int  # 1-based
    column: int  # 1-based
    message: str = ''
    severity: int | None = None

    def __str__(self) -> str:
        base = f'{self.file}:{self.line}:{self.column}'
        return f'{base} - {self.message}' if self.message else base


@dataclass
class LspSymbol:
    name: str
    kind: str
    line: int

    def __str__(self) -> str:
        return f'{self.kind} {self.name} (line {self.line})'


@dataclass
class LspCodeAction:
    """A single quick-fix / refactor suggested by the language server."""

    title: str
    kind: str = ''
    is_preferred: bool = False
    diagnostic_message: str = ''

    def __str__(self) -> str:
        prefix = '★ ' if self.is_preferred else '  '
        kind_tag = f' [{self.kind}]' if self.kind else ''
        suffix = (
            f' — fixes: {self.diagnostic_message}' if self.diagnostic_message else ''
        )
        return f'{prefix}{self.title}{kind_tag}{suffix}'


@dataclass
class LspResult:
    available: bool = True
    locations: list[LspLocation] = field(default_factory=list)
    symbols: list[LspSymbol] = field(default_factory=list)
    code_actions: list[LspCodeAction] = field(default_factory=list)
    hover_text: str = ''
    error: str = ''

    def format_text(self, command: str) -> str:
        """Return a human-readable summary for the LLM."""
        if not self.available:
            return f'LSP is not available. {_UNAVAILABLE_HINT}'
        if self.error:
            return f'LSP error: {self.error}'

        handlers = {
            'find_definition': self._format_locations,
            'find_references': self._format_locations,
            'hover': self._format_hover,
            'list_symbols': self._format_symbols,
            'diagnostics': self._format_diagnostics,
            'get_diagnostics': self._format_diagnostics,
            'code_action': self._format_code_actions,
        }

        handler = handlers.get(command)
        if handler:
            return handler()
        return str(self)

    def _format_locations(self) -> str:
        if not self.locations:
            return 'No results found.'
        lines = [f'Found {len(self.locations)} result(s):']
        for loc in self.locations[:20]:
            lines.append(f'  - {loc}')
        return '\n'.join(lines)

    def _format_hover(self) -> str:
        return self.hover_text or 'No hover information available.'

    def _format_symbols(self) -> str:
        if not self.symbols:
            return 'No symbols found.'
        lines = [f'Symbols in file ({len(self.symbols)}):']
        for sym in self.symbols[:40]:
            lines.append(f'  - {sym}')
        return '\n'.join(lines)

    def _format_diagnostics(self) -> str:
        if not self.locations:
            return 'No diagnostics found. File looks clean.'
        lines = [f'Diagnostics ({len(self.locations)} issue(s)):']
        for loc in self.locations[:30]:
            lines.append(f'  - {loc}')
        return '\n'.join(lines)

    def _format_code_actions(self) -> str:
        if not self.code_actions:
            return (
                'No code actions / quick-fixes available at this location. '
                'Either the file is clean or the language server has no '
                'suggestions for this range. Apply edits manually via '
                'the file editing tools.'
            )
        lines = [
            f'Available code actions ({len(self.code_actions)}; ★ = preferred):',
            '(Discovery-only — no auto-apply yet. Implement the chosen fix '
            'and re-run `get_diagnostics` to verify.)',
        ]
        for act in self.code_actions[:25]:
            lines.append(f'  {act}')
        return '\n'.join(lines)


class LspClient:
    """JSON-RPC client backed by persistent language-server sessions."""

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

    def _get_context(self, file_path: str) -> LspFileContext | None:
        try:
            ctx = lsp_context_for_file(file_path)
        except Exception:
            return None
        if ctx is not None:
            return ctx
        return self._try_auto_install(file_path)

    def _try_auto_install(self, file_path: str) -> LspFileContext | None:
        """Install the canonical server for *file_path*, then re-resolve."""
        from backend.utils.lsp.lsp_installer import (
            install_server,
            is_auto_install_enabled,
        )
        from backend.utils.lsp.lsp_project_routing import (
            find_project_root,
            resolve_language_key,
        )
        from backend.utils.runtime_detect import (
            CANONICAL_LSP_SERVERS,
            reset_detection_cache,
        )

        if not is_auto_install_enabled():
            return None
        path = Path(file_path)
        ext = path.suffix.lower()
        if not ext:
            return None
        try:
            root = find_project_root(path)
            language_key = resolve_language_key(ext, root)
            if language_key is None:
                return None
            spec = CANONICAL_LSP_SERVERS.get(language_key)
            if spec is None:
                return None
            if not install_server(
                spec.name,
                spec.install,
                spec.install_method,
            ):
                return None
            reset_detection_cache()
            return lsp_context_for_file(file_path)
        except Exception:
            return None

    def _get_server_command(self, file_path: str) -> list[str] | None:
        ctx = self._get_context(file_path)
        return list(ctx.command) if ctx is not None else None

    def _unavailable(self, file_path: str) -> LspResult:
        suffix = Path(file_path).suffix or 'this file type'
        return LspResult(
            available=False,
            error=f'No LSP server configured for {suffix}. {_UNAVAILABLE_HINT}',
        )

    def query(
        self,
        command: str,
        file: str,
        line: int = 1,
        column: int = 1,
        symbol: str = '',
        *,
        process_timeout: float | None = None,
        post_edit: bool = False,
    ) -> LspResult:
        """Execute a single LSP query and return structured results."""
        if self._get_server_command(file) is None:
            return self._unavailable(file)

        try:
            return self._run_query(
                command,
                file,
                line,
                column,
                symbol,
                process_timeout=process_timeout,
                post_edit=post_edit,
            )
        except Exception as exc:
            logger.warning('LspClient query failed: %s', exc)
            return LspResult(available=False, error=str(exc))

    def _resolve_timeout(
        self,
        ctx: LspFileContext,
        process_timeout: float | None,
        *,
        post_edit: bool = False,
    ) -> float:
        return effective_query_timeout(
            ctx.server_name, process_timeout, post_edit=post_edit
        )

    def _use_session(
        self,
        ctx: LspFileContext,
        uri: str,
        language_id: str,
        source: str,
    ) -> tuple[LspSession | None, bool]:
        """Return ``(session, allow_one_shot_fallback)``."""
        session = get_lsp_session_pool().get(ctx)
        if session is None:
            return None, True
        if not session.prepare_document(uri, language_id, source):
            return None, False
        return session, False

    def _diagnostics_from_payload(
        self, abs_path: str, uri: str, payload: list[dict[str, Any]]
    ) -> list[LspLocation]:
        errors: list[LspLocation] = []
        for diag in payload:
            start = diag.get('range', {}).get('start', {})
            errors.append(
                LspLocation(
                    file=abs_path,
                    line=start.get('line', 0) + 1,
                    column=start.get('character', 0) + 1,
                    message=str(diag.get('message') or ''),
                    severity=diag.get('severity'),
                )
            )
        return errors

    def _diagnostics_from_responses(
        self, abs_path: str, uri: str, responses: list[dict[str, Any]]
    ) -> list[LspLocation]:
        errors: list[LspLocation] = []
        for resp in responses:
            if resp.get('method') == 'textDocument/publishDiagnostics':
                params = resp.get('params', {})
                if params.get('uri') == uri:
                    errors.extend(
                        self._diagnostics_from_payload(
                            abs_path, uri, params.get('diagnostics', [])
                        )
                    )
        return errors

    def _run_query(
        self,
        command: str,
        file: str,
        line: int,
        column: int,
        symbol: str,
        *,
        process_timeout: float | None = None,
        post_edit: bool = False,
    ) -> LspResult:
        abs_path = str(Path(file).resolve())
        try:
            source = Path(abs_path).read_text(encoding='utf-8', errors='replace')
        except FileNotFoundError:
            return LspResult(available=False, error=f'File not found: {abs_path}')

        uri = Path(abs_path).as_uri()
        lsp_line = max(0, line - 1)
        lsp_col = max(0, column - 1)

        if command == 'list_symbols':
            return self._query_document_symbols(
                abs_path,
                uri,
                source,
                symbol,
                process_timeout=process_timeout,
                post_edit=post_edit,
            )
        if command == 'hover':
            return self._query_hover(
                abs_path,
                uri,
                source,
                lsp_line,
                lsp_col,
                process_timeout=process_timeout,
                post_edit=post_edit,
            )
        if command in ('diagnostics', 'get_diagnostics'):
            return self._query_diagnostics(
                abs_path,
                uri,
                source,
                process_timeout=process_timeout,
                post_edit=post_edit,
            )
        if command == 'code_action':
            return self._query_code_actions(
                abs_path,
                uri,
                source,
                lsp_line,
                lsp_col,
                process_timeout=process_timeout,
                post_edit=post_edit,
            )
        if command in ('find_definition', 'find_references'):
            return self._query_locations(
                command,
                abs_path,
                uri,
                source,
                lsp_line,
                lsp_col,
                process_timeout=process_timeout,
                post_edit=post_edit,
            )
        return LspResult(available=False, error=f'Unknown command: {command}')

    def _rpc(
        self,
        messages: list[dict],
        server_cmd: list[str],
        *,
        process_timeout: float = 15.0,
    ) -> tuple[list[dict], bool, str]:
        """Run a one-shot LSP batch. Returns ``(responses, started, stderr_snippet)``.

        ``stderr_snippet`` carries the tail of server stderr (up to ~500 chars) so
        callers can surface it via :meth:`_server_failed` instead of the generic
        "failed to start" message — aids debugging startup/crash failures that
        were previously swallowed by ``stderr=DEVNULL``.
        """
        frames: list[bytes] = []
        for message in messages:
            body = json.dumps(message, ensure_ascii=False).encode('utf-8')
            header = f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii')
            frames.append(header + body)
        payload = b''.join(frames)
        try:
            result = _run_lsp_subprocess(
                server_cmd,
                stdin_data=payload,
                process_timeout=process_timeout,
            )
            if result.timed_out:
                logger.warning('%s subprocess timed out', server_cmd[0])
                return [], False, _snippet_from_stderr(result.stderr)
            responses = parse_content_length_json_messages(result.stdout)
            if responses:
                return responses, True, ''
            if result.returncode != 0:
                snippet = _snippet_from_stderr(result.stderr)
                if snippet:
                    logger.warning(
                        '%s subprocess exited %s. stderr:\n%s',
                        server_cmd[0],
                        result.returncode,
                        snippet,
                    )
                return [], False, snippet
            return [], bool(result.stdout.strip()), ''
        except TimeoutError:
            logger.warning('%s subprocess timed out', server_cmd[0])
            return [], False, ''
        except Exception as exc:
            logger.warning('%s subprocess failed: %s', server_cmd[0], exc)
            return [], False, ''

    def _parse_lsp_responses(self, raw: str) -> list[dict[str, Any]]:
        return parse_content_length_json_messages(raw)

    def _build_init_msgs(self, uri: str, file_path: str, source: str) -> list[dict]:
        from backend.utils.lsp.lsp_capabilities import CLIENT_CAPABILITIES

        ctx = self._get_context(file_path)
        if ctx is None:
            raise RuntimeError(f'no LSP context for {file_path}')

        root_uri = ctx.workspace_root.as_uri()
        return [
            {
                'jsonrpc': '2.0',
                'id': _ONESHOT_ID_INIT,
                'method': 'initialize',
                'params': {
                    'processId': os.getpid(),
                    'rootUri': root_uri,
                    'workspaceFolders': [
                        {
                            'uri': root_uri,
                            'name': ctx.workspace_root.name or 'workspace',
                        }
                    ],
                    'capabilities': CLIENT_CAPABILITIES,
                },
            },
            {'jsonrpc': '2.0', 'method': 'initialized', 'params': {}},
            {
                'jsonrpc': '2.0',
                'method': 'textDocument/didOpen',
                'params': {
                    'textDocument': {
                        'uri': uri,
                        'languageId': ctx.language_id,
                        'version': 1,
                        'text': source,
                    }
                },
            },
        ]

    def _server_failed(self, stderr: str = '') -> LspResult:
        message = 'Language server failed to start or did not respond'
        if stderr:
            message = f'{message}. Server stderr:\n{stderr[:500]}'
        return LspResult(
            available=False,
            error=message,
        )

    @staticmethod
    def _error_from_response(response: dict[str, Any]) -> str | None:
        """Return a human-readable message if *response* carries a JSON-RPC error.

        LSP servers reply to unsupported/failed requests with
        ``{"error": {"code": ..., "message": ...}}`` instead of a ``result``
        member. Previously such responses were silently swallowed (no ``result``
        → callers returned an empty success). This extracts the server's error
        message so callers can surface it as an explicit ``LspResult`` error.
        """
        err = response.get('error')
        if not isinstance(err, dict):
            return None
        message = str(err.get('message') or '').strip()
        code = err.get('code')
        if message and code is not None:
            return f'{message} (code {code})'
        if message:
            return message
        if code is not None:
            return f'LSP error code {code}'
        return 'LSP error (no message)'

    def _error_result(self, response: dict[str, Any], *, hint: str = '') -> LspResult:
        err = self._error_from_response(response)
        if err is None:
            return LspResult(
                available=False,
                error=f'LSP response had no result{f" [{hint}]" if hint else ""}',
            )
        return LspResult(
            available=False,
            error=f'LSP error{f" [{hint}]" if hint else ""}: {err}',
        )

    @staticmethod
    def _unsupported_result(ctx: LspFileContext, method: str) -> LspResult:
        return LspResult(
            available=False,
            error=f'{ctx.server_name} does not advertise support for {method}',
        )

    def _query_diagnostics(
        self,
        abs_path: str,
        uri: str,
        source: str,
        *,
        process_timeout: float | None = None,
        post_edit: bool = False,
    ) -> LspResult:
        ctx = self._get_context(abs_path)
        if ctx is None:
            return self._unavailable(abs_path)

        timeout = self._resolve_timeout(ctx, process_timeout, post_edit=post_edit)
        session, use_fallback = self._use_session(ctx, uri, ctx.language_id, source)
        if session is not None:
            diagnostics = session.wait_publish_diagnostics(uri, timeout=timeout)
            return LspResult(
                available=True,
                locations=self._diagnostics_from_payload(abs_path, uri, diagnostics),
            )
        if not use_fallback:
            return self._server_failed()

        server_cmd = list(ctx.command)
        msgs = self._build_init_msgs(uri, abs_path, source)
        msgs.append(
            {
                'jsonrpc': '2.0',
                'method': 'shutdown',
                'id': _ONESHOT_ID_DIAGNOSTICS_SHUTDOWN,
                'params': {},
            }
        )

        # One-shot path must initialize + didOpen + receive diagnostics + shutdown
        # in a single subprocess run. Floor the budget at the server's init
        # timeout so a cold one-shot (no warm session) isn't starved by a small
        # post-edit caller budget (e.g. 3-5s) that would skip diagnostics on
        # every first edit.
        oneshot_timeout = max(timeout, init_timeout_for_server(ctx.server_name))
        responses, server_started, stderr_snippet = self._rpc(
            msgs, server_cmd, process_timeout=oneshot_timeout
        )
        if not server_started:
            return self._server_failed(stderr=stderr_snippet)

        return LspResult(
            available=True,
            locations=self._diagnostics_from_responses(abs_path, uri, responses),
        )

    def _query_code_actions(
        self,
        abs_path: str,
        uri: str,
        source: str,
        lsp_line: int,
        lsp_col: int,
        *,
        process_timeout: float | None = None,
        post_edit: bool = False,
    ) -> LspResult:
        ctx = self._get_context(abs_path)
        if ctx is None:
            return self._unavailable(abs_path)

        timeout = self._resolve_timeout(ctx, process_timeout, post_edit=post_edit)
        session, use_fallback = self._use_session(ctx, uri, ctx.language_id, source)
        if session is not None:
            if not session.supports('textDocument/codeAction'):
                return self._unsupported_result(ctx, 'textDocument/codeAction')
            diagnostics_payload = session.wait_publish_diagnostics(uri, timeout=timeout)
            req_range, relevant_diags = self._build_code_action_range_and_diags(
                source, diagnostics_payload, lsp_line, lsp_col
            )
            response = session.request(
                'textDocument/codeAction',
                {
                    'textDocument': {'uri': uri},
                    'range': req_range,
                    'context': {'diagnostics': relevant_diags},
                },
                timeout=timeout,
            )
            if response is None:
                return self._server_failed()
            if 'result' not in response:
                return self._error_result(response, hint='code_action')
            actions = self._parse_code_action_items(response.get('result') or [])
            return LspResult(available=True, code_actions=actions)

        if not use_fallback:
            return self._server_failed()

        server_cmd = list(ctx.command)
        diagnostics_payload = self._collect_diagnostics_for_code_action(
            server_cmd, uri, abs_path, source, process_timeout=timeout
        )
        req_range, relevant_diags = self._build_code_action_range_and_diags(
            source, diagnostics_payload, lsp_line, lsp_col
        )
        return self._execute_code_action_request(
            server_cmd,
            uri,
            abs_path,
            source,
            req_range,
            relevant_diags,
            process_timeout=timeout,
        )

    def _collect_diagnostics_for_code_action(
        self,
        server_cmd: list[str],
        uri: str,
        abs_path: str,
        source: str,
        *,
        process_timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        diag_msgs = self._build_init_msgs(uri, abs_path, source)
        diag_msgs.append(
            {
                'jsonrpc': '2.0',
                'method': 'shutdown',
                'id': _ONESHOT_ID_DIAGNOSTICS_SHUTDOWN,
                'params': {},
            }
        )
        diag_responses, _server_started, _stderr_snippet = self._rpc(
            diag_msgs, server_cmd, process_timeout=process_timeout or 15.0
        )
        for resp in diag_responses:
            if resp.get('method') == 'textDocument/publishDiagnostics':
                params = resp.get('params', {})
                if params.get('uri') == uri:
                    return list(params.get('diagnostics', []))
        return []

    def _build_code_action_range_and_diags(
        self,
        source: str,
        diagnostics_payload: list[dict[str, Any]],
        lsp_line: int,
        lsp_col: int,
    ) -> tuple[dict, list[dict[str, Any]]]:
        if lsp_line == 0 and lsp_col == 0:
            line_count = source.count('\n') + 1
            req_range = {
                'start': {'line': 0, 'character': 0},
                'end': {'line': max(0, line_count - 1), 'character': 0},
            }
            return req_range, diagnostics_payload

        req_range = {
            'start': {'line': lsp_line, 'character': lsp_col},
            'end': {'line': lsp_line, 'character': lsp_col},
        }
        relevant_diags = [
            d
            for d in diagnostics_payload
            if self._diag_contains_point(d, lsp_line, lsp_col)
        ]
        if not relevant_diags:
            relevant_diags = diagnostics_payload
        return req_range, relevant_diags

    def _execute_code_action_request(
        self,
        server_cmd: list[str],
        uri: str,
        abs_path: str,
        source: str,
        req_range: dict,
        relevant_diags: list[dict[str, Any]],
        *,
        process_timeout: float | None = None,
    ) -> LspResult:
        msgs = self._build_init_msgs(uri, abs_path, source)
        msgs.append(
            {
                'jsonrpc': '2.0',
                'id': _ONESHOT_ID_CODE_ACTION,
                'method': 'textDocument/codeAction',
                'params': {
                    'textDocument': {'uri': uri},
                    'range': req_range,
                    'context': {'diagnostics': relevant_diags},
                },
            }
        )
        msgs.append(
            {
                'jsonrpc': '2.0',
                'method': 'shutdown',
                'id': _ONESHOT_ID_CODE_ACTION_SHUTDOWN,
                'params': {},
            }
        )

        responses, server_started, stderr_snippet = self._rpc(
            msgs, server_cmd, process_timeout=process_timeout or 15.0
        )
        if not server_started:
            return self._server_failed(stderr=stderr_snippet)
        for resp in responses:
            if resp.get('id') == _ONESHOT_ID_CODE_ACTION:
                if 'result' not in resp:
                    return self._error_result(resp, hint='code_action')
                result = resp.get('result') or []
                actions = self._parse_code_action_items(result)
                return LspResult(available=True, code_actions=actions)

        return LspResult(available=True, code_actions=[])

    def _parse_code_action_items(self, result: list) -> list[LspCodeAction]:
        actions: list[LspCodeAction] = []
        seen_titles: set[str] = set()
        for item in result:
            if not isinstance(item, dict):
                continue
            title = str(item.get('title', '')).strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            diag_msg = ''
            diags = item.get('diagnostics') or []
            if diags and isinstance(diags[0], dict):
                diag_msg = str(diags[0].get('message', '')).strip()
            actions.append(
                LspCodeAction(
                    title=title,
                    kind=str(item.get('kind', '')),
                    is_preferred=bool(item.get('isPreferred', False)),
                    diagnostic_message=diag_msg,
                )
            )
        actions.sort(key=lambda a: (not a.is_preferred, a.title.lower()))
        return actions

    @staticmethod
    def _diag_contains_point(diag: dict, lsp_line: int, lsp_col: int) -> bool:
        rng = diag.get('range') or {}
        start = rng.get('start') or {}
        end = rng.get('end') or {}
        s_line = int(start.get('line', 0))
        s_col = int(start.get('character', 0))
        e_line = int(end.get('line', 0))
        e_col = int(end.get('character', 0))
        if lsp_line < s_line or lsp_line > e_line:
            return False
        if lsp_line == s_line and lsp_col < s_col:
            return False
        if lsp_line == e_line and lsp_col > e_col:
            return False
        return True

    def _query_document_symbols(
        self,
        abs_path: str,
        uri: str,
        source: str,
        symbol_filter: str,
        *,
        process_timeout: float | None = None,
        post_edit: bool = False,
    ) -> LspResult:
        ctx = self._get_context(abs_path)
        if ctx is None:
            return self._unavailable(abs_path)

        timeout = self._resolve_timeout(ctx, process_timeout, post_edit=post_edit)
        session, use_fallback = self._use_session(ctx, uri, ctx.language_id, source)
        if session is not None:
            if not session.supports('textDocument/documentSymbol'):
                return self._unsupported_result(ctx, 'textDocument/documentSymbol')
            response = session.request(
                'textDocument/documentSymbol',
                {'textDocument': {'uri': uri}},
                timeout=timeout,
            )
            if response is None:
                return self._server_failed()
            if 'result' not in response:
                return self._error_result(response, hint='documentSymbol')
            symbols = self._parse_document_symbols(
                response.get('result'), symbol_filter
            )
            return LspResult(available=True, symbols=symbols)

        if not use_fallback:
            return self._server_failed()

        server_cmd = list(ctx.command)
        msgs = self._build_init_msgs(uri, abs_path, source)
        msgs.append(
            {
                'jsonrpc': '2.0',
                'id': _ONESHOT_ID_DOCUMENT_SYMBOL,
                'method': 'textDocument/documentSymbol',
                'params': {'textDocument': {'uri': uri}},
            }
        )
        msgs.append(
            {
                'jsonrpc': '2.0',
                'method': 'shutdown',
                'id': _ONESHOT_ID_DOCUMENT_SYMBOL_SHUTDOWN,
                'params': {},
            }
        )

        responses, server_started, stderr_snippet = self._rpc(
            msgs, server_cmd, process_timeout=timeout
        )
        if not server_started:
            return self._server_failed(stderr=stderr_snippet)
        for resp in responses:
            if resp.get('id') == _ONESHOT_ID_DOCUMENT_SYMBOL:
                if 'result' not in resp:
                    return self._error_result(resp, hint='documentSymbol')
                symbols = self._parse_document_symbols(
                    resp.get('result'), symbol_filter
                )
                return LspResult(available=True, symbols=symbols)

        return LspResult(available=True, symbols=[])

    def _parse_document_symbols(
        self, result: Any, symbol_filter: str
    ) -> list[LspSymbol]:
        symbols: list[LspSymbol] = []

        def walk(items: Any) -> None:
            if not isinstance(items, list):
                return
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = str(item.get('name', '')).strip()
                kind = self._SYMBOL_KIND_MAP.get(int(item.get('kind', 0)), 'Symbol')
                line = 1
                if 'location' in item:
                    start = item.get('location', {}).get('range', {}).get('start', {})
                    line = int(start.get('line', 0)) + 1
                elif 'range' in item:
                    start = item.get('range', {}).get('start', {})
                    line = int(start.get('line', 0)) + 1
                if name and (
                    not symbol_filter or symbol_filter.lower() in name.lower()
                ):
                    symbols.append(LspSymbol(name=name, kind=kind, line=line))
                walk(item.get('children'))

        walk(result)
        symbols.sort(key=lambda s: (s.line, s.name))
        return symbols

    def _query_hover(
        self,
        abs_path: str,
        uri: str,
        source: str,
        lsp_line: int,
        lsp_col: int,
        *,
        process_timeout: float | None = None,
        post_edit: bool = False,
    ) -> LspResult:
        ctx = self._get_context(abs_path)
        if ctx is None:
            return self._unavailable(abs_path)

        timeout = self._resolve_timeout(ctx, process_timeout, post_edit=post_edit)
        session, use_fallback = self._use_session(ctx, uri, ctx.language_id, source)
        if session is not None:
            if not session.supports('textDocument/hover'):
                return self._unsupported_result(ctx, 'textDocument/hover')
            response = session.request(
                'textDocument/hover',
                {
                    'textDocument': {'uri': uri},
                    'position': {'line': lsp_line, 'character': lsp_col},
                },
                timeout=timeout,
            )
            if response is None:
                return self._server_failed()
            if 'result' not in response:
                return self._error_result(response, hint='hover')
            return self._parse_hover_response(response['result'])

        if not use_fallback:
            return self._server_failed()

        server_cmd = list(ctx.command)
        msgs = self._build_init_msgs(uri, abs_path, source)
        msgs.append(self._build_hover_request_message(uri, lsp_line, lsp_col))
        msgs.append(
            {
                'jsonrpc': '2.0',
                'method': 'shutdown',
                'id': _ONESHOT_ID_HOVER_SHUTDOWN,
                'params': {},
            }
        )

        responses, server_started, stderr_snippet = self._rpc(
            msgs, server_cmd, process_timeout=timeout
        )
        if not server_started:
            return self._server_failed(stderr=stderr_snippet)
        for resp in responses:
            if resp.get('id') == _ONESHOT_ID_HOVER:
                if 'result' not in resp:
                    return self._error_result(resp, hint='hover')
                return self._parse_hover_response(resp['result'])

        return LspResult(available=True, hover_text='No hover info')

    def _build_hover_request_message(
        self, uri: str, lsp_line: int, lsp_col: int
    ) -> dict[str, Any]:
        return {
            'jsonrpc': '2.0',
            'id': _ONESHOT_ID_HOVER,
            'method': 'textDocument/hover',
            'params': {
                'textDocument': {'uri': uri},
                'position': {'line': lsp_line, 'character': lsp_col},
            },
        }

    def _parse_hover_response(self, result: Any) -> LspResult:
        if result and 'contents' in result:
            contents = result['contents']
            if isinstance(contents, dict):
                return LspResult(available=True, hover_text=contents.get('value', ''))
            if isinstance(contents, list):
                return LspResult(
                    available=True,
                    hover_text='\n'.join([str(c) for c in contents]),
                )
            return LspResult(available=True, hover_text=str(contents))
        return LspResult(available=True)

    def _query_locations(
        self,
        command: str,
        abs_path: str,
        uri: str,
        source: str,
        lsp_line: int,
        lsp_col: int,
        *,
        process_timeout: float | None = None,
        post_edit: bool = False,
    ) -> LspResult:
        ctx = self._get_context(abs_path)
        if ctx is None:
            return self._unavailable(abs_path)

        timeout = self._resolve_timeout(ctx, process_timeout, post_edit=post_edit)
        session, use_fallback = self._use_session(ctx, uri, ctx.language_id, source)
        if session is not None:
            lsp_method = (
                'textDocument/definition'
                if command == 'find_definition'
                else 'textDocument/references'
            )
            if not session.supports(lsp_method):
                return self._unsupported_result(ctx, lsp_method)
            params: dict[str, Any] = {
                'textDocument': {'uri': uri},
                'position': {'line': lsp_line, 'character': lsp_col},
            }
            if command == 'find_references':
                params['context'] = {'includeDeclaration': True}
            response = session.request(lsp_method, params, timeout=timeout)
            if response is None:
                return self._server_failed()
            if 'result' not in response:
                return self._error_result(response, hint=lsp_method)
            return self._parse_location_response(response['result'])

        if not use_fallback:
            return self._server_failed()

        server_cmd = list(ctx.command)
        result, started = self._try_lsp_locations(
            server_cmd,
            command,
            uri,
            abs_path,
            source,
            lsp_line,
            lsp_col,
            process_timeout=timeout,
        )
        if not started:
            return self._server_failed()
        return result

    def _try_lsp_locations(
        self,
        server_cmd: list[str],
        command: str,
        uri: str,
        abs_path: str,
        source: str,
        lsp_line: int,
        lsp_col: int,
        *,
        process_timeout: float | None = None,
    ) -> tuple[LspResult, bool]:
        msg_id = 10
        msgs = self._build_init_msgs(uri, abs_path, source)
        msgs.append(
            self._build_location_request_message(
                command, msg_id, uri, lsp_line, lsp_col
            )
        )
        msgs.append(
            {'jsonrpc': '2.0', 'method': 'shutdown', 'id': msg_id + 1, 'params': {}}
        )

        responses, server_started, stderr_snippet = self._rpc(
            msgs, server_cmd, process_timeout=process_timeout or 15.0
        )
        if not server_started:
            return self._server_failed(stderr=stderr_snippet), False
        for resp in responses:
            if resp.get('id') == msg_id:
                if 'result' not in resp:
                    return self._error_result(resp, hint=command), True
                return self._parse_location_response(resp['result']), True
        return LspResult(available=True), True

    def _build_location_request_message(
        self, command: str, msg_id: int, uri: str, lsp_line: int, lsp_col: int
    ) -> dict[str, Any]:
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
        return msg

    def _parse_location_response(self, result: Any) -> LspResult:
        if not result:
            return LspResult(available=True)
        if isinstance(result, dict):
            result = [result]
        locations = []
        for loc in result:
            start = loc.get('range', {}).get('start', {})
            path = self._path_from_file_uri(loc.get('uri', ''))
            locations.append(
                LspLocation(
                    file=path,
                    line=start.get('line', 0) + 1,
                    column=start.get('character', 0) + 1,
                )
            )
        return LspResult(available=True, locations=locations)

    @staticmethod
    def _path_from_file_uri(uri: str) -> str:
        parsed = urlparse(uri)
        if parsed.scheme != 'file':
            return uri
        if parsed.netloc:
            return unquote(f'//{parsed.netloc}{parsed.path}')
        path = unquote(parsed.path)
        if os.name == 'nt' and len(path) >= 3 and path[0] == '/' and path[2] == ':':
            return path[1:]
        return path


_LSP_CLIENT = LspClient()


def get_lsp_client() -> LspClient:
    return _LSP_CLIENT
