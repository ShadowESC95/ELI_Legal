from __future__ import annotations

import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from eli_legal.application.container import AppContext
from eli_legal.domain.enums import ActorType, MatterStatus, Profile
from eli_legal.domain.errors import InvalidInput, InvalidState, PolicyDenied
from eli_legal.domain.models import Document, Matter, Party, User, utcnow
from eli_legal.domain.profiles import OVERSIGHT_ROLES, profile_spec
from eli_legal.security.rbac import DEFAULT_ROLE_ACTIONS


@dataclass(slots=True)
class UserService:
    ctx: AppContext

    def bootstrap_admin(self, user_id: str, display_name: str = "") -> User:
        """Create the first administrator. Only possible while no user exists."""
        if self.ctx.store.list_users():
            raise PolicyDenied("users already exist; use an administrator account to add more")
        user = User(
            user_id=user_id,
            display_name=display_name or user_id,
            roles={"legal_admin", "system_admin"},
        )
        self.ctx.store.put_user(user)
        self.ctx.log(
            "user_created",
            actor_id=user_id,
            matter_id="-",
            action="user.manage",
            subject_id=user_id,
            outcome="bootstrap",
            object_type="user",
            payload={"roles": sorted(user.roles)},
        )
        return user

    def add_user(
        self,
        *,
        actor_id: str,
        user_id: str,
        display_name: str,
        roles: Iterable[str],
        actor_type: ActorType = ActorType.HUMAN,
    ) -> User:
        self.ctx.authorizer().require_global(actor_id, "user.manage")
        role_set = set(roles)
        unknown = role_set - set(DEFAULT_ROLE_ACTIONS)
        if unknown:
            raise InvalidInput(f"unknown role(s): {', '.join(sorted(unknown))}")
        if actor_type is not ActorType.HUMAN and role_set:
            # A service or agent identity can be named in the audit trail, but it can hold no
            # role, so it can never review, approve, release or resolve anything.
            raise PolicyDenied("only a human user may hold a role")
        existing = self.ctx.store.get_user(user_id)
        user = existing or User(user_id=user_id, display_name=display_name, actor_type=actor_type)
        user.display_name, user.roles, user.active = (
            display_name or user.display_name,
            role_set,
            True,
        )
        self.ctx.store.put_user(user)
        self.ctx.log(
            "user_updated" if existing else "user_created",
            actor_id=actor_id,
            matter_id="-",
            action="user.manage",
            subject_id=user_id,
            outcome="ok",
            object_type="user",
            payload={"roles": sorted(role_set), "actor_type": actor_type.value},
        )
        return user

    def deactivate(self, *, actor_id: str, user_id: str) -> None:
        self.ctx.authorizer().require_global(actor_id, "user.manage")
        user = self.ctx.user(user_id)
        user.active = False
        self.ctx.store.put_user(user)
        self.ctx.store.revoke_tokens(user_id)
        self.ctx.log(
            "user_deactivated",
            actor_id=actor_id,
            matter_id="-",
            action="user.manage",
            subject_id=user_id,
            outcome="ok",
            object_type="user",
        )

    def issue_token(self, *, actor_id: str, user_id: str, label: str = "") -> str:
        """Create an API token. It is shown once; only its hash is stored."""
        if actor_id != user_id:
            self.ctx.authorizer().require_global(actor_id, "user.manage")
        self.ctx.user(user_id)
        token = "elg_" + secrets.token_urlsafe(32)
        self.ctx.store.add_token(token, user_id, label)
        self.ctx.log(
            "token_issued",
            actor_id=actor_id,
            matter_id="-",
            action="user.manage",
            subject_id=user_id,
            outcome="ok",
            object_type="api_token",
        )
        return token


@dataclass(slots=True)
class MatterService:
    ctx: AppContext

    def create(
        self,
        *,
        actor_id: str,
        name: str,
        purpose: str,
        jurisdiction: str,
        profile: Profile,
        governing_law: str | None = None,
        forum: str = "",
        procedural_rules: str = "",
        relevant_date: date | None = None,
        parties: Sequence[tuple[str, str]] = (),
        stated_issues: Sequence[str] = (),
        represented_party: str | None = None,
    ) -> Matter:
        spec = profile_spec(profile)
        authz = self.ctx.authorizer()
        authz.require_global(actor_id, "matter.create")
        if not authz.bindings.can(actor_id, "matter.create", roles=spec.roles | OVERSIGHT_ROLES):
            raise PolicyDenied(
                f"none of {actor_id!r}'s roles may open a matter under the {profile.value} profile"
            )
        party_list = [Party(name=n, role=r) for n, r in parties]
        represented = None
        if represented_party:
            if profile is not Profile.PARTY_REPRESENTATIVE:
                raise InvalidState("only a party-representative matter has a represented party")
            represented = next(
                (p.party_id for p in party_list if p.name.lower() == represented_party.lower()),
                None,
            )
            if represented is None:
                raise InvalidState(
                    f"represented party {represented_party!r} is not among the parties"
                )
        matter = Matter(
            name=name,
            purpose=purpose,
            jurisdiction=jurisdiction,
            owner_user_id=actor_id,
            status=MatterStatus.ACTIVE,
            profile=profile,
            governing_law=governing_law or jurisdiction,
            forum=forum,
            procedural_rules=procedural_rules,
            relevant_date=relevant_date,
            parties=party_list,
            stated_issues=list(stated_issues),
            represented_party_id=represented,
            authorised_user_ids={actor_id},
        )
        self.ctx.store.put_matter(matter)
        packs = self.ctx.jurisdictions.for_matter(matter)
        self.ctx.log(
            "matter_created",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            action="matter.create",
            subject_id=matter.matter_id,
            outcome="created",
            object_type="matter",
            payload={
                "profile": profile.value,
                "jurisdiction": jurisdiction,
                "governing_law": matter.governing_law,
                "packs": [p.code for p in packs],
                "parties": len(party_list),
            },
        )
        return matter

    def get(self, matter_id: str, actor_id: str) -> Matter:
        return self.ctx.matter_for(matter_id, actor_id, "matter.read")

    def list_for(self, actor_id: str) -> list[Matter]:
        authz = self.ctx.authorizer()
        return [
            m for m in self.ctx.store.list_matters() if authz.can_matter(m, actor_id, "matter.read")
        ]

    def documents(self, matter_id: str, actor_id: str) -> list[Document]:
        matter = self.ctx.matter_for(matter_id, actor_id, "document.read")
        return self.ctx.store.list(Document, matter.matter_id)

    def _save(self, matter: Matter, actor_id: str, change: str, **payload: object) -> Matter:
        self.ctx.store.put_matter(matter)
        self.ctx.log(
            "matter_updated",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            action="matter.manage",
            subject_id=matter.matter_id,
            outcome=change,
            object_type="matter",
            payload=dict(payload),
        )
        return matter

    def grant(self, matter_id: str, *, actor_id: str, user_id: str) -> Matter:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.manage")
        user = self.ctx.user(user_id)
        spec = profile_spec(matter.profile)
        if not any(spec.allows_role(r) for r in user.roles):
            raise PolicyDenied(
                f"{user_id!r} holds no role that is valid on a {matter.profile.value} matter"
            )
        matter.authorised_user_ids.add(user_id)
        return self._save(matter, actor_id, "access_granted", user=user_id)

    def revoke(self, matter_id: str, *, actor_id: str, user_id: str) -> Matter:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.manage")
        if user_id == matter.owner_user_id:
            raise InvalidState(
                "the matter owner's access cannot be revoked; transfer ownership first"
            )
        matter.authorised_user_ids.discard(user_id)
        matter.reviewer_user_ids.discard(user_id)
        return self._save(matter, actor_id, "access_revoked", user=user_id)

    def set_reviewers(
        self, matter_id: str, *, actor_id: str, reviewer_ids: Iterable[str]
    ) -> Matter:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.manage")
        spec = profile_spec(matter.profile)
        chosen = set(reviewer_ids)
        for uid in chosen:
            user = self.ctx.user(uid)
            if user.actor_type is not ActorType.HUMAN:
                raise PolicyDenied(f"{uid!r} is not a human user and cannot be a reviewer")
            if not (user.roles & spec.reviewer_roles):
                raise PolicyDenied(
                    f"{uid!r} holds none of the reviewing roles for this profile: "
                    f"{', '.join(sorted(spec.reviewer_roles))}"
                )
            if uid != matter.owner_user_id and uid not in matter.authorised_user_ids:
                raise PolicyDenied(f"{uid!r} has not been granted access to this matter")
        matter.reviewer_user_ids = chosen
        return self._save(matter, actor_id, "reviewers_set", reviewers=sorted(chosen))

    def set_sources(self, matter_id: str, *, actor_id: str, source_ids: Iterable[str]) -> Matter:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.manage")
        chosen = set(source_ids)
        for sid in chosen:
            self.ctx.sources.require_approved(sid)
        matter.approved_source_ids = chosen
        return self._save(matter, actor_id, "sources_set", sources=sorted(chosen))

    def update(
        self,
        matter_id: str,
        *,
        actor_id: str,
        relevant_date: date | None = None,
        stated_issues: Sequence[str] | None = None,
        forum: str | None = None,
        procedural_rules: str | None = None,
        add_parties: Sequence[tuple[str, str]] = (),
    ) -> Matter:
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.manage")
        changed = []
        if relevant_date is not None:
            matter.relevant_date = relevant_date
            changed.append("relevant_date")
        if stated_issues is not None:
            matter.stated_issues = list(stated_issues)
            changed.append("stated_issues")
        if forum is not None:
            matter.forum = forum
            changed.append("forum")
        if procedural_rules is not None:
            matter.procedural_rules = procedural_rules
            changed.append("procedural_rules")
        for name, role in add_parties:
            matter.parties.append(Party(name=name, role=role))
            changed.append("parties")
        return self._save(matter, actor_id, "details_updated", fields=sorted(set(changed)))

    def close(
        self, matter_id: str, *, actor_id: str, purge_content: bool, reason: str
    ) -> dict[str, int]:
        """Close a matter: end all access and, if asked, delete documents, text and indexes.

        Accountability records (runs, reviews, releases, holds, incidents and the audit ledger)
        are kept. They hold identifiers, hashes and decisions, not document content.
        """
        matter = self.ctx.matter_for(matter_id, actor_id, "matter.close")
        if not reason.strip():
            raise InvalidInput("a reason is required to close a matter")
        counts: dict[str, int] = {}
        if purge_content:
            counts = self.ctx.store.purge_matter_content(matter.matter_id)
            counts["vault_files"] = self.ctx.vault.purge_matter(matter.matter_id)
        revoked = len(matter.authorised_user_ids - {matter.owner_user_id})
        matter.authorised_user_ids = {matter.owner_user_id}
        matter.reviewer_user_ids = set()
        matter.status = MatterStatus.CLOSED
        matter.closed_at = utcnow()
        self.ctx.store.put_matter(matter)
        self.ctx.log(
            "matter_closed",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            action="matter.close",
            subject_id=matter.matter_id,
            outcome="purged" if purge_content else "closed",
            object_type="matter",
            payload={"access_revoked": revoked, "deleted": counts},
        )
        return counts
