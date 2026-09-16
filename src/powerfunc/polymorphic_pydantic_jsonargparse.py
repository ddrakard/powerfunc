"""A base class whose fields may hold any subclass, for pydantic in jsonargparse's form."""

import dataclasses
import importlib
from typing import Any, TypeVar

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

ClassT = TypeVar("ClassT", bound=type)


def polymorphic_pydantic_jsonargparse(cls: ClassT) -> ClassT:
    """Let a pydantic field typed as the decorated class hold an instance of any of its
    subclasses, and save and load it as that subclass. Compatible with pydantic and
    jsonargparse.

    Use::

        @polymorphic_pydantic_jsonargparse
        class Base: ...
    """
    cls.__get_pydantic_core_schema__ = classmethod(_schema)  # type: ignore[attr-defined]
    return cls


def _schema(cls: type, source_type: Any, handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
    def validate(value: Any) -> Any:
        if isinstance(value, cls):
            return value
        if isinstance(value, dict) and "class_path" in value:
            class_path = value["class_path"]
            module_name, _, class_name = class_path.rpartition(".")
            subclass = getattr(importlib.import_module(module_name), class_name)
            if not (isinstance(subclass, type) and issubclass(subclass, cls)):
                raise ValueError(f"{class_path} is not a subclass of {cls.__name__}")
            return subclass(**value.get("init_args", {}))
        raise ValueError(f"expected a {cls.__name__} or a class_path mapping, got {value!r}")

    def serialize(value: Any) -> dict[str, Any]:
        subclass = type(value)
        fields = dataclasses.asdict(value) if dataclasses.is_dataclass(value) else {}
        return {"class_path": f"{subclass.__module__}.{subclass.__qualname__}", "init_args": fields}

    return core_schema.no_info_plain_validator_function(
        validate, serialization=core_schema.plain_serializer_function_ser_schema(serialize)
    )
