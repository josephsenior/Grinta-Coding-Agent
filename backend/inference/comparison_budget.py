"""Aggregate attempt accounting shared with the Grinta comparison runner."""

import hashlib
import json
import math
import threading
import time
from collections import Counter
from contextlib import contextmanager


class BudgetExceeded(RuntimeError):
    pass


class AttemptBudget:
    def __init__(
        self,
        seconds=7200,
        tokens=2000000,
        *,
        clock=time.monotonic,
        accounting='cumulative',
    ):
        if (
            not math.isfinite(seconds)
            or seconds <= 0
            or type(tokens) is not int
            or tokens <= 0
        ):
            raise ValueError('positive finite time and token limits required')
        if accounting not in ('cumulative', 'once_only_context'):
            raise ValueError('unknown token accounting mode')
        self.seconds, self.tokens, self.clock = seconds, tokens, clock
        self.accounting = accounting
        self.started = None
        self.excluded = 0
        self.used = 0
        self.processed_inputs = self.processed_outputs = 0
        self.context_used = 0
        self._seen = Counter()
        self._encoding = None
        if accounting == 'once_only_context':
            import tiktoken

            self._encoding = tiktoken.get_encoding('o200k_base')
        self.stop_reason = None
        self.lock = threading.RLock()

    @classmethod
    def pilot(cls):
        return cls(tokens=1000000, accounting='once_only_context')

    @property
    def counted_tokens(self):
        return (
            self.context_used if self.accounting == 'once_only_context' else self.used
        )

    @staticmethod
    def _entry(item):
        kind = item.get('type', 'message')
        if kind == 'reasoning':
            return None  # Opaque/internal reasoning is reported in provider usage.
        if kind == 'message':
            content = item.get('content', '')
            if isinstance(content, list):
                content = ''.join(
                    p.get('text', '')
                    for p in content
                    if p.get('type') in ('input_text', 'output_text', 'text')
                )
            return {'role': item.get('role', 'assistant'), 'content': content}
        if kind == 'function_call':
            return {
                k: item.get(k, '') for k in ('type', 'call_id', 'name', 'arguments')
            }
        if kind == 'function_call_output':
            return {k: item.get(k, '') for k in ('type', 'call_id', 'output')}
        raise ValueError('unsupported item in once-only content accounting: ' + kind)

    def _observe(self, entries, *, generated):
        if self.accounting != 'once_only_context':
            return
        with self.lock:
            counts = Counter()
            costs = {}
            for entry in entries:
                if entry is None:
                    continue
                text = json.dumps(
                    entry, sort_keys=True, ensure_ascii=False, separators=(',', ':')
                )
                key = hashlib.sha256(text.encode('utf-8')).hexdigest()
                counts[key] += 1
                costs[key] = len(self._encoding.encode(text, disallowed_special=()))
            for key, count in counts.items():
                # Newly generated messages are new occurrences even when equal.
                # Replayed input history is matched by content and multiplicity.
                added = count if generated else max(0, count - self._seen[key])
                self._seen[key] += added
                self.context_used += added * costs[key]
            self.check()

    def observe_request(self, payload):
        if self.accounting != 'once_only_context':
            return
        entries = [self._entry(item) for item in payload.get('input', [])]
        if payload.get('instructions'):
            entries.append({'role': 'system', 'content': payload['instructions']})
        if payload.get('tools'):
            entries.append({'tools': payload['tools']})
        self._observe(entries, generated=False)

    def observe_response(self, output):
        if self.accounting == 'once_only_context':
            self._observe([self._entry(item) for item in output], generated=True)

    def start(self):
        with self.lock:
            if self.started is None:
                self.started = self.clock()

    @property
    def remaining(self):
        return (
            self.seconds
            if self.started is None
            else max(0, self.seconds - (self.clock() - self.started - self.excluded))
        )

    def check(self):
        with self.lock:
            if self.stop_reason:
                raise BudgetExceeded(self.stop_reason)
            if self.counted_tokens >= self.tokens:
                raise BudgetExceeded('token_limit')
            if self.remaining <= 0:
                raise BudgetExceeded('time_limit')

    def charge(self, inputs, outputs):
        if any(type(n) is not int or n < 0 for n in (inputs, outputs)):
            self.stop_reason = 'usage_unavailable'
            raise BudgetExceeded(self.stop_reason)
        with self.lock:
            self.used += inputs + outputs
            self.processed_inputs += inputs
            self.processed_outputs += outputs
            self.check()

    @contextmanager
    def exclude_baseline(self):
        begin = self.clock()
        try:
            yield
        finally:
            if self.started is not None:
                self.excluded += self.clock() - begin

    def snapshot(self):
        return {
            'time_limit_seconds': self.seconds,
            'token_limit': self.tokens,
            'used_tokens': self.counted_tokens,
            'token_overshoot': max(0, self.counted_tokens - self.tokens),
            'token_accounting': self.accounting,
            'content_tokenizer': 'o200k_base' if self._encoding else None,
            'processed_input_tokens': self.processed_inputs,
            'processed_output_tokens': self.processed_outputs,
            'processed_tokens': self.used,
            'remaining_seconds': self.remaining,
        }
