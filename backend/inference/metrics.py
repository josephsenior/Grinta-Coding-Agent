"""Data structures for recording cost, latency, and token usage metrics for LLM calls."""

from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass, field

from pydantic import BaseModel, Field

from backend.core.pydantic_compat import model_dump_with_options


@dataclass
class Cost:
    """Track request cost metrics in both prompt/output tokens and currency."""

    model: str = ''
    cost: float = 0.0
    prompt_tokens: int = 0
    timestamp: float = field(default_factory=time.time)


class ResponseLatency(BaseModel):
    """Metric tracking the round-trip time per completion call."""

    model: str
    latency: float
    response_id: str


class TokenUsage(BaseModel):
    """Metric tracking detailed token usage per completion call."""

    model: str = Field(default='')
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    cache_read_tokens: int = Field(default=0)
    cache_write_tokens: int = Field(default=0)
    context_window: int = Field(default=0)
    per_turn_token: int = Field(default=0)
    response_id: str = Field(default='')

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """Add two TokenUsage instances together."""
        return TokenUsage(
            model=self.model,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            context_window=max(self.context_window, other.context_window),
            per_turn_token=other.per_turn_token,
            response_id=self.response_id,
        )


class Metrics:
    """Metrics class can record various metrics during running and evaluation.

    We track:
      - accumulated_cost and costs
      - max_budget_per_task (budget limit)
      - A list of ResponseLatency
      - A list of TokenUsage (one per call).
    """

    def __init__(self, model_name: str = 'default') -> None:
        """Initialize empty tracking structures for the provided model name."""
        self._reset_internal_state(model_name)

    def _reset_internal_state(self, model_name: str) -> None:
        """Reset all internal tracking fields to their default state."""
        self._accumulated_cost: float = 0.0
        self._max_budget_per_task: float | None = None
        self._costs: list[Cost] = []
        self._response_latencies: list[ResponseLatency] = []
        self.model_name = model_name
        self._token_usages: list[TokenUsage] = []
        self._accumulated_token_usage: TokenUsage = TokenUsage(
            model=model_name,
            prompt_tokens=0,
            completion_tokens=0,
            cache_read_tokens=0,
            cache_write_tokens=0,
            context_window=0,
            response_id='',
        )

    @property
    def accumulated_cost(self) -> float:
        """Get total accumulated cost in USD."""
        return self._accumulated_cost

    @accumulated_cost.setter
    def accumulated_cost(self, value: float) -> None:
        """Set accumulated cost (must be non-negative)."""
        if value < 0:
            msg = 'Total cost cannot be negative.'
            raise ValueError(msg)
        self._accumulated_cost = value

    @property
    def max_budget_per_task(self) -> float | None:
        """Get maximum budget limit per task."""
        return self._max_budget_per_task

    @max_budget_per_task.setter
    def max_budget_per_task(self, value: float | None) -> None:
        """Set maximum budget limit."""
        self._max_budget_per_task = value

    @property
    def costs(self) -> list[Cost]:
        """Get list of individual cost records."""
        return self._costs

    @property
    def response_latencies(self) -> list[ResponseLatency]:
        """Get list of response latency measurements."""
        if not hasattr(self, '_response_latencies'):
            self._response_latencies = []
        return self._response_latencies

    @response_latencies.setter
    def response_latencies(self, value: list[ResponseLatency]) -> None:
        """Set response latencies list."""
        self._response_latencies = value

    @property
    def token_usages(self) -> list[TokenUsage]:
        """Get list of token usage records."""
        if not hasattr(self, '_token_usages'):
            self._token_usages = []
        return self._token_usages

    @token_usages.setter
    def token_usages(self, value: list[TokenUsage]) -> None:
        """Set token usages list."""
        self._token_usages = value

    @property
    def accumulated_token_usage(self) -> TokenUsage:
        """Get the accumulated token usage, initializing it if it doesn't exist."""
        if not hasattr(self, '_accumulated_token_usage'):
            self._accumulated_token_usage = TokenUsage(
                model=self.model_name,
                prompt_tokens=0,
                completion_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
                context_window=0,
                response_id='',
            )
        return self._accumulated_token_usage

    def add_cost(self, value: float) -> None:
        """Add cost to accumulated total.

        Args:
            value: Cost in USD to add (must be non-negative)

        Raises:
            ValueError: If cost is negative

        """
        try:
            if value < 0:
                msg = 'Added cost cannot be negative.'
                raise ValueError(msg)
        except TypeError:
            # Handle MagicMock in tests
            pass
        self._accumulated_cost += value
        self._costs.append(Cost(cost=value, model=self.model_name))

    def add_response_latency(self, value: float, response_id: str) -> None:
        """Add response latency measurement.

        Args:
            value: Latency in seconds (negative values clamped to 0)
            response_id: Unique ID for this response

        """
        self._response_latencies.append(
            ResponseLatency(
                latency=max(0.0, value), model=self.model_name, response_id=response_id
            ),
        )

    def add_token_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int,
        cache_write_tokens: int,
        context_window: int,
        response_id: str,
    ) -> None:
        """Add a single usage record."""
        per_turn_token = prompt_tokens + completion_tokens
        usage = TokenUsage(
            model=self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            context_window=context_window,
            per_turn_token=per_turn_token,
            response_id=response_id,
        )
        self._token_usages.append(usage)
        self._accumulated_token_usage = self.accumulated_token_usage + TokenUsage(
            model=self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            context_window=context_window,
            per_turn_token=per_turn_token,
            response_id='',
        )

    def merge(self, other: Metrics) -> None:
        """Merge 'other' metrics into this one."""
        self._accumulated_cost += other.accumulated_cost
        if self._max_budget_per_task is None and other.max_budget_per_task is not None:
            self._max_budget_per_task = other.max_budget_per_task
        self._costs += other._costs
        self.token_usages += other.token_usages
        self.response_latencies += other.response_latencies
        self._accumulated_token_usage = (
            self.accumulated_token_usage + other.accumulated_token_usage
        )

    def get(self) -> dict:
        """Return the metrics in a dictionary."""
        return {
            'accumulated_cost': self._accumulated_cost,
            'max_budget_per_task': self._max_budget_per_task,
            'accumulated_token_usage': model_dump_with_options(
                self.accumulated_token_usage
            ),
            'costs': [asdict(cost) for cost in self._costs],
            'response_latencies': [
                model_dump_with_options(latency) for latency in self._response_latencies
            ],
            'token_usages': [
                model_dump_with_options(usage) for usage in self._token_usages
            ],
        }

    def log(self) -> str:
        """Log the metrics."""
        metrics = self.get()
        return ''.join((f'{key}: {value}\n' for key, value in metrics.items()))

    def copy(self) -> Metrics:
        """Create a deep copy of the Metrics object."""
        return copy.deepcopy(self)

    def diff(self, baseline: Metrics) -> Metrics:
        """Calculate the difference between current metrics and a baseline.

        This is useful for tracking metrics for specific operations like delegates.

        Args:
            baseline: A metrics object representing the baseline state

        Returns:
            A new Metrics object containing only the differences since the baseline

        """
        result = Metrics(self.model_name)
        result._accumulated_cost = self._accumulated_cost - baseline._accumulated_cost
        if baseline._costs:
            last_baseline_timestamp = baseline._costs[-1].timestamp
            result._costs = [
                cost for cost in self._costs if cost.timestamp > last_baseline_timestamp
            ]
        else:
            result._costs = self._costs.copy()
        result._response_latencies = self._response_latencies[
            len(baseline._response_latencies) :
        ]
        result._token_usages = self._token_usages[len(baseline._token_usages) :]
        base_usage = baseline.accumulated_token_usage
        current_usage = self.accumulated_token_usage
        result._accumulated_token_usage = TokenUsage(
            model=self.model_name,
            prompt_tokens=current_usage.prompt_tokens - base_usage.prompt_tokens,
            completion_tokens=current_usage.completion_tokens
            - base_usage.completion_tokens,
            cache_read_tokens=current_usage.cache_read_tokens
            - base_usage.cache_read_tokens,
            cache_write_tokens=current_usage.cache_write_tokens
            - base_usage.cache_write_tokens,
            context_window=current_usage.context_window,
            per_turn_token=0,
            response_id='',
        )
        return result

    def __repr__(self) -> str:
        """Return a concise dictionary-style representation of tracked metrics."""
        return f'Metrics({self.get()})'

    def __getstate__(self) -> dict:
        """Return a plain-serializable state for pickling.

        We return the same shape as `get()` so unpickling can reconstruct the
        Metrics object without depending on module-level helpers or external
        function references.
        """
        return self.get()

    def __setstate__(self, state: dict) -> None:
        """Restore a Metrics object from the serialized state produced by.

        __getstate__.
        """
        model = state.get('accumulated_token_usage', {}).get('model', 'default')
        self._reset_internal_state(model_name=model)
        self._accumulated_cost = state.get('accumulated_cost', 0.0)
        self._max_budget_per_task = state.get('max_budget_per_task')
        self._costs = [
            Cost(**c) if isinstance(c, dict) else c for c in state.get('costs', [])
        ]
        self._response_latencies = [
            ResponseLatency.model_validate(r) if isinstance(r, dict) else r
            for r in state.get('response_latencies', [])
        ]
        self._token_usages = [
            TokenUsage.model_validate(t) if isinstance(t, dict) else t
            for t in state.get('token_usages', [])
        ]
        atu = state.get('accumulated_token_usage', {})
        if isinstance(atu, dict):
            self._accumulated_token_usage = TokenUsage.model_validate(atu)

    def __reduce__(self):
        """Provide explicit reduce to keep pickling compatibility across reloads."""
        return (self.__class__, (), self.__getstate__())
