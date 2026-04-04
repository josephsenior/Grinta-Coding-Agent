"""Tests for backend.execution.utils.prompt_detector — InteractivePromptDetector."""

from __future__ import annotations

from backend.execution.utils.prompt_detector import (
    InteractivePromptDetector,
    PromptPattern,
    PromptType,
    detect_interactive_prompt,
    suggest_noninteractive_command,
)

# ---------------------------------------------------------------------------
# PromptPattern
# ---------------------------------------------------------------------------


class TestPromptPattern:
    """Tests for PromptPattern."""

    def test_matches_true(self):
        p = PromptPattern(
            pattern=r'\(y/n\)',
            prompt_type=PromptType.YES_NO_CONFIRMATION,
            response='y\n',
            description='test',
        )
        assert p.matches('Continue? (y/n)') is True

    def test_matches_false(self):
        p = PromptPattern(
            pattern=r'\(y/n\)',
            prompt_type=PromptType.YES_NO_CONFIRMATION,
            response='y\n',
            description='test',
        )
        assert p.matches('no prompt here') is False

    def test_case_insensitive(self):
        p = PromptPattern(
            pattern=r'proceed',
            prompt_type=PromptType.OK_PROCEED,
            response='y\n',
            description='test',
        )
        assert p.matches('PROCEED now') is True

    def test_default_confidence(self):
        p = PromptPattern(
            pattern=r'x',
            prompt_type=PromptType.UNKNOWN,
            response='',
            description='test',
        )
        assert p.confidence == 1.0


# ---------------------------------------------------------------------------
# InteractivePromptDetector
# ---------------------------------------------------------------------------


class TestInteractivePromptDetector:
    """Tests for the InteractivePromptDetector class."""

    def test_detect_npm_prompt(self):
        detector = InteractivePromptDetector()
        output = 'Need to install the following packages:\n  some-tool@1.0\nOk to proceed? (y)'
        result = detector.detect_prompt(output)
        assert result is not None
        assert result.prompt_type == PromptType.OK_PROCEED

    def test_detect_yn_prompt(self):
        detector = InteractivePromptDetector()
        output = 'Some warning message\nDo you want to do this? (y/n) '
        result = detector.detect_prompt(output)
        assert result is not None
        assert result.prompt_type == PromptType.YES_NO_CONFIRMATION

    def test_detect_apt_prompt(self):
        detector = InteractivePromptDetector()
        output = (
            'After this operation, 50MB will be used.\nDo you want to continue? [Y/n] '
        )
        result = detector.detect_prompt(output)
        assert result is not None

    def test_detect_press_key(self):
        detector = InteractivePromptDetector()
        output = 'Installation complete.\nPress any key to continue'
        result = detector.detect_prompt(output)
        assert result is not None
        assert result.prompt_type == PromptType.PRESS_KEY

    def test_no_prompt_detected(self):
        detector = InteractivePromptDetector()
        output = 'Compiling...\nDone.'
        result = detector.detect_prompt(output)
        assert result is None

    def test_empty_output(self):
        detector = InteractivePromptDetector()
        assert detector.detect_prompt('') is None
        assert detector.detect_prompt('   ') is None

    def test_confidence_filter(self):
        detector = InteractivePromptDetector(min_confidence=0.99)
        # only exact 1.0 confidence patterns should match
        output = 'Ok to proceed? (y)'  # confidence 1.0
        result = detector.detect_prompt(output)
        assert result is not None

    def test_auto_response_disabled(self):
        detector = InteractivePromptDetector(enable_auto_response=False)
        pattern = PromptPattern(
            pattern=r'test',
            prompt_type=PromptType.YES_NO_CONFIRMATION,
            response='y\n',
            description='test',
            confidence=1.0,
        )
        assert detector.should_auto_respond(pattern) is False

    def test_no_auto_respond_for_password(self):
        detector = InteractivePromptDetector()
        pattern = PromptPattern(
            pattern=r'Password:',
            prompt_type=PromptType.PASSWORD,
            response='',
            description='password',
            confidence=1.0,
        )
        assert detector.should_auto_respond(pattern) is False

    def test_no_auto_respond_for_sudo(self):
        detector = InteractivePromptDetector()
        pattern = PromptPattern(
            pattern=r'sudo',
            prompt_type=PromptType.SUDO_PASSWORD,
            response='',
            description='sudo',
            confidence=1.0,
        )
        assert detector.should_auto_respond(pattern) is False

    def test_should_auto_respond_true(self):
        detector = InteractivePromptDetector()
        pattern = PromptPattern(
            pattern=r'test',
            prompt_type=PromptType.YES_NO_CONFIRMATION,
            response='y\n',
            description='test',
            confidence=1.0,
        )
        assert detector.should_auto_respond(pattern) is True

    def test_should_auto_respond_none_pattern(self):
        detector = InteractivePromptDetector()
        assert detector.should_auto_respond(None) is False

    def test_get_response(self):
        detector = InteractivePromptDetector()
        pattern = PromptPattern(
            pattern=r'test',
            prompt_type=PromptType.OK_PROCEED,
            response='yes\n',
            description='test',
        )
        assert detector.get_response(pattern) == 'yes\n'

    def test_looks_like_prompt_heuristic(self):
        detector = InteractivePromptDetector()
        assert detector._looks_like_prompt('Enter your choice:') is True
        assert detector._looks_like_prompt('Select an option [1/2/3]') is True
        assert detector._looks_like_prompt('Just regular output') is False


# ---------------------------------------------------------------------------
# detect_interactive_prompt convenience function
# ---------------------------------------------------------------------------


class TestDetectInteractivePrompt:
    """Tests for the convenience detect_interactive_prompt function."""

    def test_prompt_detected(self):
        output = 'Ok to proceed? (y)'
        is_prompt, response = detect_interactive_prompt(output)
        assert is_prompt is True
        assert response is not None

    def test_no_prompt(self):
        is_prompt, response = detect_interactive_prompt('Compiling... done.')
        assert is_prompt is False
        assert response is None


# ---------------------------------------------------------------------------
# suggest_noninteractive_command
# ---------------------------------------------------------------------------


class TestSuggestNoninteractiveCommand:
    """Tests for suggest_noninteractive_command."""

    def test_npx_command(self):
        result = suggest_noninteractive_command('npx create-react-app myapp')
        assert result is not None
        assert '--yes' in result

    def test_apt_install(self):
        result = suggest_noninteractive_command('apt install curl')
        assert result is not None
        assert '-y' in result

    def test_apt_get_install(self):
        result = suggest_noninteractive_command('apt-get install curl')
        assert result is not None
        assert '-y' in result

    def test_already_noninteractive(self):
        result = suggest_noninteractive_command('apt install -y curl')
        assert result is None

    def test_no_transform_available(self):
        result = suggest_noninteractive_command('ls -la')
        assert result is None

    def test_rm_command(self):
        result = suggest_noninteractive_command('rm somefile.txt')
        assert result is None

    def test_already_force_flag(self):
        result = suggest_noninteractive_command('rm --force somefile.txt')
        assert result is None


# ---------------------------------------------------------------------------
# PromptType enum
# ---------------------------------------------------------------------------


class TestPromptType:
    """Tests for PromptType enum."""

    def test_all_types_exist(self):
        assert PromptType.YES_NO_CONFIRMATION.value == 'yes_no'
        assert PromptType.PASSWORD.value == 'password'
        assert PromptType.SELECTION.value == 'selection'
        assert PromptType.PRESS_KEY.value == 'press_key'
        assert PromptType.OVERWRITE.value == 'overwrite'
        assert PromptType.SUDO_PASSWORD.value == 'sudo_password'
        assert PromptType.LICENSE_AGREEMENT.value == 'license'
        assert PromptType.UNKNOWN.value == 'unknown'
