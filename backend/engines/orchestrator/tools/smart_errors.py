"""Smart error messages with helpful suggestions and fuzzy matching.

Provides intelligent error messages when edits fail:
- Fuzzy matching for typos in symbol names
- Suggestions for similar symbols
- Context-aware error messages
- Auto-correction hints
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any


@dataclass
class ErrorSuggestion:
    """A suggestion for fixing an error."""

    message: str
    suggestions: list[str]
    confidence: float  # 0.0 to 1.0
    auto_fixable: bool = False
    fix_code: str | None = None


class SmartErrorHandler:
    """Intelligent error handler that provides helpful suggestions.

    Features:
    - Fuzzy matching for typos ("functino" → "function")
    - Similar symbol suggestions
    - Context-aware error messages
    - Auto-fix recommendations
    """

    # Common typos and corrections
    COMMON_TYPOS = {
        "functino": "function",
        "fucntion": "function",
        "funciton": "function",
        "calss": "class",
        "classs": "class",
        "clas": "class",
        "defination": "definition",
        "definiton": "definition",
        "improt": "import",
        "imoprt": "import",
        "retrun": "return",
        "reutrn": "return",
        "variabel": "variable",
        "variabl": "variable",
    }

    @staticmethod
    def _check_common_typo(symbol_name: str) -> ErrorSuggestion | None:
        """Check if symbol is a common typo.

        Args:
            symbol_name: Symbol to check

        Returns:
            ErrorSuggestion if typo found, None otherwise

        """
        if symbol_name.lower() in SmartErrorHandler.COMMON_TYPOS:
            correction = SmartErrorHandler.COMMON_TYPOS[symbol_name.lower()]
            return ErrorSuggestion(
                message=f"Symbol '{symbol_name}' not found. Did you mean '{correction}'?",
                suggestions=[correction],
                confidence=0.95,
                auto_fixable=True,
                fix_code=correction,
            )
        return None

    @staticmethod
    def _create_fuzzy_match_suggestion(
        symbol_name: str, close_matches: list[str]
    ) -> ErrorSuggestion:
        """Create suggestion from fuzzy matches.

        Args:
            symbol_name: Symbol that was not found
            close_matches: List of close matches

        Returns:
            ErrorSuggestion with matches

        """
        best_match = close_matches[0]
        similarity = difflib.SequenceMatcher(None, symbol_name, best_match).ratio()

        if similarity > 0.9:
            message = f"Symbol '{symbol_name}' not found. Did you mean '{best_match}'?"
            auto_fixable = True
        elif similarity > 0.7:
            message = f"Symbol '{symbol_name}' not found. Similar symbols: {', '.join(close_matches[:3])}"
            auto_fixable = False
        else:
            message = f"Symbol '{symbol_name}' not found. Possible matches: {', '.join(close_matches[:3])}"
            auto_fixable = False

        return ErrorSuggestion(
            message=message,
            suggestions=close_matches,
            confidence=similarity,
            auto_fixable=auto_fixable,
            fix_code=best_match if auto_fixable else None,
        )

    @staticmethod
    def _group_symbols_by_type(
        available_symbols: list[str],
    ) -> tuple[list[str], list[str]]:
        """Group symbols into functions and classes.

        Args:
            available_symbols: List of available symbols

        Returns:
            Tuple of (functions, classes)

        """
        functions = [s for s in available_symbols if not s[0].isupper()]
        classes = [s for s in available_symbols if s[0].isupper()]
        return functions, classes

    @staticmethod
    def _build_symbol_context(classes: list[str], functions: list[str]) -> str:
        """Build context string describing available symbols.

        Args:
            classes: List of class names
            functions: List of function names

        Returns:
            Context string

        """
        available_info = []
        if classes:
            available_info.append(f"{len(classes)} classes")
        if functions:
            available_info.append(f"{len(functions)} functions")
        return f" ({', '.join(available_info)} available)" if available_info else ""

    @staticmethod
    def _build_symbol_list_message(
        symbol_name: str, available_symbols: list[str], context: str
    ) -> str:
        """Build message listing available symbols.

        Args:
            symbol_name: Symbol that was not found
            available_symbols: Available symbols list
            context: Context string

        Returns:
            Formatted message

        """
        message = (
            f"Symbol '{symbol_name}' not found{context}. Available symbols:\n"
            + "\n".join(f"  - {s}" for s in available_symbols[:10])
        )

        if len(available_symbols) > 10:
            message += f"\n  ... and {len(available_symbols) - 10} more"

        return message

    @staticmethod
    def _create_available_symbols_message(
        symbol_name: str, available_symbols: list[str], max_suggestions: int
    ) -> ErrorSuggestion:
        """Create message showing available symbols.

        Args:
            symbol_name: Symbol that was not found
            available_symbols: Available symbols list
            max_suggestions: Max suggestions to show

        Returns:
            ErrorSuggestion with available symbols

        """
        if not available_symbols:
            return ErrorSuggestion(
                message=f"Symbol '{symbol_name}' not found and no symbols are available in this file.",
                suggestions=[],
                confidence=0.0,
            )

        functions, classes = SmartErrorHandler._group_symbols_by_type(available_symbols)
        context = SmartErrorHandler._build_symbol_context(classes, functions)
        message = SmartErrorHandler._build_symbol_list_message(
            symbol_name, available_symbols, context
        )

        return ErrorSuggestion(
            message=message,
            suggestions=available_symbols[:max_suggestions],
            confidence=0.0,
        )

    @staticmethod
    def symbol_not_found(
        symbol_name: str, available_symbols: list[str], max_suggestions: int = 5
    ) -> ErrorSuggestion:
        """Generate error message when a symbol is not found.

        Args:
            symbol_name: The symbol that was not found
            available_symbols: List of available symbols
            max_suggestions: Maximum number of suggestions to return

        Returns:
            ErrorSuggestion with helpful hints

        """
        # Check for common typos
        if typo_suggestion := SmartErrorHandler._check_common_typo(symbol_name):
            return typo_suggestion

        # Try fuzzy matching
        close_matches = difflib.get_close_matches(
            symbol_name, available_symbols, n=max_suggestions, cutoff=0.6
        )

        if close_matches:
            return SmartErrorHandler._create_fuzzy_match_suggestion(
                symbol_name, close_matches
            )

        # No matches - show available symbols
        return SmartErrorHandler._create_available_symbols_message(
            symbol_name, available_symbols, max_suggestions
        )

    @staticmethod
    def _analyze_indent_error(error_lower: str) -> tuple[list[str], float]:
        """Analyze indentation errors."""
        if "unexpected indent" in error_lower or "indentation" in error_lower:
            return [
                "Check your indentation - Python requires consistent spacing",
                "Make sure you're using either tabs or spaces, not both",
            ], 0.8
        return [], 0.5

    @staticmethod
    def _analyze_string_error(error_lower: str) -> tuple[list[str], float]:
        """Analyze string termination errors."""
        if "unterminated string" in error_lower:
            return [
                "You have an unclosed string - check for missing quotes",
                "Look for unescaped quotes inside your string",
            ], 0.9
        return [], 0.5

    @staticmethod
    def _check_missing_colon(code_context: str) -> str | None:
        """Check for missing colon in code context.

        Args:
            code_context: Code context to check

        Returns:
            Suggestion message or None

        """
        if ":" in code_context:
            return "Check for missing colons after if/for/def/class statements"
        return None

    @staticmethod
    def _check_unmatched_parentheses(code_context: str) -> str | None:
        """Check for unmatched parentheses in code context.

        Args:
            code_context: Code context to check

        Returns:
            Suggestion message or None

        """
        if "(" in code_context and ")" not in code_context:
            return "You might have unmatched parentheses"
        return None

    @staticmethod
    def _check_unmatched_brackets(code_context: str) -> str | None:
        """Check for unmatched brackets in code context.

        Args:
            code_context: Code context to check

        Returns:
            Suggestion message or None

        """
        if "[" in code_context and "]" not in code_context:
            return "You might have unmatched brackets"
        return None

    @staticmethod
    def _analyze_invalid_syntax(
        error_lower: str, code_context: str | None
    ) -> tuple[list[str], float]:
        """Analyze invalid syntax errors."""
        if "invalid syntax" not in error_lower:
            return [], 0.5

        code_ctx = code_context or ""
        suggestions = []

        if suggestion := SmartErrorHandler._check_missing_colon(code_ctx):
            suggestions.append(suggestion)
        if suggestion := SmartErrorHandler._check_unmatched_parentheses(code_ctx):
            suggestions.append(suggestion)
        if suggestion := SmartErrorHandler._check_unmatched_brackets(code_ctx):
            suggestions.append(suggestion)

        suggestions.append("Double-check your syntax against language documentation")

        return suggestions, 0.6

    @staticmethod
    def _analyze_eof_error(error_lower: str) -> tuple[list[str], float]:
        """Analyze unexpected EOF errors."""
        if "unexpected eof" in error_lower or "unexpected end" in error_lower:
            return [
                "File ends unexpectedly - check for unclosed brackets/braces",
                "Make sure all functions and classes are complete",
            ], 0.85
        return [], 0.5

    @staticmethod
    def _analyze_undefined_error(error_lower: str) -> tuple[list[str], float]:
        """Analyze undefined symbol errors."""
        if "undefined" in error_lower or "not defined" in error_lower:
            return [
                "This symbol is used before being defined",
                "Check for typos in the variable/function name",
            ], 0.75
        return [], 0.5

    @staticmethod
    def _build_error_message(
        error_message: str,
        line_number: int | None,
        code_context: str | None,
        suggestions: list[str],
    ) -> str:
        """Build formatted error message."""
        message_parts = [f"Syntax Error: {error_message}"]

        if line_number:
            message_parts.append(f"at line {line_number}")

        if code_context:
            message_parts.append(f"\nContext:\n{code_context}")

        if suggestions:
            message_parts.append("\nSuggestions:")
            for i, suggestion in enumerate(suggestions, 1):
                message_parts.append(f"  {i}. {suggestion}")

        return "\n".join(message_parts)

    @staticmethod
    def syntax_error(
        error_message: str,
        line_number: int | None = None,
        code_context: str | None = None,
    ) -> ErrorSuggestion:
        """Generate helpful message for syntax errors.

        Args:
            error_message: Original error message
            line_number: Line where error occurred
            code_context: Code surrounding the error

        Returns:
            ErrorSuggestion with context and hints

        """
        error_lower = error_message.lower()
        all_suggestions = []
        confidence = 0.5

        # Analyze different error patterns
        analyzers = [
            SmartErrorHandler._analyze_indent_error,
            SmartErrorHandler._analyze_string_error,
            lambda el: SmartErrorHandler._analyze_invalid_syntax(el, code_context),
            SmartErrorHandler._analyze_eof_error,
            SmartErrorHandler._analyze_undefined_error,
        ]

        for analyzer in analyzers:
            suggestions, conf = analyzer(error_lower)
            if suggestions:
                all_suggestions.extend(suggestions)
                confidence = max(confidence, conf)

        # Build formatted message
        message = SmartErrorHandler._build_error_message(
            error_message, line_number, code_context, all_suggestions
        )

        return ErrorSuggestion(
            message=message, suggestions=all_suggestions, confidence=confidence
        )

    @staticmethod
    def file_not_found(
        path: str, similar_files: list[str] | None = None
    ) -> ErrorSuggestion:
        """Generate error message when file is not found.

        Args:
            path: The file that was not found
            similar_files: List of similar file paths

        Returns:
            ErrorSuggestion with file suggestions

        """
        if not similar_files:
            return ErrorSuggestion(
                message=f"File not found: {path}", suggestions=[], confidence=0.0
            )

        # Fuzzy match file paths
        close_matches = difflib.get_close_matches(
            path, similar_files, n=5, cutoff=0.5
        )

        if close_matches:
            best_match = close_matches[0]
            similarity = difflib.SequenceMatcher(None, path, best_match).ratio()

            message = f"File not found: {path}\n\nDid you mean one of these?"
            for match in close_matches[:3]:
                message += f"\n  - {match}"

            return ErrorSuggestion(
                message=message,
                suggestions=close_matches,
                confidence=similarity,
                auto_fixable=similarity > 0.85,
                fix_code=best_match if similarity > 0.85 else None,
            )

        return ErrorSuggestion(
            message=f"File not found: {path}\n\nNo similar files found.",
            suggestions=[],
            confidence=0.0,
        )

    @staticmethod
    def whitespace_mismatch(
        expected_indent: str, actual_indent: str, line_number: int
    ) -> ErrorSuggestion:
        """Generate error for whitespace/indentation mismatches.

        Args:
            expected_indent: Expected indentation style
            actual_indent: Actual indentation found
            line_number: Line number with issue

        Returns:
            ErrorSuggestion with fix hints

        """
        expected_type = "tabs" if "\t" in expected_indent else "spaces"
        actual_type = "tabs" if "\t" in actual_indent else "spaces"

        if expected_type != actual_type:
            message = (
                f"Indentation mismatch at line {line_number}:\n"
                f"  Expected: {expected_type}\n"
                f"  Found: {actual_type}\n\n"
                f"This file uses {expected_type} for indentation. "
                f"Please be consistent."
            )
        else:
            expected_count = len(expected_indent)
            actual_count = len(actual_indent)
            message = (
                f"Indentation error at line {line_number}:\n"
                f"  Expected: {expected_count} {expected_type}\n"
                f"  Found: {actual_count} {actual_type}\n\n"
                f"Check your editor's tab/space settings."
            )

        return ErrorSuggestion(
            message=message,
            suggestions=[
                "Enable 'show whitespace' in your editor to see tabs vs. spaces",
                "Configure your editor to use consistent indentation",
                "Use an auto-formatter like Black (Python) or Prettier (JS)",
            ],
            confidence=1.0,
            auto_fixable=True,
        )

    @staticmethod
    def suggest_similar(
        target: str, candidates: list[str], threshold: float = 0.6
    ) -> list[str]:
        """Find similar strings using fuzzy matching.

        Args:
            target: String to match
            candidates: List of candidate strings
            threshold: Minimum similarity ratio (0.0-1.0)

        Returns:
            List of similar strings, sorted by similarity

        """
        return difflib.get_close_matches(target, candidates, n=10, cutoff=threshold)

    @staticmethod
    def format_edit_conflict(
        path: str, your_edit: str, other_edit: str
    ) -> ErrorSuggestion:
        """Format message for edit conflicts in multi-file refactoring.

        Args:
            path: File with conflict
            your_edit: Description of your edit
            other_edit: Description of conflicting edit

        Returns:
            ErrorSuggestion explaining the conflict

        """
        message = (
            f"Edit conflict in {path}:\n\n"
            f"Your edit: {your_edit}\n"
            f"Conflicts with: {other_edit}\n\n"
            f"These edits cannot be applied simultaneously."
        )

        suggestions = [
            "Apply one edit at a time",
            "Merge the edits manually",
            "Use a different approach that doesn't conflict",
        ]

        return ErrorSuggestion(message=message, suggestions=suggestions, confidence=1.0)

    @staticmethod
    def validate_edit_result(
        original_code: str,
        new_code: str,
        expected_changes: dict[str, Any] | None = None,
    ) -> ErrorSuggestion | None:
        """Validate an edit result and suggest improvements if needed.

        Args:
            original_code: Original code before edit
            new_code: Code after edit
            expected_changes: Expected changes (optional)

        Returns:
            ErrorSuggestion if issues found, None if OK

        """
        # Check if edit actually changed something
        if original_code == new_code:
            return ErrorSuggestion(
                message="Edit did not change anything. Verify your target location.",
                suggestions=[
                    "Double-check the symbol name",
                    "Verify the file path",
                    "Check if the code is already in the desired state",
                ],
                confidence=0.9,
            )

        # Check for dramatic size changes (might indicate error)
        original_lines = len(original_code.split("\n"))
        new_lines = len(new_code.split("\n"))

        if original_lines > 100 and new_lines < original_lines * 0.1:
            return ErrorSuggestion(
                message=f"Warning: File shrank dramatically ({original_lines} → {new_lines} lines). "
                f"This might indicate an error.",
                suggestions=[
                    "Review the changes carefully",
                    "Make sure you didn't accidentally delete important code",
                    "Consider rolling back if this wasn't intentional",
                ],
                confidence=0.7,
            )

        return None
