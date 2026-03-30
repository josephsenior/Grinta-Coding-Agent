"""Tenacity stop condition integrating App shutdown listener."""

from typing import TYPE_CHECKING

from tenacity.stop import stop_base

from backend.utils.shutdown_listener import should_exit


if TYPE_CHECKING:
    from tenacity import RetryCallState


class stop_if_should_exit(stop_base):
    """Stop if the should_exit flag is set."""

    def __call__(self, retry_state: "RetryCallState") -> bool:
        """Check if retry should stop based on shutdown flag.

        Args:
            retry_state: The retry call state from tenacity.

        Returns:
            bool: True if retry should stop, False otherwise.

        """
        # Resolve from the canonical module to ensure monkeypatches always apply
        from importlib import import_module

        mod = import_module("backend.utils.tenacity_stop")
        # Consider both the canonical module and this module's binding
        local = globals().get("should_exit")
        try:
            if mod.should_exit():
                return True
        except Exception:
            pass
        return bool(local()) if callable(local) else False
