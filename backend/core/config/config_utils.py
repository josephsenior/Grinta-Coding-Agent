"""Helpers for loading and normalising Forge configuration data."""

from types import NoneType, UnionType
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from backend.core.constants import FORGE_DEFAULT_AGENT, FORGE_MAX_ITERATIONS


def get_field_info(field: FieldInfo) -> dict[str, Any]:
    """Extract information about a dataclass field: type, optional, and default.

    Args:
        field: The field to extract information from.

    Returns: A dict with the field's type, whether it's optional, and its default value.

    """
    field_type = field.annotation
    optional = False
    if get_origin(field_type) is UnionType:
        types = get_args(field_type)
        non_none_arg = next(
            (t for t in types if t is not None and t is not NoneType), None
        )
        if non_none_arg is not None:
            field_type = non_none_arg
            optional = True
    type_name = (
        str(field_type)
        if field_type is None
        else field_type.__name__
        if hasattr(field_type, "__name__")
        else str(field_type)
    )
    default = field.default
    return {"type": type_name.lower(), "optional": optional, "default": default}


def model_defaults_to_dict(model: BaseModel) -> dict[str, Any]:
    """Serialize field information in a dict for the client, including type
    hints, defaults, and whether it's optional."""
    result = {}
    for name, field in model.__class__.model_fields.items():
        field_value = getattr(model, name)
        if isinstance(field_value, BaseModel):
            result[name] = model_defaults_to_dict(field_value)
        else:
            result[name] = get_field_info(field)
    return result


__all__ = [
    "FORGE_DEFAULT_AGENT",
    "FORGE_MAX_ITERATIONS",
    "get_field_info",
    "model_defaults_to_dict",
]
