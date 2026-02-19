"""Tests for backend.core.provider_types — provider models and enums."""

import pytest
from pydantic import SecretStr

from backend.core.provider_types import (
    AuthenticationError,
    CreatePlaybook,
    CustomSecret,
    ProviderToken,
    ProviderType,
    SuggestedTask,
    TaskType,
)


class TestProviderType:
    """Tests for ProviderType enum."""

    def test_enterprise_sso_variant(self):
        """Test ENTERPRISE_SSO variant exists."""
        assert ProviderType.ENTERPRISE_SSO.value == "enterprise_sso"

    def test_enum_members(self):
        """Test enum has expected members."""
        members = list(ProviderType)
        assert members
        assert ProviderType.ENTERPRISE_SSO in members


class TestTaskType:
    """Tests for TaskType enum."""

    def test_task_type_variants(self):
        """Test TaskType enum has expected variants."""
        assert TaskType.MERGE_CONFLICTS.value == "MERGE_CONFLICTS"
        assert TaskType.FAILING_CHECKS.value == "FAILING_CHECKS"
        assert TaskType.UNRESOLVED_COMMENTS.value == "UNRESOLVED_COMMENTS"
        assert TaskType.OPEN_ISSUE.value == "OPEN_ISSUE"
        assert TaskType.OPEN_PR.value == "OPEN_PR"
        assert TaskType.CREATE_PLAYBOOK.value == "CREATE_PLAYBOOK"

    def test_task_type_is_str_enum(self):
        """Test TaskType inherits from str."""
        assert isinstance(TaskType.OPEN_ISSUE, str)


class TestProviderToken:
    """Tests for ProviderToken model."""

    def test_create_provider_token(self):
        """Test creating ProviderToken."""
        token = ProviderToken(
            token=SecretStr("secret123"), user_id="user1", host="github.com"
        )
        assert token.user_id == "user1"
        assert token.host == "github.com"
        assert token.token.get_secret_value() == "secret123"

    def test_create_with_none_values(self):
        """Test creating ProviderToken with None values."""
        token = ProviderToken()
        assert token.token is None
        assert token.user_id is None
        assert token.host is None

    def test_frozen_model(self):
        """Test ProviderToken is frozen."""
        token = ProviderToken(user_id="user1")
        with pytest.raises(Exception):  # Pydantic ValidationError
            token.user_id = "user2"  # type: ignore

    def test_from_value_with_existing_instance(self):
        """Test from_value with existing ProviderToken."""
        original = ProviderToken(user_id="user1")
        result = ProviderToken.from_value(original)
        assert result is original

    def test_from_value_with_dict(self):
        """Test from_value with dictionary."""
        token_dict = {
            "token": "secret123",
            "user_id": "user1",
            "host": "github.com",
        }
        result = ProviderToken.from_value(token_dict)
        assert result.user_id == "user1"
        assert result.host == "github.com"
        assert result.token.get_secret_value() == "secret123"

    def test_from_value_with_empty_dict(self):
        """Test from_value with empty dictionary."""
        result = ProviderToken.from_value({})
        assert result.token.get_secret_value() == ""
        assert result.user_id is None

    def test_from_value_with_invalid_type_raises(self):
        """Test from_value with invalid type raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported Provider token type"):
            ProviderToken.from_value("invalid")

    def test_validate_empty_user_id_raises(self):
        """Test empty user_id raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            ProviderToken(user_id="")

    def test_validate_empty_host_raises(self):
        """Test empty host raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            ProviderToken(host="")


class TestCustomSecret:
    """Tests for CustomSecret model."""

    def test_create_custom_secret(self):
        """Test creating CustomSecret."""
        secret = CustomSecret(
            secret=SecretStr("my_secret"), description="API key for service"
        )
        assert secret.secret.get_secret_value() == "my_secret"
        assert secret.description == "API key for service"

    def test_create_with_defaults(self):
        """Test creating CustomSecret with defaults."""
        secret = CustomSecret()
        assert secret.secret.get_secret_value() == ""
        assert secret.description == ""

    def test_frozen_model(self):
        """Test CustomSecret is frozen."""
        secret = CustomSecret(description="Test")
        with pytest.raises(Exception):  # Pydantic ValidationError
            secret.description = "Modified"  # type: ignore

    def test_from_value_with_existing_instance(self):
        """Test from_value with existing CustomSecret."""
        original = CustomSecret(description="test")
        result = CustomSecret.from_value(original)
        assert result is original

    def test_from_value_with_dict(self):
        """Test from_value with dictionary."""
        secret_dict = {"secret": "my_secret", "description": "Test secret"}
        result = CustomSecret.from_value(secret_dict)
        assert result.secret.get_secret_value() == "my_secret"
        assert result.description == "Test secret"

    def test_from_value_with_empty_dict(self):
        """Test from_value with empty dictionary."""
        result = CustomSecret.from_value({})
        assert result.secret.get_secret_value() == ""
        assert result.description == ""

    def test_from_value_with_invalid_type_raises(self):
        """Test from_value with invalid type raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported Provider token type"):
            CustomSecret.from_value(123)


class TestSuggestedTask:
    """Tests for SuggestedTask model."""

    def test_create_suggested_task(self):
        """Test creating SuggestedTask."""
        task = SuggestedTask(
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            task_type=TaskType.OPEN_ISSUE,
            repo="owner/repo",
            issue_number=42,
            title="Fix bug",
        )
        assert task.vcs_provider == ProviderType.ENTERPRISE_SSO
        assert task.task_type == TaskType.OPEN_ISSUE
        assert task.repo == "owner/repo"
        assert task.issue_number == 42
        assert task.title == "Fix bug"

    def test_get_prompt_for_task(self):
        """Test get_prompt_for_task generates prompt."""
        task = SuggestedTask(
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            task_type=TaskType.MERGE_CONFLICTS,
            repo="owner/repo",
            issue_number=10,
            title="Resolve conflicts",
        )
        prompt = task.get_prompt_for_task()
        assert "MERGE_CONFLICTS" in prompt
        assert "Resolve conflicts" in prompt
        assert "#10" in prompt
        assert "owner/repo" in prompt

    def test_validate_empty_repo_raises(self):
        """Test empty repo raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            SuggestedTask(
                vcs_provider=ProviderType.ENTERPRISE_SSO,
                task_type=TaskType.OPEN_ISSUE,
                repo="",
                issue_number=1,
                title="Test",
            )

    def test_validate_empty_title_raises(self):
        """Test empty title raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            SuggestedTask(
                vcs_provider=ProviderType.ENTERPRISE_SSO,
                task_type=TaskType.OPEN_ISSUE,
                repo="owner/repo",
                issue_number=1,
                title="",
            )

    def test_validate_zero_issue_number_raises(self):
        """Test zero issue number raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            SuggestedTask(
                vcs_provider=ProviderType.ENTERPRISE_SSO,
                task_type=TaskType.OPEN_ISSUE,
                repo="owner/repo",
                issue_number=0,
                title="Test",
            )

    def test_validate_negative_issue_number_raises(self):
        """Test negative issue number raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            SuggestedTask(
                vcs_provider=ProviderType.ENTERPRISE_SSO,
                task_type=TaskType.OPEN_ISSUE,
                repo="owner/repo",
                issue_number=-1,
                title="Test",
            )


class TestCreatePlaybook:
    """Tests for CreatePlaybook model."""

    def test_create_playbook(self):
        """Test creating CreatePlaybook."""
        playbook = CreatePlaybook(repo="owner/repo")
        assert playbook.repo == "owner/repo"
        assert playbook.vcs_provider is None
        assert playbook.title is None

    def test_create_with_all_fields(self):
        """Test creating with all fields."""
        playbook = CreatePlaybook(
            repo="owner/repo",
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            title="My Playbook",
        )
        assert playbook.repo == "owner/repo"
        assert playbook.vcs_provider == ProviderType.ENTERPRISE_SSO
        assert playbook.title == "My Playbook"

    def test_validate_empty_repo_raises(self):
        """Test empty repo raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            CreatePlaybook(repo="")

    def test_validate_empty_title_raises(self):
        """Test empty title raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError
            CreatePlaybook(repo="owner/repo", title="")

    def test_title_none_is_valid(self):
        """Test title can be None."""
        playbook = CreatePlaybook(repo="owner/repo", title=None)
        assert playbook.title is None


class TestAuthenticationError:
    """Tests for AuthenticationError exception."""

    def test_create_error(self):
        """Test creating AuthenticationError."""
        error = AuthenticationError("Auth failed")
        assert str(error) == "Auth failed"

    def test_inherits_value_error(self):
        """Test AuthenticationError inherits ValueError."""
        error = AuthenticationError("Test")
        assert isinstance(error, ValueError)

    def test_can_be_raised(self):
        """Test error can be raised and caught."""
        with pytest.raises(AuthenticationError):
            raise AuthenticationError("Invalid credentials")

    def test_can_be_caught_as_value_error(self):
        """Test can catch as ValueError."""
        with pytest.raises(ValueError):
            raise AuthenticationError("Test")
