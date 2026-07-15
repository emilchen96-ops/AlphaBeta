"""Generic, explicit-boundary conversion between dataclasses and ORM rows."""

from dataclasses import fields, is_dataclass
from enum import Enum
from types import UnionType
from typing import Any, cast, get_args, get_origin, get_type_hints

from sqlalchemy.orm import DeclarativeBase

FIELD_ALIASES = {"metadata": "metadata_json"}
NON_PERSISTED_FIELDS = {"items"}


def _enum_type(annotation: Any) -> type[Enum] | None:
    candidates = get_args(annotation) if get_origin(annotation) in (UnionType, None) else ()
    if not candidates:
        candidates = (annotation,)
    for candidate in candidates:
        if isinstance(candidate, type) and issubclass(candidate, Enum):
            return candidate
    return None


def _model_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_model_value(item) for item in value]
    return value


def _domain_value(annotation: Any, value: Any) -> Any:
    enum_type = _enum_type(annotation)
    if enum_type is not None and value is not None:
        return enum_type(value)
    if get_origin(annotation) is tuple and isinstance(value, list):
        item_annotation = get_args(annotation)[0]
        item_enum = _enum_type(item_annotation)
        return tuple(item_enum(item) if item_enum is not None else item for item in value)
    return value


def model_from_entity[ModelT: DeclarativeBase](model_type: type[ModelT], entity: object) -> ModelT:
    if not is_dataclass(entity):
        raise TypeError("entity must be a dataclass instance")
    values: dict[str, Any] = {}
    for domain_field in fields(entity):
        if domain_field.name in NON_PERSISTED_FIELDS:
            continue
        model_name = FIELD_ALIASES.get(domain_field.name, domain_field.name)
        if not hasattr(model_type, model_name):
            continue
        value = getattr(entity, domain_field.name)
        if value is None and domain_field.name == "id":
            continue
        values[model_name] = _model_value(value)
    return model_type(**values)


def entity_from_model[DomainT](entity_type: type[DomainT], model: DeclarativeBase) -> DomainT:
    hints = get_type_hints(entity_type)
    values: dict[str, Any] = {}
    for domain_field in fields(cast(Any, entity_type)):
        if domain_field.name in NON_PERSISTED_FIELDS:
            continue
        model_name = FIELD_ALIASES.get(domain_field.name, domain_field.name)
        if not hasattr(model, model_name):
            continue
        value = getattr(model, model_name)
        values[domain_field.name] = _domain_value(hints[domain_field.name], value)
    return entity_type(**values)
