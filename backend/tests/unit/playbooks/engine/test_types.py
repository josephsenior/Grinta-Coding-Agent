"""Tests for backend.playbooks.engine.types — playbook metadata models."""

from datetime import datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError

from backend.playbooks.engine.types import (
    InputMetadata,
    PlaybookContentResponse,
    PlaybookMetadata,
    PlaybookResponse,
    PlaybookType,
)


class TestPlaybookType:
    """Tests for PlaybookType enum."""

    def test_knowledge_type(self):
        """Test KNOWLEDGE playbook type."""
        assert PlaybookType.KNOWLEDGE == "knowledge"

    def test_repo_knowledge_type(self):
        """Test REPO_KNOWLEDGE playbook type."""
        assert PlaybookType.REPO_KNOWLEDGE == "repo"

    def test_task_type(self):
        """Test TASK playbook type."""
        assert PlaybookType.TASK == "task"

    def test_all_enum_values(self):
        """Test all enum values are accessible."""
        types = list(PlaybookType)
        assert len(types) == 3
        assert PlaybookType.KNOWLEDGE in types
        assert PlaybookType.REPO_KNOWLEDGE in types
        assert PlaybookType.TASK in types

    def test_enum_value_equality(self):
        """Test enum value equality with strings."""
        assert PlaybookType.KNOWLEDGE.value == "knowledge"
        assert PlaybookType.REPO_KNOWLEDGE.value == "repo"
        assert PlaybookType.TASK.value == "task"


class TestInputMetadata:
    """Tests for InputMetadata model."""

    def test_create_basic_input(self):
        """Test creating basic input metadata."""
        input_meta = InputMetadata(
            name="workspace_path", description="Path to workspace"
        )
        assert input_meta.name == "workspace_path"
        assert input_meta.description == "Path to workspace"

    def test_name_required(self):
        """Test name is required."""
        with pytest.raises(ValidationError):
            cast(Any, InputMetadata)(description="Test description")

    def test_description_required(self):
        """Test description is required."""
        with pytest.raises(ValidationError):
            cast(Any, InputMetadata)(name="test_name")

    def test_empty_name_allowed(self):
        """Test empty name is allowed."""
        input_meta = InputMetadata(name="", description="desc")
        assert input_meta.name == ""

    def test_empty_description_allowed(self):
        """Test empty description is allowed."""
        input_meta = InputMetadata(name="name", description="")
        assert input_meta.description == ""

    def test_unicode_in_fields(self):
        """Test unicode characters in fields."""
        input_meta = InputMetadata(name="路径", description="工作区路径 🚀")
        assert input_meta.name == "路径"
        assert "🚀" in input_meta.description


class TestPlaybookMetadata:
    """Tests for PlaybookMetadata model."""

    def test_create_minimal_metadata(self):
        """Test creating metadata with defaults."""
        metadata = PlaybookMetadata()
        assert metadata.name == "default"
        assert metadata.type == PlaybookType.REPO_KNOWLEDGE
        assert metadata.version == "1.0.0"
        assert metadata.agent == "Orchestrator"
        assert metadata.triggers == []
        assert metadata.inputs == []
        assert metadata.mcp_tools is None

    def test_create_full_metadata(self):
        """Test creating metadata with all fields."""
        inputs = [
            InputMetadata(name="input1", description="First input"),
            InputMetadata(name="input2", description="Second input"),
        ]
        metadata = PlaybookMetadata(
            name="test_playbook",
            type=PlaybookType.TASK,
            version="2.0.0",
            agent="CustomAgent",
            triggers=["trigger1", "trigger2"],
            inputs=inputs,
        )
        assert metadata.name == "test_playbook"
        assert metadata.type == PlaybookType.TASK
        assert metadata.version == "2.0.0"
        assert metadata.agent == "CustomAgent"
        assert len(metadata.triggers) == 2
        assert len(metadata.inputs) == 2

    def test_type_defaults_to_repo_knowledge(self):
        """Test type defaults to REPO_KNOWLEDGE."""
        metadata = PlaybookMetadata(name="test")
        assert metadata.type == PlaybookType.REPO_KNOWLEDGE

    def test_empty_triggers_list(self):
        """Test triggers defaults to empty list."""
        metadata = PlaybookMetadata()
        assert metadata.triggers == []
        assert isinstance(metadata.triggers, list)

    def test_empty_inputs_list(self):
        """Test inputs defaults to empty list."""
        metadata = PlaybookMetadata()
        assert metadata.inputs == []
        assert isinstance(metadata.inputs, list)

    def test_set_knowledge_type(self):
        """Test setting type to KNOWLEDGE."""
        metadata = PlaybookMetadata(type=PlaybookType.KNOWLEDGE)
        assert metadata.type == PlaybookType.KNOWLEDGE

    def test_set_task_type(self):
        """Test setting type to TASK."""
        metadata = PlaybookMetadata(type=PlaybookType.TASK)
        assert metadata.type == PlaybookType.TASK

    def test_multiple_inputs(self):
        """Test metadata with multiple inputs."""
        inputs = [
            InputMetadata(name=f"input{i}", description=f"Input {i}") for i in range(5)
        ]
        metadata = PlaybookMetadata(inputs=inputs)
        assert len(metadata.inputs) == 5

    def test_multiple_triggers(self):
        """Test metadata with multiple triggers."""
        triggers = ["trigger1", "trigger2", "trigger3"]
        metadata = PlaybookMetadata(triggers=triggers)
        assert metadata.triggers == triggers

    def test_custom_agent_name(self):
        """Test custom agent name."""
        metadata = PlaybookMetadata(agent="MyCustomAgent")
        assert metadata.agent == "MyCustomAgent"

    def test_custom_version(self):
        """Test custom version string."""
        metadata = PlaybookMetadata(version="3.2.1-beta")
        assert metadata.version == "3.2.1-beta"


class TestPlaybookResponse:
    """Tests for PlaybookResponse model."""

    def test_create_basic_response(self):
        """Test creating basic playbook response."""
        created = datetime(2024, 1, 1, 12, 0, 0)
        response = PlaybookResponse(
            name="test_playbook", path="/path/to/playbook.md", created_at=created
        )
        assert response.name == "test_playbook"
        assert response.path == "/path/to/playbook.md"
        assert response.created_at == created

    def test_name_required(self):
        """Test name is required."""
        with pytest.raises(ValidationError):
            cast(Any, PlaybookResponse)(path="/path", created_at=datetime.now())

    def test_path_required(self):
        """Test path is required."""
        with pytest.raises(ValidationError):
            cast(Any, PlaybookResponse)(name="test", created_at=datetime.now())

    def test_created_at_required(self):
        """Test created_at is required."""
        with pytest.raises(ValidationError):
            cast(Any, PlaybookResponse)(name="test", path="/path")

    def test_datetime_object(self):
        """Test created_at is a datetime object."""
        created = datetime.now()
        response = PlaybookResponse(name="test", path="/path", created_at=created)
        assert isinstance(response.created_at, datetime)

    def test_path_with_spaces(self):
        """Test path with spaces."""
        response = PlaybookResponse(
            name="test", path="/path/with spaces/playbook.md", created_at=datetime.now()
        )
        assert " " in response.path

    def test_name_with_special_chars(self):
        """Test name with special characters."""
        response = PlaybookResponse(
            name="test-playbook_v2", path="/path", created_at=datetime.now()
        )
        assert response.name == "test-playbook_v2"


class TestPlaybookContentResponse:
    """Tests for PlaybookContentResponse model."""

    def test_create_minimal_content_response(self):
        """Test creating content response with minimal fields."""
        response = PlaybookContentResponse(
            content="# Playbook\n\nContent here", path="/path/to/playbook.md"
        )
        assert response.content == "# Playbook\n\nContent here"
        assert response.path == "/path/to/playbook.md"
        assert response.triggers == []
        assert response.vcs_provider is None

    def test_create_full_content_response(self):
        """Test creating content response with all fields."""
        response = PlaybookContentResponse(
            content="# Full Playbook",
            path="/path/playbook.md",
            triggers=["on_push", "on_pr"],
            vcs_provider="github",
        )
        assert response.content == "# Full Playbook"
        assert response.path == "/path/playbook.md"
        assert response.triggers == ["on_push", "on_pr"]
        assert response.vcs_provider == "github"

    def test_content_required(self):
        """Test content is required."""
        with pytest.raises(ValidationError):
            cast(Any, PlaybookContentResponse)(path="/path")

    def test_path_required(self):
        """Test path is required."""
        with pytest.raises(ValidationError):
            cast(Any, PlaybookContentResponse)(content="content")

    def test_empty_content_allowed(self):
        """Test empty content is allowed."""
        response = PlaybookContentResponse(content="", path="/path")
        assert response.content == ""

    def test_triggers_defaults_to_empty_list(self):
        """Test triggers defaults to empty list."""
        response = PlaybookContentResponse(content="content", path="/path")
        assert response.triggers == []
        assert isinstance(response.triggers, list)

    def test_vcs_provider_defaults_to_none(self):
        """Test vcs_provider defaults to None."""
        response = PlaybookContentResponse(content="content", path="/path")
        assert response.vcs_provider is None

    def test_multiple_triggers(self):
        """Test content response with multiple triggers."""
        triggers = ["trigger1", "trigger2", "trigger3"]
        response = PlaybookContentResponse(
            content="content", path="/path", triggers=triggers
        )
        assert response.triggers == triggers

    def test_vcs_provider_github(self):
        """Test vcs_provider set to github."""
        response = PlaybookContentResponse(
            content="content", path="/path", vcs_provider="github"
        )
        assert response.vcs_provider == "github"

    def test_vcs_provider_gitlab(self):
        """Test vcs_provider set to gitlab."""
        response = PlaybookContentResponse(
            content="content", path="/path", vcs_provider="gitlab"
        )
        assert response.vcs_provider == "gitlab"

    def test_long_content(self):
        """Test content response with long content."""
        long_content = "# Playbook\n" + ("Line\n" * 1000)
        response = PlaybookContentResponse(content=long_content, path="/path")
        assert len(response.content) > 5000

    def test_content_with_markdown(self):
        """Test content with markdown formatting."""
        markdown = """# Playbook Title

## Section 1

- Item 1
- Item 2

```python
def example():
    pass
```

## Section 2

Some text here.
"""
        response = PlaybookContentResponse(content=markdown, path="/path")
        assert "```python" in response.content
        assert "# Playbook Title" in response.content

    def test_empty_triggers_list(self):
        """Test explicitly setting empty triggers list."""
        response = PlaybookContentResponse(content="content", path="/path", triggers=[])
        assert response.triggers == []

    def test_none_vcs_provider_explicit(self):
        """Test explicitly setting vcs_provider to None."""
        response = PlaybookContentResponse(
            content="content", path="/path", vcs_provider=None
        )
        assert response.vcs_provider is None
