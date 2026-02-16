"""Utility helpers shared by action and observation serialization modules."""

from __future__ import annotations


def remove_fields(obj: dict | list | tuple, fields: set[str]) -> None:
    """Remove fields from an object.

    Parameters:
    - obj: The dictionary, or list of dictionaries to remove fields from
    - fields (set[str]): A set of field names to remove from the object
    """
    if isinstance(obj, dict):
        for field in fields:
            if field in obj:
                del obj[field]
        for value in obj.values():
            remove_fields(value, fields)
    elif isinstance(obj, list | tuple):
        for item in obj:
            remove_fields(item, fields)
    if hasattr(obj, "__dataclass_fields__"):
        msg = "Object must not contain dataclass, consider converting to dict first"
        raise ValueError(msg)
