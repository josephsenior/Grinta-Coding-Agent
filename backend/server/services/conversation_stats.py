"""Utilities for tracking and persisting per-conversation usage metrics."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, Any, cast

from backend.core.logger import FORGE_logger as logger
from backend.llm.metrics import Metrics
from backend.storage.locations import get_conversation_stats_filename

if TYPE_CHECKING:
    from backend.llm.llm_registry import RegistryEvent
    from backend.storage.files import FileStore


@dataclass
class ConversationStats:
    """Aggregated counters describing conversation activity for dashboards."""

    conversations: int = 0

    def __init__(
        self,
        file_store: FileStore | None,
        conversation_id: str,
        user_id: str | None,
    ) -> None:
        """Initialize storage paths and prime metrics recovery for a conversation."""
        self.metrics_path = get_conversation_stats_filename(conversation_id, user_id)
        self.file_store = file_store
        self.conversation_id = conversation_id
        self.user_id = user_id
        self._save_lock = Lock()
        self.service_to_metrics: dict[str, Metrics] = {}
        self.restored_metrics: dict[str, Metrics] = {}
        self.maybe_restore_metrics()

    def save_metrics(self) -> None:
        """Save conversation metrics to persistent storage.

        Combines restored and current metrics, serializes to JSON (base64 encoded),
        and writes to file store.
        """
        if not self.file_store:
            return
        with self._save_lock:
            if duplicate_services := (set(self.restored_metrics.keys()) & set(self.service_to_metrics.keys())):
                logger.error(
                    "Duplicate service IDs found between restored and service metrics: %s. This should not happen as registered services should be removed from restored_metrics. Proceeding by preferring service_to_metrics values for duplicates.",
                    duplicate_services,
                    extra={
                        "conversation_id": self.conversation_id,
                        "duplicate_services": list(duplicate_services),
                    },
                )
            combined_metrics: dict[str, Metrics | dict[str, Any] | Any] = {}
            combined_metrics.update(self.restored_metrics)
            combined_metrics.update(self.service_to_metrics)
            serializable: dict[str, dict[str, Any]] = {}
            for sid, metrics in combined_metrics.items():
                if isinstance(metrics, Metrics):
                    serializable[sid] = metrics.get()
                elif isinstance(metrics, dict):
                    serializable[sid] = cast(dict[str, Any], metrics)
                else:
                    # Fallback for unexpected types; best-effort serialization
                    getter = getattr(metrics, "get", None)
                    if callable(getter):
                        serializable[sid] = cast(dict[str, Any], getter())
                    else:
                        serializable[sid] = {"value": repr(metrics)}
            # Use JSON instead of pickle for security
            json_data = json.dumps(serializable)
            serialized_metrics = base64.b64encode(json_data.encode("utf-8")).decode(
                "utf-8",
            )
            self.file_store.write(self.metrics_path, serialized_metrics)
            logger.info(
                "Saved converation stats",
                extra={"conversation_id": self.conversation_id},
            )

    def maybe_restore_metrics(self) -> None:
        """Attempt to restore metrics from previous session.

        Uses JSON format only. Silently skips if no saved metrics exist.
        """
        if not self.file_store or not self.conversation_id:
            return
        try:
            encoded = self.file_store.read(self.metrics_path)
            decoded = base64.b64decode(encoded)
            try:
                loaded = json.loads(decoded.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.warning(
                    "Invalid metrics payload format for conversation %s; skipping restore",
                    self.conversation_id,
                )
                return

            normalized: dict[str, Metrics] = {}

            if isinstance(loaded, dict):
                for sid, v in loaded.items():
                    if isinstance(v, Metrics):
                        normalized[sid] = v
                    elif isinstance(v, dict):
                        m = Metrics()
                        m.__setstate__(v)
                        normalized[sid] = m
                    else:
                        continue
            else:
                normalized = {}
            self.restored_metrics = normalized
            logger.info("restored metrics: %s", self.conversation_id)
        except FileNotFoundError:
            pass

    def get_combined_metrics(self) -> Metrics:
        """Get combined metrics across all services.

        Returns:
            Merged metrics object with totals from all services

        """
        total_metrics = Metrics()
        for metrics in self.service_to_metrics.values():
            total_metrics.merge(metrics)
        return total_metrics

    def get_metrics_for_service(self, service_id: str) -> Metrics:
        """Get metrics for specific LLM service.

        Args:
            service_id: Service identifier

        Returns:
            Metrics object for the service

        Raises:
            KeyError: If service doesn't exist

        """
        if service_id not in self.service_to_metrics:
            msg = f"LLM service does not exist {service_id}"
            raise KeyError(msg)
        return self.service_to_metrics[service_id]

    def register_llm(self, event: RegistryEvent) -> None:
        """Register new LLM service and set up metrics tracking.

        Args:
            event: Registry event containing LLM and service_id

        """
        llm = event.llm
        service_id = event.service_id
        if llm is None or service_id is None:
            logger.warning(
                "Registry event missing llm or service_id",
                extra={
                    "conversation_id": self.conversation_id,
                    "service_id": service_id,
                },
            )
            return
        if service_id in self.restored_metrics:
            llm.metrics = self.restored_metrics[service_id].copy()
            del self.restored_metrics[service_id]
        metrics = getattr(llm, "metrics", None)
        if metrics is None:
            metrics = Metrics()
            llm.metrics = metrics
        self.service_to_metrics[service_id] = metrics

    def merge_and_save(self, conversation_stats: ConversationStats) -> None:
        """Merge restored metrics from another ConversationStats into this one.

        Important:
        - This method is intended to be used immediately after restoring metrics from
          storage, before any LLM services are registered. In that state, only
          `restored_metrics` should contain entries and `service_to_metrics` should
          be empty. If either side has entries in `service_to_metrics`, we log an
          error but continue execution.

        Behavior:
        - Drop entries with zero accumulated_cost from both `restored_metrics` dicts
          (self and incoming) before merging.
        - Merge only `restored_metrics`. For duplicate keys, the incoming
          `conversation_stats.restored_metrics` overwrites existing entries.
        - Do NOT merge `service_to_metrics` here.
        - Persist results by calling save_metrics().

        """
        if self.service_to_metrics or conversation_stats.service_to_metrics:
            logger.error(
                "merge_and_save should be used only when service_to_metrics are empty; found active service metrics during merge. Proceeding anyway.",
                extra={
                    "conversation_id": self.conversation_id,
                    "self_service_to_metrics_keys": list(
                        self.service_to_metrics.keys(),
                    ),
                    "incoming_service_to_metrics_keys": list(
                        conversation_stats.service_to_metrics.keys(),
                    ),
                },
            )

        def _drop_zero_cost(d: dict[str, Metrics]) -> None:
            to_delete = [k for k, v in d.items() if getattr(v, "accumulated_cost", 0) == 0]
            for k in to_delete:
                del d[k]

        _drop_zero_cost(self.restored_metrics)
        _drop_zero_cost(conversation_stats.restored_metrics)
        self.restored_metrics.update(conversation_stats.restored_metrics)
        self.save_metrics()
        logger.info(
            "Merged conversation stats",
            extra={"conversation_id": self.conversation_id},
        )
