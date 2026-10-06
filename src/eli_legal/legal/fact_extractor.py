from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FactCandidate:
    fact_id: str
    text: str
    evidence_refs: tuple[str, ...]
    disputed: bool | None = None


class FactExtractor:
    def extract(self, *, matter_id: str, document_ids: list[str]) -> list[FactCandidate]:
        raise NotImplementedError("fact extraction must preserve evidence locators")
