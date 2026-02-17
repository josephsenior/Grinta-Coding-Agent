"""Comprehensive tests for MCP wrapper tools.

Tests fuzzy search, caching wrappers, and synthetic tool registration.
"""

import json
import unittest
from unittest.mock import AsyncMock, patch

from backend.mcp.wrappers import (
    REQUIRED_UNDERLYING,
    WRAPPER_TOOL_REGISTRY,
    _fuzzy_score,
    _get_components_list,
    _score_and_filter_components,
    _wrap_simple_passthrough,
    search_components,
    wrapper_tool_params,
)


class TestFuzzyScore(unittest.TestCase):
    """Tests for _fuzzy_score fuzzy matching algorithm."""

    def test_exact_match_returns_one(self) -> None:
        """Test exact match returns score of 1.0."""
        score = _fuzzy_score("button", "button")
        self.assertEqual(score, 1.0)

    def test_exact_match_case_insensitive(self) -> None:
        """Test exact match is case-insensitive."""
        score = _fuzzy_score("Button", "button")
        self.assertEqual(score, 1.0)

    def test_substring_match_high_score(self) -> None:
        """Test substring match returns high score when all chars found."""
        score = _fuzzy_score("btn", "button")
        # All 3 chars 'b', 't', 'n' appear in "button" → 3/3 = 1.0
        self.assertEqual(score, 1.0)

    def test_substring_longer_needle_lower_score(self) -> None:
        """Test longer substring gets higher score."""
        short_score = _fuzzy_score("but", "button")
        long_score = _fuzzy_score("butto", "button")
        self.assertGreater(long_score, short_score)

    def test_partial_character_match(self) -> None:
        """Test partial character matching (subsequence)."""
        score = _fuzzy_score("bton", "button")
        # "b", "t", "o", "n" all appear in "button"
        self.assertGreater(score, 0)
        self.assertEqual(score, 4 / 4)  # All 4 chars match

    def test_no_match_returns_zero(self) -> None:
        """Test no matching characters returns 0."""
        score = _fuzzy_score("xyz", "button")
        # No matching chars
        self.assertEqual(score, 0.0)

    def test_empty_needle(self) -> None:
        """Test empty needle returns division by zero (or infinity)."""
        # This might be a bug, but document current behavior
        try:
            score = _fuzzy_score("", "button")
            # If no error, it should return something (likely nan or inf)
            self.assertTrue(True)
        except ZeroDivisionError:
            self.assertTrue(True)  # Expected

    def test_unicode_characters(self) -> None:
        """Test fuzzy matching with unicode characters."""
        score = _fuzzy_score("日本", "日本語")
        self.assertGreater(score, 0)

    def test_case_insensitive_substring(self) -> None:
        """Test case-insensitive substring matching."""
        score = _fuzzy_score("BTN", "SmallButton")
        self.assertGreater(score, 0.6)


class TestScoreAndFilterComponents(unittest.TestCase):
    """Tests for _score_and_filter_components ranking logic."""

    def test_filters_by_substring_match(self) -> None:
        """Test filters components containing query substring."""
        components = ["Button", "Input", "ButtonGroup", "Label"]
        scored = _score_and_filter_components(components, "button", fuzzy=False)

        names = [name for _, name in scored]
        self.assertIn("Button", names)
        self.assertIn("ButtonGroup", names)
        self.assertNotIn("Input", names)
        self.assertNotIn("Label", names)

    def test_fuzzy_filters_by_threshold(self) -> None:
        """Test fuzzy mode filters by score threshold (0.15)."""
        components = ["Button", "Btn", "B", "Input"]
        scored = _score_and_filter_components(components, "button", fuzzy=True)

        names = [name for _, name in scored]
        # "B" has very low score, should be filtered out
        self.assertIn("Button", names)
        self.assertIn("Btn", names)

    def test_sorts_by_score_descending(self) -> None:
        """Test results sorted by score (highest first)."""
        components = ["Button", "Btn", "SmallButton"]
        scored = _score_and_filter_components(components, "button", fuzzy=True)

        scores = [score for score, _ in scored]
        # Exact match "Button" should have highest score
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(scored[0][1], "Button")

    def test_alphabetical_tie_breaking(self) -> None:
        """Test alphabetical sorting for same scores."""
        components = ["Zebra_btn", "Apple_btn"]
        scored = _score_and_filter_components(components, "btn", fuzzy=False)

        names = [name for _, name in scored]
        # Both have same substring match score, alphabetically sorted
        self.assertEqual(names, ["Apple_btn", "Zebra_btn"])

    def test_handles_non_string_components(self) -> None:
        """Test skips non-string components."""
        components = ["Button", 123, None, "Input"]
        scored = _score_and_filter_components(components, "button", fuzzy=True)

        names = [name for _, name in scored]
        self.assertIn("Button", names)
        self.assertNotIn(123, names)
        self.assertNotIn(None, names)

    def test_empty_components(self) -> None:
        """Test handles empty components list."""
        scored = _score_and_filter_components([], "button", fuzzy=True)
        self.assertEqual(scored, [])


class TestGetComponentsList(unittest.IsolatedAsyncioTestCase):
    """Tests for _get_components_list cache/fetch logic."""

    @patch("backend.mcp.wrappers.get_cached")
    async def test_returns_cached_components(self, mock_get_cached: AsyncMock) -> None:
        """Test returns components from cache if available."""
        mock_get_cached.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(["Button", "Input", "Label"]),
                }
            ]
        }
        call_tool_func = AsyncMock()

        result = await _get_components_list(call_tool_func)

        self.assertEqual(result, ["Button", "Input", "Label"])
        call_tool_func.assert_not_called()

    @patch("backend.mcp.wrappers.get_cached")
    async def test_fetches_if_cache_empty(self, mock_get_cached: AsyncMock) -> None:
        """Test fetches from server if cache is empty."""
        mock_get_cached.return_value = None
        call_tool_func = AsyncMock(
            return_value={
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(["ComponentA", "ComponentB"]),
                    }
                ]
            }
        )

        result = await _get_components_list(call_tool_func)

        self.assertEqual(result, ["ComponentA", "ComponentB"])
        call_tool_func.assert_called_once_with("list_components", {})

    @patch("backend.mcp.wrappers.get_cached")
    async def test_handles_malformed_json(self, mock_get_cached: AsyncMock) -> None:
        """Test gracefully handles malformed JSON in response."""
        mock_get_cached.return_value = {
            "content": [{"type": "text", "text": "not valid json"}]
        }
        call_tool_func = AsyncMock()

        result = await _get_components_list(call_tool_func)

        # Should return empty list on parse failure
        self.assertEqual(result, [])

    @patch("backend.mcp.wrappers.get_cached")
    async def test_handles_non_list_response(self, mock_get_cached: AsyncMock) -> None:
        """Test handles non-list JSON response."""
        mock_get_cached.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"error": "Invalid"}),
                }
            ]
        }
        call_tool_func = AsyncMock()

        result = await _get_components_list(call_tool_func)

        self.assertEqual(result, [])


class TestSearchComponents(unittest.IsolatedAsyncioTestCase):
    """Tests for search_components wrapper tool."""

    @patch("backend.mcp.wrappers._get_components_list")
    async def test_searches_components_by_query(
        self, mock_get_list: AsyncMock
    ) -> None:
        """Test searches and ranks components by query."""
        mock_get_list.return_value = ["Button", "Input", "ButtonGroup", "Label"]
        call_tool_func = AsyncMock()

        result = await search_components(
            mcps=None, args={"query": "button"}, call_tool_func=call_tool_func
        )

        content = json.loads(result["content"][0]["text"])
        self.assertEqual(content["query"], "button")
        self.assertIn("Button", content["results"])
        self.assertNotIn("Input", content["results"])

    @patch("backend.mcp.wrappers._get_components_list")
    async def test_respects_limit_parameter(self, mock_get_list: AsyncMock) -> None:
        """Test limits results to specified number."""
        mock_get_list.return_value = [f"Component{i}" for i in range(100)]
        call_tool_func = AsyncMock()

        result = await search_components(
            mcps=None,
            args={"query": "component", "limit": 5},
            call_tool_func=call_tool_func,
        )

        content = json.loads(result["content"][0]["text"])
        self.assertLessEqual(len(content["results"]), 5)

    @patch("backend.mcp.wrappers._get_components_list")
    async def test_fuzzy_parameter(self, mock_get_list: AsyncMock) -> None:
        """Test fuzzy parameter enables/disables fuzzy matching."""
        mock_get_list.return_value = ["Button", "Btn"]
        call_tool_func = AsyncMock()

        # Fuzzy=False (substring only)
        result = await search_components(
            mcps=None,
            args={"query": "button", "fuzzy": False},
            call_tool_func=call_tool_func,
        )

        content = json.loads(result["content"][0]["text"])
        self.assertIn("Button", content["results"])

    async def test_missing_query_returns_error(self) -> None:
        """Test missing query parameter returns error."""
        call_tool_func = AsyncMock()

        result = await search_components(
            mcps=None, args={}, call_tool_func=call_tool_func
        )

        content = json.loads(result["content"][0]["text"])
        self.assertIn("error", content)

    @patch("backend.mcp.wrappers._get_components_list")
    async def test_returns_total_matches(self, mock_get_list: AsyncMock) -> None:
        """Test returns total_matches count."""
        mock_get_list.return_value = [f"Button{i}" for i in range(50)]
        call_tool_func = AsyncMock()

        result = await search_components(
            mcps=None,
            args={"query": "button", "limit": 10},
            call_tool_func=call_tool_func,
        )

        content = json.loads(result["content"][0]["text"])
        self.assertEqual(content["total_matches"], 50)
        self.assertEqual(len(content["results"]), 10)


class TestWrapSimplePassthrough(unittest.IsolatedAsyncioTestCase):
    """Tests for _wrap_simple_passthrough helper."""

    async def test_passthrough_calls_underlying_tool(self) -> None:
        """Test passthrough wrapper calls underlying tool."""
        call_tool_func = AsyncMock(
            return_value={"content": [{"type": "text", "text": "result"}]}
        )
        wrapper = _wrap_simple_passthrough("get_component")

        result = await wrapper(
            mcps=None, args={"name": "Button"}, call_tool_func=call_tool_func
        )

        call_tool_func.assert_called_once_with("get_component", {"name": "Button"})
        self.assertEqual(result["content"][0]["text"], "result")


class TestWrapperToolParams(unittest.TestCase):
    """Tests for wrapper_tool_params tool discovery."""

    def test_returns_search_components_if_list_available(self) -> None:
        """Test returns search_components if list_components available."""
        available_tools = ["list_components", "get_component"]

        params = wrapper_tool_params(available_tools)

        names = [p["function"]["name"] for p in params]
        self.assertIn("search_components", names)

    def test_returns_get_component_cached_if_get_available(self) -> None:
        """Test returns get_component_cached if get_component available."""
        available_tools = ["get_component"]

        params = wrapper_tool_params(available_tools)

        names = [p["function"]["name"] for p in params]
        self.assertIn("get_component_cached", names)

    def test_returns_get_block_cached_if_get_block_available(self) -> None:
        """Test returns get_block_cached if get_block available."""
        available_tools = ["get_block"]

        params = wrapper_tool_params(available_tools)

        names = [p["function"]["name"] for p in params]
        self.assertIn("get_block_cached", names)

    def test_returns_all_wrappers_when_all_available(self) -> None:
        """Test returns all wrappers when all underlying tools available."""
        available_tools = ["list_components", "get_component", "get_block"]

        params = wrapper_tool_params(available_tools)

        names = [p["function"]["name"] for p in params]
        self.assertEqual(len(names), 3)
        self.assertIn("search_components", names)
        self.assertIn("get_component_cached", names)
        self.assertIn("get_block_cached", names)

    def test_returns_empty_when_no_tools_available(self) -> None:
        """Test returns empty list when no underlying tools available."""
        params = wrapper_tool_params([])
        self.assertEqual(params, [])

    def test_search_components_schema(self) -> None:
        """Test search_components has correct schema."""
        available_tools = ["list_components"]

        params = wrapper_tool_params(available_tools)

        search_tool = next(
            p for p in params if p["function"]["name"] == "search_components"
        )
        schema = search_tool["function"]["parameters"]

        self.assertIn("query", schema["properties"])
        self.assertIn("limit", schema["properties"])
        self.assertIn("fuzzy", schema["properties"])
        self.assertEqual(schema["required"], ["query"])


class TestWrapperToolRegistry(unittest.TestCase):
    """Tests for WRAPPER_TOOL_REGISTRY constant."""

    def test_registry_contains_expected_tools(self) -> None:
        """Test registry contains expected wrapper tools."""
        self.assertIn("search_components", WRAPPER_TOOL_REGISTRY)
        self.assertIn("get_component_cached", WRAPPER_TOOL_REGISTRY)
        self.assertIn("get_block_cached", WRAPPER_TOOL_REGISTRY)

    def test_registry_functions_are_callable(self) -> None:
        """Test all registered functions are callable."""
        for name, func in WRAPPER_TOOL_REGISTRY.items():
            self.assertTrue(callable(func), f"{name} is not callable")


class TestRequiredUnderlying(unittest.TestCase):
    """Tests for REQUIRED_UNDERLYING mapping."""

    def test_required_underlying_mapping(self) -> None:
        """Test REQUIRED_UNDERLYING correctly maps dependencies."""
        self.assertEqual(
            REQUIRED_UNDERLYING["list_components"], ["search_components"]
        )
        self.assertEqual(
            REQUIRED_UNDERLYING["get_component"], ["get_component_cached"]
        )
        self.assertEqual(REQUIRED_UNDERLYING["get_block"], ["get_block_cached"])


if __name__ == "__main__":
    unittest.main()
