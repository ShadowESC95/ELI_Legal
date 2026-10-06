from __future__ import annotations

from pathlib import Path

from eli_legal.adapters.eli_v2.compat import import_attr


class EliV2DocumentParser:
    """Reuse only ELI v2's format parsers; do not use ELI personal-memory indexing."""

    def parse(self, path: str | Path) -> str:
        reader_cls = import_attr("eli.plugins.document_reader.plugin", "DocumentReaderPlugin")
        result = reader_cls(max_chars=4_000_000, max_pages=5_000, max_parts=5_000).read(
            {"path": str(Path(path).expanduser().resolve())}
        )
        if not result.get("ok"):
            raise ValueError(str(result.get("error") or "document parse failed"))
        return str(result.get("content") or "")
