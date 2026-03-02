from unittest.mock import MagicMock, patch
from backend.llm.direct_clients import GeminiClient


def test_gemini_client_concatenates_system_messages():
    # Patch genai.Client to prevent any real SDK operations
    with patch("backend.llm.direct_clients.genai.Client") as mock_client_class:
        mock_instance = mock_client_class.return_value
        mock_chats = MagicMock()
        mock_instance.chats = mock_chats

        client = GeminiClient(model_name="gemini-1.5-pro", api_key="test-key")
        messages = [
            {"role": "system", "content": "Instruction 1"},
            {"role": "system", "content": "Instruction 2"},
            {"role": "user", "content": "Hello"},
        ]

        mock_chat_session = MagicMock()
        mock_chats.create.return_value = mock_chat_session
        mock_chat_session.send_message.return_value = MagicMock()

        client.completion(messages)

        # Verify system_instruction in config passed to create
        args, kwargs = mock_chats.create.call_args
        config = kwargs.get("config")
        assert config["system_instruction"] == "Instruction 1\n\nInstruction 2"


def test_gemini_client_maps_tools_correctly():
    with patch("backend.llm.direct_clients.genai.Client") as mock_client_class:
        mock_instance = mock_client_class.return_value
        mock_chats = MagicMock()
        mock_instance.chats = mock_chats

        client = GeminiClient(model_name="gemini-1.5-pro", api_key="test-key")
        messages = [{"role": "user", "content": "Hello"}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather info",
                    "parameters": {
                        "type": "object",
                        "properties": {"location": {"type": "string"}},
                        "required": ["location"],
                    },
                },
            }
        ]

        mock_chat_session = MagicMock()
        mock_chats.create.return_value = mock_chat_session
        mock_chat_session.send_message.return_value = MagicMock()

        client.completion(messages, tools=tools)

        # Verify tools in config
        args, kwargs = mock_chats.create.call_args
        config = kwargs.get("config")
        assert "tools" in config
        gemini_tools = config["tools"]
        assert len(gemini_tools) == 1
        assert "function_declarations" in gemini_tools[0]
        fd = gemini_tools[0]["function_declarations"][0]
        assert fd["name"] == "get_weather"
        assert fd["description"] == "Get weather info"
        assert fd["parameters"]["type"] == "object"


def test_gemini_client_sanitizes_kwargs():
    with patch("backend.llm.direct_clients.genai.Client") as mock_client_class:
        mock_instance = mock_client_class.return_value
        mock_chats = MagicMock()
        mock_instance.chats = mock_chats

        client = GeminiClient(model_name="gemini-1.5-pro", api_key="test-key")
        messages = [{"role": "user", "content": "Hello"}]

        mock_chat_session = MagicMock()
        mock_chats.create.return_value = mock_chat_session
        mock_chat_session.send_message.return_value = (
            MagicMock()
        )  # Ensure send_message returns a mock

        client.completion(
            messages,
            temperature=0.7,
            stream=False,
            reasoning_effort="high",
            metadata={"foo": "bar"},
        )

        # Verify kwargs passed to send_message
        send_args, send_kwargs = mock_chat_session.send_message.call_args
        assert "temperature" not in send_kwargs
        assert "reasoning_effort" not in send_kwargs
        assert "metadata" not in send_kwargs
        assert "stream" not in send_kwargs

        # Verify temperature in flattened config (merged **gen_cfg)
        args, kwargs = mock_chats.create.call_args
        config = kwargs.get("config")
        assert config["temperature"] == 0.7
        assert "generation_config" not in config
