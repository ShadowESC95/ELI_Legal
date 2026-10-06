from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DocumentPort(Protocol):
    def ingest(self, *, matter_id: str, path: Path, actor_id: str) -> str: ...
    def extract_text(self, *, matter_id: str, document_id: str) -> str: ...
