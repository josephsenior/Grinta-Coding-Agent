"""Tests for backend.api.services.conversation_service helper functions.

Targets the 19.4% coverage gap by testing pure helper functions
that don't require async infrastructure.
"""

from __future__ import annotations

import pytest
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch
from typing import cast


from backend.core.provider_types import ProviderToken, ProviderType
from backend.events.action.message import MessageAction
from backend.storage.data_models.user_secrets import CustomSecret

# Only member: ProviderType.ENTERPRISE_SSO
_SSO = ProviderType.ENTERPRISE_SSO

from backend.api.services.conversation_service import (  # noqa: E402
    _create_initial_message_action,
    _ensure_provider_tokens_for_providers,
    _get_normalized_provider_tokens,
    _normalize_provider_list,
    _process_custom_secrets,
    _process_git_provider_tokens,
    create_provider_tokens_object,
)


# -----------------------------------------------------------
# _process_git_provider_tokens
# -----------------------------------------------------------


class TestProcessGitProviderTokens:
    def test_none_returns_empty(self):
        result = _process_git_provider_tokens(None)
        assert isinstance(result, MappingProxyType)
        assert not result

    def test_empty_dict_returns_empty(self):
        result = _process_git_provider_tokens({})
        assert isinstance(result, MappingProxyType)
        assert not result

    def test_dict_wrapped_in_mapping_proxy(self):
        tokens = {_SSO: ProviderToken(token="abc", user_id="u")}
        result = _process_git_provider_tokens(tokens)
        assert isinstance(result, MappingProxyType)
        assert _SSO in result

    def test_mapping_proxy_returned_as_is(self):
        tokens = MappingProxyType({_SSO: ProviderToken(token="x", user_id="u")})
        result = _process_git_provider_tokens(tokens)
        assert result is tokens


# -----------------------------------------------------------
# _process_custom_secrets
# -----------------------------------------------------------


class TestProcessCustomSecrets:
    def test_none_returns_empty(self):
        result = _process_custom_secrets(None)
        assert isinstance(result, MappingProxyType)
        assert not result

    def test_empty_dict_returns_empty(self):
        result = _process_custom_secrets({})
        assert isinstance(result, MappingProxyType)

    def test_dict_wrapped(self):
        result = _process_custom_secrets({"API_KEY": "secret"})
        assert isinstance(result, MappingProxyType)
        assert result["API_KEY"] == "secret"

    def test_mapping_proxy_returned_directly(self):
        mp = MappingProxyType({"KEY": "VAL"})
        result = _process_custom_secrets(mp)
        assert result is mp

    def test_user_secrets_object(self):
        from backend.storage.data_models.user_secrets import CustomSecret, UserSecrets

        us = UserSecrets(custom_secrets={"K": CustomSecret(secret="V")})
        result = _process_custom_secrets(us)
        assert isinstance(result, MappingProxyType)
        assert "K" in result

    def test_unknown_type_returns_empty(self):
        result = _process_custom_secrets(42)
        assert isinstance(result, MappingProxyType)
        assert not result


# -----------------------------------------------------------
# _normalize_provider_list
# -----------------------------------------------------------


class TestNormalizeProviderList:
    def test_none_returns_empty(self):
        assert _normalize_provider_list(None) == []

    def test_empty_list(self):
        assert _normalize_provider_list([]) == []

    def test_enum_values_pass_through(self):
        result = _normalize_provider_list([_SSO])
        assert result == [_SSO]

    def test_string_values_converted(self):
        result = _normalize_provider_list(["enterprise_sso"])
        assert result == [_SSO]

    def test_invalid_string_skipped(self):
        result = _normalize_provider_list(["nonexistent_provider_xyz"])
        assert result == []


# -----------------------------------------------------------
# _get_normalized_provider_tokens
# -----------------------------------------------------------


class TestGetNormalizedProviderTokens:
    def test_with_valid_tokens(self):
        tokens = {_SSO: ProviderToken(token="t", user_id="u")}
        result = _get_normalized_provider_tokens(tokens, None)
        assert result is not None
        assert _SSO in result

    def test_none_tokens_falls_back_to_defaults(self):
        defaults = MappingProxyType({_SSO: ProviderToken(token="d", user_id="u")})
        result = _get_normalized_provider_tokens(None, defaults)
        assert result is defaults

    def test_empty_tokens_falls_back_to_defaults(self):
        defaults = MappingProxyType({_SSO: ProviderToken(token="d", user_id="u")})
        result = _get_normalized_provider_tokens({}, defaults)
        assert result is defaults


# -----------------------------------------------------------
# _ensure_provider_tokens_for_providers
# -----------------------------------------------------------


class TestEnsureProviderTokensForProviders:
    def test_no_providers_returns_existing(self):
        tokens = MappingProxyType({_SSO: ProviderToken(token="t", user_id="u")})
        result = _ensure_provider_tokens_for_providers(tokens, None, "u")
        assert result is tokens

    def test_adds_missing_provider(self):
        result = _ensure_provider_tokens_for_providers(
            MappingProxyType({}), [_SSO], "u1"
        )
        assert _SSO in result
        assert result[_SSO].user_id == "u1"

    def test_existing_provider_not_overwritten(self):
        existing = MappingProxyType(
            {_SSO: ProviderToken(token="existing", user_id="u")}
        )
        result = _ensure_provider_tokens_for_providers(existing, [_SSO], "u2")
        # token is SecretStr, compare via get_secret_value
        token = result[_SSO].token
        assert token is not None
        assert token.get_secret_value() == "existing"

    def test_none_tokens_creates_new(self):
        result = _ensure_provider_tokens_for_providers(None, [_SSO], "u1")
        assert _SSO in result


# -----------------------------------------------------------
# _create_initial_message_action
# -----------------------------------------------------------


class TestCreateInitialMessageAction:
    def test_no_msg_no_images_returns_none(self):
        assert _create_initial_message_action(None, None) is None

    def test_empty_msg_no_images_returns_none(self):
        assert _create_initial_message_action("", None) is None

    def test_with_message(self):
        action = _create_initial_message_action("Hello", None)
        assert action is not None
        assert isinstance(action, MessageAction)
        assert action.content == "Hello"

    def test_with_images_only(self):
        action = _create_initial_message_action(None, ["http://img.png"])
        assert action is not None
        assert isinstance(action, MessageAction)
        assert action.image_urls == ["http://img.png"]

    def test_with_msg_and_images(self):
        action = _create_initial_message_action("Hi", ["http://a.png"])
        assert action is not None
        assert action.content == "Hi"
        assert action.image_urls == ["http://a.png"]


# -----------------------------------------------------------
# create_provider_tokens_object
# -----------------------------------------------------------


class TestCreateProviderTokensObject:
    def test_empty_providers(self):
        result = create_provider_tokens_object([])
        assert isinstance(result, MappingProxyType)
        assert not result

    def test_single_provider(self):
        result = create_provider_tokens_object([_SSO])
        assert _SSO in result
        assert result[_SSO].token is None

    def test_same_provider_twice(self):
        result = create_provider_tokens_object([_SSO, _SSO])
        assert _SSO in result


# -----------------------------------------------------------
# initialize_conversation
# -----------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_conversation_store_instance")
@patch("uuid.uuid4")
async def test_initialize_conversation_new(mock_uuid, mock_get_store):
    from backend.api.services.conversation_service import initialize_conversation

    mock_uuid.return_value.hex = "mock-uuid"
    store = AsyncMock()
    store.exists.return_value = False
    mock_get_store.return_value = store

    result = await initialize_conversation(
        user_id="u1",
        conversation_id=None,
        selected_repository="repo",
        selected_branch="main",
    )

    assert result is not None
    assert result.conversation_id == "mock-uuid"
    assert result.title.startswith("Conversation")
    store.save_metadata.assert_awaited_once()


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_conversation_store_instance")
async def test_initialize_conversation_existing(mock_get_store):
    from backend.api.services.conversation_service import initialize_conversation

    store = AsyncMock()
    store.exists.return_value = True
    meta = MagicMock()
    store.get_metadata.return_value = meta
    mock_get_store.return_value = store

    result = await initialize_conversation("u1", "existing-id", "repo", "main")

    assert result == meta
    store.get_metadata.assert_awaited_once_with("existing-id")


# -----------------------------------------------------------
# start_conversation
# -----------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_settings_store_instance")
@patch("backend.api.services.conversation_service.get_conversation_manager")
async def test_start_conversation_success(mock_get_manager, mock_get_settings_store):
    from backend.api.services.conversation_service import start_conversation
    from backend.storage.data_models.settings import Settings

    # Mock settings
    settings = Settings(agent="default")
    settings_store = AsyncMock()
    settings_store.load.return_value = settings
    mock_get_settings_store.return_value = settings_store

    # Mock manager
    manager = AsyncMock()
    mock_get_manager.return_value = manager
    loop_info = MagicMock()
    manager.maybe_start_agent_loop.return_value = loop_info

    metadata = MagicMock()
    metadata.trigger = "gui"
    metadata.conversation_id = "conv1"
    metadata.selected_repository = "repo"
    metadata.selected_branch = "main"
    metadata.vcs_provider = None

    result = await start_conversation(
        user_id="u1",
        vcs_provider_tokens=None,
        custom_secrets=None,
        initial_user_msg="hi",
        image_urls=None,
        replay_json=None,
        conversation_id="conv1",
        conversation_metadata=metadata,
        conversation_instructions=None,
    )

    assert result == loop_info
    manager.maybe_start_agent_loop.assert_called_once()


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_settings_store_instance")
async def test_start_conversation_no_settings(mock_get_settings_store):
    from backend.api.services.conversation_service import (
        MissingSettingsError,
        start_conversation,
    )

    settings_store = AsyncMock()
    settings_store.load.return_value = None
    mock_get_settings_store.return_value = settings_store

    with pytest.raises(MissingSettingsError):
        await start_conversation(
            "u1", None, None, "hi", None, None, "c1", MagicMock(), None
        )


# -----------------------------------------------------------
# setup_init_conversation_settings
# -----------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_conversation_store_instance")
@patch("backend.api.services.conversation_service.get_settings_store_instance")
async def test_setup_init_conversation_settings_success(
    mock_get_settings, mock_get_store
):
    from backend.api.services.conversation_service import (
        setup_init_conversation_settings,
    )
    from backend.storage.data_models.settings import Settings

    # Store/Metadata
    store = AsyncMock()
    meta = MagicMock()
    meta.selected_repository = "repo"
    meta.selected_branch = "main"
    meta.vcs_provider = None
    store.get_metadata.return_value = meta
    mock_get_store.return_value = store

    # Settings
    settings_store = AsyncMock()
    settings = Settings(agent="default")
    settings_store.load.return_value = settings
    mock_get_settings.return_value = settings_store

    result = await setup_init_conversation_settings("u1", "c1")

    assert result.agent == "default"
    assert result.selected_repository == "repo"
    store.get_metadata.assert_called_once_with("c1")


# -----------------------------------------------------------
# _build_session_init_args
# -----------------------------------------------------------


class TestBuildSessionInitArgs:
    def test_basic_session_args(self):
        from backend.api.services.conversation_service import (
            _build_session_init_args,
        )

        settings = MagicMock()
        settings.__dict__ = {"agent": "default", "model": "gpt4"}

        metadata = MagicMock()
        metadata.selected_repository = "repo"
        metadata.selected_branch = "main"
        metadata.vcs_provider = None

        result = _build_session_init_args(
            settings, metadata, None, None, "custom_inst", None
        )

        assert result["agent"] == "default"
        assert result["model"] == "gpt4"
        assert result["selected_repository"] == "repo"
        assert result["selected_branch"] == "main"
        assert result["conversation_instructions"] == "custom_inst"
        assert isinstance(result["vcs_provider_tokens"], MappingProxyType)
        assert isinstance(result["custom_secrets"], MappingProxyType)

    def test_with_provider_tokens(self):
        from backend.api.services.conversation_service import (
            _build_session_init_args,
        )

        settings = MagicMock()
        settings.__dict__ = {"agent": "default"}
        metadata = MagicMock()
        metadata.selected_repository = "repo"
        metadata.selected_branch = "main"
        metadata.vcs_provider = None

        tokens = {_SSO: ProviderToken(token="t", user_id="u")}

        result = _build_session_init_args(settings, metadata, tokens, None, None, None)

        assert _SSO in result["vcs_provider_tokens"]

    def test_with_custom_secrets(self):
        from backend.api.services.conversation_service import (
            _build_session_init_args,
        )

        settings = MagicMock()
        settings.__dict__ = {"agent": "default"}
        metadata = MagicMock()
        metadata.selected_repository = "repo"
        metadata.selected_branch = "main"
        metadata.vcs_provider = None

        secrets = {"API_KEY": CustomSecret(secret="secret")}

        result = _build_session_init_args(
            settings, metadata, None, secrets, None, None
        )

        # custom_secrets passes through CustomSecret objects (not raw values)
        assert "API_KEY" in result["custom_secrets"]
        assert result["custom_secrets"]["API_KEY"].secret.get_secret_value() == "secret"

    def test_with_mcp_config(self):
        from backend.api.services.conversation_service import (
            _build_session_init_args,
        )

        settings = MagicMock()
        settings.__dict__ = {"agent": "default"}
        metadata = MagicMock()
        metadata.selected_repository = "repo"
        metadata.selected_branch = "main"
        metadata.vcs_provider = None

        mcp_config = MagicMock()

        result = _build_session_init_args(
            settings, metadata, None, None, None, mcp_config
        )

        assert result["mcp_config"] is mcp_config


# -----------------------------------------------------------
# create_new_conversation
# -----------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.initialize_conversation")
@patch("backend.api.services.conversation_service.start_conversation")
async def test_create_new_conversation_success(mock_start, mock_init):
    from backend.api.services.conversation_service import create_new_conversation

    # Mock initialize_conversation
    metadata = MagicMock()
    metadata.conversation_id = "conv_new_1"
    mock_init.return_value = metadata

    # Mock start_conversation
    loop_info = MagicMock()
    mock_start.return_value = loop_info

    result = await create_new_conversation(
        user_id="u1",
        vcs_provider_tokens=None,
        custom_secrets=None,
        selected_repository="repo",
        selected_branch="main",
        initial_user_msg="Hello",
        image_urls=None,
        replay_json=None,
    )

    assert result is loop_info
    mock_init.assert_called_once()
    mock_start.assert_called_once()


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.initialize_conversation")
async def test_create_new_conversation_init_fails(mock_init):
    from backend.api.services.conversation_service import create_new_conversation

    mock_init.return_value = None

    with pytest.raises(ValueError, match="Failed to initialize conversation"):
        await create_new_conversation(
            user_id="u1",
            vcs_provider_tokens=None,
            custom_secrets=None,
            selected_repository="repo",
            selected_branch="main",
            initial_user_msg=None,
            image_urls=None,
            replay_json=None,
        )


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.initialize_conversation")
@patch("backend.api.services.conversation_service.start_conversation")
async def test_create_new_conversation_with_custom_trigger(mock_start, mock_init):
    from backend.api.services.conversation_service import create_new_conversation
    from backend.storage.data_models.conversation_metadata import (
        ConversationTrigger,
    )

    metadata = MagicMock()
    metadata.conversation_id = "conv_new_2"
    mock_init.return_value = metadata

    loop_info = MagicMock()
    mock_start.return_value = loop_info

    await create_new_conversation(
        user_id="u1",
        vcs_provider_tokens=None,
        custom_secrets=None,
        selected_repository="repo",
        selected_branch="main",
        initial_user_msg=None,
        image_urls=None,
        replay_json=None,
        conversation_trigger=ConversationTrigger.PLAYBOOK_MANAGEMENT,
    )

    # Verify the trigger was passed to initialize_conversation
    mock_init.assert_called_once()
    # Access positional arguments from call_args
    # conversation_trigger is the 5th positional argument (index 4)
    args, kwargs = mock_init.call_args
    assert args[4] == ConversationTrigger.PLAYBOOK_MANAGEMENT


# -----------------------------------------------------------
# initialize_conversation edge cases
# -----------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_conversation_store_instance")
async def test_initialize_conversation_with_all_params(mock_get_store):
    from backend.api.services.conversation_service import initialize_conversation
    from backend.storage.data_models.conversation_metadata import (
        ConversationTrigger,
    )

    store = AsyncMock()
    store.exists.return_value = False
    store.save_metadata = AsyncMock()
    mock_get_store.return_value = store

    with patch("uuid.uuid4") as mock_uuid:
        mock_uuid.return_value.hex = "test-uuid-123"

        result = await initialize_conversation(
            user_id="u1",
            conversation_id=None,
            selected_repository="myrepo",
            selected_branch="develop",
            conversation_trigger=ConversationTrigger.PLAYBOOK_MANAGEMENT,
            vcs_provider=_SSO,
        )

    assert result is not None
    assert result.conversation_id == "test-uuid-123"
    assert result.selected_repository == "myrepo"
    assert result.selected_branch == "develop"
    assert result.trigger == ConversationTrigger.PLAYBOOK_MANAGEMENT
    assert result.vcs_provider == _SSO
    store.save_metadata.assert_called_once()


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_conversation_store_instance")
async def test_initialize_conversation_get_metadata_fails(mock_get_store):
    from backend.api.services.conversation_service import initialize_conversation

    store = AsyncMock()
    store.exists.return_value = True
    store.get_metadata.side_effect = Exception("DB error")
    mock_get_store.return_value = store

    result = await initialize_conversation(
        user_id="u1",
        conversation_id="existing_id",
        selected_repository="repo",
        selected_branch="main",
    )

    assert result is None


# -----------------------------------------------------------
# start_conversation edge cases
# -----------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_settings_store_instance")
@patch("backend.api.services.conversation_service.get_conversation_manager")
async def test_start_conversation_with_images(mock_get_manager, mock_get_settings_store):
    from backend.api.services.conversation_service import start_conversation

    settings = MagicMock()
    settings_store = AsyncMock()
    settings_store.load.return_value = settings
    mock_get_settings_store.return_value = settings_store

    manager = AsyncMock()
    mock_get_manager.return_value = manager
    loop_info = MagicMock()
    manager.maybe_start_agent_loop.return_value = loop_info

    metadata = MagicMock()
    metadata.trigger = "gui"
    metadata.conversation_id = "conv1"
    metadata.selected_repository = "repo"
    metadata.selected_branch = "main"
    metadata.vcs_provider = None

    result = await start_conversation(
        user_id="u1",
        vcs_provider_tokens=None,
        custom_secrets=None,
        initial_user_msg="Check this image",
        image_urls=["http://example.com/image.png", "http://example.com/image2.png"],
        replay_json=None,
        conversation_id="conv1",
        conversation_metadata=metadata,
        conversation_instructions=None,
    )

    assert result == loop_info
    # Verify init data passed to maybe_start_agent_loop
    call_args = manager.maybe_start_agent_loop.call_args
    # Second positional argument is conversation_init_data
    init_data = call_args[0][1]
    assert init_data.selected_repository == "repo"


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_settings_store_instance")
@patch("backend.api.services.conversation_service.get_conversation_manager")
async def test_start_conversation_with_custom_instructions(
    mock_get_manager, mock_get_settings_store
):
    from backend.api.services.conversation_service import start_conversation

    settings = MagicMock()
    settings_store = AsyncMock()
    settings_store.load.return_value = settings
    mock_get_settings_store.return_value = settings_store

    manager = AsyncMock()
    mock_get_manager.return_value = manager
    loop_info = MagicMock()
    manager.maybe_start_agent_loop.return_value = loop_info

    metadata = MagicMock()
    metadata.trigger = "gui"
    metadata.conversation_id = "conv1"
    metadata.selected_repository = "repo"
    metadata.selected_branch = "main"
    metadata.vcs_provider = None

    custom_instructions = "Use Python only, no JavaScript"

    result = await start_conversation(
        user_id="u1",
        vcs_provider_tokens=None,
        custom_secrets=None,
        initial_user_msg="Build me something",
        image_urls=None,
        replay_json=None,
        conversation_id="conv1",
        conversation_metadata=metadata,
        conversation_instructions=custom_instructions,
    )

    assert result == loop_info
    # Verify instructions passed to ConversationInitData
    call_args = manager.maybe_start_agent_loop.call_args
    # Second positional argument is conversation_init_data
    init_data = call_args[0][1]
    assert init_data.conversation_instructions == custom_instructions


# -----------------------------------------------------------
# setup_init_conversation_settings edge cases
# -----------------------------------------------------------


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_conversation_store_instance")
@patch("backend.api.services.conversation_service.get_settings_store_instance")
async def test_setup_init_conversation_settings_with_providers(
    mock_get_settings, mock_get_store
):
    from backend.api.services.conversation_service import (
        setup_init_conversation_settings,
    )
    from backend.storage.data_models.settings import Settings

    # Store/Metadata
    store = AsyncMock()
    meta = MagicMock()
    meta.selected_repository = "repo"
    meta.selected_branch = "main"
    meta.vcs_provider = None
    store.get_metadata.return_value = meta
    mock_get_store.return_value = store

    # Settings
    settings_store = AsyncMock()
    settings = Settings(agent="default")
    settings_store.load.return_value = settings
    mock_get_settings.return_value = settings_store

    result = await setup_init_conversation_settings(
        "u1", "c1", providers_set=[_SSO, "github"]
    )

    assert result.agent == "default"
    assert result.selected_repository == "repo"


@pytest.mark.asyncio
@patch("backend.api.services.conversation_service.get_conversation_store_instance")
@patch("backend.api.services.conversation_service.get_settings_store_instance")
async def test_setup_init_conversation_settings_metadata_not_found(
    mock_get_settings, mock_get_store
):
    from backend.api.services.conversation_service import (
        setup_init_conversation_settings,
    )

    store = AsyncMock()
    store.get_metadata.side_effect = Exception("Not found")
    mock_get_store.return_value = store

    settings_store = AsyncMock()
    settings_store.load.return_value = MagicMock()
    mock_get_settings.return_value = settings_store

    with pytest.raises(Exception):
        await setup_init_conversation_settings("u1", "nonexistent")
