"""Circuit breaker pattern for external service calls.

Prevents cascading failures by stopping requests to failing services
and allowing them to recover.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from backend.core.constants import (
    DEFAULT_CIRCUIT_FAILURE_THRESHOLD,
    DEFAULT_CIRCUIT_SUCCESS_THRESHOLD,
    DEFAULT_CIRCUIT_TIMEOUT_SECONDS,
)
from backend.core.enums import CircuitState
from backend.core.logger import FORGE_logger as logger

if TYPE_CHECKING:
    pass


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = DEFAULT_CIRCUIT_FAILURE_THRESHOLD  # Open circuit after N failures
    success_threshold: int = DEFAULT_CIRCUIT_SUCCESS_THRESHOLD  # Close circuit after N successes in half-open
    timeout_seconds: int = DEFAULT_CIRCUIT_TIMEOUT_SECONDS  # Time before trying half-open state
    expected_exception: type[Exception] = Exception  # Exception type to catch


@dataclass
class CircuitBreaker:
    """Circuit breaker for external service calls."""

    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float | None = None
    last_state_change: float = field(default_factory=time.time)

    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: If function raises an exception
        """
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_state_change >= self.config.timeout_seconds:
                # Try half-open state
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                self.last_state_change = time.time()
                logger.info("Circuit breaker %s entering HALF_OPEN state", self.name)
            else:
                raise CircuitBreakerOpenError(f"Circuit breaker {self.name} is OPEN. Service unavailable.")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.config.expected_exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Handle successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.last_state_change = time.time()
                logger.info("Circuit breaker %s CLOSED (recovered)", self.name)
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0

    def _on_failure(self) -> None:
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            # Failed in half-open, go back to open
            self.state = CircuitState.OPEN
            self.last_state_change = time.time()
            logger.warning("Circuit breaker %s OPEN (failed in half-open)", self.name)
        elif self.state == CircuitState.CLOSED and self.failure_count >= self.config.failure_threshold:
            # Too many failures, open circuit
            self.state = CircuitState.OPEN
            self.last_state_change = time.time()
            logger.error("Circuit breaker %s OPEN (failure threshold reached: %s)", self.name, self.failure_count)

    def reset(self) -> None:
        """Manually reset circuit breaker to closed state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.last_state_change = time.time()
        logger.info("Circuit breaker %s manually reset", self.name)


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass


# Global circuit breakers for external services
_llm_circuit_breaker = CircuitBreaker(
    "llm_api",
    config=CircuitBreakerConfig(
        failure_threshold=5,
        success_threshold=2,
        timeout_seconds=60,
    ),
)

_database_circuit_breaker = CircuitBreaker(
    "database",
    config=CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=1,
        timeout_seconds=30,
    ),
)

_runtime_circuit_breaker = CircuitBreaker(
    "runtime",
    config=CircuitBreakerConfig(
        failure_threshold=3,
        success_threshold=1,
        timeout_seconds=30,
    ),
)


def get_llm_circuit_breaker() -> CircuitBreaker:
    """Get circuit breaker for LLM API calls."""
    return _llm_circuit_breaker


def get_database_circuit_breaker() -> CircuitBreaker:
    """Get circuit breaker for database operations."""
    return _database_circuit_breaker


def get_runtime_circuit_breaker() -> CircuitBreaker:
    """Get circuit breaker for runtime operations."""
    return _runtime_circuit_breaker
