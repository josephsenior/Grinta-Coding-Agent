"""Tests for backend._canonical — canonical metaclasses for cross-reload isinstance."""

from __future__ import annotations

from backend._canonical import CanonicalMeta, CanonicalModelMetaclass


# ── CanonicalModelMetaclass ──────────────────────────────────────────


class TestCanonicalModelMetaclass:
    """Test CanonicalModelMetaclass name-based isinstance/issubclass."""

    def test_normal_isinstance(self):
        """Standard isinstance still works."""
        from pydantic import BaseModel

        class MyModel(BaseModel, metaclass=CanonicalModelMetaclass):
            x: int = 1

        obj = MyModel()
        assert isinstance(obj, MyModel)

    def test_cross_reload_isinstance(self):
        """Objects whose type.__name__ matches are considered instances."""
        from pydantic import BaseModel

        class Original(BaseModel, metaclass=CanonicalModelMetaclass):
            x: int = 1

        # Simulate a "reloaded" class with same name but different identity
        class Reloaded(BaseModel):
            x: int = 2

        Reloaded.__name__ = "Original"
        obj = Reloaded(x=42)
        # CanonicalModelMetaclass.__instancecheck__ matches by name
        assert isinstance(obj, Original)

    def test_different_name_not_instance(self):
        from pydantic import BaseModel

        class ModelA(BaseModel, metaclass=CanonicalModelMetaclass):
            x: int = 1

        class ModelB(BaseModel):
            x: int = 2

        obj_b = ModelB(x=5)
        assert not isinstance(obj_b, ModelA)

    def test_subclasscheck_same_name(self):
        from pydantic import BaseModel

        class Base(BaseModel, metaclass=CanonicalModelMetaclass):
            x: int = 1

        class Other(BaseModel):
            x: int = 2

        Other.__name__ = "Base"
        assert issubclass(Other, Base)

    def test_subclasscheck_different_name(self):
        from pydantic import BaseModel

        class Base(BaseModel, metaclass=CanonicalModelMetaclass):
            x: int = 1

        class Unrelated(BaseModel):
            x: int = 2

        assert not issubclass(Unrelated, Base)


# ── CanonicalMeta ────────────────────────────────────────────────────


class TestCanonicalMeta:
    def test_normal_isinstance(self):
        class MyClass(metaclass=CanonicalMeta):
            pass

        obj = MyClass()
        assert isinstance(obj, MyClass)

    def test_cross_reload_isinstance_by_name(self):
        class Original(metaclass=CanonicalMeta):
            pass

        class Reloaded:
            pass

        Reloaded.__name__ = "Original"
        obj = Reloaded()
        assert isinstance(obj, Original)

    def test_different_name_not_instance(self):
        class ClassA(metaclass=CanonicalMeta):
            pass

        class ClassB:
            pass

        obj = ClassB()
        assert not isinstance(obj, ClassA)

    def test_subclasscheck_same_name(self):
        class Base(metaclass=CanonicalMeta):
            pass

        class Other:
            pass

        Other.__name__ = "Base"
        assert issubclass(Other, Base)

    def test_subclasscheck_different_name(self):
        class Base(metaclass=CanonicalMeta):
            pass

        class Unrelated:
            pass

        assert not issubclass(Unrelated, Base)

    def test_action_base_class_mro_check(self):
        """Special case: if cls.__name__ is 'Action', check MRO."""

        class Action(metaclass=CanonicalMeta):
            pass

        class ChildAction:
            pass

        # Simulate a child with Action in its MRO
        # We rename to "some other name" but put "Action" in MRO name
        class FakeBase:
            pass

        FakeBase.__name__ = "Action"

        class SubAction(FakeBase):
            pass

        # SubAction has FakeBase (name="Action") in its MRO
        assert isinstance(SubAction(), Action)

    def test_type_attribute_matching(self):
        """When both cls and instance have action/observation attr, compare them."""

        class MyAction(metaclass=CanonicalMeta):
            action = "run"

        class Reloaded:
            action = "run"

        Reloaded.__name__ = "MyAction"
        obj = Reloaded()
        assert isinstance(obj, MyAction)

    def test_type_attribute_mismatch(self):
        """Different action type attributes → not instance."""

        class MyAction(metaclass=CanonicalMeta):
            action = "run"

        class Reloaded:
            action = "browse"

        Reloaded.__name__ = "MyAction"
        obj = Reloaded()
        assert not isinstance(obj, MyAction)
