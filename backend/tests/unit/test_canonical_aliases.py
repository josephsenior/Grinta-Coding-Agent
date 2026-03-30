"""Tests for the remaining canonical vocabulary compatibility aliases."""

from backend.core.config import TranscriptConfig, TrajectoryConfig
from backend.core.rollback import Checkpoint, Snapshot
from backend.gateway.session import Run, Session
from backend.ledger import Event, EventStore, EventStream, Ledger, LedgerStore, Outcome, Record
from backend.ledger import Observation
from backend.ledger.action import Action, Operation
from backend.ledger.observation import Outcome as ObservationOutcome
from backend.ledger.observation import Observation as ObservationBase
from backend.orchestration.services import ExecutionPolicyService, OpenOperationService
from backend.orchestration.services.autonomy_service import AutonomyService
from backend.orchestration.services.pending_action_service import PendingActionService
from backend.orchestration.tool_pipeline import OperationPipeline, ToolInvocationPipeline
from backend.orchestration.state.state import RunState, State


def test_record_alias_points_to_event() -> None:
    assert Record is Event


def test_operation_alias_points_to_action() -> None:
    assert Operation is Action


def test_outcome_alias_points_to_observation() -> None:
    assert Outcome is Observation
    assert ObservationOutcome is ObservationBase


def test_ledger_aliases_point_to_existing_types() -> None:
    assert Ledger is EventStream
    assert LedgerStore is EventStore


def test_run_alias_points_to_session() -> None:
    assert Run is Session


def test_snapshot_alias_points_to_checkpoint() -> None:
    assert Snapshot is Checkpoint


def test_run_state_alias_points_to_state() -> None:
    assert RunState is State


def test_open_operation_service_alias_points_to_pending_action_service() -> None:
    assert OpenOperationService is PendingActionService


def test_execution_policy_service_alias_points_to_autonomy_service() -> None:
    assert ExecutionPolicyService is AutonomyService


def test_operation_pipeline_alias_points_to_tool_invocation_pipeline() -> None:
    assert OperationPipeline is ToolInvocationPipeline


def test_transcript_config_alias_points_to_trajectory_config() -> None:
    assert TranscriptConfig is TrajectoryConfig