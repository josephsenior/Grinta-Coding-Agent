import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os
from backend.api.services.prompt_service import (
    get_contextual_events,
    generate_prompt_template,
    generate_prompt,
    build_remember_prompt
)
from backend.core.config.llm_config import LLMConfig

def test_get_contextual_events_calls_query_service():
    """Test that get_contextual_events calls the underlying query service with filter."""
    mock_event_store = MagicMock()
    
    with patch("backend.api.services.prompt_service.get_contextual_events_text") as mock_query:
        mock_query.return_value = "stringified events"
        result = get_contextual_events(mock_event_store, 123)
        
        assert result == "stringified events"
        mock_query.assert_called_once()
        # Verify event_id and event_store passed through
        call_args = mock_query.call_args[1]
        assert call_args["event_store"] == mock_event_store
        assert call_args["event_id"] == 123
        assert "event_filter" in call_args

@patch("jinja2.Environment")
def test_generate_prompt_template_rendering(mock_env_class):
    """Test that the Jinja2 template is correctly loaded and rendered."""
    mock_env = MagicMock()
    mock_env_class.return_value = mock_env
    mock_template = MagicMock()
    mock_env.get_template.return_value = mock_template
    mock_template.render.return_value = "rendered prompt"
    
    result = generate_prompt_template("some events")
    
    assert result == "rendered prompt"
    mock_env.get_template.assert_called_with("generate_remember_prompt.j2")
    mock_template.render.assert_called_with(events="some events")

@pytest.mark.asyncio
@patch("backend.api.services.prompt_service.get_conversation_manager_impl")
async def test_generate_prompt_success(mock_get_manager):
    """Test successful extraction of update_prompt from LLM response."""
    mock_manager = AsyncMock()
    mock_get_manager.return_value = mock_manager
    mock_manager.request_llm_completion = AsyncMock(return_value="Some noise <update_prompt>Remember I like Python</update_prompt> more noise")
    
    llm_config = LLMConfig(model="gpt-4")
    result = await generate_prompt(llm_config, "template", "conv1")
    
    assert result == "Remember I like Python"
    mock_manager.request_llm_completion.assert_called_once()
    # Verify the role messages
    messages = mock_manager.request_llm_completion.call_args[0][3]
    assert messages[0]["content"] == "template"

@pytest.mark.asyncio
@patch("backend.api.services.prompt_service.get_conversation_manager_impl")
async def test_generate_prompt_no_tag(mock_get_manager):
    """Test that ValueError is raised if no update_prompt tag is present."""
    mock_manager = AsyncMock()
    mock_get_manager.return_value = mock_manager
    mock_manager.request_llm_completion = AsyncMock(return_value="No tags here")
    
    llm_config = LLMConfig(model="gpt-4")
    with pytest.raises(ValueError, match="No valid prompt found"):
        await generate_prompt(llm_config, "template", "conv1")

@pytest.mark.asyncio
@patch("backend.api.services.prompt_service.get_conversation_manager_impl")
async def test_generate_prompt_manager_none(mock_get_manager):
    """Test RuntimeError when conversation manager is unavailable."""
    mock_get_manager.return_value = None
    
    llm_config = LLMConfig(model="gpt-4")
    with pytest.raises(RuntimeError, match="Conversation manager implementation unavailable"):
        await generate_prompt(llm_config, "template", "conv1")

@pytest.mark.asyncio
@patch("backend.api.services.prompt_service.EventStore")
@patch("backend.api.services.prompt_service.get_contextual_events")
@patch("backend.api.services.prompt_service.generate_prompt")
async def test_build_remember_prompt_success(mock_gen_prompt, mock_get_ctx_events, mock_event_store_class):
    """Test the full orchestration of build_remember_prompt."""
    mock_user_settings_store = AsyncMock()
    mock_file_store = MagicMock()
    
    mock_get_ctx_events.return_value = "events string"
    mock_gen_prompt.return_value = "Final Prompt"
    
    # Mock settings
    mock_settings = MagicMock()
    mock_settings.llm_model = "gpt-4"
    mock_settings.llm_api_key = "sk-test"
    mock_settings.llm_base_url = "https://api.openai.com"
    mock_user_settings_store.load.return_value = mock_settings
    
    result = await build_remember_prompt(
        conversation_id="conv1",
        event_id=123,
        user_id="user1",
        user_settings_store=mock_user_settings_store,
        file_store=mock_file_store
    )
    
    assert result == "Final Prompt"
    mock_event_store_class.assert_called_once_with(
        sid="conv1",
        file_store=mock_file_store,
        user_id="user1"
    )
    mock_gen_prompt.assert_called_once()
    # Check LLMConfig passed to generate_prompt
    llm_config = mock_gen_prompt.call_args[0][0]
    assert llm_config.model == "gpt-4"
    assert llm_config.api_key.get_secret_value() == "sk-test"
    assert llm_config.base_url == "https://api.openai.com"

@pytest.mark.asyncio
@patch("backend.api.services.prompt_service.get_conversation_manager_impl")
async def test_generate_prompt_multiple_tags(mock_get_manager):
    """Test that the first update_prompt tag is matched (non-greedy or as per regex)."""
    mock_manager = AsyncMock()
    mock_get_manager.return_value = mock_manager
    mock_manager.request_llm_completion = AsyncMock(return_value="<update_prompt>First</update_prompt><update_prompt>Second</update_prompt>")
    
    llm_config = LLMConfig(model="gpt-4")
    result = await generate_prompt(llm_config, "template", "conv1")
    
    assert result == "First"

@pytest.mark.asyncio
@patch("backend.api.services.prompt_service.EventStore")
@patch("backend.api.services.prompt_service.get_contextual_events")
@patch("backend.api.services.prompt_service.generate_prompt")
async def test_build_remember_prompt_partial_settings(mock_gen_prompt, mock_get_ctx_events, mock_event_store_class):
    """Test orchestration when some settings are missing."""
    mock_user_settings_store = AsyncMock()
    mock_settings = MagicMock()
    mock_settings.llm_model = None
    mock_settings.llm_api_key = None
    mock_settings.llm_base_url = None
    mock_user_settings_store.load.return_value = mock_settings
    
    await build_remember_prompt(
        conversation_id="conv1",
        event_id=123,
        user_id="user1",
        user_settings_store=mock_user_settings_store,
        file_store=MagicMock()
    )
    
    llm_config = mock_gen_prompt.call_args[0][0]
    # LLMConfig should have defaults if settings were None
    assert llm_config.model is not None # Default in LLMConfig
    assert llm_config.api_key is None

@pytest.mark.asyncio
@patch("backend.api.services.prompt_service.EventStore")
async def test_build_remember_prompt_no_settings(mock_es):
    """Test failure when settings cannot be loaded."""
    mock_user_settings_store = AsyncMock()
    mock_user_settings_store.load.return_value = None
    
    with pytest.raises(ValueError, match="Settings not found"):
        await build_remember_prompt(
            conversation_id="conv1",
            event_id=123,
            user_id="user1",
            user_settings_store=mock_user_settings_store,
            file_store=MagicMock()
        )


