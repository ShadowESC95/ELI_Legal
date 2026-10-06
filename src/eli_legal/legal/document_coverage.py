from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CoverageResult:
    expected_ids: frozenset[str]
    processed_ids: frozenset[str]

    @property
    def missing_ids(self) -> frozenset[str]:
        return self.expected_ids - self.processed_ids

    @property
    def complete(self) -> bool:
        return not self.missing_ids
