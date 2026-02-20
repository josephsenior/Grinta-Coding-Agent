"""Tests for action model types – construction, properties, str/repr, ClassVar defaults."""

from __future__ import annotations

import unittest

from backend.core.enums import (
    ActionConfirmationStatus,
    ActionSecurityRisk,
    ActionType,
    FileEditSource,
    FileReadSource,
    RecallType,
)
from backend.core.schemas import AgentState, EventSource
from backend.events.action.action import Action
from backend.events.action.agent import (
    AgentRejectAction,
    AgentThinkAction,
    ChangeAgentStateAction,
    CondensationAction,
    CondensationRequestAction,
    PlaybookFinishAction,
    RecallAction,
    TaskTrackingAction,
)
from backend.events.action.commands import CmdRunAction
from backend.events.action.empty import NullAction
from backend.events.action.files import FileEditAction, FileReadAction, FileWriteAction
from backend.events.action.mcp import MCPAction
from backend.events.action.message import (
    MessageAction,
    StreamingChunkAction,
    SystemMessageAction,
)


# ---------------------------------------------------------------------------
# Action base
# ---------------------------------------------------------------------------
class TestActionBase(unittest.TestCase):
    def test_default_action_class_var(self):
        self.assertEqual(Action.action, "")

    def test_default_runnable(self):
        self.assertFalse(Action.runnable)

    def test_confirmation_state_default(self):
        a = Action()
        self.assertEqual(a.confirmation_state, ActionConfirmationStatus.CONFIRMED)

    def test_post_init_sets_confirmation(self):
        a = Action()
        a.__post_init__()
        self.assertEqual(a.confirmation_state, ActionConfirmationStatus.CONFIRMED)


# ---------------------------------------------------------------------------
# MessageAction
# ---------------------------------------------------------------------------
class TestMessageAction(unittest.TestCase):
    def test_defaults(self):
        m = MessageAction()
        self.assertEqual(m.content, "")
        self.assertIsNone(m.file_urls)
        self.assertIsNone(m.image_urls)
        self.assertFalse(m.wait_for_response)

    def test_action_type(self):
        self.assertEqual(MessageAction.action, ActionType.MESSAGE)

    def test_message_property(self):
        m = MessageAction(content="hello")
        self.assertEqual(m.message, "hello")

    def test_str_basic(self):
        m = MessageAction(content="hi")
        m.source = EventSource.USER
        s = str(m)
        self.assertIn("MessageAction", s)
        self.assertIn("hi", s)

    def test_str_with_images(self):
        m = MessageAction(content="pic", image_urls=["http://a.png", "http://b.png"])
        m.source = EventSource.AGENT
        s = str(m)
        self.assertIn("IMAGE_URL: http://a.png", s)
        self.assertIn("IMAGE_URL: http://b.png", s)

    def test_str_with_files(self):
        m = MessageAction(content="doc", file_urls=["f1.txt"])
        m.source = EventSource.USER
        s = str(m)
        self.assertIn("FILE_URL: f1.txt", s)

    def test_security_risk_default(self):
        self.assertEqual(MessageAction().security_risk, ActionSecurityRisk.UNKNOWN)


# ---------------------------------------------------------------------------
# SystemMessageAction
# ---------------------------------------------------------------------------
class TestSystemMessageAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(SystemMessageAction.action, ActionType.SYSTEM)

    def test_message_property(self):
        s = SystemMessageAction(content="sys prompt")
        self.assertEqual(s.message, "sys prompt")

    def test_tools_and_agent_class(self):
        s = SystemMessageAction(content="x", tools=[{"t": 1}], agent_class="TestAgent")
        self.assertEqual(len(s.tools), 1)
        self.assertEqual(s.agent_class, "TestAgent")

    def test_str_with_tools(self):
        s = SystemMessageAction(content="x", tools=[1, 2, 3], agent_class="A")
        s.source = EventSource.USER
        text = str(s)
        self.assertIn("3 tools available", text)
        self.assertIn("AGENT_CLASS: A", text)

    def test_str_no_tools(self):
        s = SystemMessageAction(content="only content")
        s.source = EventSource.USER
        text = str(s)
        self.assertNotIn("TOOLS", text)


# ---------------------------------------------------------------------------
# StreamingChunkAction
# ---------------------------------------------------------------------------
class TestStreamingChunkAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(StreamingChunkAction.action, ActionType.STREAMING_CHUNK)

    def test_not_runnable(self):
        self.assertFalse(StreamingChunkAction.runnable)

    def test_defaults(self):
        c = StreamingChunkAction()
        self.assertEqual(c.chunk, "")
        self.assertEqual(c.accumulated, "")
        self.assertFalse(c.is_final)

    def test_str_streaming(self):
        c = StreamingChunkAction(chunk="tok", accumulated="hello tok")
        self.assertIn("STREAMING", str(c))
        self.assertIn("9 chars", str(c))

    def test_str_final(self):
        c = StreamingChunkAction(accumulated="done", is_final=True)
        self.assertIn("FINAL", str(c))


# ---------------------------------------------------------------------------
# CmdRunAction
# ---------------------------------------------------------------------------
class TestCmdRunAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(CmdRunAction.action, ActionType.RUN)

    def test_runnable(self):
        self.assertTrue(CmdRunAction.runnable)

    def test_defaults(self):
        c = CmdRunAction()
        self.assertEqual(c.command, "")
        self.assertFalse(c.is_input)
        self.assertFalse(c.blocking)
        self.assertFalse(c.hidden)
        self.assertIsNone(c.cwd)

    def test_message_property(self):
        c = CmdRunAction(command="ls -la")
        self.assertIn("ls -la", c.message)

    def test_str_with_thought(self):
        c = CmdRunAction(command="pwd", thought="check dir")
        c.source = EventSource.AGENT
        s = str(c)
        self.assertIn("THOUGHT: check dir", s)
        self.assertIn("pwd", s)

    def test_str_no_thought(self):
        c = CmdRunAction(command="echo hi")
        c.source = EventSource.AGENT
        s = str(c)
        self.assertNotIn("THOUGHT", s)

    def test_security_risk(self):
        self.assertEqual(CmdRunAction().security_risk, ActionSecurityRisk.UNKNOWN)

    def test_confirmation_state(self):
        self.assertEqual(
            CmdRunAction().confirmation_state, ActionConfirmationStatus.CONFIRMED
        )


# ---------------------------------------------------------------------------
# FileReadAction
# ---------------------------------------------------------------------------
class TestFileReadAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(FileReadAction.action, ActionType.READ)

    def test_runnable(self):
        self.assertTrue(FileReadAction.runnable)

    def test_defaults(self):
        f = FileReadAction()
        self.assertEqual(f.path, "")
        self.assertEqual(f.start, 0)
        self.assertEqual(f.end, -1)

    def test_message_property(self):
        f = FileReadAction(path="/tmp/foo.py")
        self.assertIn("/tmp/foo.py", f.message)

    def test_impl_source_default(self):
        self.assertEqual(FileReadAction().impl_source, FileReadSource.DEFAULT)


# ---------------------------------------------------------------------------
# FileWriteAction
# ---------------------------------------------------------------------------
class TestFileWriteAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(FileWriteAction.action, ActionType.WRITE)

    def test_runnable(self):
        self.assertTrue(FileWriteAction.runnable)

    def test_message_property(self):
        f = FileWriteAction(path="out.txt")
        self.assertIn("out.txt", f.message)

    def test_repr(self):
        f = FileWriteAction(path="a.py", content="x=1", start=1, end=5, thought="fix")
        r = repr(f)
        self.assertIn("FileWriteAction", r)
        self.assertIn("a.py", r)
        self.assertIn("x=1", r)


# ---------------------------------------------------------------------------
# FileEditAction
# ---------------------------------------------------------------------------
class TestFileEditAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(FileEditAction.action, ActionType.EDIT)

    def test_runnable(self):
        self.assertTrue(FileEditAction.runnable)

    def test_default_impl_source(self):
        self.assertEqual(FileEditAction().impl_source, FileEditSource.FILE_EDITOR)

    def test_repr_llm_mode(self):
        f = FileEditAction(
            path="x.py",
            content="new code",
            thought="refactor",
            impl_source=FileEditSource.LLM_BASED_EDIT,
        )
        r = repr(f)
        self.assertIn("FileEditAction", r)
        self.assertIn("x.py", r)
        self.assertIn("new code", r)

    def test_repr_file_editor_create(self):
        f = FileEditAction(path="y.py", command="create", file_text="hello")
        r = repr(f)
        self.assertIn("Command: create", r)
        self.assertIn("hello", r)

    def test_repr_str_replace(self):
        f = FileEditAction(path="z.py", command="str_replace", old_str="a", new_str="b")
        r = repr(f)
        self.assertIn("Old String", r)
        self.assertIn("New String", r)

    def test_repr_insert(self):
        f = FileEditAction(path="w.py", command="insert", insert_line=5, new_str="line")
        r = repr(f)
        self.assertIn("Insert Line: 5", r)

    def test_repr_undo(self):
        f = FileEditAction(path="u.py", command="undo_edit")
        r = repr(f)
        self.assertIn("Undo Edit", r)


# ---------------------------------------------------------------------------
# MCPAction
# ---------------------------------------------------------------------------
class TestMCPAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(MCPAction.action, ActionType.MCP)

    def test_runnable(self):
        self.assertTrue(MCPAction.runnable)

    def test_defaults(self):
        m = MCPAction()
        self.assertEqual(m.name, "")
        self.assertEqual(m.arguments, {})

    def test_message_property(self):
        m = MCPAction(name="read_file", arguments={"path": "/a"})
        self.assertIn("read_file", m.message)

    def test_str_with_thought(self):
        m = MCPAction(name="tool", arguments={"k": "v"}, thought="need data")
        s = str(m)
        self.assertIn("THOUGHT: need data", s)
        self.assertIn("NAME: tool", s)


# ---------------------------------------------------------------------------
# NullAction
# ---------------------------------------------------------------------------
class TestNullAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(NullAction.action, ActionType.NULL)

    def test_message(self):
        self.assertEqual(NullAction().message, "No action")

    def test_not_runnable(self):
        self.assertFalse(NullAction.runnable)


# ---------------------------------------------------------------------------
# ChangeAgentStateAction
# ---------------------------------------------------------------------------
class TestChangeAgentStateAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(ChangeAgentStateAction.action, ActionType.CHANGE_AGENT_STATE)

    def test_message(self):
        c = ChangeAgentStateAction(agent_state=AgentState.RUNNING)
        self.assertIn("RUNNING", c.message)

    def test_default_agent_state(self):
        self.assertEqual(ChangeAgentStateAction().agent_state, "")


# ---------------------------------------------------------------------------
# PlaybookFinishAction
# ---------------------------------------------------------------------------
class TestPlaybookFinishAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(PlaybookFinishAction.action, ActionType.FINISH)

    def test_message_with_thought(self):
        f = PlaybookFinishAction(thought="done")
        self.assertEqual(f.message, "done")

    def test_message_without_thought(self):
        f = PlaybookFinishAction()
        self.assertIn("What's next", f.message)

    def test_outputs_default(self):
        self.assertEqual(PlaybookFinishAction().outputs, {})

    def test_force_finish_default(self):
        self.assertFalse(PlaybookFinishAction().force_finish)


# ---------------------------------------------------------------------------
# AgentThinkAction
# ---------------------------------------------------------------------------
class TestAgentThinkAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(AgentThinkAction.action, ActionType.THINK)

    def test_message(self):
        t = AgentThinkAction(thought="hmm")
        self.assertIn("hmm", t.message)


# ---------------------------------------------------------------------------
# AgentRejectAction
# ---------------------------------------------------------------------------
class TestAgentRejectAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(AgentRejectAction.action, ActionType.REJECT)

    def test_message_no_reason(self):
        r = AgentRejectAction()
        self.assertIn("rejected", r.message)

    def test_message_with_reason(self):
        r = AgentRejectAction(outputs={"reason": "unsafe"})
        self.assertIn("unsafe", r.message)


# ---------------------------------------------------------------------------
# RecallAction
# ---------------------------------------------------------------------------
class TestRecallAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(RecallAction.action, ActionType.RECALL)

    def test_default_recall_type(self):
        self.assertEqual(RecallAction().recall_type, RecallType.WORKSPACE_CONTEXT)

    def test_message_truncates(self):
        r = RecallAction(query="a" * 100)
        self.assertIn("a" * 50, r.message)
        # Should truncate at 50 chars
        self.assertNotIn("a" * 51, r.message)

    def test_str(self):
        r = RecallAction(query="find tests")
        s = str(r)
        self.assertIn("RecallAction", s)
        self.assertIn("find tests", s)


# ---------------------------------------------------------------------------
# CondensationAction
# ---------------------------------------------------------------------------
class TestCondensationAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(CondensationAction.action, ActionType.CONDENSATION)

    def test_with_event_ids(self):
        c = CondensationAction(forgotten_event_ids=[1, 2, 3])
        self.assertEqual(c.forgotten, [1, 2, 3])

    def test_with_event_range(self):
        c = CondensationAction(forgotten_events_start_id=5, forgotten_events_end_id=10)
        self.assertEqual(c.forgotten, [5, 6, 7, 8, 9, 10])

    def test_with_summary(self):
        c = CondensationAction(
            forgotten_event_ids=[1],
            summary="condensed",
            summary_offset=0,
        )
        self.assertIn("condensed", c.message)

    def test_message_without_summary(self):
        c = CondensationAction(forgotten_event_ids=[1, 2])
        self.assertIn("dropping", c.message)

    def test_invalid_config_raises(self):
        # Both event_ids and event_range → invalid
        with self.assertRaises(ValueError):
            CondensationAction(
                forgotten_event_ids=[1],
                forgotten_events_start_id=2,
                forgotten_events_end_id=3,
            )

    def test_no_ids_and_no_range_raises(self):
        with self.assertRaises(ValueError):
            CondensationAction()

    def test_summary_without_offset_raises(self):
        with self.assertRaises(ValueError):
            CondensationAction(forgotten_event_ids=[1], summary="s")

    def test_offset_without_summary_raises(self):
        with self.assertRaises(ValueError):
            CondensationAction(forgotten_event_ids=[1], summary_offset=0)


# ---------------------------------------------------------------------------
# CondensationRequestAction
# ---------------------------------------------------------------------------
class TestCondensationRequestAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(
            CondensationRequestAction.action, ActionType.CONDENSATION_REQUEST
        )

    def test_message(self):
        self.assertIn("condensation", CondensationRequestAction().message)


# ---------------------------------------------------------------------------
# TaskTrackingAction
# ---------------------------------------------------------------------------
class TestTaskTrackingAction(unittest.TestCase):
    def test_action_type(self):
        self.assertEqual(TaskTrackingAction.action, ActionType.TASK_TRACKING)

    def test_message_empty(self):
        t = TaskTrackingAction()
        self.assertIn("Clearing", t.message)

    def test_message_one_task(self):
        t = TaskTrackingAction(task_list=[{"id": 1, "status": "done"}])
        self.assertIn("1 task", t.message)

    def test_message_multiple_tasks(self):
        t = TaskTrackingAction(task_list=[{"id": 1}, {"id": 2}, {"id": 3}])
        self.assertIn("3 task items", t.message)

    def test_default_command(self):
        self.assertEqual(TaskTrackingAction().command, "view")


if __name__ == "__main__":
    unittest.main()
