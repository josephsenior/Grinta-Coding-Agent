"""Tests for backend.core.enums — all core enumeration types."""

from __future__ import annotations

from backend.core.enums import (
    ActionConfirmationStatus,
    ActionSecurityRisk,
    ActionType,
    AgentState,
    AppMode,
    CircuitState,
    ContentType,
    ErrorCategory,
    ErrorSeverity,
    EventSource,
    EventVersion,
    ExitReason,
    FileEditSource,
    FileReadSource,
    LifecyclePhase,
    ObservationType,
    QuotaPlan,
    RecallType,
    RetryStrategy,
    RuntimeStatus,
)


class TestQuotaPlan:
    def test_values(self):
        assert QuotaPlan.UNLIMITED.value == "unlimited"

    def test_count(self):
        assert len(QuotaPlan) == 1

    def test_str_subclass(self):
        assert isinstance(QuotaPlan.UNLIMITED, str)
        assert QuotaPlan.UNLIMITED == "unlimited"

    def test_no_plan_tiers(self):
        """Plan tiers removed — local-first single-user app has no billing tiers."""
        assert not hasattr(QuotaPlan, "FREE")
        assert not hasattr(QuotaPlan, "PRO")
        assert not hasattr(QuotaPlan, "ENTERPRISE")


class TestCircuitState:
    def test_values(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_count(self):
        assert len(CircuitState) == 3


class TestErrorSeverity:
    def test_values(self):
        assert ErrorSeverity.INFO.value == "info"
        assert ErrorSeverity.WARNING.value == "warning"
        assert ErrorSeverity.ERROR.value == "error"
        assert ErrorSeverity.CRITICAL.value == "critical"

    def test_count(self):
        assert len(ErrorSeverity) == 4


class TestErrorCategory:
    def test_values(self):
        expected = {
            "user_input",
            "system",
            "rate_limit",
            "authentication",
            "network",
            "ai_model",
            "configuration",
        }
        actual = {c.value for c in ErrorCategory}
        assert actual == expected

    def test_count(self):
        assert len(ErrorCategory) == 7


class TestContentType:
    def test_values(self):
        assert ContentType.TEXT.value == "text"
        assert ContentType.IMAGE_URL.value == "image_url"


class TestActionType:
    def test_has_all_core_actions(self):
        for name in (
            "MESSAGE",
            "SYSTEM",
            "START",
            "READ",
            "WRITE",
            "EDIT",
            "RUN",
            "BROWSE",
            "THINK",
            "FINISH",
            "REJECT",
            "NULL",
            "PAUSE",
            "RESUME",
            "STOP",
            "PUSH",
            "RECALL",
        ):
            assert hasattr(ActionType, name)

    def test_message_value(self):
        assert ActionType.MESSAGE.value == "message"

    def test_finish_value(self):
        assert ActionType.FINISH.value == "finish"


class TestLifecyclePhase:
    def test_lifecycle_order(self):
        phases = [
            LifecyclePhase.INITIALIZING,
            LifecyclePhase.ACTIVE,
            LifecyclePhase.CLOSING,
            LifecyclePhase.CLOSED,
        ]
        assert len(phases) == len(LifecyclePhase)

    def test_values(self):
        assert LifecyclePhase.INITIALIZING.value == "initializing"
        assert LifecyclePhase.CLOSED.value == "closed"


class TestAgentState:
    def test_no_init_state(self):
        """AgentState does not have an INIT value."""
        assert not hasattr(AgentState, "INIT")

    def test_core_states(self):
        assert AgentState.LOADING.value == "loading"
        assert AgentState.RUNNING.value == "running"
        assert AgentState.FINISHED.value == "finished"
        assert AgentState.ERROR.value == "error"
        assert AgentState.STOPPED.value == "stopped"
        assert AgentState.PAUSED.value == "paused"

    def test_count(self):
        assert len(AgentState) == 12


class TestObservationType:
    def test_has_key_values(self):
        assert ObservationType.READ.value == "read"
        assert ObservationType.WRITE.value == "write"
        assert ObservationType.RUN.value == "run"
        assert ObservationType.ERROR.value == "error"
        assert ObservationType.MCP.value == "mcp"

    def test_count(self):
        assert len(ObservationType) == 25


class TestExitReason:
    def test_values(self):
        assert ExitReason.INTENTIONAL.value == "intentional"
        assert ExitReason.INTERRUPTED.value == "interrupted"
        assert ExitReason.ERROR.value == "error"

    def test_count(self):
        assert len(ExitReason) == 3


class TestActionConfirmationStatus:
    def test_values(self):
        assert ActionConfirmationStatus.CONFIRMED.value == "confirmed"
        assert ActionConfirmationStatus.REJECTED.value == "rejected"
        assert (
            ActionConfirmationStatus.AWAITING_CONFIRMATION.value
            == "awaiting_confirmation"
        )


class TestActionSecurityRisk:
    def test_int_subclass(self):
        assert isinstance(ActionSecurityRisk.LOW, int)

    def test_values(self):
        assert ActionSecurityRisk.UNKNOWN.value == -1
        assert ActionSecurityRisk.LOW.value == 0
        assert ActionSecurityRisk.MEDIUM.value == 1
        assert ActionSecurityRisk.HIGH.value == 2

    def test_ordering(self):
        assert (
            ActionSecurityRisk.LOW < ActionSecurityRisk.MEDIUM < ActionSecurityRisk.HIGH
        )

    def test_dynamic_access(self):
        first = list(ActionSecurityRisk)[0]
        assert first.value == -1


class TestAppMode:
    def test_values(self):
        assert AppMode.OSS.value == "oss"
        assert AppMode.SAAS.value == "saas"


class TestEventVersion:
    def test_values(self):
        assert EventVersion.V1.value == "1.0.0"
        assert EventVersion.V2.value == "2.0.0"


class TestEventSource:
    def test_values(self):
        assert EventSource.AGENT.value == "agent"
        assert EventSource.USER.value == "user"
        assert EventSource.ENVIRONMENT.value == "environment"


class TestFileEditSource:
    def test_values(self):
        assert FileEditSource.LLM_BASED_EDIT.value == "llm_based_edit"
        assert FileEditSource.FILE_EDITOR.value == "file_editor"


class TestFileReadSource:
    def test_values(self):
        assert FileReadSource.FILE_EDITOR.value == "file_editor"
        assert FileReadSource.DEFAULT.value == "default"


class TestRecallType:
    def test_values(self):
        assert RecallType.WORKSPACE_CONTEXT.value == "workspace_context"
        assert RecallType.KNOWLEDGE.value == "knowledge"


class TestRetryStrategy:
    def test_values(self):
        assert RetryStrategy.EXPONENTIAL.value == "exponential"
        assert RetryStrategy.LINEAR.value == "linear"
        assert RetryStrategy.FIXED.value == "fixed"
        assert RetryStrategy.IMMEDIATE.value == "immediate"


class TestRuntimeStatus:
    def test_ready(self):
        assert RuntimeStatus.READY.value == "STATUS$READY"

    def test_error(self):
        assert RuntimeStatus.ERROR.value == "STATUS$ERROR"

    def test_stopped(self):
        assert RuntimeStatus.STOPPED.value == "STATUS$STOPPED"

    def test_unknown(self):
        assert RuntimeStatus.UNKNOWN.value == "UNKNOWN"

    def test_is_str(self):
        assert isinstance(RuntimeStatus.READY, str)

    def test_has_error_variants(self):
        error_statuses = [s for s in RuntimeStatus if "ERROR" in s.value]
        assert len(error_statuses) >= 5
