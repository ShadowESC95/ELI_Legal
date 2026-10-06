from __future__ import annotations

from typing import Protocol


class ModelRegistryPort(Protocol):
    def active_versions(self) -> dict[str, str]: ...
