"""Dataclass <-> JSON codec used by the SQLite store.

Records are stored as one JSON document per row beside a few indexed columns. The codec is driven
by the dataclass type hints, so a field added to a model needs no storage change.
"""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from datetime import date, datetime
from enum import Enum
from functools import cache
from typing import Any, TypeVar, Union, get_args, get_origin

T = TypeVar("T")


def to_jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(to_jsonable(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    return value


@cache
def _hints(cls: Any) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def from_jsonable(tp: Any, value: Any) -> Any:
    if value is None or tp is Any:
        return value
    origin = get_origin(tp)
    if origin is Union or origin is types.UnionType:
        candidates = [a for a in get_args(tp) if a is not type(None)]
        return from_jsonable(candidates[0], value) if candidates else value
    if origin in (list, typing.Sequence):
        (inner,) = get_args(tp) or (Any,)
        return [from_jsonable(inner, v) for v in value]
    if origin in (set, frozenset):
        (inner,) = get_args(tp) or (Any,)
        return origin(from_jsonable(inner, v) for v in value)
    if origin is tuple:
        args = get_args(tp)
        inner = args[0] if args else Any
        return tuple(from_jsonable(inner, v) for v in value)
    if origin is dict:
        args = get_args(tp)
        inner = args[1] if len(args) == 2 else Any
        return {k: from_jsonable(inner, v) for k, v in value.items()}
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            return decode(tp, value)
        if issubclass(tp, Enum):
            return tp(value)
        if tp is datetime:
            return datetime.fromisoformat(value)
        if tp is date:
            return date.fromisoformat(value)
    return value


def decode(cls: type[T], data: dict[str, Any]) -> T:
    hints: dict[str, Any] = _hints(cls)  # type: ignore[arg-type]
    kwargs = {
        f.name: from_jsonable(hints.get(f.name, Any), data[f.name])
        for f in dataclasses.fields(cls)  # type: ignore[arg-type]
        if f.name in data and f.init
    }
    return cls(**kwargs)


def dumps(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def loads(cls: type[T], raw: str) -> T:
    return decode(cls, json.loads(raw))
