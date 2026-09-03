"""Encoding and decoding between canonical entities and plain JSON structures.

The codec is reflective: it reads the dataclass field types and derives the
mapping, so adding a field to an entity does not mean editing two hand-written
functions that can drift apart. Every value it emits is JSON-native and
integer-valued, so :mod:`sto.core.hashing` can hash the result directly.

Round-tripping is the contract: ``decode(encode(x)) == x`` for every entity, and
a test asserts it on a real 562-task schedule rather than a toy.
"""

from __future__ import annotations

import types
import typing
from dataclasses import MISSING, fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar
from uuid import UUID

from . import entities as _entities

T = TypeVar("T")

_TYPE_CACHE: dict[type, dict[str, Any]] = {}


class CodecError(ValueError):
    """Raised when a payload cannot be decoded into the requested entity."""


def _hints(cls: type) -> dict[str, Any]:
    cached = _TYPE_CACHE.get(cls)
    if cached is None:
        cached = typing.get_type_hints(cls, vars(_entities))
        _TYPE_CACHE[cls] = cached
    return cached


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0], True
        return annotation, True
    return annotation, False


def encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return encode(value)
    if isinstance(value, (list, tuple)):
        return [encode_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): encode_value(item) for key, item in sorted(value.items())}
    raise CodecError(f"cannot encode {type(value).__name__}")


def encode(entity: Any) -> dict[str, Any]:
    """Encode a dataclass entity, omitting fields still at their default.

    Omitting defaults keeps a 562-task document readable and, more usefully,
    keeps its hash stable when a field is added with a default: documents that
    do not set it serialise exactly as before.
    """

    out: dict[str, Any] = {}
    for spec in fields(entity):
        value = getattr(entity, spec.name)
        if spec.default is not MISSING and value == spec.default:
            continue
        if spec.default_factory is not MISSING:  # type: ignore[misc]
            if value == spec.default_factory():  # type: ignore[misc]
                continue
        out[spec.name] = encode_value(value)
    return out


def decode_value(annotation: Any, value: Any) -> Any:
    annotation, optional = _unwrap_optional(annotation)
    if value is None:
        if not optional:
            raise CodecError(f"null for non-optional {annotation}")
        return None

    origin = typing.get_origin(annotation)
    if origin in (tuple, list):
        args = typing.get_args(annotation)
        item_type = args[0] if args else Any
        return tuple(decode_value(item_type, item) for item in value)
    if origin is dict:
        args = typing.get_args(annotation)
        value_type = args[1] if len(args) == 2 else Any
        return {str(key): decode_value(value_type, item) for key, item in value.items()}

    if annotation is Any:
        return value
    if isinstance(annotation, type):
        if issubclass(annotation, Enum):
            return annotation(value)
        if annotation is UUID:
            return UUID(str(value))
        if annotation is datetime:
            return datetime.fromisoformat(str(value))
        if annotation is bool:
            # Never coerce: bool("false") is True, so a version-skewed or
            # hand-edited document would decode to the opposite meaning.
            if not isinstance(value, bool):
                raise CodecError(f"expected a boolean, got {value!r}")
            return value
        if annotation is int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise CodecError(f"expected an integer, got {value!r}")
            return value
        if annotation is str:
            return str(value)
        if is_dataclass(annotation):
            return decode(annotation, value)
    return value


def decode(cls: type[T], payload: dict[str, Any]) -> T:
    hints = _hints(cls)
    kwargs: dict[str, Any] = {}
    for spec in fields(cls):  # type: ignore[arg-type]
        if spec.name not in payload:
            continue
        try:
            kwargs[spec.name] = decode_value(hints[spec.name], payload[spec.name])
        except CodecError:
            raise
        except Exception as error:  # pragma: no cover - defensive
            raise CodecError(f"{cls.__name__}.{spec.name}: {error}") from error
    return cls(**kwargs)  # type: ignore[call-arg]


def encode_schedule(schedule: _entities.Schedule) -> dict[str, Any]:
    """Encode a whole schedule.

    ``schema_version`` is always written even though it equals its default. It
    is the discriminator a reader needs before it can interpret anything else,
    and a document that omits it is not self-describing.
    """

    payload = encode(schedule)
    payload["schema_version"] = schedule.schema_version
    return payload


def decode_schedule(payload: dict[str, Any]) -> _entities.Schedule:
    """Decode a whole schedule, checking the discriminator first.

    ``encode_schedule`` always writes ``schema_version`` because a reader needs
    it before it can interpret anything else. Honouring that means refusing a
    document that omits it or declares a version this code does not implement,
    rather than reflectively decoding a future document under v1 semantics.
    """

    version = payload.get("schema_version")
    if version is None:
        raise CodecError("document has no schema_version")
    if version != _entities.SCHEMA_VERSION:
        raise CodecError(
            f"unsupported schema_version {version!r}; this build reads "
            f"{_entities.SCHEMA_VERSION!r}"
        )
    return decode(_entities.Schedule, payload)
