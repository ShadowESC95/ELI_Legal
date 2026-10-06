from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class Incident:
    incident_id: str
    matter_id: str
    run_id: str
    category: str
    detail: str
    affected_claim_ids: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class IncidentService:
    def create(self, incident: Incident) -> Incident:
        return incident
