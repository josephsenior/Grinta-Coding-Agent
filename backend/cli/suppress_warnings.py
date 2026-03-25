"""Module to suppress common warnings in CLI mode."""

import warnings


def suppress_cli_warnings() -> None:
    """Suppress common warnings that appear during CLI usage."""
    warnings.filterwarnings(
        "ignore",
        message="Couldn't find ffmpeg or avconv - defaulting to ffmpeg, but may not work",
        category=RuntimeWarning,
    )
    warnings.filterwarnings(
        "ignore", message=".*Pydantic serializer warnings.*", category=UserWarning
    )
    warnings.filterwarnings(
        "ignore",
        message=".*PydanticSerializationUnexpectedValue.*",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore", message=".*Expected .* fields but got .*", category=UserWarning
    )
    warnings.filterwarnings("ignore", category=SyntaxWarning, module="pydub\\.utils")


suppress_cli_warnings()
