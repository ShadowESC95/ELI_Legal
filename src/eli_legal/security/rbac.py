from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from eli_legal.domain.errors import PolicyDenied
from eli_legal.domain.models import User

ROLE_LEGAL_ADMIN = "legal_admin"
ROLE_SUPERVISING_SOLICITOR = "supervising_solicitor"
ROLE_SOLICITOR = "solicitor"
ROLE_BARRISTER = "barrister"
ROLE_PARALEGAL = "paralegal"
ROLE_IN_HOUSE_COUNSEL = "in_house_counsel"
ROLE_JUDGE = "judge"
ROLE_TRIBUNAL_MEMBER = "tribunal_member"
ROLE_ARBITRATOR = "arbitrator"
ROLE_TRIBUNAL_SECRETARY = "tribunal_secretary"
ROLE_MEDIATOR = "mediator"
ROLE_CONCILIATOR = "conciliator"
ROLE_REVIEWER = "reviewer"
ROLE_GOVERNANCE = "governance_officer"
ROLE_AUDITOR = "auditor"
ROLE_SYSTEM_ADMIN = "system_admin"
ROLE_READ_ONLY = "read_only"

_READ = {"matter.read", "document.read"}
_OPERATE = {
    "workflow.run",
    "document.ingest",
    "facts.extract",
    "issues.map",
    "evidence.map",
    "research.run",
    "report.draft",
}
# Recording a human verification result for a held finding.
_VERIFY = {"citation.verify", "authority.status_check", "proposition.verify"}
_REVIEW = {"report.review", "report.approve", "report.export"}
_RELEASE = {"report.prepare_release", "report.send"}
_CONTROL = {
    "workflow.hold",
    "workflow.stop",
    "workflow.restart",
    "hold.resolve",
    "document.waive",
    "verification.override",
    "incident.manage",
}
_AUDIT = {"audit.read", "audit.verify", "evidence.export"}

# The person who decides: operates, verifies, reviews, releases and can stop the system.
_DECISION_MAKER = (
    _READ
    | _OPERATE
    | _VERIFY
    | _REVIEW
    | _RELEASE
    | _CONTROL
    | {
        "matter.create",
        "matter.manage",
        "matter.close",
        "audit.read",
        "audit.verify",
    }
)

# Role permissions are intentionally explicit. Matter membership and the matter's profile are
# checked separately; holding a role never grants access to every matter.
DEFAULT_ROLE_ACTIONS: dict[str, set[str]] = {
    ROLE_JUDGE: set(_DECISION_MAKER),
    ROLE_TRIBUNAL_MEMBER: set(_DECISION_MAKER),
    ROLE_ARBITRATOR: set(_DECISION_MAKER),
    ROLE_MEDIATOR: set(_DECISION_MAKER),
    ROLE_CONCILIATOR: set(_DECISION_MAKER),
    # Registrar, clerk or tribunal secretary: runs approved tasks; decides nothing.
    ROLE_TRIBUNAL_SECRETARY: _READ
    | _OPERATE
    | {"matter.create", "workflow.hold", "workflow.stop", "report.export"},
    ROLE_SUPERVISING_SOLICITOR: set(_DECISION_MAKER),
    ROLE_IN_HOUSE_COUNSEL: set(_DECISION_MAKER),
    ROLE_SOLICITOR: _READ
    | _OPERATE
    | _VERIFY
    | {"report.review", "report.export", "report.prepare_release", "workflow.hold"},
    ROLE_BARRISTER: _READ
    | _VERIFY
    | {
        "facts.extract",
        "issues.map",
        "evidence.map",
        "research.run",
        "report.draft",
        "report.review",
        "report.export",
        "workflow.hold",
    },
    ROLE_PARALEGAL: _READ | _OPERATE,
    ROLE_REVIEWER: _READ | _VERIFY | _REVIEW,
    ROLE_LEGAL_ADMIN: _DECISION_MAKER
    | _AUDIT
    | {
        "user.manage",
        "source.manage",
        "config.manage",
        "framework.manage",
        "compliance.manage",
        "checks.run",
    },
    ROLE_GOVERNANCE: {
        "matter.read",
        "workflow.hold",
        "workflow.stop",
        "workflow.restart",
        "hold.resolve",
        "incident.manage",
        "source.manage",
        "config.manage",
        "framework.manage",
        "compliance.manage",
        "checks.run",
    }
    | _AUDIT,
    ROLE_AUDITOR: set(_AUDIT),
    # Technical administration is deliberately not equivalent to legal-matter access.
    ROLE_SYSTEM_ADMIN: {"audit.verify", "user.manage", "config.manage", "checks.run"},
    ROLE_READ_ONLY: set(_READ),
}

ALL_ACTIONS: frozenset[str] = frozenset().union(*DEFAULT_ROLE_ACTIONS.values())


@dataclass(slots=True)
class RoleBindings:
    user_roles: dict[str, set[str]] = field(default_factory=dict)
    role_actions: dict[str, set[str]] = field(
        default_factory=lambda: {
            role: set(actions) for role, actions in DEFAULT_ROLE_ACTIONS.items()
        }
    )

    @classmethod
    def from_users(cls, users: Iterable[User]) -> RoleBindings:
        return cls(user_roles={u.user_id: set(u.roles) for u in users if u.active})

    def roles_for(self, user_id: str) -> frozenset[str]:
        return frozenset(self.user_roles.get(user_id, set()))

    def bind(self, user_id: str, *roles: str) -> None:
        unknown = [r for r in roles if r not in self.role_actions]
        if unknown:
            raise ValueError(f"unknown role(s): {', '.join(unknown)}")
        self.user_roles.setdefault(user_id, set()).update(roles)

    def can(self, user_id: str, action: str, *, roles: Iterable[str] | None = None) -> bool:
        """Whether the user may perform ``action``; ``roles`` narrows to roles valid in context."""
        held = self.user_roles.get(user_id, set())
        usable = held if roles is None else held & set(roles)
        return any(action in self.role_actions.get(role, set()) for role in usable)

    def require(self, user_id: str, action: str) -> None:
        if not self.can(user_id, action):
            raise PolicyDenied(f"user {user_id!r} is not permitted to perform {action!r}")
