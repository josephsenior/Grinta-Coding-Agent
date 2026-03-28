"""Mock FastAPI/Socket.IO server used for local testing and demos."""

import uvicorn
from fastapi import FastAPI, WebSocket

from backend.core.logger import forge_logger as logger
from backend.utils.shutdown_listener import should_continue

app = FastAPI()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Mock WebSocket endpoint for testing.

    Echoes back received messages with 'receive' prefix.

    Args:
        websocket: WebSocket connection

    """
    await websocket.accept()
    try:
        while should_continue():
            data = await websocket.receive_json()
            logger.debug("Received message: %s", data)
            response = {"message": f"receive {data}"}
            await websocket.send_json(response)
            logger.debug("Sent message: %s", response)
    except Exception as e:
        logger.debug("WebSocket Error: %s", e)


@app.get("/")
def read_root() -> dict[str, str]:
    """Root endpoint.

    Returns:
        Welcome message dictionary

    """
    return {"message": "This is a mock server"}


@app.get("/api/options/models")
def read_llm_models() -> list[str]:
    """Get mock list of available LLM models.

    Returns:
        List of mock GPT-4 model names

    """
    return ["gpt-4", "gpt-4-turbo-preview", "gpt-4-0314", "gpt-4-0613"]


@app.get("/api/options/agents")
def read_llm_agents() -> list[str]:
    """Get mock list of available agents.

    Returns:
        List containing Orchestrator

    """
    return ["Orchestrator"]


@app.get("/api/list-files")
def refresh_files() -> list[str]:
    """Get mock list of workspace files.

    Returns:
        List with single mock file

    """
    return ["hello_world.py"]


@app.get("/api/options/config")
def get_config() -> dict:
    """Get mock server configuration.

    Returns:
        Configuration dictionary with all required fields

    """
    return {
        "APP_MODE": "saas",
        "APP_SLUG": "Forge-pro",
        "GITHUB_CLIENT_ID": "mock_github_client_id",
        "POSTHOG_CLIENT_KEY": "mock_posthog_key",
        "PROVIDERS_CONFIGURED": ["openai", "anthropic"],
        "AUTH_URL": "https://auth.Forge.pro",
        "FEATURE_FLAGS": {
            "ENABLE_BILLING": True,
            "HIDE_LLM_SETTINGS": False,
            "ENABLE_JIRA": True,
            "ENABLE_JIRA_DC": True,
            "ENABLE_LINEAR": True,
        },
        "MAINTENANCE": None,
    }


@app.get("/api/options/security-analyzers")
def get_analyzers() -> list[str]:
    """Get mock list of security analyzers.

    Returns:
        Empty list (no analyzers in mock)

    """
    return []


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=3000, ws="websockets-sansio")
