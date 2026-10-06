from __future__ import annotations

from typing import Protocol, TypeVar

T = TypeVar("T")


class RepositoryPort(Protocol[T]):
    def put(self, obj: T) -> None: ...
    def get(self, object_id: str) -> T | None: ...
