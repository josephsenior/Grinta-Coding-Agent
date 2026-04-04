"""File editor module - Production implementation.

Provides file editing capabilities using the production-grade FileEditor.
"""

from backend.execution.utils.file_editor import FileEditor

# Create a singleton callable instance for agent skill wiring
_file_editor_instance = FileEditor()


def file_editor(*args, **kwargs):
    """File editor function interface.

    This function provides a callable interface to the FileEditor singleton.
    """
    return _file_editor_instance(*args, **kwargs)


__all__ = ['file_editor', 'FileEditor']
