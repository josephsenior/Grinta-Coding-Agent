"""Shared modal dialog base for the Grinta TUI.

Provides consistent styling and structure for all modal dialogs
(settings, sessions, help, confirm, add-skill, add-mcp).
"""

from __future__ import annotations

from typing import ClassVar, TypeVar

from textual.screen import ModalScreen

_T = TypeVar('_T')


class ModalDialog(ModalScreen[_T]):
    """Base class for modal dialogs with consistent styling and bindings.

    Subclasses should compose inside a container with id="dialog-container",
    use id="dialog-title" for the title, and id="dialog-buttons" for the
    button row to inherit shared CSS automatically.
    """

    DEFAULT_CSS = """
    ModalDialog {
        background: #060a14 70%;
        align: center middle;
    }
    ModalDialog > #dialog-container {
        background: #080c18;
        border: round #26324f;
        border-left: heavy #5eead4;
        padding: 2 3;
        width: auto;
        min-width: 52;
        max-width: 90%;
        height: auto;
        max-height: 92%;
    }
    ModalDialog #dialog-title {
        color: #c8d4e8;
        margin-bottom: 1;
    }
    ModalDialog #dialog-subtitle {
        color: #6f83aa;
        margin-bottom: 1;
        height: auto;
    }
    ModalDialog #dialog-body {
        color: #cbd5e1;
        margin-bottom: 2;
    }
    ModalDialog .field-label {
        color: #969aad;
        margin-top: 1;
    }
    ModalDialog #dialog-feedback {
        color: #8f9fc1;
        margin-top: 1;
    }
    ModalDialog #dialog-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 2;
    }
    ModalDialog #dialog-buttons Button {
        margin-left: 2;
    }
    """

    BINDINGS: ClassVar = [
        ('escape', 'dismiss(None)', 'Cancel'),
    ]
