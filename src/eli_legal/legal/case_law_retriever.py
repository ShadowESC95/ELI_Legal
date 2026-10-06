from __future__ import annotations

from eli_legal.ports.legal_sources import LegalSourcePort


class CaseLawRetriever:
    def __init__(self, connector: LegalSourcePort) -> None:
        self.connector = connector

    def search(self, *, jurisdiction: str, query: str, limit: int = 20):
        return self.connector.search(jurisdiction=jurisdiction, query=query, limit=limit)
