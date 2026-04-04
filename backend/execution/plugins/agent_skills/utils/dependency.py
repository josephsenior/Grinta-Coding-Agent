"""Utility to dynamically import agent skill functions into plugin namespaces."""

from types import ModuleType


def import_functions(
    module: ModuleType, function_names: list[str], target_globals: dict[str, object]
) -> None:
    """Import specified functions from a module into target globals namespace.

    Args:
        module: The source module to import functions from.
        function_names: List of function names to import from the module.
        target_globals: Target globals dictionary to import functions into.

    Raises:
        ValueError: If any specified function name is not found in the module.

    """
    for name in function_names:
        if hasattr(module, name):
            target_globals[name] = getattr(module, name)
        else:
            msg = f'Function {name} not found in {module.__name__}'
            raise ValueError(msg)
