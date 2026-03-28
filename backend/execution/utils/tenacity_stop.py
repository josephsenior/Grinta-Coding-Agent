"""Custom Tenacity stop condition integrated with runtime shutdown hooks."""

from typing import TYPE_CHECKING

from tenacity.stop import stop_base

from backend.utils.shutdown_listener import should_exit

if TYPE_CHECKING:
    from tenacity import RetryCallState


class stop_if_should_exit(stop_base):
    """Stop if the should_exit flag is set."""

    def __call__(self, retry_state: "RetryCallState") -> bool:
        """Return True when the global shutdown signal has been triggered."""
        return should_exit()
