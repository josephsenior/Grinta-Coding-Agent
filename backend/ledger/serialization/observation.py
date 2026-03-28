"""Serialization helpers for converting observations to and from dictionaries."""

from __future__ import annotations

import copy
import importlib
from typing import Any

from backend.core.enums import RecallType
from backend.ledger.observation.agent import (
    AgentCondensationObservation,
    AgentStateChangedObservation,
    AgentThinkObservation,
    PlaybookKnowledge,
    RecallFailureObservation,
    RecallObservation,
)
from backend.ledger.observation.commands import (
    CmdOutputMetadata,
    CmdOutputObservation,
)
from backend.ledger.observation.code_nav import LspQueryObservation
from backend.ledger.observation.empty import NullObservation
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.file_download import FileDownloadObservation
from backend.ledger.observation.files import (
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
)
from backend.ledger.observation.mcp import MCPObservation
from backend.ledger.observation.observation import Observation
from backend.ledger.observation.reject import UserRejectObservation
from backend.ledger.observation.status import StatusObservation
from backend.ledger.observation.success import SuccessObservation
from backend.ledger.observation.task_tracking import TaskTrackingObservation

observations = (
    NullObservation,
    CmdOutputObservation,
    FileReadObservation,
    FileWriteObservation,
    FileEditObservation,
    SuccessObservation,
    ErrorObservation,
    AgentStateChangedObservation,
    UserRejectObservation,
    AgentCondensationObservation,
    AgentThinkObservation,
    RecallObservation,
    RecallFailureObservation,
    MCPObservation,
    FileDownloadObservation,
    TaskTrackingObservation,
    StatusObservation,
    LspQueryObservation,
)


def _observation_key_for_class(observation_class: type[Observation]) -> str:
    key = getattr(observation_class, "observation", "")
    if not key:
        key = getattr(observation_class, "observation_type", "")
    return key


_OBSERVATION_CLASS_PATHS = {
    _observation_key_for_class(observation_class): (
        observation_class.__module__,
        observation_class.__name__,
    )
    for observation_class in observations
}


def _update_cmd_output_metadata(
    metadata: dict[str, Any] | CmdOutputMetadata | None,
    **kwargs: Any,
) -> dict[str, Any] | CmdOutputMetadata:
    """Update the metadata of a CmdOutputObservation.

    If metadata is None, create a new CmdOutputMetadata instance.
    If metadata is a dict, update the dict.
    If metadata is a CmdOutputMetadata instance, update the instance.
    """
    if metadata is None:
        return CmdOutputMetadata(**kwargs)
    if isinstance(metadata, dict):
        metadata.update(**kwargs)
    elif isinstance(metadata, CmdOutputMetadata):
        for key, value in kwargs.items():
            setattr(metadata, key, value)
    return metadata


def _validate_observation_dict(observation: dict) -> None:
    """Validate that observation dict has required keys."""
    if "observation" not in observation:
        msg = f"'observation' key is not found in observation={observation!r}"
        raise KeyError(msg)


def _get_observation_class(observation_type: str):
    """Get observation class from observation type."""
    class_info = _OBSERVATION_CLASS_PATHS.get(observation_type)
    if class_info is None:
        msg = (
            f"'observation['observation']={observation_type!r}' is not defined. "
            f"Available observations: {_OBSERVATION_CLASS_PATHS.keys()}"
        )
        raise KeyError(msg)
    module_name, class_name = class_info
    module = importlib.import_module(module_name)
    observation_class = getattr(module, class_name, None)
    if observation_class is None:
        msg = (
            f"Observation class '{class_name}' not found in module '{module_name}'. "
            f"Available observations: {_OBSERVATION_CLASS_PATHS.keys()}"
        )
        raise KeyError(msg)
    return observation_class


from backend.ledger.serialization.common import (  # noqa: E402
    COMMON_METADATA_FIELDS as METADATA_FIELDS,
)


def _extract_observation_data(observation: dict) -> tuple[str, dict, dict]:
    """Extract content, extras, and metadata from observation dict."""
    observation.pop("observation")
    observation.pop("message", None)
    observation.pop("success", None)
    observation.pop("error", None)
    content = observation.pop("content", "")
    extras = copy.deepcopy(observation.pop("extras", {}))

    metadata: dict = {}
    for field in METADATA_FIELDS:
        if field in observation:
            metadata[field] = observation.pop(field)
        if field in extras and field not in metadata:
            metadata[field] = extras.pop(field)
        else:
            extras.pop(field, None)

    # Remove transient runtime-only fields that are set as attributes after
    # construction and must not be passed back to __init__ on deserialization.
    observation.pop("tool_result", None)

    # Remaining keys (e.g., command, metadata) should be treated as extras/kwargs
    if observation:
        extras.update(observation)
    return content, extras, metadata


def _process_cmd_output_metadata(extras: dict) -> None:
    """Process CmdOutputObservation metadata."""
    if "metadata" in extras and isinstance(extras["metadata"], dict):
        extras["metadata"] = CmdOutputMetadata(**extras["metadata"])
    elif "metadata" not in extras or not isinstance(
        extras["metadata"], CmdOutputMetadata
    ):
        extras["metadata"] = CmdOutputMetadata()


def _process_recall_observation_data(extras: dict) -> None:
    """Process RecallObservation specific data."""
    if "recall_type" in extras:
        extras["recall_type"] = RecallType(extras["recall_type"])
    if "playbook_knowledge" in extras and isinstance(
        extras["playbook_knowledge"], list
    ):
        extras["playbook_knowledge"] = [
            PlaybookKnowledge(**item) if isinstance(item, dict) else item
            for item in extras["playbook_knowledge"]
        ]


def observation_from_dict(observation: dict) -> Observation:
    """Deserialize observation from dictionary representation.

    Converts dictionary to Observation instance, handling special cases for
    CmdOutputObservation and RecallObservation types.

    Args:
        observation: Dictionary with observation type and data

    Returns:
        Deserialized Observation instance

    Raises:
        KeyError: If observation dict is invalid

    """
    observation = observation.copy()
    _validate_observation_dict(observation)
    observation_class = _get_observation_class(observation["observation"])
    content, extras, metadata = _extract_observation_data(observation)

    if observation_class.__name__ == "CmdOutputObservation":
        _process_cmd_output_metadata(extras)
    if observation_class.__name__ == "RecallObservation":
        _process_recall_observation_data(extras)

    obs = observation_class(content=content, **extras)
    for attr, value in metadata.items():
        setattr(obs, attr, value)
    return obs
