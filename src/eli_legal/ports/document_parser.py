from __future__ import annotations

from typing import Protocol

from eli_legal.adapters.local.parsers import ParsedDocument


class DocumentParserPort(Protocol):
    version: str

    def parse(self, filename: str, raw: bytes) -> ParsedDocument: ...
