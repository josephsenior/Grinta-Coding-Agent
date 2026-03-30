"""LLM API request batching and failover utilities.

Provides:
- Request batching for multiple LLM calls
- Automatic failover to backup providers
- Load balancing across providers
- Cost-aware provider selection
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.inference import LLM


@dataclass
class BatchRequest:
    """A single request in a batch."""

    prompt: str
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        """Initialize metadata if None."""
        if self.metadata is None:
            self.metadata = {}


@dataclass
class BatchResult:
    """Result of a batch request."""

    success: bool
    response: str | None = None
    error: Exception | None = None
    provider: str | None = None
    cost: float = 0.0
    latency_ms: float = 0.0


class LLMBatchProcessor:
    """Processes multiple LLM requests in batches."""

    def __init__(
        self,
        primary_llm: LLM,
        backup_llms: list[LLM] | None = None,
        batch_size: int = 5,
        max_concurrent: int = 10,
    ):
        """Initialize batch processor.

        Args:
            primary_llm: Primary LLM instance
            backup_llms: Backup LLM instances for failover
            batch_size: Maximum requests per batch
            max_concurrent: Maximum concurrent requests
        """
        self.primary_llm = primary_llm
        self.backup_llms = backup_llms or []
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def process_batch(self, requests: list[BatchRequest]) -> list[BatchResult]:
        """Process a batch of LLM requests.

        Args:
            requests: List of batch requests

        Returns:
            List of batch results
        """
        # Split into batches
        batches = [
            requests[i : i + self.batch_size]
            for i in range(0, len(requests), self.batch_size)
        ]

        # Process batches concurrently
        results = []
        for batch in batches:
            batch_results = await self._process_single_batch(batch)
            results.extend(batch_results)

        return results

    async def _process_single_batch(
        self, batch: list[BatchRequest]
    ) -> list[BatchResult]:
        """Process a single batch of requests.

        Args:
            batch: Batch of requests

        Returns:
            List of batch results
        """
        tasks = [self._process_single_request(req) for req in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Filter out exceptions and convert to BatchResult
        batch_results: list[BatchResult] = []
        for result in results:
            if isinstance(result, Exception):
                batch_results.append(BatchResult(success=False, error=result))
            else:
                # Type narrowing: result is BatchResult here
                assert isinstance(result, BatchResult), "Expected BatchResult"
                batch_results.append(result)
        return batch_results

    async def _process_single_request(self, request: BatchRequest) -> BatchResult:
        """Process a single request with failover.

        Args:
            request: Single batch request

        Returns:
            Batch result
        """
        import time

        start_time = time.time()

        # Try primary LLM first
        try:
            async with self._semaphore:
                # Use getattr to handle dynamic method access
                acompletion = getattr(self.primary_llm, "acompletion", None)
                if acompletion is None:
                    # Fallback to completion if acompletion doesn't exist
                    completion_func = self.primary_llm.completion()
                    response = await asyncio.to_thread(
                        completion_func,
                        messages=[{"role": "user", "content": request.prompt}],
                        model=request.model,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                    )
                else:
                    response = await acompletion(
                        messages=[{"role": "user", "content": request.prompt}],
                        model=request.model,
                        temperature=request.temperature,
                        max_tokens=request.max_tokens,
                    )

            latency = (time.time() - start_time) * 1000
            cost = getattr(self.primary_llm, "metrics", {}).get("accumulated_cost", 0.0)

            return BatchResult(
                success=True,
                response=response.choices[0].message.content
                if response.choices
                else None,
                provider="primary",
                cost=cost,
                latency_ms=latency,
            )
        except Exception as e:
            logger.warning("Primary LLM failed: %s, trying backup providers...", e)

            # Try backup providers
            for backup_llm in self.backup_llms:
                try:
                    async with self._semaphore:
                        # Use getattr to handle dynamic method access
                        acompletion = getattr(backup_llm, "acompletion", None)
                        if acompletion is None:
                            # Fallback to completion if acompletion doesn't exist
                            completion_func = backup_llm.completion()
                            response = await asyncio.to_thread(
                                completion_func,
                                messages=[{"role": "user", "content": request.prompt}],
                                model=request.model,
                                temperature=request.temperature,
                                max_tokens=request.max_tokens,
                            )
                        else:
                            response = await acompletion(
                                messages=[{"role": "user", "content": request.prompt}],
                                model=request.model,
                                temperature=request.temperature,
                                max_tokens=request.max_tokens,
                            )

                    latency = (time.time() - start_time) * 1000
                    cost = getattr(backup_llm, "metrics", {}).get(
                        "accumulated_cost", 0.0
                    )

                    return BatchResult(
                        success=True,
                        response=response.choices[0].message.content
                        if response.choices
                        else None,
                        provider="backup",
                        cost=cost,
                        latency_ms=latency,
                    )
                except Exception as backup_error:
                    logger.warning("Backup LLM failed: %s", backup_error)
                    continue

            # All providers failed
            latency = (time.time() - start_time) * 1000
            return BatchResult(
                success=False,
                error=e,
                latency_ms=latency,
            )


def create_batch_processor(
    primary_llm: LLM,
    backup_llms: list[LLM] | None = None,
    batch_size: int = 5,
    max_concurrent: int = 10,
) -> LLMBatchProcessor:
    """Create a batch processor instance.

    Args:
        primary_llm: Primary LLM instance
        backup_llms: Backup LLM instances
        batch_size: Batch size
        max_concurrent: Max concurrent requests

    Returns:
        LLMBatchProcessor instance
    """
    return LLMBatchProcessor(
        primary_llm=primary_llm,
        backup_llms=backup_llms,
        batch_size=batch_size,
        max_concurrent=max_concurrent,
    )
