"""Grinta logging utilities and formatters for console and structured outputs."""

from __future__ import annotations

import atexit
import collections.abc as mapping
import contextlib
import hashlib
import logging
import os
import re
import sys
import threading
import traceback
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from pythonjsonlogger.json import JsonFormatter

from backend.core.constants import (
    DEBUG,
    LOG_JSON,
    LOG_JSON_LEVEL_KEY,
    LOG_LEVEL,
    LOG_TO_FILE,
    OTEL_LOG_CORRELATION,
)
from backend.core.logging.session_event_logger import (
    SessionEventLogHandler,
    bind_session_event_logger,
    close_session_event_logger,
    get_session_event_logger,
)

# Re-export formatter/filter classes from dedicated module for backward compat.
from backend.core.logging.log_formatters import (
    _TRACE_LOCAL as TRACE_LOCAL,  # type: ignore
)
from backend.core.logging.log_formatters import (
    ColoredFormatter,
    ColorType,
    EnhancedJSONFormatter,
    NoColorFormatter,
    OpenTelemetryTraceFilter,
    SensitiveDataFilter,
    StackInfoFilter,
    TraceContextFilter,
    file_formatter,
    file_json_formatter,
    strip_ansi,
)
from backend.core.logging.log_formatters import (
    _fix_record as fix_record,  # type: ignore
)

__all__ = [
    'configure_file_logging',
    'bind_session_logging',
    'format_active_session_log_path',
    'finalize_session_logging_audit',
    'mcp_log_stream',
    'get_log_dir',
    'TRACE_LOCAL',
    'ColoredFormatter',
    'ColorType',
    'EnhancedJSONFormatter',
    'NoColorFormatter',
    'OpenTelemetryTraceFilter',
    'SensitiveDataFilter',
    'StackInfoFilter',
    'TraceContextFilter',
    'fix_record',
    'file_formatter',
    'file_json_formatter',
    'strip_ansi',
]

if TYPE_CHECKING:
    from collections.abc import MutableMapping
    from types import TracebackType

    _LoggerAdapter = logging.LoggerAdapter[logging.Logger]
else:
    _LoggerAdapter = logging.LoggerAdapter

# DEBUG enables stack traces on ERROR via StackInfoFilter.
if DEBUG:
    current_log_level = logging.DEBUG
else:
    current_log_level = logging.INFO

llm_formatter = logging.Formatter('%(message)s')  # legacy compat for tests


def get_session_file_handler() -> SessionEventLogHandler:
    """Return handler that writes app logger records into session.jsonl."""
    return SessionEventLogHandler()


class RollingLogger:
    """Rolling logger for displaying rotating log messages in debug mode.

    Maintains a fixed-size buffer of log lines that display in place
    when running in a TTY with debug mode enabled.
    """

    max_lines: int
    char_limit: int
    log_lines: list[str]
    all_lines: str

    def __init__(self, max_lines: int = 10, char_limit: int = 80) -> None:
        """Initialize the rolling buffer with display bounds."""
        self.max_lines = max_lines
        self.char_limit = char_limit
        self.log_lines = [''] * self.max_lines
        self.all_lines = ''

    def is_enabled(self) -> bool:
        """Check if rolling logger should be active.

        Returns:
            True if debug mode enabled and stdout is a TTY

        """
        return DEBUG and sys.stdout.isatty()

    def start(self, message: str = '') -> None:
        """Start rolling logger with optional initial message."""
        self._write('\n' * self.max_lines)
        self._flush()

    def add_line(self, line: str) -> None:
        """Add new line to rolling display buffer."""
        self.log_lines.pop(0)
        self.log_lines.append(line[: self.char_limit])
        self.print_lines()
        self.all_lines += line + '\n'

    def write_immediately(self, line: str) -> None:
        """Write line immediately without buffering."""
        self._write(line)
        self._flush()

    def print_lines(self) -> None:
        """Display the last n log_lines in the console."""
        self.move_back()
        for line in self.log_lines:
            self.replace_current_line(line)

    def move_back(self, amount: int = -1) -> None:
        r"""'\\033[F' moves the cursor up one line."""
        if amount == -1:
            amount = self.max_lines
        self._write('\x1b[F' * self.max_lines)
        self._flush()

    def replace_current_line(self, line: str = '') -> None:
        r"""'\\033[2K\\r' clears the line and moves the cursor to the beginning."""
        self._write('\x1b[2K' + line + '\n')
        self._flush()

    def _write(self, line: str) -> None:
        if not self.is_enabled():
            return
        sys.stdout.write(line)

    def _flush(self) -> None:
        if not self.is_enabled():
            return
        sys.stdout.flush()


def set_trace_context(ctx: dict[str, object] | None) -> None:
    """Set thread-local trace context (overwrites existing). Pass None to clear."""
    with contextlib.suppress(Exception):
        if ctx is None:
            if hasattr(TRACE_LOCAL, 'context'):
                delattr(TRACE_LOCAL, 'context')
        else:
            TRACE_LOCAL.context = dict(ctx)


def clear_trace_context() -> None:
    """Clear the thread-local trace context.

    Removes trace context from thread-local storage if it exists.
    Silently handles any exceptions during cleanup.
    """
    with contextlib.suppress(Exception):
        if hasattr(TRACE_LOCAL, 'context'):
            delattr(TRACE_LOCAL, 'context')


def get_trace_context() -> dict[str, Any]:
    """Return a shallow copy of the current thread-local trace context.

    If no context exists, returns an empty dict. Safe for import anywhere.
    """
    with contextlib.suppress(Exception):
        ctx = getattr(TRACE_LOCAL, 'context', None)
        if isinstance(ctx, dict):
            return dict(ctx)  # type: ignore
    return {}


def get_console_handler(log_level: int = logging.INFO) -> logging.StreamHandler[TextIO]:
    """Returns a console handler for logging."""
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    formatter_str = '\x1b[92m%(asctime)s - %(name)s:%(levelname)s\x1b[0m: %(filename)s:%(lineno)s - %(message)s'
    console_handler.setFormatter(ColoredFormatter(formatter_str, datefmt='%H:%M:%S'))
    return console_handler


def get_file_handler(
    log_dir: str,
    log_level: int = logging.INFO,
    when: str = 'd',
    backup_count: int = 7,
    utc: bool = False,
) -> TimedRotatingFileHandler:
    """Returns a file handler for logging."""
    os.makedirs(log_dir, exist_ok=True)
    file_name = 'app.log'
    file_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, file_name),
        when=when,
        backupCount=backup_count,
        utc=utc,
    )
    file_handler.setLevel(log_level)
    if LOG_JSON:
        file_handler.setFormatter(file_json_formatter())
    else:
        file_handler.setFormatter(file_formatter)
    return file_handler


def json_formatter() -> JsonFormatter:
    """Create JSON formatter for structured logging.

    Returns:
        JsonFormatter configured with timestamp and custom level field naming

    """
    fmt = '{asctime} {message} {levelname}'
    return JsonFormatter(
        fmt, style='{', rename_fields={'levelname': LOG_JSON_LEVEL_KEY}, timestamp=True
    )


def json_log_handler(
    level: int = logging.INFO, _out: TextIO = sys.stdout
) -> logging.Handler:
    """Configure logger instance for structured logging as json lines."""
    handler = logging.StreamHandler(_out)
    handler.setLevel(level)
    handler.setFormatter(json_formatter())
    return handler


logging.basicConfig(level=logging.ERROR)


def log_uncaught_exceptions(
    ex_cls: type[BaseException], ex: BaseException, tb: TracebackType | None
) -> Any:
    """Logs uncaught exceptions along with the traceback.

    Args:
        ex_cls: The type of the exception.
        ex: The exception instance.
        tb: The traceback object.

    Returns:
        None

    """
    if tb:
        logging.error(''.join(traceback.format_tb(tb)))
    logging.error('%s: %s', ex_cls, ex)


sys.excepthook = log_uncaught_exceptions

# Module-level flags that can be toggled at runtime by config loading
DISABLE_COLOR_PRINTING: bool = False

app_logger = logging.getLogger('app')
access_logger = logging.getLogger('app.access')


# Polyfill for getLevelNamesMapping (Python < 3.11)
def _get_level_names_mapping() -> dict[str, int]:
    if hasattr(logging, 'getLevelNamesMapping'):
        return logging.getLevelNamesMapping()  # type: ignore
    # Fallback for older versions
    return {str(logging.getLevelName(lvl)): lvl for lvl in range(0, 51, 10)}


_level_mapping = _get_level_names_mapping()
if LOG_LEVEL in _level_mapping:
    current_log_level = _level_mapping[LOG_LEVEL]
else:
    current_log_level = logging.INFO
app_logger.setLevel(current_log_level)
access_logger.setLevel(current_log_level)
if DEBUG:
    app_logger.addFilter(StackInfoFilter())
if current_log_level == logging.DEBUG:
    app_logger.debug('DEBUG mode enabled.')

# Always suppress stdout logging — Rich Live owns the terminal.
app_logger.addHandler(logging.NullHandler())
access_logger.addHandler(logging.NullHandler())
# Without a file handler, clamp to ERROR so nothing leaks to the console via other handlers.
# When LOG_TO_FILE is true, keep current_log_level so TimedRotatingFileHandler actually receives
# INFO/DEBUG (logger level is applied before handler level; ERROR here made app.log nearly empty).
if not LOG_TO_FILE:
    app_logger.setLevel(logging.ERROR)
    access_logger.setLevel(logging.ERROR)
app_logger.addFilter(SensitiveDataFilter(app_logger.name))
app_logger.addFilter(TraceContextFilter())
# Optionally correlate logs with active OpenTelemetry spans
if OTEL_LOG_CORRELATION:
    app_logger.addFilter(OpenTelemetryTraceFilter())
app_logger.propagate = False
access_logger.addFilter(SensitiveDataFilter(access_logger.name))
access_logger.addFilter(TraceContextFilter())
# Apply OTEL correlation to access logs as well
if OTEL_LOG_CORRELATION:
    access_logger.addFilter(OpenTelemetryTraceFilter())
access_logger.propagate = False

# Add log shipping handler if enabled
LOG_SHIPPING_ENABLED = os.getenv('LOG_SHIPPING_ENABLED', 'false').lower() in [
    'true',
    '1',
    'yes',
]
if LOG_SHIPPING_ENABLED:
    try:
        from backend.core.logging.log_shipping import (
            LogShippingHandler,
            get_log_shipper,
        )

        log_shipper = get_log_shipper()
        if log_shipper:
            app_logger.addHandler(LogShippingHandler(log_shipper))
            access_logger.addHandler(LogShippingHandler(log_shipper))
            app_logger.debug('Log shipping handler added')
    except Exception as e:
        app_logger.warning('Failed to initialize log shipping: %s', e)

app_logger.debug('Logging initialized')


_LEGACY_LOGS_MIGRATION_DONE = False
_LEGACY_LOGS_MIGRATION_LOCK = threading.Lock()


def _grinta_install_tree_root() -> str:
    """Directory that contains ``backend/`` (editable install or wheel).

    Session files live under ``logs/workspaces/<segment>/`` here (never only in
    the user's repo tree). ``segment`` is derived from ``PROJECT_ROOT`` so each
    workspace is isolated while you keep one Grinta checkout for debugging.
    """
    override = os.getenv('GRINTA_REPO_ROOT', '').strip()
    if override:
        return str(Path(override).expanduser().resolve())
    marker = Path(__file__).resolve()
    for parent in marker.parents:
        if (parent / 'backend').is_dir() and (parent / 'pyproject.toml').is_file():
            return str(parent)
    # ``logger.py`` lives at ``backend/core/logging/logger.py`` — four parents
    # to the install/repo root (was three when the module was ``backend/core/logger.py``).
    return str(marker.parents[3])


def _grinta_log_base() -> str:
    """Canonical ``logs/`` directory under the Grinta repo (single source of truth)."""
    override = os.getenv('GRINTA_LOG_ROOT', '').strip()
    if override:
        return str(Path(override).expanduser().resolve())
    return os.path.join(_grinta_install_tree_root(), 'logs')


def _workspace_logs_segment() -> str | None:
    """Filesystem segment for the active workspace, or ``None`` if unresolved."""
    from backend.core.workspace_resolution import resolve_cli_workspace_directory

    root_path = resolve_cli_workspace_directory()
    if root_path is None:
        return None
    root = str(root_path)
    key = os.path.normcase(os.path.normpath(root))
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]
    base = os.path.basename(root.rstrip('/\\')) or 'workspace'
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', base)[:48].strip('_') or 'workspace'
    return f'{safe}__{digest}'


def _workspace_logs_root() -> str:
    """Canonical root for workspace logs under the install tree."""
    return os.path.join(_grinta_log_base(), 'workspaces')


def _legacy_workspace_logs_root() -> str:
    """Legacy workspace-log root kept for backward-compatibility migration."""
    return os.path.join(_grinta_install_tree_root(), 'backend', 'logs', 'workspaces')


def _next_legacy_target(path: str) -> str:
    """Return a non-colliding target path for migrated legacy artifacts."""
    base, ext = os.path.splitext(path)
    idx = 1
    candidate = f'{base}.legacy-{idx}{ext}'
    while os.path.exists(candidate):
        idx += 1
        candidate = f'{base}.legacy-{idx}{ext}'
    return candidate


def _move_legacy_tree(src_dir: str, dst_dir: str) -> tuple[int, int]:
    """Move all entries from ``src_dir`` into ``dst_dir`` without overwriting."""
    moved_dirs = 0
    moved_files = 0
    os.makedirs(dst_dir, exist_ok=True)
    for entry in os.scandir(src_dir):
        src_path = entry.path
        dst_path = os.path.join(dst_dir, entry.name)
        if entry.is_dir(follow_symlinks=False):
            if os.path.isdir(dst_path):
                child_dirs, child_files = _move_legacy_tree(src_path, dst_path)
                moved_dirs += child_dirs
                moved_files += child_files
                with contextlib.suppress(OSError):
                    os.rmdir(src_path)
                continue
            if os.path.exists(dst_path):
                dst_path = _next_legacy_target(dst_path)
            os.replace(src_path, dst_path)
            moved_dirs += 1
            continue
        if os.path.exists(dst_path):
            dst_path = _next_legacy_target(dst_path)
        os.replace(src_path, dst_path)
        moved_files += 1
    return moved_dirs, moved_files


def _migrate_legacy_workspace_logs() -> None:
    """Consolidate historical ``backend/logs/workspaces`` into canonical logs root."""
    global _LEGACY_LOGS_MIGRATION_DONE
    with _LEGACY_LOGS_MIGRATION_LOCK:
        if _LEGACY_LOGS_MIGRATION_DONE:
            return
        _LEGACY_LOGS_MIGRATION_DONE = True
    legacy_root = _legacy_workspace_logs_root()
    if not os.path.isdir(legacy_root):
        return
    canonical_root = _workspace_logs_root()
    try:
        moved_dirs, moved_files = _move_legacy_tree(legacy_root, canonical_root)
        with contextlib.suppress(OSError):
            os.rmdir(legacy_root)
        with contextlib.suppress(OSError):
            os.rmdir(os.path.dirname(legacy_root))
        if moved_dirs or moved_files:
            app_logger.info(
                'Migrated legacy workspace logs into canonical root (%d dirs, %d files)',
                moved_dirs,
                moved_files,
            )
        _remove_empty_legacy_log_dirs(legacy_root)
    except Exception:
        app_logger.debug('Legacy workspace log migration failed', exc_info=True)


def _remove_empty_legacy_log_dirs(legacy_root: str) -> None:
    """Drop ``backend/logs`` after migration so only ``logs/`` remains."""
    try:
        if not os.path.isdir(legacy_root):
            return
        for root, dirs, files in os.walk(legacy_root, topdown=False):
            for name in files:
                os.unlink(os.path.join(root, name))
            for name in dirs:
                with contextlib.suppress(OSError):
                    os.rmdir(os.path.join(root, name))
        with contextlib.suppress(OSError):
            os.rmdir(legacy_root)
        legacy_parent = os.path.dirname(legacy_root)
        if os.path.basename(legacy_parent) == 'logs':
            with contextlib.suppress(OSError):
                os.rmdir(legacy_parent)
    except Exception:
        app_logger.debug('Legacy log directory cleanup failed', exc_info=True)


def _workspace_logs_dir() -> str | None:
    """Workspace-level log directory (shared by all sessions of a workspace)."""
    segment = _workspace_logs_segment()
    if segment is None:
        return None
    _migrate_legacy_workspace_logs()
    return os.path.join(_workspace_logs_root(), segment)


def _effective_workspace_logs_dir() -> str:
    """Workspace log root, falling back to a temp dir when PROJECT_ROOT is unset."""
    return _workspace_logs_dir() or _unbound_log_dir()


def _unbound_log_dir() -> str:
    """Ephemeral fallback when no workspace directory can be resolved."""
    import tempfile

    return os.path.join(tempfile.gettempdir(), 'grinta', 'unbound_logs')


def get_log_dir() -> str:
    """Return the active log directory for this process.

    Once a session is bound via :func:`bind_session_logging`, this resolves to
    ``logs/workspaces/<workspace>/sessions/<session_id>/`` where ``session.jsonl``
    and derived artifacts live.
    Before a session is bound (early startup) it falls back to the
    workspace-level directory so nothing is lost.
    """
    override = globals().get('LOG_DIR')
    if isinstance(override, (str, os.PathLike)):
        return os.fspath(override)
    base = _workspace_logs_dir()
    if base is None:
        return _unbound_log_dir()
    sid = globals().get('_LOG_SESSION_ID')
    if isinstance(sid, str) and sid:
        return os.path.join(base, 'sessions', sid)
    return base


def __getattr__(name: str) -> Any:
    if name == 'LOG_DIR':
        return get_log_dir()
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


LOQUACIOUS_LOGGERS = [
    'engineio',
    'engineio.server',
]
for logger_name in LOQUACIOUS_LOGGERS:
    logging.getLogger(logger_name).setLevel('WARNING')


_file_logging_configured = False

# Session-scoped logging via session.jsonl
_LOG_SESSION_ID: str | None = None
_ACTIVE_SESSION_LOG_DIR: str | None = None
_FILE_LOGGER_NAMES: tuple[str, ...] = (
    'app',
    'app.access',
    'grinta.tui',
)


def _remove_session_file_handlers() -> None:
    for name in _FILE_LOGGER_NAMES:
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            if isinstance(h, SessionEventLogHandler):
                lg.removeHandler(h)
                h.close()


def _attach_session_file_handlers() -> None:
    if not LOG_TO_FILE:
        return
    handler = get_session_file_handler()
    for name in _FILE_LOGGER_NAMES:
        lg = logging.getLogger(name)
        if any(isinstance(h, SessionEventLogHandler) for h in lg.handlers):
            continue
        lg.addHandler(handler)


def configure_file_logging() -> None:
    """Mark file logging ready; ``session.jsonl`` opens on :func:`bind_session_logging`."""
    global _file_logging_configured
    if _file_logging_configured or not LOG_TO_FILE:
        return
    workspace_dir = _effective_workspace_logs_dir()
    os.makedirs(workspace_dir, exist_ok=True)
    if _workspace_logs_dir() is None:
        app_logger.debug(
            'File logging using fallback directory (set PROJECT_ROOT or -p): %s',
            workspace_dir,
        )
    _file_logging_configured = True


def _safe_session_segment(session_id: str) -> str:
    """Filesystem-safe, bounded directory name for a session id."""
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', session_id).strip('_')
    return safe[:64] or 'session'


def _flush_shared_file_handler() -> None:
    """Ensure session.jsonl is flushed before audit generation."""
    sel = get_session_event_logger()
    if sel is not None:
        with contextlib.suppress(Exception):
            sel.flush()
    for name in _FILE_LOGGER_NAMES:
        for handler in logging.getLogger(name).handlers:
            if isinstance(handler, SessionEventLogHandler):
                with contextlib.suppress(Exception):
                    handler.flush()


def finalize_session_logging_audit(log_dir: str | None = None) -> None:
    """Write ``session.audit.txt`` and ``session.txt`` from ``session.jsonl``."""
    if not LOG_TO_FILE:
        return
    from backend.core.logging.session_log_audit import generate_session_audit_artifacts

    _flush_shared_file_handler()
    target_dir = log_dir or get_log_dir()
    try:
        result = generate_session_audit_artifacts(target_dir)
    except Exception:
        app_logger.debug('Session log audit generation failed', exc_info=True)
        return
    if result is None:
        return
    app_logger.info(
        'Session audit artifacts written (%s): kept=%d stripped=%d verdict=%s',
        result.report_path.parent,
        result.kept_lines,
        result.stripped_lines,
        result.verdict,
    )


def _audit_previous_session_log(previous_segment: str | None) -> None:
    if not previous_segment:
        return
    workspace_dir = _workspace_logs_dir()
    if workspace_dir is None:
        return
    previous_dir = os.path.join(workspace_dir, 'sessions', previous_segment)
    finalize_session_logging_audit(previous_dir)


def _audit_session_log_on_exit() -> None:
    if not LOG_TO_FILE:
        return
    target_dir = _ACTIVE_SESSION_LOG_DIR
    if not target_dir and _LOG_SESSION_ID:
        target_dir = get_log_dir()
    if not target_dir:
        return
    finalize_session_logging_audit(target_dir)


atexit.register(_audit_session_log_on_exit)


def bind_session_logging(session_id: str | None) -> None:
    """Bind unified session logging to ``sessions/<session_id>/session.jsonl``.

    Called once the session id is known. Emits ``SESSION_START`` and
    ``SESSION_CONTEXT``. Idempotent per session id.
    """
    global _LOG_SESSION_ID, _ACTIVE_SESSION_LOG_DIR
    if not LOG_TO_FILE or not session_id:
        return
    workspace_dir = _effective_workspace_logs_dir()
    segment = _safe_session_segment(str(session_id))
    if _LOG_SESSION_ID == segment:
        return
    previous_segment = _LOG_SESSION_ID
    _flush_shared_file_handler()
    close_session_event_logger()
    _audit_previous_session_log(previous_segment)
    _LOG_SESSION_ID = segment
    log_dir = os.path.join(workspace_dir, 'sessions', segment)
    _ACTIVE_SESSION_LOG_DIR = log_dir
    os.makedirs(log_dir, exist_ok=True)
    _remove_session_file_handlers()
    workspace_segment = _workspace_logs_segment()
    bind_session_event_logger(
        segment,
        log_dir,
        workspace_segment=workspace_segment,
    )
    _attach_session_file_handlers()
    _file_logging_configured = True
    app_logger.info('Session logging bound to %s', log_dir)


def format_active_session_log_path() -> str | None:
    """Return the active ``session.jsonl`` path when file logging is enabled."""
    if not LOG_TO_FILE:
        return None
    from backend.core.logging.session_event_logger import session_log_path

    try:
        return str(session_log_path(get_log_dir()))
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────
# MCP server stderr → session.jsonl MCP events
# ──────────────────────────────────────────────────────────────────────────
_MCP_LOG_STREAMS: dict[str, Any] = {}
_MCP_LOG_LOCK = threading.Lock()


def _mcp_stderr_forwarder(read_stream: Any, server_name: str) -> None:
    from backend.core.logging.session_event_logger import emit_session_event

    try:
        for raw in iter(read_stream.readline, ''):
            line = raw.rstrip('\r\n')
            if line:
                emit_session_event(
                    'MCP',
                    {'server': server_name, 'line': line},
                    level='INFO',
                )
    except Exception:  # pragma: no cover - defensive; pipe teardown races
        pass
    finally:
        with contextlib.suppress(Exception):
            read_stream.close()


def mcp_log_stream(server_name: str) -> Any:
    """Return a writable stream whose lines become ``MCP`` events in session.jsonl."""
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', server_name or 'mcp').strip('_') or 'mcp'
    with _MCP_LOG_LOCK:
        existing = _MCP_LOG_STREAMS.get(safe)
        if existing is not None and not getattr(existing, 'closed', False):
            return existing
        read_fd, write_fd = os.pipe()
        read_stream = os.fdopen(read_fd, 'r', encoding='utf-8', errors='replace')
        write_stream = os.fdopen(write_fd, 'w', encoding='utf-8', errors='replace')
        thread = threading.Thread(
            target=_mcp_stderr_forwarder,
            args=(read_stream, safe),
            name=f'mcp-stderr-{safe}',
            daemon=True,
        )
        thread.start()
        _MCP_LOG_STREAMS[safe] = write_stream
        return write_stream


class AppLoggerAdapter(_LoggerAdapter):
    """Logger adapter with context binding support.

    Allows binding contextual information (trace IDs, session IDs, etc.)
    to logger instances for structured logging.
    """

    def __init__(
        self,
        logger: logging.Logger = app_logger,
        extra: mapping.MutableMapping[str, Any] | None = None,
    ) -> None:
        """Initialize the adapter with a logger and optional context."""
        super().__init__(logger, extra or {})  # type: ignore

    def bind(self, **context: Any) -> AppLoggerAdapter:
        """Return a new adapter with additional context merged into extra.

        Example: adapter.bind(trace_id='abc', goal_id='g1')
        """
        # self.extra is defined as Mapping[str, Any] in base class
        new_extra: dict[str, Any] = {**self.extra, **context}  # type: ignore
        return AppLoggerAdapter(self.logger, new_extra)  # type: ignore

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        """If 'extra' is supplied in kwargs, merge it with the adapters 'extra' dict.

        Starting in Python 3.13, LoggerAdapter's merge_extra option will do this.
        """
        if 'extra' in kwargs and isinstance(
            kwargs['extra'], (dict, mapping.MutableMapping)
        ):
            kwargs['extra'] = {**(self.extra or {}), **kwargs['extra']}  # type: ignore
        else:
            kwargs['extra'] = self.extra  # type: ignore
        return (msg, kwargs)


def bind_context(
    logger: logging.Logger | AppLoggerAdapter, **context: Any
) -> AppLoggerAdapter:
    """Utility to bind tracing/context information to a logger.

    Returns an AppLoggerAdapter which will include the provided context in all
    emitted logs via the `extra` dict. Intended keys: trace_id, goal_id, step_id, event_source, msg_type.
    """
    if isinstance(logger, AppLoggerAdapter):
        return logger.bind(**context)
    return AppLoggerAdapter(logger, context)
