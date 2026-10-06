from eli_legal.domain.models import Claim
from eli_legal.legal.report_builder import LegalReportBuilder


class ReportService:
    def __init__(self, builder: LegalReportBuilder | None = None) -> None:
        self.builder = builder or LegalReportBuilder()

    def draft(self, *, matter_id: str, run_id: str, claims: list[Claim]):
        return self.builder.build(matter_id=matter_id, run_id=run_id, claims=claims)
