from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MonitoringSample:
    failed_source_checks: int = 0
    unsupported_claims: int = 0
    missing_documents: int = 0
    reviewer_corrections: int = 0
    overrides: int = 0


class MonitoringService:
    def requires_review(self, sample: MonitoringSample, *, failed_check_threshold: int = 1) -> bool:
        return sample.failed_source_checks >= failed_check_threshold
