from eli_legal.legal.source_registry import SourceRegistry


class SourceService:
    def __init__(self, registry: SourceRegistry) -> None:
        self.registry = registry

    def require_source(self, source_id: str, jurisdiction: str):
        return self.registry.require_approved(source_id, jurisdiction)
