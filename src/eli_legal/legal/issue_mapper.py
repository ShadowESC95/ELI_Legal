from dataclasses import dataclass, field


@dataclass(slots=True)
class Issue:
    issue_id: str
    label: str
    fact_ids: list[str] = field(default_factory=list)
    claim_ids: list[str] = field(default_factory=list)


class IssueMapper:
    def map(self, *, issue_id: str, label: str) -> Issue:
        return Issue(issue_id=issue_id, label=label)
