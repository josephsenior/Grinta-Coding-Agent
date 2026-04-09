"""Targeted symbol-not-found suggestions for structure-aware editing.

This module intentionally stays narrow: production call sites currently use it
for symbol lookup failures inside the structure editor. Keep heuristics focused
on high-confidence symbol suggestions rather than broad generic error advice.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass
class ErrorSuggestion:
    """A suggestion for fixing an error."""

    message: str
    suggestions: list[str]
    confidence: float  # 0.0 to 1.0
    auto_fixable: bool = False
    fix_code: str | None = None


class SmartErrorHandler:
    """Symbol-oriented error helper for structure-aware editing.

    Focus areas:
    - Common typo correction for symbol names
    - Fuzzy matching against available symbols
    - Concise listing of available symbols when no close match exists
    """

    # Common typos and corrections
    COMMON_TYPOS = {
        'functino': 'function',
        'fucntion': 'function',
        'funciton': 'function',
        'calss': 'class',
        'classs': 'class',
        'clas': 'class',
        'defination': 'definition',
        'definiton': 'definition',
        'improt': 'import',
        'imoprt': 'import',
        'retrun': 'return',
        'reutrn': 'return',
        'variabel': 'variable',
        'variabl': 'variable',
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
        def _count_label(count: int, singular: str, plural: str) -> str:
            return f'{count} {singular if count == 1 else plural}'

        available_info = []
        if classes:
            available_info.append(_count_label(len(classes), 'class', 'classes'))
        if functions:
            available_info.append(_count_label(len(functions), 'function', 'functions'))
        return f' ({", ".join(available_info)} available)' if available_info else ''

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
            + '\n'.join(f'  - {s}' for s in available_symbols[:10])
        )

        if len(available_symbols) > 10:
            message += f'\n  ... and {len(available_symbols) - 10} more'

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
