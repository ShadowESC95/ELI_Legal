from __future__ import annotations

from dataclasses import dataclass

from eli_legal.domain.enums import MatterStatus
from eli_legal.domain.errors import MatterAccessDenied, PolicyDenied
from eli_legal.domain.models import AuditEvent, Matter
from eli_legal.domain.policy import RuntimePolicy
from eli_legal.domain.profiles import OVERSIGHT_ROLES, profile_spec
from eli_legal.ports.audit import AuditPort
from eli_legal.security.matter_guard import require_matter_access
from eli_legal.security.rbac import RoleBindings

# What may still be done on a closed matter: account for past use, nothing else.
_CLOSED_MATTER_ACTIONS = frozenset({"matter.read", "audit.read", "audit.verify", "evidence.export"})


@dataclass(slots=True)
class MatterAuthorizer:
    """Role permission, matter membership and matter profile must all agree.

    Every refusal is written to the audit ledger before the exception is raised, so an
    unauthorised attempt leaves a record even though nothing was disclosed.
    """

    bindings: RoleBindings
    audit: AuditPort | None = None
    policy: RuntimePolicy | None = None

    def _deny(
        self, exc: Exception, *, user_id: str, action: str, matter_id: str, reason: str
    ) -> None:
        if self.audit is not None:
            self.audit.append(
                AuditEvent(
                    event_type="access_denied",
                    actor_id=user_id,
                    matter_id=matter_id,
                    run_id=None,
                    action=action,
                    subject_id=matter_id,
                    outcome="denied",
                    object_type="matter",
                    payload={"reason": reason},
                )
            )
        raise exc

    def require_global(self, user_id: str, action: str) -> None:
        if self.policy is not None and not self.policy.permits(action):
            self._deny(
                PolicyDenied(f"action is not authorised by policy: {action}"),
                user_id=user_id,
                action=action,
                matter_id="-",
                reason="not_authorised_by_policy",
            )
        if not self.bindings.can(user_id, action):
            self._deny(
                PolicyDenied(f"user {user_id!r} is not permitted to perform {action!r}"),
                user_id=user_id,
                action=action,
                matter_id="-",
                reason="role_lacks_permission",
            )

    def require_matter(self, matter: Matter, user_id: str, action: str) -> None:
        mid = matter.matter_id
        if self.policy is not None and not self.policy.permits(action):
            self._deny(
                PolicyDenied(f"action is not authorised by policy: {action}"),
                user_id=user_id,
                action=action,
                matter_id=mid,
                reason="not_authorised_by_policy",
            )
        spec = profile_spec(matter.profile)
        usable = spec.roles | OVERSIGHT_ROLES
        if not self.bindings.can(user_id, action, roles=usable):
            held_any = self.bindings.can(user_id, action)
            self._deny(
                PolicyDenied(f"user {user_id!r} is not permitted to perform {action!r}"),
                user_id=user_id,
                action=action,
                matter_id=mid,
                reason="role_not_valid_for_profile" if held_any else "role_lacks_permission",
            )
        try:
            require_matter_access(matter, user_id)
        except MatterAccessDenied as exc:
            self._deny(exc, user_id=user_id, action=action, matter_id=mid, reason="not_a_member")
        if matter.status is MatterStatus.CLOSED and action not in _CLOSED_MATTER_ACTIONS:
            self._deny(
                PolicyDenied(f"matter {mid} is closed"),
                user_id=user_id,
                action=action,
                matter_id=mid,
                reason="matter_closed",
            )

    def record_cross_matter_attempt(
        self, *, user_id: str, matter_id: str, action: str, object_type: str, object_id: str
    ) -> None:
        """A record id from another matter was presented. Log it; reveal nothing about it."""
        if self.audit is not None:
            self.audit.append(
                AuditEvent(
                    event_type="cross_matter_access",
                    actor_id=user_id,
                    matter_id=matter_id,
                    run_id=None,
                    action=action,
                    subject_id=object_id,
                    outcome="denied",
                    object_type=object_type,
                    payload={"reason": "record_belongs_to_another_matter"},
                )
            )

    def can_matter(self, matter: Matter, user_id: str, action: str) -> bool:
        spec = profile_spec(matter.profile)
        if not self.bindings.can(user_id, action, roles=spec.roles | OVERSIGHT_ROLES):
            return False
        return user_id == matter.owner_user_id or user_id in matter.authorised_user_ids
