"""Persistent language-server sessions keyed by workspace + server."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from typing import Any

from backend.core.logging.logger import app_logger as logger
from backend.utils.http.stdio_json_rpc import encode_json_rpc_message, feed_content_length_buffer
from backend.utils.lsp.lsp_project_routing import LspFileContext
from backend.utils.lsp.lsp_timeouts import init_timeout_for_server

_CLIENT_CAPABILITIES: dict[str, Any] = {
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


def _sessions_disabled() -> bool:
    return os.getenv('GRINTA_DISABLE_LSP_SESSION', '').strip().lower() in {
        '1',
        'true',
        'yes',
        'on',
    }


class LspSession:
    """One long-lived stdio LSP subprocess for a workspace/server pair."""

    def __init__(self, ctx: LspFileContext) -> None:
        self.ctx = ctx
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stdout_buffer = b''
        self._initialized = False
        self._next_id = 2
        self._doc_versions: dict[str, int] = {}
        self._closed = False

    def is_alive(self) -> bool:
        return (
            not self._closed
            and self._process is not None
            and self._process.poll() is None
        )

    def start(self) -> bool:
        with self._lock:
            if self.is_alive():
                return True
            try:
                self._process = subprocess.Popen(
                    list(self.ctx.command),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    cwd=str(self.ctx.workspace_root),
                )
                self._reader_thread = threading.Thread(
                    target=self._read_stdout,
                    name=f'lsp-reader-{self.ctx.server_name}',
                    daemon=True,
                )
                self._reader_thread.start()
                return True
            except Exception as exc:
                logger.warning(
                    'LSP session failed to start %s: %s', self.ctx.server_name, exc
                )
                self._process = None
                return False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            proc = self._process
            if proc and proc.stdin and self._initialized:
                try:
                    self._write_message(
                        {
                            'jsonrpc': '2.0',
                            'id': 99_999,
                            'method': 'shutdown',
                            'params': {},
                        }
                    )
                except Exception:
                    pass
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._process = None

    def _read_stdout(self) -> None:
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        try:
            while proc.poll() is None:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                with self._lock:
                    self._stdout_buffer += chunk
                    messages, self._stdout_buffer = feed_content_length_buffer(
                        self._stdout_buffer
                    )
                for message in messages:
                    self._inbox.put(message)
            if proc.stdout:
                tail = proc.stdout.read()
                if tail:
                    with self._lock:
                        self._stdout_buffer += tail
                        messages, self._stdout_buffer = feed_content_length_buffer(
                            self._stdout_buffer
                        )
                    for message in messages:
                        self._inbox.put(message)
        except Exception:
            logger.debug('LSP reader stopped for %s', self.ctx.server_name, exc_info=True)

    def _write_message(self, message: dict[str, Any]) -> None:
        proc = self._process
        if proc is None or proc.stdin is None:
            raise OSError('LSP process stdin is not available')
        proc.stdin.write(encode_json_rpc_message(message))
        proc.stdin.flush()

    def _poll_inbox(self, timeout: float) -> dict[str, Any] | None:
        try:
            return self._inbox.get(timeout=timeout)
        except queue.Empty:
            return None

    def _wait_for_response(
        self, response_id: int, timeout: float
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        deferred: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            message = self._poll_inbox(min(0.2, max(0.01, remaining)))
            if message is None:
                continue
            if message.get('id') == response_id:
                for item in deferred:
                    self._inbox.put(item)
                return message
            deferred.append(message)
        for item in deferred:
            self._inbox.put(item)
        return None

    def _collect_notifications(
        self,
        method: str,
        *,
        timeout: float,
        uri: str | None = None,
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        matched: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            message = self._poll_inbox(min(0.2, max(0.01, remaining)))
            if message is None:
                continue
            if message.get('method') == method:
                params = message.get('params') or {}
                if uri is None or params.get('uri') == uri:
                    matched.append(message)
                    continue
            deferred.append(message)
        for item in deferred:
            self._inbox.put(item)
        return matched

    def ensure_initialized(self, timeout: float | None = None) -> bool:
        with self._lock:
            if self._initialized:
                return True
            if not self.start():
                return False
            init_timeout = timeout or init_timeout_for_server(self.ctx.server_name)
            init_id = 1
            root_uri = self.ctx.workspace_root.as_uri()
            self._write_message(
                {
                    'jsonrpc': '2.0',
                    'id': init_id,
                    'method': 'initialize',
                    'params': {
                        'processId': os.getpid(),
                        'rootUri': root_uri,
                        'workspaceFolders': [
                            {
                                'uri': root_uri,
                                'name': self.ctx.workspace_root.name or 'workspace',
                            }
                        ],
                        'capabilities': _CLIENT_CAPABILITIES,
                    },
                }
            )
            response = self._wait_for_response(init_id, init_timeout)
            if response is None or 'result' not in response:
                self.close()
                return False
            self._write_message({'jsonrpc': '2.0', 'method': 'initialized', 'params': {}})
            self._initialized = True
            return True

    def sync_document(self, uri: str, language_id: str, source: str) -> None:
        with self._lock:
            if uri in self._doc_versions:
                self._doc_versions[uri] += 1
                version = self._doc_versions[uri]
                self._write_message(
                    {
                        'jsonrpc': '2.0',
                        'method': 'textDocument/didChange',
                        'params': {
                            'textDocument': {'uri': uri, 'version': version},
                            'contentChanges': [{'text': source}],
                        },
                    }
                )
                return
            self._doc_versions[uri] = 1
            self._write_message(
                {
                    'jsonrpc': '2.0',
                    'method': 'textDocument/didOpen',
                    'params': {
                        'textDocument': {
                            'uri': uri,
                            'languageId': language_id,
                            'version': 1,
                            'text': source,
                        }
                    },
                }
            )

    def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any] | None:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            self._write_message(
                {
                    'jsonrpc': '2.0',
                    'id': request_id,
                    'method': method,
                    'params': params,
                }
            )
            return self._wait_for_response(request_id, timeout)

    def prepare_document(
        self,
        uri: str,
        language_id: str,
        source: str,
        *,
        init_timeout: float | None = None,
    ) -> bool:
        with self._lock:
            if not self.ensure_initialized(timeout=init_timeout):
                return False
            self.sync_document(uri, language_id, source)
            return True

    def wait_publish_diagnostics(
        self, uri: str, *, timeout: float
    ) -> list[dict[str, Any]]:
        messages = self._collect_notifications(
            'textDocument/publishDiagnostics',
            timeout=timeout,
            uri=uri,
        )
        diagnostics: list[dict[str, Any]] = []
        for message in messages:
            params = message.get('params') or {}
            diagnostics.extend(params.get('diagnostics', []))
        return diagnostics


class LspSessionPool:
    """Cache of live LSP sessions per (server, workspace)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[tuple[str, str], LspSession] = {}

    def get(self, ctx: LspFileContext) -> LspSession | None:
        if _sessions_disabled():
            return None
        key = (ctx.server_name, str(ctx.workspace_root.resolve()))
        with self._lock:
            session = self._sessions.get(key)
            if session is not None and session.is_alive():
                return session
            if session is not None:
                session.close()
            session = LspSession(ctx)
            if not session.start():
                return None
            self._sessions[key] = session
            return session

    def reset(self) -> None:
        with self._lock:
            for session in self._sessions.values():
                session.close()
            self._sessions.clear()


_POOL = LspSessionPool()


def get_lsp_session_pool() -> LspSessionPool:
    return _POOL


def reset_lsp_session_pool() -> None:
    _POOL.reset()
