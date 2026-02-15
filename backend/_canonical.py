"""Shared registry for canonical classes across reloads."""

from __future__ import annotations

from pydantic._internal._model_construction import ModelMetaclass


class CanonicalModelMetaclass(ModelMetaclass):
    """Metaclass that ensures Pydantic models behave consistently across reloads.

    Instead of trying to return the same class object (which causes issues with super()),
    this metaclass overrides __instancecheck__ and __subclasscheck__ to support
    isinstance() and issubclass() checks across reloaded versions of the same class.
    """

    def __instancecheck__(cls, instance):
        if super().__instancecheck__(instance):
            return True
        # Check if the class names match. This allows isinstance(reloaded_obj, original_class) to be True.
        return type(instance).__name__ == cls.__name__

    def __subclasscheck__(cls, subclass):
        if super().__subclasscheck__(subclass):
            return True
        # Check if the class names match. This allows issubclass(reloaded_class, original_class) to be True.
        return getattr(subclass, "__name__", None) == cls.__name__


class CanonicalMeta(type):
    """Metaclass that ensures non-Pydantic classes behave consistently across reloads.

    Supports isinstance() and issubclass() checks across reloaded versions of the
    same class by comparing class names.
    """

    def __instancecheck__(cls, instance: object) -> bool:
        if super().__instancecheck__(instance):
            return True
        # Check if the class names match.
        inst_type = type(instance)
        if getattr(inst_type, "__name__", None) != getattr(cls, "__name__", None):
            # Special case for base classes to allow subclasses from other reloads
            if cls.__name__ in ("Action", "Observation", "Event"):
                return any(b.__name__ == cls.__name__ for b in inst_type.__mro__)
            return False

        # If it's an Action/Observation, we can also check the type attribute
        cls_type = getattr(cls, "action", getattr(cls, "observation", None))
        inst_type_attr = getattr(
            instance, "action", getattr(instance, "observation", None)
        )
        if cls_type and inst_type_attr:
            return cls_type == inst_type_attr

        return True

    def __subclasscheck__(cls, subclass: type) -> bool:
        if super().__subclasscheck__(subclass):
            return True
        # Check if the class names match.
        return getattr(subclass, "__name__", None) == cls.__name__
