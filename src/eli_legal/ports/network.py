from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol


class NetworkPort(Protocol):
    def allow(self, *, reason: str) -> AbstractContextManager[None]: ...
