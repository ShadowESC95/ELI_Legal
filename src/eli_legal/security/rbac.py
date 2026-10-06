from __future__ import annotations

from dataclasses import dataclass, field

from eli_legal.domain.errors import PolicyDenied

ROLE_LEGAL_ADMIN = "legal_admin"
ROLE_SUPERVISING_SOLICITOR = "supervising_solicitor"
ROLE_SOLICITOR = "solicitor"
ROLE_BARRISTER = "barrister"
ROLE_PARALEGAL = "paralegal"
ROLE_ARBITRATOR = "arbitrator"
ROLE_REVIEWER = "reviewer"
ROLE_GOVERNANCE = "governance_officer"
ROLE_AUDITOR = "auditor"
ROLE_SYSTEM_ADMIN = "system_admin"
ROLE_READ_ONLY = "read_only"

# Role permissions are intentionally explicit. Matter membership is checked separately.
DEFAULT_ROLE_ACTIONS: dict[str, set[str]] = {
    ROLE_LEGAL_ADMIN: {
        "matter.create",
        "matter.read",
        "matter.manage",
        "document.ingest",
        "document.read",
        "facts.extract",
        "issues.map",
        "evidence.map",
        "research.run",
        "citation.verify",
        "authority.status_check",
        "proposition.verify",
        "report.draft",
        "report.review",
        "report.approve",
        "report.export",
        "report.prepare_release",
        "report.send",
        "workflow.hold",
        "workflow.stop",
        "workflow.restart",
        "audit.read",
        "audit.verify",
    },
    ROLE_SUPERVISING_SOLICITOR: {
        "matter.read",
        "matter.manage",
        "document.ingest",
        "document.read",
        "facts.extract",
        "issues.map",
        "evidence.map",
        "research.run",
        "citation.verify",
        "authority.status_check",
        "proposition.verify",
        "report.draft",
        "report.review",
        "report.approve",
        "report.export",
        "report.prepare_release",
        "report.send",
        "workflow.hold",
        "workflow.stop",
        "workflow.restart",
        "audit.read",
    },
    ROLE_SOLICITOR: {
        "matter.read",
        "document.ingest",
        "document.read",
        "facts.extract",
        "issues.map",
        "evidence.map",
        "research.run",
        "citation.verify",
        "authority.status_check",
        "proposition.verify",
        "report.draft",
        "report.review",
        "report.export",
        "report.prepare_release",
    },
    ROLE_BARRISTER: {
        "matter.read",
        "document.read",
        "facts.extract",
        "issues.map",
        "evidence.map",
        "research.run",
        "citation.verify",
        "authority.status_check",
        "proposition.verify",
        "report.draft",
        "report.review",
        "report.export",
    },
    ROLE_PARALEGAL: {
        "matter.read",
        "document.ingest",
        "document.read",
        "facts.extract",
        "evidence.map",
        "research.run",
        "report.draft",
    },
    ROLE_ARBITRATOR: {
        "matter.read",
        "document.read",
        "report.review",
        "report.approve",
        "report.export",
        "report.prepare_release",
        "report.send",
        "workflow.hold",
        "workflow.stop",
    },
    ROLE_REVIEWER: {
        "matter.read",
        "document.read",
        "citation.verify",
        "authority.status_check",
        "proposition.verify",
        "report.review",
        "report.approve",
        "report.export",
    },
    ROLE_GOVERNANCE: {
        "matter.read",
        "workflow.hold",
        "workflow.stop",
        "workflow.restart",
        "audit.read",
        "audit.verify",
    },
    ROLE_AUDITOR: {"audit.read", "audit.verify"},
    # Technical administration is deliberately not equivalent to legal-matter access.
    ROLE_SYSTEM_ADMIN: {"audit.verify"},
    ROLE_READ_ONLY: {"matter.read", "document.read"},
}


@dataclass(slots=True)
class RoleBindings:
    user_roles: dict[str, set[str]] = field(default_factory=dict)
    role_actions: dict[str, set[str]] = field(
        default_factory=lambda: {
            role: set(actions) for role, actions in DEFAULT_ROLE_ACTIONS.items()
        }
    )

    def roles_for(self, user_id: str) -> frozenset[str]:
        return frozenset(self.user_roles.get(user_id, set()))

    def bind(self, user_id: str, *roles: str) -> None:
        self.user_roles.setdefault(user_id, set()).update(roles)

    def can(self, user_id: str, action: str) -> bool:
        return any(
            action in self.role_actions.get(role, set())
            for role in self.user_roles.get(user_id, set())
        )

    def require(self, user_id: str, action: str) -> None:
        if not self.can(user_id, action):
            raise PolicyDenied(f"user {user_id!r} is not permitted to perform {action!r}")
