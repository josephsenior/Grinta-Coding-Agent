import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.events.action import CmdRunAction
from backend.events.observation import CmdOutputObservation
from backend.runtime.action_execution_server import ActionExecutor

@pytest.fixture
def mock_executor():
    """Create a minimal mocked ActionExecutor to avoid full initialization."""
    with patch("os.makedirs"), \
         patch("backend.runtime.action_execution_server.SessionManager") as MockSessionManager, \
         patch("backend.runtime.action_execution_server.ActionExecutor._init_browser_async"):
        
        executor = ActionExecutor(
            plugins_to_load=[],
            work_dir="/tmp/test",
            username="testuser",
            user_id=1000,
            enable_browser=False
        )
        # Session manager is mocked by patch, but we can refine it
        executor.session_manager = MagicMock()
        return executor

@pytest.mark.asyncio
async def test_cmd_run_grep_pattern(mock_executor):
    """Test that grep_pattern filters the output correctly."""
    # Setup
    mock_session = MagicMock()
    # Mock return value of execute to be an Observation
    mock_obs = CmdOutputObservation(
        content="line1\nmatch this\nline3\nalso match this\nline5", 
        command_id=0,
        command="echo test"
    )
    
    # mock_session.execute is called via call_sync_from_async
    mock_session.execute.return_value = mock_obs
    
    # Configure session manager to return this session
    mock_executor.session_manager.get_session.return_value = mock_session
    
    # Create action with grep_pattern
    action = CmdRunAction(command="echo test", grep_pattern="match")
    
    # Act
    obs = await mock_executor.run(action)
    
    # Assert
    assert "match this" in obs.content
    assert "also match this" in obs.content
    assert "line1" not in obs.content
    assert "line3" not in obs.content
    assert "line5" not in obs.content

@pytest.mark.asyncio
async def test_cmd_run_grep_pattern_no_match(mock_executor):
    """Test grep_pattern when no lines match."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content="line1\nline2\nline3", 
        command_id=0,
        command="echo test"
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session
    
    action = CmdRunAction(command="echo test", grep_pattern="nomatch")
    
    obs = await mock_executor.run(action)
    assert "[Grep: No lines matched pattern 'nomatch']" in obs.content

@pytest.mark.asyncio
async def test_cmd_run_grep_pattern_invalid_regex(mock_executor):
    """Test grep_pattern with invalid regex."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content="line1\nline2", 
        command_id=0,
        command="echo test"
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session
    
    # Invalid regex (unbalanced parenthesis)
    action = CmdRunAction(command="echo test", grep_pattern="(")
    
    obs = await mock_executor.run(action)
    assert "[Grep Error: Invalid regex pattern '('" in obs.content
    assert "line1" in obs.content  # Should return original content on error

@pytest.mark.asyncio
async def test_cmd_run_background_spawns_session(mock_executor):
    """Test that is_background=True spawns a new session and returns immediately."""
    # Mock the create_session method to return a mock session
    mock_session = MagicMock()
    mock_session.read_output.return_value = "Background process started"
    mock_executor.session_manager.create_session.return_value = mock_session
    mock_executor.session_manager.get_session.return_value = MagicMock(cwd="/tmp") # Mock default session for cwd fallback
    
    action = CmdRunAction(command="long_running_task", is_background=True)
    
    with patch("time.sleep"):  # avoid actual sleep
        obs = await mock_executor.run(action)
        
    # Assert
    assert "Background task started" in obs.content
    assert "bg-" in obs.content
    
    # Verify session creation call
    mock_executor.session_manager.create_session.assert_called_once()
    
    # Verify input was written
    mock_session.write_input.assert_called_with("long_running_task\n")
