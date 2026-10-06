from __future__ import annotations
import hashlib
from pathlib import Path
from eli_legal.domain.models import new_id


class LocalFileDocumentAdapter:
    def __init__(self, root: str | Path = "./data/matters") -> None:
        self.root = Path(root)

    def ingest(self, *, matter_id: str, path: Path, actor_id: str) -> str:
        raw = path.read_bytes()
        document_id = new_id("doc")
        target_dir = self.root / matter_id / "documents"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{document_id}{path.suffix.lower()}"
        target.write_bytes(raw)
        (target.with_suffix(target.suffix + ".sha256")).write_text(hashlib.sha256(raw).hexdigest())
        return document_id

    def extract_text(self, *, matter_id: str, document_id: str) -> str:
        raise NotImplementedError("Use a format-specific parser; do not silently decode binary containers")
