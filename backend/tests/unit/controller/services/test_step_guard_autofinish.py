"""Tests for StepGuardService auto-finish and file extraction fixes.

Covers:
- _extract_task_files regex for various extensions including NextJS bracket paths
- _try_auto_finish with 100% and 60% completion thresholds
- _check_recreation_auto_finish with sustained re-creation loops
- _normalize_path workspace prefix stripping
"""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.controller.services.step_guard_service import StepGuardService
from backend.events import EventSource
from backend.events.action.files import FileEditAction, FileWriteAction
from backend.events.action.message import MessageAction
from backend.events.observation.files import FileEditObservation


class TestExtractTaskFiles(unittest.TestCase):
    """Test _extract_task_files regex covers all required extensions."""

    def test_tsx_files(self):
        text = "Create src/app/page.tsx and src/app/layout.tsx"
        result = StepGuardService._extract_task_files(text)
        self.assertIn("src/app/page.tsx", result)
        self.assertIn("src/app/layout.tsx", result)

    def test_prisma_extension(self):
        text = "Create prisma/schema.prisma for the database"
        result = StepGuardService._extract_task_files(text)
        self.assertIn("prisma/schema.prisma", result)

    def test_env_example(self):
        text = "Create .env.example with database URL"
        result = StepGuardService._extract_task_files(text)
        self.assertTrue(any(".env.example" in f for f in result))

    def test_nextjs_bracket_path(self):
        text = "Create src/app/api/auth/[...nextauth]/route.ts"
        result = StepGuardService._extract_task_files(text)
        self.assertTrue(
            any("nextauth" in f and f.endswith("route.ts") for f in result)
        )

    def test_dynamic_route_brackets(self):
        text = "Create src/app/posts/[id]/page.tsx"
        result = StepGuardService._extract_task_files(text)
        self.assertTrue(any("[id]/page.tsx" in f for f in result))

    def test_json_config(self):
        text = "Create tsconfig.json and package.json"
        result = StepGuardService._extract_task_files(text)
        self.assertIn("tsconfig.json", result)
        self.assertIn("package.json", result)

    def test_mjs_extension(self):
        text = "Create postcss.config.mjs"
        result = StepGuardService._extract_task_files(text)
        self.assertIn("postcss.config.mjs", result)

    def test_framework_names_extracted_raw(self):
        """_extract_task_files is a raw regex — framework names may appear.

        Filtering of Next.js / Node.js happens downstream in
        _get_missing_task_files, not here.
        """
        text = "Use Next.js framework with Node.js runtime"
        result = StepGuardService._extract_task_files(text)
        # The regex matches .js extension — this is expected behavior
        # (downstream filtering removes false positives)
        self.assertIsInstance(result, set)

    def test_multiple_extensions(self):
        text = "src/app/globals.css src/lib/db.ts src/middleware.ts"
        result = StepGuardService._extract_task_files(text)
        self.assertIn("src/app/globals.css", result)
        self.assertIn("src/lib/db.ts", result)
        self.assertIn("src/middleware.ts", result)


class TestNormalizePath(unittest.TestCase):
    """Test _normalize_path strips workspace prefix and normalizes slashes."""

    def test_workspace_prefix(self):
        self.assertEqual(
            StepGuardService._normalize_path("/workspace/src/app/page.tsx"),
            "src/app/page.tsx",
        )

    def test_backslash_normalization(self):
        self.assertEqual(
            StepGuardService._normalize_path("workspace\\src\\app\\page.tsx"),
            "src/app/page.tsx",
        )

    def test_plain_path(self):
        self.assertEqual(
            StepGuardService._normalize_path("src/app/page.tsx"),
            "src/app/page.tsx",
        )

    def test_leading_trailing_slashes(self):
        self.assertEqual(
            StepGuardService._normalize_path("/src/app/page.tsx/"),
            "src/app/page.tsx",
        )


class TestTryAutoFinish(unittest.IsolatedAsyncioTestCase):
    """Test _try_auto_finish with completion thresholds."""

    def setUp(self):
        self.context = MagicMock()
        self.controller = MagicMock()
        self.controller.event_stream = MagicMock()
        self.service = StepGuardService(self.context)

    def _make_user_message(self, text: str) -> MessageAction:
        msg = MagicMock(spec=MessageAction)
        msg.__class__ = MessageAction
        type(msg).content = text
        type(msg).source = EventSource.USER
        return msg

    def _make_file_write(self, path: str) -> FileWriteAction:
        action = MagicMock(spec=FileWriteAction)
        action.__class__ = FileWriteAction
        type(action).path = path
        return action

    async def test_all_files_created_triggers_finish(self):
        """Auto-finish when all task files are created."""
        user_msg = self._make_user_message("Create src/app/page.tsx and src/app/layout.tsx")
        file1 = self._make_file_write("/workspace/src/app/page.tsx")
        file2 = self._make_file_write("/workspace/src/app/layout.tsx")

        state = MagicMock()
        state.history = [user_msg, file1, file2]
        self.controller.state = state

        result = await self.service._try_auto_finish(self.controller)

        self.assertTrue(result)
        self.controller.event_stream.add_event.assert_called_once()

    async def test_60_percent_triggers_finish(self):
        """Auto-finish at 60% completion threshold."""
        user_msg = self._make_user_message(
            "Create src/a.tsx src/b.tsx src/c.tsx src/d.tsx src/e.tsx"
        )
        # Create 3/5 = 60%
        writes = [
            self._make_file_write("/workspace/src/a.tsx"),
            self._make_file_write("/workspace/src/b.tsx"),
            self._make_file_write("/workspace/src/c.tsx"),
        ]
        state = MagicMock()
        state.history = [user_msg] + writes
        self.controller.state = state

        result = await self.service._try_auto_finish(self.controller)

        self.assertTrue(result)

    async def test_below_60_percent_does_not_finish(self):
        """Below 60% completion should NOT auto-finish."""
        user_msg = self._make_user_message(
            "Create src/a.tsx src/b.tsx src/c.tsx src/d.tsx src/e.tsx"
        )
        # Create 2/5 = 40% — below threshold
        writes = [
            self._make_file_write("/workspace/src/a.tsx"),
            self._make_file_write("/workspace/src/b.tsx"),
        ]
        state = MagicMock()
        state.history = [user_msg] + writes
        self.controller.state = state

        result = await self.service._try_auto_finish(self.controller)

        self.assertFalse(result)

    async def test_no_files_created_returns_false(self):
        """No files created means no auto-finish."""
        user_msg = self._make_user_message("Create src/app/page.tsx")
        state = MagicMock()
        state.history = [user_msg]
        self.controller.state = state

        result = await self.service._try_auto_finish(self.controller)

        self.assertFalse(result)

    async def test_no_task_files_returns_false(self):
        """No task files extractable means no auto-finish."""
        user_msg = self._make_user_message("Build me something cool")
        file1 = self._make_file_write("/workspace/src/app.tsx")
        state = MagicMock()
        state.history = [user_msg, file1]
        self.controller.state = state

        result = await self.service._try_auto_finish(self.controller)

        self.assertFalse(result)

    async def test_force_finish_flag_set(self):
        """Auto-finish action should have force_finish=True."""
        user_msg = self._make_user_message("Create src/app/page.tsx")
        file1 = self._make_file_write("/workspace/src/app/page.tsx")
        state = MagicMock()
        state.history = [user_msg, file1]
        self.controller.state = state

        await self.service._try_auto_finish(self.controller)

        args, _ = self.controller.event_stream.add_event.call_args
        action = args[0]
        self.assertTrue(getattr(action, "force_finish", False))


class TestCheckRecreationAutoFinish(unittest.IsolatedAsyncioTestCase):
    """Test _check_recreation_auto_finish for sustained re-creation loops."""

    def setUp(self):
        self.context = MagicMock()
        self.controller = MagicMock()
        self.controller.event_stream = MagicMock()
        self.service = StepGuardService(self.context)

    def _make_file_edit_obs(self, old: str, new: str) -> FileEditObservation:
        obs = MagicMock(spec=FileEditObservation)
        obs.__class__ = FileEditObservation
        type(obs).old_content = old
        type(obs).new_content = new
        return obs

    async def test_below_500_events_returns_false(self):
        """Should not fire before 500 events."""
        state = MagicMock()
        state.history = [MagicMock() for _ in range(400)]
        self.controller.state = state

        result = await self.service._check_recreation_auto_finish(self.controller)
        self.assertFalse(result)

    async def test_insufficient_recreates_returns_false(self):
        """Less than 8 re-creates should not trigger."""
        state = MagicMock()
        # 500+ events total, but only 5 re-creates in last 80
        filler = [MagicMock() for _ in range(500)]
        recreates = [self._make_file_edit_obs("same", "same") for _ in range(5)]
        state.history = filler + recreates
        self.controller.state = state

        result = await self.service._check_recreation_auto_finish(self.controller)
        self.assertFalse(result)

    async def test_too_many_new_creates_returns_false(self):
        """More than 2 new creates alongside re-creates should not trigger."""
        state = MagicMock()
        filler = [MagicMock() for _ in range(500)]
        recreates = [self._make_file_edit_obs("same", "same") for _ in range(10)]
        new_creates = [self._make_file_edit_obs("old", "new") for _ in range(3)]
        state.history = filler + recreates + new_creates
        self.controller.state = state

        result = await self.service._check_recreation_auto_finish(self.controller)
        self.assertFalse(result)

    @patch.object(StepGuardService, "_try_auto_finish", new_callable=AsyncMock)
    async def test_sustained_recreation_triggers_auto_finish(self, mock_auto_finish):
        """8+ re-creates with <=2 new creates after 500 events should trigger."""
        mock_auto_finish.return_value = True

        state = MagicMock()
        filler = [MagicMock() for _ in range(500)]
        recreates = [self._make_file_edit_obs("same", "same") for _ in range(10)]
        state.history = filler + recreates
        self.controller.state = state

        result = await self.service._check_recreation_auto_finish(self.controller)

        self.assertTrue(result)
        mock_auto_finish.assert_awaited_once_with(self.controller)


if __name__ == "__main__":
    unittest.main()
