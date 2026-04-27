"""Log formatters and filters for App.

Extracted from logger.py to keep single-responsibility modules.
Classes are re-exported from logger.py as the canonical import surface.
"""

from __future__ import annotations

import copy
import logging
import os
import re
import sys
import threading as _threading
import traceback
from datetime import UTC
from typing import TYPE_CHECKING, Any, Literal

from pythonjsonlogger.json import JsonFormatter
from termcolor import colored

from backend.core.constants import LOG_ALL_EVENTS, LOG_COLORS

if TYPE_CHECKING:
    pass


ColorType = Literal[
    'red',
    'green',
    'yellow',
    'blue',
    'magenta',
    'cyan',
    'light_grey',
    'dark_grey',
    'light_red',
    'light_green',
    'light_yellow',
    'light_blue',
    'light_magenta',
    'light_cyan',
    'white',
]


def strip_ansi(s: str) -> str:
    """Remove ANSI escape sequences (terminal color/formatting codes) from string.

    Removes ANSI escape sequences from str, as defined by ECMA-048 in
    http://www.ecma-international.org/publications/files/ECMA-ST/Ecma-048.pdf
    # https://github.com/ewen-lbh/python-strip-ansi/blob/master/strip_ansi/__init__.py
    """
    pattern = re.compile('\\x1B\\[\\d+(;\\d+){0,2}m')
    return pattern.sub('', s)


def _fix_record(record: logging.LogRecord) -> logging.LogRecord:
    new_record = copy.copy(record)
    if getattr(new_record, 'exc_info', None) is True:
        new_record.exc_info = sys.exc_info()
        new_record.stack_info = None
    return new_record


class StackInfoFilter(logging.Filter):
    """Filter that adds stack trace information to error log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.ERROR:
            exc_info = sys.exc_info()
            if exc_info and exc_info[0] is not None:
                stack = traceback.format_stack()
                stack = stack[:-3]
                stack_str = ''.join(stack)
                record.stack_info = stack_str
                record.exc_info = exc_info
        return True


class NoColorFormatter(logging.Formatter):
    """Formatter for non-colored logging in files."""

    def format(self, record: logging.LogRecord) -> str:
        new_record = _fix_record(record)
        new_record.msg = strip_ansi(new_record.msg)
        return super().format(new_record)


class EnhancedJSONFormatter(JsonFormatter):
    """Enhanced JSON formatter with request IDs and structured data."""

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)

        request_id = getattr(record, 'request_id', None)
        if request_id:
            log_record['request_id'] = request_id

        conversation_id = getattr(record, 'conversation_id', None)
        if conversation_id:
            log_record['conversation_id'] = conversation_id

        from datetime import datetime

        log_record['timestamp'] = datetime.now(UTC).isoformat()

        agent_type = getattr(record, 'agent_type', None)
        if agent_type:
            log_record['agent_type'] = agent_type

        action_type = getattr(record, 'action_type', None)
        if action_type:
            log_record['action_type'] = action_type

        model_used = getattr(record, 'model_used', None)
        if model_used:
            log_record['model_used'] = model_used

        tokens_consumed = getattr(record, 'tokens_consumed', None)
        if tokens_consumed is not None:
            log_record['tokens_consumed'] = tokens_consumed

        cost_usd = getattr(record, 'cost_usd', None)
        if cost_usd is not None:
            log_record['cost_usd'] = cost_usd

        duration_ms = getattr(record, 'duration_ms', None)
        if duration_ms is not None:
            log_record['duration_ms'] = duration_ms

        log_record['thread_name'] = record.threadName
        log_record['process_id'] = record.process
        log_record['location'] = f'{record.filename}:{record.lineno}'
        log_record['function'] = record.funcName


class ColoredFormatter(logging.Formatter):
    """Custom formatter that colorizes log messages based on type and severity."""

    def _get_resolved_msg_type(self, record: logging.LogRecord) -> str:
        msg_type = record.__dict__.get('msg_type', '')
        if event_source := record.__dict__.get('event_source', ''):
            new_msg_type = f'{event_source.upper()}_{msg_type}'
            if new_msg_type in LOG_COLORS:
                return new_msg_type
        return msg_type

    def _format_colored_message(self, record: logging.LogRecord, msg_type: str) -> str:
        from backend.core.constants import DEBUG

        msg_type_color = colored(msg_type, LOG_COLORS[msg_type])
        msg = colored(record.msg, LOG_COLORS[msg_type])
        time_str = colored(self.formatTime(record, self.datefmt), LOG_COLORS[msg_type])
        name_str = colored(record.name, LOG_COLORS[msg_type])
        level_str = colored(record.levelname, LOG_COLORS[msg_type])

        if msg_type in {'ERROR'} or DEBUG:
            return f'{time_str} - {name_str}:{level_str}: {record.filename}:{record.lineno}\n{msg_type_color}\n{msg}'
        return f'{time_str} - {msg_type_color}\n{msg}'

    def _format_step_message(self, record: logging.LogRecord) -> str:
        return f'\n\n==============\n{record.msg}\n' if LOG_ALL_EVENTS else record.msg

    def format(self, record: logging.LogRecord) -> str:
        from backend.core.constants import DISABLE_COLOR_PRINTING

        msg_type = self._get_resolved_msg_type(record)

        if msg_type in LOG_COLORS and (not DISABLE_COLOR_PRINTING):
            return self._format_colored_message(record, msg_type)

        if msg_type == 'STEP':
            return self._format_step_message(record)

        new_record = _fix_record(record)
        return super().format(new_record)


class SensitiveDataFilter(logging.Filter):
    """Filter that redacts sensitive data from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        sensitive_values: list[str] = []
        for key, value in os.environ.items():
            key_upper = key.upper()
            if (
                len(value) > 2
                and value != 'default'
                and any(s in key_upper for s in ('SECRET', '_KEY', '_CODE', '_TOKEN'))
            ):
                sensitive_values.append(value)
        msg = record.getMessage()
        for sensitive_value in sensitive_values:
            msg = msg.replace(sensitive_value, '******')
        sensitive_patterns = [
            'api_key',
            'git_provider_token',
            'jwt_secret',
            'llm_api_key',
            'runtime_env_git_provider_token',
        ]
        env_vars = [attr.upper() for attr in sensitive_patterns]
        sensitive_patterns.extend(env_vars)
        for attr in sensitive_patterns:
            pattern = f"{attr}='?([\\w-]+)'?"
            msg = re.sub(pattern, f"{attr}='******'", msg)
        record.msg = msg
        record.args = ()
        return True


class TraceContextFilter(logging.Filter):
    """Injects thread-local trace context keys into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx: dict[str, Any] = getattr(_TRACE_LOCAL, "context", None) or {}
        for k, v in ctx.items():
            if not hasattr(record, k):
                setattr(record, k, v)
        return True


class OpenTelemetryTraceFilter(logging.Filter):
    """Adds OpenTelemetry trace_id/span_id to log records when a current span exists."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            from opentelemetry import trace as _otel_trace  # type: ignore

            span: Any = _otel_trace.get_current_span()
            if span is None:
                return True
            ctx = span.get_span_context()
            if not getattr(ctx, "is_valid", False):
                return True

            trace_id_hex = f"{ctx.trace_id:032x}"
            span_id_hex = f"{ctx.span_id:016x}"

            if not hasattr(record, "trace_id"):
                record.trace_id = trace_id_hex
            if not hasattr(record, "span_id"):
                record.span_id = span_id_hex
        except Exception:
            pass
        return True


# Shared thread-local for trace context
_TRACE_LOCAL: _threading.local = _threading.local()

# Pre-built file formatter instance
file_formatter = NoColorFormatter(
    '%(asctime)s - %(name)s:%(levelname)s: %(filename)s:%(lineno)s - %(message)s',
    datefmt='%H:%M:%S',
)
