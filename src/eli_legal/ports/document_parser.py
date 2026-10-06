from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DocumentParserPort(Protocol):
    def parse(self, path: str | Path) -> str: ...
