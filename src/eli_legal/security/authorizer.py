from __future__ import annotations

from dataclasses import dataclass

from eli_legal.domain import plain
from eli_legal.domain.enums import MatterStatus
from eli_legal.domain.errors import AuthenticationFailed, MatterAccessDenied, PolicyDenied
from eli_legal.domain.models import AuditEvent, Matter
from eli_legal.domain.policy import RuntimePolicy
from eli_legal.domain.profiles import OVERSIGHT_ROLES, ProfileSpec, profile_spec
from eli_legal.ports.audit import AuditPort
from eli_legal.security import access, authn
from eli_legal.security.matter_guard import require_matter_access
from eli_legal.security.rbac import PARTY_ACTIONS, RoleBindings


def _usable_roles(spec: ProfileSpec, action: str) -> frozenset[str]:
    """The account roles that count on a matter of this profile, for this action. A party's
    people (prosecution, defence, a party's lawyers) count only for what a party may do there."""
    usable = spec.roles | OVERSIGHT_ROLES
    return usable | spec.party_roles if action in PARTY_ACTIONS else usable


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

    def _require_identity(self, user_id: str, action: str, matter_id: str) -> None:
        """A name is not proof. The identity must have been established by a front end."""
        try:
            authn.require(user_id)
        except AuthenticationFailed as exc:
            self._deny(
                exc,
                user_id=user_id,
                action=action,
                matter_id=matter_id,
                reason="identity_not_established",
            )

    def require_global(self, user_id: str, action: str) -> None:
        self._require_identity(user_id, action, "-")
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
        self._require_identity(user_id, action, mid)
        if self.policy is not None and not self.policy.permits(action):
            self._deny(
                PolicyDenied(f"action is not authorised by policy: {action}"),
                user_id=user_id,
                action=action,
                matter_id=mid,
                reason="not_authorised_by_policy",
            )
        spec = profile_spec(matter.profile)
        usable = _usable_roles(spec, action)
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
        if not access.permits(matter, user_id, self.bindings.roles_for(user_id), action):
            role = access.matter_role(matter, user_id, self.bindings.roles_for(user_id))
            self._deny(
                PolicyDenied(
                    f"as {access.MATTER_ROLES[role].label.lower()} on this matter, {user_id!r} "
                    f"may not {plain.action(action)}"
                ),
                user_id=user_id,
                action=action,
                matter_id=mid,
                reason="matter_role_lacks_permission",
            )
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
        if not self.bindings.can(user_id, action, roles=_usable_roles(spec, action)):
            return False
        if not (user_id == matter.owner_user_id or user_id in matter.authorised_user_ids):
            return False
        return access.permits(matter, user_id, self.bindings.roles_for(user_id), action)

    def visibility(self, matter: Matter, user_id: str) -> access.Visibility:
        """What this person may read of the matter."""
        return access.Visibility.of(matter, user_id, self.bindings.roles_for(user_id))
