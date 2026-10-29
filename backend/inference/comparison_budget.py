"""Aggregate attempt accounting shared with the Grinta comparison runner."""

import math
import threading
import time
from contextlib import contextmanager


class BudgetExceeded(RuntimeError):
    pass


class AttemptBudget:
    def __init__(self, seconds=7200, tokens=2000000, *, clock=time.monotonic):
        if (
            not math.isfinite(seconds)
            or seconds <= 0
            or type(tokens) is not int
            or tokens <= 0
        ):
            raise ValueError('positive finite time and token limits required')
        self.seconds, self.tokens, self.clock = seconds, tokens, clock
        self.started = None
        self.excluded = 0
        self.used = 0
        self.stop_reason = None
        self.lock = threading.RLock()

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
            if self.used >= self.tokens:
                raise BudgetExceeded('token_limit')
            if self.remaining <= 0:
                raise BudgetExceeded('time_limit')

    def charge(self, inputs, outputs):
        if any(type(n) is not int or n < 0 for n in (inputs, outputs)):
            self.stop_reason = 'usage_unavailable'
            raise BudgetExceeded(self.stop_reason)
        with self.lock:
            self.used += inputs + outputs
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
            'used_tokens': self.used,
            'token_overshoot': max(0, self.used - self.tokens),
            'remaining_seconds': self.remaining,
        }
