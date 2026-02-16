"""Dynamic import utilities used across Forge for extensibility hooks."""

from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Any, NoReturn, TypeVar

T = TypeVar("T")


def import_from(qual_name: str) -> Any:
    """Import a value from its fully qualified name.

    This function is a utility to dynamically import any Python value (class, function, variable)
    from its fully qualified name. For example, 'forge.server.user_auth.UserAuth' would
    import the UserAuth class from the forge.server.user_auth module.

    Args:
        qual_name: A fully qualified name in the format 'module.submodule.name'
                  e.g. 'forge.server.user_auth.UserAuth'

    Returns:
        The imported value (class, function, or variable)

    Example:
        >>> UserAuth = import_from('forge.server.user_auth.UserAuth')
        >>> auth = UserAuth()

    """
    parts = qual_name.split(".")
    module_name = ".".join(parts[:-1])
    module = importlib.import_module(module_name)
    return getattr(module, parts[-1])


@lru_cache
def get_impl[T](cls: type[T], impl_name: str | None) -> type[T]:
    """Import and validate a named implementation of a base class.

    This function is an extensibility mechanism in Forge that allows runtime substitution
    of implementations. It enables applications to customize behavior by providing their own
    implementations of Forge base classes.

    The function ensures type safety by validating that the imported class is either the same as
    or a subclass of the specified base class.

    Args:
        cls: The base class that defines the interface
        impl_name: Fully qualified name of the implementation class, or None to use the base class
                  e.g. 'forge.server.conversation_manager.StandaloneConversationManager'

    Returns:
        The implementation class, which is guaranteed to be a subclass of cls

    Example:
        >>> # Get default implementation
        >>> ConversationManager = get_impl(ConversationManager, None)
        >>> # Get custom implementation
        >>> CustomManager = get_impl(ConversationManager, 'myapp.CustomConversationManager')

    Common Use Cases:
        - Server components (ConversationManager, UserAuth, etc.)
        - Storage implementations (ConversationStore, SettingsStore, etc.)
        - Service integrations (GitHub service)

    The implementation is cached to avoid repeated imports of the same class.

    """
    if impl_name is None:
        return cls

    impl_class = import_from(impl_name)
    if _impl_matches_base(cls, impl_class):
        return impl_class

    if _matches_reimported_base(cls, impl_class):
        return impl_class

    _raise_invalid_impl(cls, impl_class)
    return None


def _impl_matches_base(cls: type[T], impl_class: type[T]) -> bool:
    if cls == impl_class or issubclass(impl_class, cls):
        return True
    return _matches_qualified_name_in_mro(cls, impl_class)


def _matches_qualified_name_in_mro(base_cls: type[T], impl_class: type[T]) -> bool:
    base_mod = getattr(base_cls, "__module__", None)
    base_name = getattr(base_cls, "__name__", None)
    for candidate in getattr(impl_class, "__mro__", ()):
        if (
            getattr(candidate, "__module__", None) == base_mod
            and getattr(candidate, "__name__", None) == base_name
        ):
            return True
    return False


def _reimport_base_class(base_mod: str, base_name: str) -> type[Any] | None:
    try:
        imported_base = import_from(f"{base_mod}.{base_name}")
        if isinstance(imported_base, type):
            return imported_base
    except Exception:
        return None
    return None


def _matches_reimported_base(cls: type[T], impl_class: type[T]) -> bool:
    base_mod = getattr(cls, "__module__", None)
    base_name = getattr(cls, "__name__", None)
    if not (base_mod and base_name):
        return False
    imported_base = _reimport_base_class(base_mod, base_name)
    return bool(imported_base and issubclass(impl_class, imported_base))


def _raise_invalid_impl(cls: type[T], impl_class: type[T]) -> NoReturn:
    base_mod = getattr(cls, "__module__", None)
    base_name = getattr(cls, "__name__", None)
    impl_mod = getattr(impl_class, "__module__", None)
    impl_name = getattr(impl_class, "__name__", None)
    raise AssertionError(
        "Implementation class is not a subclass of the base class. "
        f"base={base_mod}.{base_name}, impl={impl_mod}.{impl_name}"
    )
