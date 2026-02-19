"""Tests for backend.server.services.session_init_service.

Covers all pure/near-pure functions:
  - extract_request_data
  - determine_conversation_trigger
  - validate_remote_api_request
  - apply_conversation_overrides
  - normalize_provider_tokens
  - prepare_conversation_params
  - handle_conversation_errors
  - resolve_conversation_id
"""

from __future__ import annotations

import os
import re
from types import MappingProxyType
from unittest.mock import MagicMock

import pytest
from fastapi.responses import JSONResponse

from backend.core.provider_types import (
    CreatePlaybook,
    ProviderType,
    SuggestedTask,
    TaskType,
)
from backend.server.services.session_init_service import (
    apply_conversation_overrides,
    determine_conversation_trigger,
    extract_request_data,
    handle_conversation_errors,
    normalize_provider_tokens,
    prepare_conversation_params,
    resolve_conversation_id,
    validate_remote_api_request,
)
from backend.server.types import LLMAuthenticationError, MissingSettingsError
from backend.server.user_auth import AuthType
from backend.storage.data_models.conversation_metadata import ConversationTrigger
from backend.storage.data_models.user_secrets import UserSecrets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_init_request(**kwargs) -> MagicMock:
    """Create a mock InitSessionRequest with sensible defaults."""
    defaults = {
        "repository": None,
        "selected_branch": None,
        "initial_user_msg": None,
        "image_urls": None,
        "replay_json": None,
        "suggested_task": None,
        "create_playbook": None,
        "vcs_provider": None,
        "conversation_instructions": None,
        "conversation_id": None,
    }
    defaults.update(kwargs)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _make_suggested_task(
    repo: str = "owner/repo",
    title: str = "Test title",
    issue_number: int = 42,
) -> SuggestedTask:
    return SuggestedTask(
        vcs_provider=ProviderType.ENTERPRISE_SSO,
        task_type=TaskType.OPEN_ISSUE,
        repo=repo,
        issue_number=issue_number,
        title=title,
    )


def _make_create_playbook(
    repo: str = "owner/playbook-repo",
    vcs_provider: ProviderType | None = None,
) -> CreatePlaybook:
    return CreatePlaybook(repo=repo, vcs_provider=vcs_provider)


# ---------------------------------------------------------------------------
# extract_request_data
# ---------------------------------------------------------------------------


class TestExtractRequestData:
    def test_returns_nine_element_tuple(self):
        req = _make_init_request(
            repository="owner/repo",
            selected_branch="main",
            initial_user_msg="Hello",
            image_urls=["http://img.example.com/a.png"],
            replay_json='{"events": []}',
            suggested_task=None,
            create_playbook=None,
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            conversation_instructions="Be concise",
        )
        result = extract_request_data(req)
        assert len(result) == 9

    def test_extracts_all_fields(self):
        task = _make_suggested_task()
        req = _make_init_request(
            repository="owner/repo",
            selected_branch="feature",
            initial_user_msg="Do something",
            image_urls=["img1.png"],
            replay_json='{}',
            suggested_task=task,
            create_playbook=None,
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            conversation_instructions="instructions text",
        )
        (
            repository,
            branch,
            msg,
            images,
            replay,
            suggested,
            playbook,
            provider,
            instructions,
        ) = extract_request_data(req)
        assert repository == "owner/repo"
        assert branch == "feature"
        assert msg == "Do something"
        assert images == ["img1.png"]
        assert replay == '{}'
        assert suggested is task
        assert playbook is None
        assert provider == ProviderType.ENTERPRISE_SSO
        assert instructions == "instructions text"

    def test_image_urls_none_becomes_empty_list(self):
        req = _make_init_request(image_urls=None)
        _, _, _, images, _, _, _, _, _ = extract_request_data(req)
        assert images == []

    def test_image_urls_non_none_preserved(self):
        req = _make_init_request(image_urls=["a.png", "b.png"])
        _, _, _, images, _, _, _, _, _ = extract_request_data(req)
        assert images == ["a.png", "b.png"]


# ---------------------------------------------------------------------------
# determine_conversation_trigger
# ---------------------------------------------------------------------------


class TestDetermineConversationTrigger:
    def test_default_is_gui(self):
        trigger, repo, provider = determine_conversation_trigger(
            suggested_task=None, create_playbook=None, auth_type=None
        )
        assert trigger == ConversationTrigger.GUI
        assert repo is None
        assert provider is None

    def test_suggested_task_sets_trigger(self):
        task = _make_suggested_task()
        trigger, repo, provider = determine_conversation_trigger(
            suggested_task=task, create_playbook=None, auth_type=None
        )
        assert trigger == ConversationTrigger.SUGGESTED_TASK
        assert repo is None
        assert provider is None

    def test_create_playbook_with_repo_and_provider(self):
        playbook = _make_create_playbook(
            repo="myorg/myrepo",
            vcs_provider=ProviderType.ENTERPRISE_SSO,
        )
        trigger, repo, provider = determine_conversation_trigger(
            suggested_task=None, create_playbook=playbook, auth_type=None
        )
        assert trigger == ConversationTrigger.PLAYBOOK_MANAGEMENT
        assert repo == "myorg/myrepo"
        assert provider == ProviderType.ENTERPRISE_SSO

    def test_create_playbook_without_provider(self):
        playbook = _make_create_playbook(repo="myorg/repoX", vcs_provider=None)
        trigger, repo, provider = determine_conversation_trigger(
            suggested_task=None, create_playbook=playbook, auth_type=None
        )
        assert trigger == ConversationTrigger.PLAYBOOK_MANAGEMENT
        assert repo == "myorg/repoX"
        assert provider is None

    def test_bearer_auth_overrides_gui_default(self):
        trigger, repo, provider = determine_conversation_trigger(
            suggested_task=None, create_playbook=None, auth_type=AuthType.BEARER
        )
        assert trigger == ConversationTrigger.REMOTE_API_KEY

    def test_bearer_auth_overrides_suggested_task(self):
        task = _make_suggested_task()
        trigger, repo, provider = determine_conversation_trigger(
            suggested_task=task, create_playbook=None, auth_type=AuthType.BEARER
        )
        assert trigger == ConversationTrigger.REMOTE_API_KEY

    def test_bearer_auth_overrides_playbook_management(self):
        playbook = _make_create_playbook()
        trigger, repo, provider = determine_conversation_trigger(
            suggested_task=None, create_playbook=playbook, auth_type=AuthType.BEARER
        )
        assert trigger == ConversationTrigger.REMOTE_API_KEY

    def test_non_bearer_auth_type_does_not_change_trigger(self):
        trigger, _, _ = determine_conversation_trigger(
            suggested_task=None, create_playbook=None, auth_type=None
        )
        assert trigger == ConversationTrigger.GUI


# ---------------------------------------------------------------------------
# validate_remote_api_request
# ---------------------------------------------------------------------------


class TestValidateRemoteApiRequest:
    def test_remote_api_key_with_no_message_returns_400(self):
        response = validate_remote_api_request(
            ConversationTrigger.REMOTE_API_KEY, ""
        )
        assert isinstance(response, JSONResponse)
        assert response.status_code == 400

    def test_remote_api_key_with_none_message_returns_400(self):
        response = validate_remote_api_request(
            ConversationTrigger.REMOTE_API_KEY, None
        )
        assert isinstance(response, JSONResponse)
        assert response.status_code == 400

    def test_remote_api_key_with_message_returns_none(self):
        response = validate_remote_api_request(
            ConversationTrigger.REMOTE_API_KEY, "Fix the bug"
        )
        assert response is None

    def test_gui_trigger_with_no_message_returns_none(self):
        response = validate_remote_api_request(
            ConversationTrigger.GUI, ""
        )
        assert response is None

    def test_gui_trigger_with_message_returns_none(self):
        response = validate_remote_api_request(
            ConversationTrigger.GUI, "Do something"
        )
        assert response is None

    def test_suggested_task_trigger_no_message_returns_none(self):
        response = validate_remote_api_request(
            ConversationTrigger.SUGGESTED_TASK, ""
        )
        assert response is None

    def test_playbook_trigger_no_message_returns_none(self):
        response = validate_remote_api_request(
            ConversationTrigger.PLAYBOOK_MANAGEMENT, ""
        )
        assert response is None


# ---------------------------------------------------------------------------
# apply_conversation_overrides
# ---------------------------------------------------------------------------


class TestApplyConversationOverrides:
    def test_no_overrides_returns_original_values(self):
        repo, provider, msg = apply_conversation_overrides(
            repository="original/repo",
            vcs_provider=ProviderType.ENTERPRISE_SSO,
            override_repo=None,
            override_git_provider=None,
            suggested_task=None,
            initial_user_msg="original message",
        )
        assert repo == "original/repo"
        assert provider == ProviderType.ENTERPRISE_SSO
        assert msg == "original message"

    def test_override_repo_replaces_repository(self):
        repo, _, _ = apply_conversation_overrides(
            repository="old/repo",
            vcs_provider=None,
            override_repo="new/repo",
            override_git_provider=None,
            suggested_task=None,
            initial_user_msg=None,
        )
        assert repo == "new/repo"

    def test_override_git_provider_replaces_vcs_provider(self):
        _, provider, _ = apply_conversation_overrides(
            repository=None,
            vcs_provider=None,
            override_repo=None,
            override_git_provider=ProviderType.ENTERPRISE_SSO,
            suggested_task=None,
            initial_user_msg=None,
        )
        assert provider == ProviderType.ENTERPRISE_SSO

    def test_suggested_task_sets_message(self):
        task = _make_suggested_task(
            repo="owner/repo",
            title="Fix failing checks",
            issue_number=7,
        )
        _, _, msg = apply_conversation_overrides(
            repository=None,
            vcs_provider=None,
            override_repo=None,
            override_git_provider=None,
            suggested_task=task,
            initial_user_msg="original msg",
        )
        expected = task.get_prompt_for_task()
        assert msg == expected
        assert "Fix failing checks" in msg
        assert "#7" in msg

    def test_all_overrides_applied_together(self):
        task = _make_suggested_task(title="All overrides", issue_number=99)
        repo, provider, msg = apply_conversation_overrides(
            repository="old/repo",
            vcs_provider=None,
            override_repo="new/repo",
            override_git_provider=ProviderType.ENTERPRISE_SSO,
            suggested_task=task,
            initial_user_msg="old",
        )
        assert repo == "new/repo"
        assert provider == ProviderType.ENTERPRISE_SSO
        assert "All overrides" in msg


# ---------------------------------------------------------------------------
# normalize_provider_tokens
# ---------------------------------------------------------------------------


class TestNormalizeProviderTokens:
    def test_none_returns_empty_mapping_proxy(self):
        result = normalize_provider_tokens(None)
        assert isinstance(result, MappingProxyType)
        assert dict(result) == {}

    def test_already_mapping_proxy_is_returned_unchanged(self):
        original = MappingProxyType(
            {ProviderType.ENTERPRISE_SSO: "token123"}
        )
        result = normalize_provider_tokens(original)
        assert result is original

    def test_dict_with_enum_keys_becomes_mapping_proxy(self):
        tokens = {ProviderType.ENTERPRISE_SSO: "token_val"}
        result = normalize_provider_tokens(tokens)
        assert isinstance(result, MappingProxyType)
        assert result[ProviderType.ENTERPRISE_SSO] == "token_val"

    def test_dict_with_valid_string_key_converted_to_enum(self):
        tokens = {"enterprise_sso": "token_val"}
        result = normalize_provider_tokens(tokens)
        assert isinstance(result, MappingProxyType)
        assert ProviderType.ENTERPRISE_SSO in result
        assert result[ProviderType.ENTERPRISE_SSO] == "token_val"

    def test_dict_with_invalid_string_key_is_silently_dropped(self):
        tokens = {"not_a_valid_provider": "token_val"}
        result = normalize_provider_tokens(tokens)
        assert isinstance(result, MappingProxyType)
        assert len(result) == 0

    def test_dict_with_mixed_valid_invalid_keys(self):
        tokens = {
            "enterprise_sso": "good_token",
            "invalid_key": "bad_token",
        }
        result = normalize_provider_tokens(tokens)
        assert ProviderType.ENTERPRISE_SSO in result
        assert len(result) == 1

    def test_empty_dict_returns_empty_mapping_proxy(self):
        result = normalize_provider_tokens({})
        assert isinstance(result, MappingProxyType)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# prepare_conversation_params
# ---------------------------------------------------------------------------


class TestPrepareConversationParams:
    def test_none_user_id_defaults_to_dev_user(self):
        user_id, _, _ = prepare_conversation_params(
            user_id=None, provider_tokens=None, user_secrets=None
        )
        assert user_id == "dev-user"

    def test_empty_string_user_id_defaults_to_dev_user(self):
        user_id, _, _ = prepare_conversation_params(
            user_id="", provider_tokens=None, user_secrets=None
        )
        assert user_id == "dev-user"

    def test_provided_user_id_is_preserved(self):
        user_id, _, _ = prepare_conversation_params(
            user_id="alice", provider_tokens=None, user_secrets=None
        )
        assert user_id == "alice"

    def test_none_provider_tokens_returns_empty_mapping_proxy(self):
        _, tokens, _ = prepare_conversation_params(
            user_id=None, provider_tokens=None, user_secrets=None
        )
        assert isinstance(tokens, MappingProxyType)
        assert len(tokens) == 0

    def test_none_user_secrets_returns_default_user_secrets(self):
        _, _, secrets = prepare_conversation_params(
            user_id=None, provider_tokens=None, user_secrets=None
        )
        assert isinstance(secrets, UserSecrets)

    def test_provided_user_secrets_preserved(self):
        custom = UserSecrets()
        _, _, secrets = prepare_conversation_params(
            user_id=None, provider_tokens=None, user_secrets=custom
        )
        assert secrets is custom

    def test_provided_tokens_normalized(self):
        raw_tokens = {"enterprise_sso": "my_token"}
        _, tokens, _ = prepare_conversation_params(
            user_id=None, provider_tokens=raw_tokens, user_secrets=None
        )
        assert isinstance(tokens, MappingProxyType)
        assert ProviderType.ENTERPRISE_SSO in tokens


# ---------------------------------------------------------------------------
# handle_conversation_errors
# ---------------------------------------------------------------------------


class TestHandleConversationErrors:
    def test_missing_settings_error_returns_400(self):
        exc = MissingSettingsError("LLM model not configured")
        response = handle_conversation_errors(exc)
        assert isinstance(response, JSONResponse)
        assert response.status_code == 400

    def test_llm_authentication_error_returns_400(self):
        exc = LLMAuthenticationError("Invalid API key")
        response = handle_conversation_errors(exc)
        assert isinstance(response, JSONResponse)
        assert response.status_code == 400

    def test_generic_runtime_error_is_reraised(self):
        exc = RuntimeError("Something unexpected happened")
        with pytest.raises(RuntimeError, match="Something unexpected happened"):
            handle_conversation_errors(exc)

    def test_generic_value_error_is_reraised(self):
        exc = ValueError("Bad data")
        with pytest.raises(ValueError, match="Bad data"):
            handle_conversation_errors(exc)

    def test_generic_exception_is_reraised(self):
        exc = Exception("Unknown")
        with pytest.raises(Exception, match="Unknown"):
            handle_conversation_errors(exc)


# ---------------------------------------------------------------------------
# resolve_conversation_id
# ---------------------------------------------------------------------------


class TestResolveConversationId:
    def test_without_env_var_always_generates_uuid(self):
        data = _make_init_request(conversation_id="user-supplied-id")
        env = {"ALLOW_SET_CONVERSATION_ID": "0"}
        with pytest.MonkeyPatch().context() as m:
            m.setenv("ALLOW_SET_CONVERSATION_ID", "0")
            result = resolve_conversation_id(data)
        assert result != "user-supplied-id"
        # UUID4.hex is 32 lowercase hex characters
        assert re.fullmatch(r"[0-9a-f]{32}", result)

    def test_with_env_var_set_to_1_uses_supplied_id(self):
        data = _make_init_request(conversation_id="my-custom-id")
        with pytest.MonkeyPatch().context() as m:
            m.setenv("ALLOW_SET_CONVERSATION_ID", "1")
            result = resolve_conversation_id(data)
        assert result == "my-custom-id"

    def test_with_env_var_set_to_1_but_no_conversation_id_generates_uuid(self):
        data = _make_init_request(conversation_id=None)
        with pytest.MonkeyPatch().context() as m:
            m.setenv("ALLOW_SET_CONVERSATION_ID", "1")
            result = resolve_conversation_id(data)
        assert re.fullmatch(r"[0-9a-f]{32}", result)

    def test_env_var_missing_entirely_generates_uuid(self):
        data = _make_init_request(conversation_id="supplied-id")
        with pytest.MonkeyPatch().context() as m:
            m.delenv("ALLOW_SET_CONVERSATION_ID", raising=False)
            result = resolve_conversation_id(data)
        assert result != "supplied-id"
        assert re.fullmatch(r"[0-9a-f]{32}", result)

    def test_each_call_without_env_var_generates_unique_uuid(self):
        data = _make_init_request(conversation_id=None)
        with pytest.MonkeyPatch().context() as m:
            m.delenv("ALLOW_SET_CONVERSATION_ID", raising=False)
            id1 = resolve_conversation_id(data)
            id2 = resolve_conversation_id(data)
        assert id1 != id2
