"""Regression fixtures for interactive prompt detection (realistic stdout snippets)."""

from __future__ import annotations

import pytest

from backend.execution.utils.prompt_detector import (
    InteractivePromptDetector,
    PromptType,
    suggest_noninteractive_command,
)


# Captured-style terminal snippets (not secrets).
FIXTURE_NPM_OK_PROCEED = "Need to install 1 package.\nOk to proceed? (y)\n"
FIXTURE_APT_CONTINUE = "After this operation, 10 MB will be used.\nDo you want to continue? [Y/n] "
FIXTURE_GENERIC_YN = "Really delete all files (y/n)? "
FIXTURE_PRESS_KEY = "Build succeeded.\nPress any key to continue . . .\n"


@pytest.mark.parametrize(
    ("fixture", "expected_type"),
    [
        (FIXTURE_NPM_OK_PROCEED, PromptType.OK_PROCEED),
        (FIXTURE_APT_CONTINUE, PromptType.YES_NO_CONFIRMATION),
        (FIXTURE_GENERIC_YN, PromptType.YES_NO_CONFIRMATION),
        (FIXTURE_PRESS_KEY, PromptType.PRESS_KEY),
    ],
)
def test_interactive_prompt_detector_matches_fixture(
    fixture: str, expected_type: PromptType
) -> None:
    det = InteractivePromptDetector(min_confidence=0.5)
    match = det.detect_prompt(fixture, last_n_lines=20)
    assert match is not None
    assert match.prompt_type == expected_type


def test_suggest_noninteractive_npm_install() -> None:
    assert suggest_noninteractive_command("npm install foo") == "npm install --yes foo"


def test_suggest_noninteractive_none_when_already_yes() -> None:
    assert suggest_noninteractive_command("npm install --yes foo") is None
