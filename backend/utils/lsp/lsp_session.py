"""Persistent language-server sessions keyed by workspace + server."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from collections import deque
from typing import Any

from backend.core.logging.logger import app_logger as logger
from backend.utils.http.stdio_json_rpc import (
    encode_json_rpc_message,
    feed_content_length_buffer,
)
from backend.utils.lsp.lsp_capabilities import (
    CLIENT_CAPABILITIES,
    METHOD_CAPABILITY_KEYS,
)
from backend.utils.lsp.lsp_project_routing import LspFileContext
from backend.utils.lsp.lsp_timeouts import init_timeout_for_server
from backend.utils.path_normalize import to_native_path

_STDERR_RING_CAPACITY = 64
_STDERR_FAILURE_SNIPPET_LINES = 24


def _stderr_debug_enabled() -> bool:
    return os.getenv('GRINTA_LSP_DEBUG_STDERR', '').strip().lower() in {
        '1',
        'true',
        'yes',
        'on',
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
        self._stderr_thread: threading.Thread | None = None
        self._inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stdout_buffer = b''
        self._stderr_ring: deque[str] = deque(maxlen=_STDERR_RING_CAPACITY)
        self._initialized = False
        self._server_capabilities: dict[str, Any] = {}
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
                self._closed = False
                self._initialized = False
                self._server_capabilities = {}
                self._next_id = 2
                self._doc_versions.clear()
                self._stdout_buffer = b''
                self._stderr_ring.clear()
                while not self._inbox.empty():
                    try:
                        self._inbox.get_nowait()
                    except queue.Empty:
                        break
                command = [to_native_path(c) for c in self.ctx.command]
                cwd = to_native_path(str(self.ctx.workspace_root))
                self._process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                )
                self._reader_thread = threading.Thread(
                    target=self._read_stdout,
                    name=f'lsp-reader-{self.ctx.server_name}',
                    daemon=True,
                )
                self._reader_thread.start()
                self._stderr_thread = threading.Thread(
                    target=self._read_stderr,
                    name=f'lsp-stderr-{self.ctx.server_name}',
                    daemon=True,
                )
                self._stderr_thread.start()
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
            was_initialized = self._initialized
            if proc and proc.stdin and was_initialized:
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
            exit_code: int | None = None
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
            if proc is not None:
                try:
                    exit_code = proc.wait(timeout=1.0)
                except Exception:
                    exit_code = proc.poll()
            # Surface stderr when the server died unexpectedly (non-zero exit or
            # crash before a clean shutdown). Helps diagnose startup failures
            # and mid-query crashes that were previously swallowed by DEVNULL.
            if was_initialized and exit_code not in (None, 0):
                snippet = self._format_stderr_snippet()
                if snippet:
                    logger.warning(
                        'LSP server %s exited with code %s. Recent stderr:\n%s',
                        self.ctx.server_name,
                        exit_code,
                        snippet,
                    )
            elif _stderr_debug_enabled():
                snippet = self._format_stderr_snippet()
                if snippet:
                    logger.debug(
                        'LSP server %s closing. Stderr tail:\n%s',
                        self.ctx.server_name,
                        snippet,
                    )
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
            logger.debug(
                'LSP reader stopped for %s', self.ctx.server_name, exc_info=True
            )

    def _read_stderr(self) -> None:
        """Append server stderr lines to a bounded ring buffer.

        Always captured (no longer DEVNULL) so post-mortem debugging is possible.
        Logged live only when ``GRINTA_LSP_DEBUG_STDERR=1`` is set; otherwise the
        ring is surfaced via :meth:`recent_stderr` and on unexpected exit in
        :meth:`close`.
        """
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        debug = _stderr_debug_enabled()
        try:
            while proc.poll() is None:
                line = proc.stderr.readline()
                if not line:
                    break
                text = line.rstrip(b'\r\n').decode('utf-8', errors='replace')
                with self._lock:
                    self._stderr_ring.append(text)
                if debug:
                    logger.debug('LSP stderr %s: %s', self.ctx.server_name, text)
        except Exception:
            logger.debug(
                'LSP stderr reader stopped for %s', self.ctx.server_name, exc_info=True
            )

    def recent_stderr(self, max_lines: int = _STDERR_FAILURE_SNIPPET_LINES) -> str:
        """Return up to *max_lines* of recent stderr output, newest last."""
        with self._lock:
            lines = list(self._stderr_ring)
        if not lines:
            return ''
        return '\n'.join(lines[-max_lines:])

    def _format_stderr_snippet(self) -> str:
        snippet = self.recent_stderr()
        if not snippet:
            return ''
        return snippet[:2000]

    def _write_message(self, message: dict[str, Any]) -> None:
        proc = self._process
        if proc is None or proc.stdin is None:
            raise OSError('LSP process stdin is not available')
        if proc.poll() is not None:
            raise OSError(
                f'LSP process {self.ctx.server_name} exited with code '
                f'{proc.returncode} before write'
            )
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
        grace: float = 0.25,
    ) -> list[dict[str, Any]]:
        """Collect ``method`` notifications up to *timeout*.

        Once at least one matching notification has been seen, a *grace* quiet
        window (default 0.25s) gates early return: if no new match arrives
        within the grace window, we return immediately rather than waiting the
        full timeout. This lets warm servers that flush diagnostics promptly
        return fast while still coalescing multi-part diagnostic bursts.
        """
        deadline = time.monotonic() + timeout
        matched: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        grace_deadline: float | None = None
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if matched and grace_deadline is not None:
                poll_timeout = min(grace, max(0.01, remaining))
            else:
                poll_timeout = min(0.2, max(0.01, remaining))
            message = self._poll_inbox(poll_timeout)
            if message is None:
                if (
                    matched
                    and grace_deadline is not None
                    and time.monotonic() >= grace_deadline
                ):
                    break
                continue
            if message.get('method') == method:
                params = message.get('params') or {}
                if uri is None or params.get('uri') == uri:
                    matched.append(message)
                    grace_deadline = time.monotonic() + grace
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
            try:
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
                            'capabilities': CLIENT_CAPABILITIES,
                        },
                    }
                )
            except OSError as exc:
                logger.warning(
                    'LSP initialize write failed for %s: %s. stderr:\n%s',
                    self.ctx.server_name,
                    exc,
                    self._format_stderr_snippet(),
                )
                self.close()
                return False

        # Lock released — reader thread can now parse and enqueue the response.
        # Holding the lock here was the root cause of init always timing out:
        # _read_stdout needs the same lock to feed_content_length_buffer and
        # put messages into _inbox, so the initialize response was stranded
        # in the stdout buffer until the 20s timeout expired.
        response = self._wait_for_response(init_id, init_timeout)
        if response is None:
            logger.warning(
                'LSP initialize timed out for %s. stderr:\n%s',
                self.ctx.server_name,
                self._format_stderr_snippet(),
            )
            with self._lock:
                self.close()
            return False
        err = response.get('error')
        if isinstance(err, dict):
            logger.warning(
                'LSP initialize rejected by %s: %s',
                self.ctx.server_name,
                err.get('message') or err,
            )
            with self._lock:
                self.close()
            return False
        result = response.get('result')
        if not isinstance(result, dict):
            logger.warning(
                'LSP initialize returned no result for %s. stderr:\n%s',
                self.ctx.server_name,
                self._format_stderr_snippet(),
            )
            with self._lock:
                self.close()
            return False
        with self._lock:
            self._server_capabilities = result.get('capabilities') or {}
            try:
                self._write_message(
                    {'jsonrpc': '2.0', 'method': 'initialized', 'params': {}}
                )
            except OSError:
                pass
            self._initialized = True
            return True

    def capabilities(self) -> dict[str, Any]:
        """Return the server's advertised capabilities (empty until initialized)."""
        with self._lock:
            return dict(self._server_capabilities)

    def supports(self, method: str) -> bool:
        """Return True when the server advertises support for *method*.

        ``method`` is the full LSP method name, e.g.
        ``textDocument/hover``. A capability is considered supported when its
        provider entry is truthy (bool), a dict (options), or a list
        (documentSelector). Absent or ``False`` means not supported.
        """
        capabilities = self.capabilities()
        key = METHOD_CAPABILITY_KEYS.get(method)
        if key is None:
            return True
        provider = capabilities.get(key)
        if isinstance(provider, bool):
            return provider
        if isinstance(provider, (dict, list)):
            return True
        return provider is not None

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
            try:
                self._write_message(
                    {
                        'jsonrpc': '2.0',
                        'id': request_id,
                        'method': method,
                        'params': params,
                    }
                )
            except OSError:
                return None
        # Lock released so the reader thread can parse and enqueue the response.
        return self._wait_for_response(request_id, timeout)

    def prepare_document(
        self,
        uri: str,
        language_id: str,
        source: str,
        *,
        init_timeout: float | None = None,
    ) -> bool:
        if not self.ensure_initialized(timeout=init_timeout):
            return False
        with self._lock:
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
