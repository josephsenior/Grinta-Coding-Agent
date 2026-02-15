from __future__ import annotations

import threading
import time
import importlib
from typing import TYPE_CHECKING, Any, cast

from backend.core.logger import FORGE_logger as logger
from backend.core.schemas import (
    ActionSchemaUnion,
    ObservationSchemaUnion,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from prometheus_client import Counter as PromCounter
    from prometheus_client import Histogram as PromHistogram
else:  # pragma: no cover - runtime fallback when dependency missing
    PromCounter = Any
    PromHistogram = Any


class ToolTelemetry:
    """Centralized telemetry recorder for tool invocations.

    Records per-tool counts and latency metrics, exporting to Prometheus when
    available while maintaining an in-memory ring buffer for tests and ad-hoc
    diagnostics.
    """

    _instance: ToolTelemetry | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._recent_events: list[dict[str, Any]] = []
        self._recent_lock = threading.Lock()
        self._invocations: PromCounter | None = None
        self._latency: PromHistogram | None = None
        self._setup_prometheus_metrics()

    @classmethod
    def get_instance(cls) -> ToolTelemetry:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _setup_prometheus_metrics(self) -> None:
        try:
            prometheus_client = importlib.import_module("prometheus_client")
            runtime_counter = getattr(prometheus_client, "Counter")
            runtime_histogram = getattr(prometheus_client, "Histogram")
        except Exception:  # pragma: no cover - dependency unavailable
            self._invocations = None
            self._latency = None
            return

        self._invocations = runtime_counter(
            "forge_tool_invocations_total",
            "Number of tool invocations processed by the agent controller",
            labelnames=("tool", "outcome"),
        )
        self._latency = runtime_histogram(
            "forge_tool_latency_seconds",
            "Duration of tool invocations executed by the agent controller",
            labelnames=("tool", "outcome"),
            buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")),
        )

    # ------------------------------------------------------------------ #
    # Lifecycle hooks invoked by middleware/pipeline
    # ------------------------------------------------------------------ #
    def on_plan(self, ctx) -> None:
        telemetry = ctx.metadata.setdefault("telemetry", {})
        telemetry["start_time"] = time.monotonic()
        tool_identifier = getattr(ctx.action, "action", type(ctx.action).__name__)
        telemetry.setdefault("tool_name", str(tool_identifier))

        # Convert action to schema for richer typing
        try:
            action_schema = self._action_to_schema(ctx.action)
            if action_schema:
                telemetry["action_schema"] = action_schema.to_dict()
        except Exception as exc:  # pragma: no cover - schema conversion is optional
            logger.debug("Failed to convert action to schema: %s", exc)

    def on_execute(self, ctx) -> None:
        telemetry = ctx.metadata.setdefault("telemetry", {})
        telemetry["execute_time"] = time.monotonic()

    def on_observe(self, ctx, observation) -> None:
        telemetry = ctx.metadata.get("telemetry")
        if telemetry is None:
            return

        outcome = self._determine_outcome(observation)
        duration = self._elapsed_since(telemetry)
        tool_identifier = (
            telemetry.get("tool_name") if isinstance(telemetry, dict) else None
        )
        if not isinstance(tool_identifier, str) or not tool_identifier:
            tool_identifier = getattr(ctx.action, "action", type(ctx.action).__name__)
        tool_name = str(tool_identifier)

        # Convert observation to schema for richer typing
        try:
            if observation is not None:
                obs_schema = self._observation_to_schema(observation)
                if obs_schema:
                    telemetry["observation_schema"] = obs_schema.to_dict()
        except Exception as exc:  # pragma: no cover - schema conversion is optional
            logger.debug("Failed to convert observation to schema: %s", exc)

        self._record(
            tool_name,
            outcome,
            duration,
            telemetry if isinstance(telemetry, dict) else None,
        )

    def on_blocked(self, ctx, reason: str | None = None) -> None:
        telemetry = ctx.metadata.get("telemetry")
        duration = self._elapsed_since(telemetry)
        tool_name = telemetry.get("tool_name") if isinstance(telemetry, dict) else None
        if not isinstance(tool_name, str) or not tool_name:
            tool_name = str(getattr(ctx.action, "action", type(ctx.action).__name__))
        outcome_reason = reason or ctx.block_reason or "blocked"
        self._record(
            tool_name,
            f"blocked:{outcome_reason}",
            duration,
            telemetry if isinstance(telemetry, dict) else None,
        )

    # ------------------------------------------------------------------ #
    # Inspection / utilities (used by tests)
    # ------------------------------------------------------------------ #
    def recent_events(self) -> list[dict[str, Any]]:
        with self._recent_lock:
            return list(self._recent_events)

    def reset_for_test(self) -> None:
        with self._recent_lock:
            self._recent_events.clear()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _determine_outcome(self, observation) -> str:
        if observation is None:
            return "success"
        from backend.events.observation import ErrorObservation

        if isinstance(observation, ErrorObservation):
            return "failure"
        return "success"

    def _elapsed_since(self, telemetry: dict[str, Any] | None) -> float:
        start = None
        if isinstance(telemetry, dict):
            start = telemetry.get("start_time")
        if start is None:
            return 0.0
        return max(0.0, time.monotonic() - start)

    def _record(
        self,
        tool: str,
        outcome: str,
        duration: float,
        telemetry: dict[str, Any] | None = None,
    ) -> None:
        tool_name = tool or "<unknown>"
        outcome_name = outcome or "success"
        entry: dict[str, Any] = {
            "tool": tool_name,
            "outcome": outcome_name,
            "duration": duration,
            "timestamp": time.time(),
        }

        # Include schema data if available
        if isinstance(telemetry, dict):
            if "action_schema" in telemetry:
                entry["action_schema"] = telemetry["action_schema"]
            if "observation_schema" in telemetry:
                entry["observation_schema"] = telemetry["observation_schema"]

        with self._recent_lock:
            self._recent_events.append(entry)
            if len(self._recent_events) > 200:
                self._recent_events = self._recent_events[-200:]

        # Prometheus metrics are optional; guard against import failures
        try:
            if self._invocations is not None:
                self._invocations.labels(tool=tool_name, outcome=outcome_name).inc()
            if self._latency is not None:
                self._latency.labels(tool=tool_name, outcome=outcome_name).observe(
                    duration
                )
        except Exception as exc:  # pragma: no cover - metrics failures shouldn't crash
            logger.debug("Skipping telemetry metric export: %s", exc)

    @staticmethod
    def _model_validate(schema_class: Any, payload: dict[str, Any]) -> Any:
        if hasattr(schema_class, "model_validate"):
            return schema_class.model_validate(payload)
        if hasattr(schema_class, "parse_obj"):
            return schema_class.parse_obj(payload)
        return schema_class(**payload)

    def _action_to_schema(self, action: Any) -> ActionSchemaUnion | None:
        """Convert an action instance to a typed schema.

        Args:
            action: Action instance to convert

        Returns:
            Action schema if conversion succeeds, None otherwise
        """
        try:
            action_dict = self.action_to_dict(action)
            act_type = self._action_type_from_dict(action_dict)
            if not act_type:
                logger.debug("Action dict missing action_type")
                return None

            schema_class = self._schema_class_for_action_type(act_type)
            if not schema_class:
                logger.debug("Unknown action type: %s", act_type)
                return None

            metadata = self._action_event_metadata(action)
            if metadata:
                action_dict["metadata"] = metadata

            return cast(
                ActionSchemaUnion, self._model_validate(schema_class, action_dict)
            )
        except Exception as exc:  # pragma: no cover - schema conversion is optional
            logger.debug("Failed to convert action to schema: %s", exc)
            return None

    @staticmethod
    def _action_type_from_dict(action_dict: dict[str, Any]) -> str | None:
        act_type = action_dict.get("action_type")
        if isinstance(act_type, str) and act_type.strip():
            return act_type
        return None

    def _schema_class_for_action_type(
        self, act_type: str
    ) -> type[ActionSchemaUnion] | None:
        schema_map = self._action_schema_map()
        return schema_map.get(act_type)

    @staticmethod
    def _action_schema_map() -> dict[str, type[ActionSchemaUnion]]:
        from backend.core.schemas.actions import (
            AgentRejectActionSchema,
            BrowseInteractiveActionSchema,
            ChangeAgentStateActionSchema,
            CmdRunActionSchema,
            FileEditActionSchema,
            FileReadActionSchema,
            FileWriteActionSchema,
            MessageActionSchema,
            NullActionSchema,
            PlaybookFinishActionSchema,
            SystemMessageActionSchema,
        )

        return {
            "read": FileReadActionSchema,
            "write": FileWriteActionSchema,
            "edit": FileEditActionSchema,
            "run": CmdRunActionSchema,
            "message": MessageActionSchema,
            "system": SystemMessageActionSchema,
            "browse_interactive": BrowseInteractiveActionSchema,
            "finish": PlaybookFinishActionSchema,
            "reject": AgentRejectActionSchema,
            "change_agent_state": ChangeAgentStateActionSchema,
            "null": NullActionSchema,
        }

    @staticmethod
    def _action_event_metadata(action: Any) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if getattr(action, "id", None):
            metadata["event_id"] = action.id
        if getattr(action, "sequence", None):
            metadata["sequence"] = action.sequence
        if getattr(action, "timestamp", None):
            metadata["timestamp"] = action.timestamp
        source = getattr(action, "source", None)
        if source:
            metadata["source"] = (
                source.value if hasattr(source, "value") else str(source)
            )
        return metadata

    def _observation_to_schema(self, observation: Any) -> ObservationSchemaUnion | None:
        """Convert an observation instance to a typed schema.

        Args:
            observation: Observation instance to convert

        Returns:
            Observation schema if conversion succeeds, None otherwise
        """
        try:
            obs_dict = self._observation_to_dict(observation)
            obs_type = self._observation_type_from_dict(obs_dict)
            if not obs_type:
                logger.debug("Observation dict missing observation_type")
                return None

            schema_class = self._schema_class_for_observation(obs_type)
            if not schema_class:
                logger.debug("Unknown observation type: %s", obs_type)
                return None

            metadata = self._observation_event_metadata(observation)
            if metadata:
                obs_dict["metadata"] = metadata

            return cast(
                ObservationSchemaUnion, self._model_validate(schema_class, obs_dict)
            )
        except Exception as exc:  # pragma: no cover - schema conversion is optional
            logger.exception("Failed to convert observation to schema: %s", exc)
            logger.debug("Observation dict: %s", locals().get("obs_dict"))
            return None

    @staticmethod
    def _observation_type_from_dict(obs_dict: dict[str, Any]) -> str | None:
        obs_type = obs_dict.get("observation_type")
        if isinstance(obs_type, str) and obs_type.strip():
            return obs_type
        return None

    def _schema_class_for_observation(
        self, obs_type: str
    ) -> type[ObservationSchemaUnion] | None:
        return self._observation_schema_map().get(obs_type)

    @staticmethod
    def _observation_schema_map() -> dict[str, type[ObservationSchemaUnion]]:
        from backend.core.schemas.observations import (
            CmdOutputObservationSchema,
            ErrorObservationSchema,
            FileEditObservationSchema,
            FileReadObservationSchema,
        )

        return {
            "run": CmdOutputObservationSchema,
            "read": FileReadObservationSchema,
            "edit": FileEditObservationSchema,
            "error": ErrorObservationSchema,
            # Reserved for future schemas, e.g., "message": MessageObservationSchema,
        }

    @staticmethod
    def _observation_event_metadata(observation: Any) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if getattr(observation, "id", None):
            metadata["event_id"] = observation.id
        if getattr(observation, "sequence", None):
            metadata["sequence"] = observation.sequence
        if getattr(observation, "timestamp", None):
            metadata["timestamp"] = observation.timestamp
        source = getattr(observation, "source", None)
        if source:
            metadata["source"] = (
                source.value if hasattr(source, "value") else str(source)
            )
        return metadata

    @staticmethod
    def action_to_dict(action: Any) -> dict[str, Any]:
        """Convert an action instance to a dictionary.

        Args:
            action: Action instance to convert

        Returns:
            Dictionary representation of the action
        """
        action_type = ToolTelemetry._action_type(action)
        action_dict: dict[str, Any] = {
            "action_type": action_type,
            "runnable": getattr(action, "runnable", False),
        }
        ToolTelemetry._append_action_fields(action_dict, action)
        ToolTelemetry._append_confirmation_and_risk(action_dict, action)
        return action_dict

    @staticmethod
    def _action_type(action: Any) -> str:
        action_type = getattr(action, "action", None)
        if not action_type:
            return type(action).__name__
        if hasattr(action_type, "value"):
            return action_type.value
        if hasattr(action_type, "__str__"):
            return str(action_type)
        return str(action_type)

    @staticmethod
    def _append_action_fields(action_dict: dict[str, Any], action: Any) -> None:
        optional_fields = [
            "path",
            "content",
            "command",
            "code",
            "message",
            "thought",
            "start",
            "end",
            "browser_actions",
            "browsergym_send_msg_to_user",
            "return_axtree",
            "url",
            "agent",
            "state",
            "blocking",
            "is_input",
            "is_static",
            "cwd",
            "hidden",
            "include_extra",
        ]
        for field in optional_fields:
            if not hasattr(action, field):
                continue
            value = getattr(action, field)
            if ToolTelemetry._should_include_field(value):
                action_dict[field] = value

    @staticmethod
    def _should_include_field(value: Any) -> bool:
        if isinstance(value, bool):
            return True
        return value not in (None, "")

    @staticmethod
    def _append_confirmation_and_risk(action_dict: dict[str, Any], action: Any) -> None:
        if hasattr(action, "confirmation_state"):
            action_dict["confirmation_state"] = str(action.confirmation_state)
        if hasattr(action, "security_risk"):
            action_dict["security_risk"] = int(action.security_risk)

    def _observation_to_dict(self, observation: Any) -> dict[str, Any]:
        """Convert an observation instance to a dictionary.

        Args:
            observation: Observation instance to convert

        Returns:
            Dictionary representation of the observation
        """
        observation_type = self._observation_type(observation)
        obs_dict = self._base_observation_payload(observation, observation_type)
        self._append_observation_fields(obs_dict, observation)
        self._append_cmd_metadata(obs_dict, observation)
        return obs_dict

    @staticmethod
    def _observation_type(observation: Any) -> str:
        observation_type = getattr(observation, "observation", None)
        if not observation_type:
            return type(observation).__name__
        try:
            return observation_type.value  # type: ignore[attr-defined]
        except AttributeError:
            return str(observation_type)

    @staticmethod
    def _base_observation_payload(
        observation: Any, observation_type: str
    ) -> dict[str, Any]:
        return {
            "observation_type": observation_type,
            "content": getattr(observation, "content", ""),
        }

    def _append_observation_fields(
        self, obs_dict: dict[str, Any], observation: Any
    ) -> None:
        optional_fields = [
            "command",
            "code",
            "path",
            "error_id",
            "image_urls",
            "hidden",
        ]
        for field in optional_fields:
            if not hasattr(observation, field):
                continue
            value = getattr(observation, field)
            if isinstance(value, bool) or (value not in (None, "")):
                obs_dict[field] = value

    def _append_cmd_metadata(self, obs_dict: dict[str, Any], observation: Any) -> None:
        if not hasattr(observation, "metadata"):
            return
        metadata = getattr(observation, "metadata")
        meta_dict = self._safe_metadata_to_dict(metadata)
        if meta_dict is not None:
            obs_dict["cmd_metadata"] = meta_dict

    def _safe_metadata_to_dict(self, metadata: Any) -> Any:
        try:
            return self._metadata_to_dict(metadata)
        except Exception as exc:
            logger.debug("Failed to convert metadata to dict: %s", exc)
            return self._fallback_metadata_conversion(metadata)

    @staticmethod
    def _metadata_to_dict(metadata: Any) -> Any:
        if metadata is None:
            return None
        if hasattr(metadata, "model_dump"):
            return metadata.model_dump()
        if hasattr(metadata, "__dict__"):
            return {k: v for k, v in metadata.__dict__.items() if not k.startswith("_")}
        if isinstance(metadata, dict):
            return metadata
        if hasattr(metadata, "model_fields"):
            return {
                field: getattr(metadata, field, None)
                for field in metadata.model_fields.keys()
            }
        return metadata

    @staticmethod
    def _fallback_metadata_conversion(metadata: Any) -> Any:
        try:
            if hasattr(metadata, "__iter__"):
                return dict(metadata)
        except Exception:
            pass
        return str(metadata)
