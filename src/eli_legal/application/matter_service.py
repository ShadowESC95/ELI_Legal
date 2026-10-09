from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from eli_legal.application.container import AppContext
from eli_legal.application.framework_service import default_frameworks
from eli_legal.domain.enums import ActorType, MatterStatus, Profile
from eli_legal.domain.errors import (
    AccountLocked,
    AuthenticationFailed,
    InvalidInput,
    InvalidState,
    PolicyDenied,
    SecondFactorRequired,
)
from eli_legal.domain.models import Chunk, Document, Matter, Party, User, utcnow
from eli_legal.domain.profiles import OVERSIGHT_ROLES, profile_spec
from eli_legal.security import authn, totp
from eli_legal.security.rbac import DEFAULT_ROLE_ACTIONS

_PBKDF2_ITERATIONS = 240_000
MIN_PASSPHRASE_LENGTH = 10


def hash_passphrase(passphrase: str) -> str:
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise InvalidInput(f"a passphrase needs at least {MIN_PASSPHRASE_LENGTH} characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_passphrase(passphrase: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", passphrase.encode("utf-8"), bytes.fromhex(salt), int(iterations)
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), expected)


# Checked against when the user does not exist, so that costs the same as when they do.
_DUMMY_HASH = f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${'00' * 16}${'00' * 32}"


@dataclass(slots=True)
class UserService:
    ctx: AppContext

    def bootstrap_admin(
        self, user_id: str, display_name: str = "", passphrase: str | None = None
    ) -> User:
        """Create the first administrator. Only possible while no user exists."""
        if self.ctx.store.list_users():
            raise PolicyDenied("users already exist; use an administrator account to add more")
        user = User(
            user_id=user_id,
            display_name=display_name or user_id,
            roles={"legal_admin", "system_admin"},
        )
        if passphrase is not None:
            user.passphrase_hash = hash_passphrase(passphrase)
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
        authn.require_step_up(actor_id, "create a user or change their roles")
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
        self.ctx.store.revoke_sessions(user_id)
        self.ctx.log(
            "user_deactivated",
            actor_id=actor_id,
            matter_id="-",
            action="user.manage",
            subject_id=user_id,
            outcome="ok",
            object_type="user",
        )

    def set_passphrase(
        self, *, actor_id: str, user_id: str, new: str, current: str | None = None
    ) -> None:
        """Set a user's sign-in passphrase. A user changes their own by giving the current one;
        an administrator may reset someone else's. Only a salted hash is stored."""
        user = self.ctx.user(user_id)
        if actor_id == user_id:
            # Knowing the current passphrase is the proof. An account that has none yet cannot
            # be claimed by whoever asks first: an administrator sets the initial one.
            if not user.passphrase_hash or not verify_passphrase(
                current or "", user.passphrase_hash
            ):
                self._sign_in_event(user_id, "passphrase_change_refused")
                raise AuthenticationFailed(
                    "the current passphrase is not correct"
                    if user.passphrase_hash
                    else "no passphrase is set for this user; an administrator must set the first one"
                )
        else:
            authn.require_step_up(actor_id, "set another user's passphrase")
            self.ctx.authorizer().require_global(actor_id, "user.manage")
        user.passphrase_hash = hash_passphrase(new)
        self.ctx.store.put_user(user)
        self.ctx.store.revoke_sessions(user_id)  # a changed passphrase ends every open session
        self.ctx.log(
            "passphrase_set",
            actor_id=actor_id,
            matter_id="-",
            action="user.manage",
            subject_id=user_id,
            outcome="ok",
            object_type="user",
        )

    def _passphrase_checked(self, user_id: str, passphrase: str) -> User:
        """The user, if the passphrase is right and the account is not locked. Wrong attempts
        are counted; enough of them in a row lock the account for a while."""
        user = self.ctx.store.get_user(user_id)
        known = user is not None and user.active and bool(user.passphrase_hash)
        state = self.ctx.store.auth_state(user_id) if known else None
        locked = state["locked_until"] if state else None
        if locked is not None and locked > utcnow():
            self._sign_in_event(user_id, "refused_locked")
            raise AccountLocked(
                f"too many failed attempts; this account is locked until {locked:%H:%M} UTC. "
                "An administrator can unlock it."
            )
        # An unknown user costs the same work as a known one, so timing does not reveal who exists.
        ok = verify_passphrase(passphrase, user.passphrase_hash if known and user else _DUMMY_HASH)
        if not (known and ok) or user is None:
            self._failed(user_id if known else None, user_id)
            raise AuthenticationFailed("unknown user or wrong passphrase")
        return user

    def _failed(self, known_user_id: str | None, attempted: str) -> None:
        self._sign_in_event(attempted, "sign_in_refused")
        if known_user_id is None:
            return
        s = self.ctx.settings
        until = self.ctx.store.record_auth_failure(
            known_user_id, threshold=s.lockout_threshold, lock_minutes=s.lockout_minutes
        )
        if until is not None:
            self._sign_in_event(known_user_id, "account_locked")

    def authenticate(self, user_id: str, passphrase: str, *, code: str | None = None) -> User:
        """Sign a person in: the passphrase, and the code from their authenticator if they have
        set one up. Every attempt is recorded."""
        user = self._passphrase_checked(user_id, passphrase)
        state = self.ctx.store.auth_state(user_id)
        if state["totp_secret"]:
            if not code:
                self._sign_in_event(user_id, "second_factor_required")
                raise SecondFactorRequired("enter the code from your authenticator app")
            step = totp.verify(state["totp_secret"], code, last_step=state["totp_last_step"])
            if step is None:
                self._failed(user_id, user_id)
                raise AuthenticationFailed("that code is not correct, or has already been used")
            self.ctx.store.set_auth_state(user_id, totp_last_step=step)
        if state["failures"]:
            self.ctx.store.set_auth_state(user_id, failures=0)
        self._sign_in_event(
            user_id, "signed_in_two_factor" if state["totp_secret"] else "signed_in"
        )
        return user

    def confirm(self, user_id: str, passphrase: str) -> User:
        """The passphrase again, at the moment of a decision, from someone already signed in."""
        user = self._passphrase_checked(user_id, passphrase)
        if self.ctx.store.auth_state(user_id)["failures"]:
            self.ctx.store.set_auth_state(user_id, failures=0)
        return user

    def login(
        self,
        user_id: str,
        passphrase: str,
        *,
        method: str,
        hours: float = 8.0,
        code: str | None = None,
    ) -> str:
        """Verify the credentials and open a session. The token is returned once; only its hash
        is stored, and the session ends on its own after ``hours``."""
        user = self.authenticate(user_id, passphrase, code=code)
        token = "els_" + secrets.token_urlsafe(32)
        self.ctx.store.add_session(token, user.user_id, method, utcnow() + timedelta(hours=hours))
        return token

    def session_user(
        self, token: str, *, method: str | None = None, idle_minutes: float | None = None
    ) -> User:
        """The user behind a session token. Refuses an expired, idle, revoked or orphaned
        session, and one opened by a different kind of front end."""
        user_id = (
            self.ctx.store.session_user(token, method=method, idle_minutes=idle_minutes)
            if token
            else None
        )
        user = self.ctx.store.get_user(user_id) if user_id else None
        if user is None or not user.active:
            raise AuthenticationFailed("not signed in, or the session has ended; sign in again")
        return user

    # ── the second factor ────────────────────────────────────────────────────
    def has_second_factor(self, user_id: str) -> bool:
        return bool(self.ctx.store.auth_state(user_id)["totp_secret"])

    def second_factor_begin(self, *, actor_id: str) -> tuple[str, str]:
        """Start setting up an authenticator. Returns the secret and the address an app reads.
        Nothing changes at sign-in until a code from the app has been confirmed."""
        authn.require_step_up(actor_id, "set up a second factor")
        secret = totp.new_secret()
        self.ctx.store.set_auth_state(actor_id, totp_pending=secret)
        return secret, totp.provisioning_uri(secret, actor_id)

    def second_factor_confirm(self, *, actor_id: str, code: str) -> None:
        authn.require(actor_id)
        state = self.ctx.store.auth_state(actor_id)
        pending = state["totp_pending"]
        step = totp.verify(pending, code) if pending else None
        if step is None:
            raise AuthenticationFailed(
                "that code does not match; check the time on your device and try again"
            )
        self.ctx.store.set_auth_state(
            actor_id, totp_secret=pending, totp_pending=None, totp_last_step=step
        )
        self._user_event(actor_id, actor_id, "second_factor_enabled")

    def second_factor_remove(self, *, actor_id: str, user_id: str) -> None:
        """Remove a second factor: your own, or (as an administrator) someone else's who has
        lost their device. Either way it needs the passphrase again and is recorded."""
        authn.require_step_up(actor_id, "remove a second factor")
        if actor_id != user_id:
            self.ctx.authorizer().require_global(actor_id, "user.manage")
        self.ctx.user(user_id)
        self.ctx.store.set_auth_state(
            user_id, totp_secret=None, totp_pending=None, totp_last_step=0
        )
        self.ctx.store.revoke_sessions(user_id)
        self._user_event(actor_id, user_id, "second_factor_removed")

    def unlock(self, *, actor_id: str, user_id: str) -> None:
        authn.require_step_up(actor_id, "unlock an account")
        self.ctx.authorizer().require_global(actor_id, "user.manage")
        self.ctx.user(user_id)
        self.ctx.store.set_auth_state(user_id, failures=0, locked_until=None)
        self._user_event(actor_id, user_id, "account_unlocked")

    def account_status(self, user_id: str) -> dict[str, object]:
        state = self.ctx.store.auth_state(user_id)
        locked = state["locked_until"]
        return {
            "second_factor": bool(state["totp_secret"]),
            "locked_until": locked.isoformat() if locked and locked > utcnow() else None,
        }

    def _user_event(self, actor_id: str, user_id: str, outcome: str) -> None:
        self.ctx.log(
            "user_security",
            actor_id=actor_id,
            matter_id="-",
            action="user.security",
            subject_id=user_id,
            outcome=outcome,
            object_type="user",
        )

    def logout(self, token: str) -> None:
        user_id = self.ctx.store.session_user(token)
        if self.ctx.store.revoke_session(token) and user_id:
            self._sign_in_event(user_id, "signed_out")

    def directory(self, actor_id: str) -> list[User]:
        """Who exists and what roles they hold. Any signed-in user may see this, since granting
        access to a matter means choosing people from it; it holds no credentials."""
        authn.require(actor_id)
        return self.ctx.store.list_users()

    def needs_passphrase(self, user_id: str) -> bool:
        user = self.ctx.store.get_user(user_id)
        return user is not None and user.active and not user.passphrase_hash

    def _sign_in_event(self, user_id: str, outcome: str) -> None:
        self.ctx.log(
            "sign_in",
            actor_id=user_id[:60],
            matter_id="-",
            action="sign_in",
            subject_id=user_id[:60],
            outcome=outcome,
            object_type="user",
        )

    def issue_token(self, *, actor_id: str, user_id: str, label: str = "") -> str:
        """Create an API token. It is shown once; only its hash is stored."""
        authn.require_step_up(actor_id, "issue an API token")
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
        frameworks: Sequence[str] | None = None,
        recommended_frameworks: bool = True,
    ) -> Matter:
        """Open a matter. Its law and standards packages are the recommended ones for its kind
        and legal system, plus any named in ``frameworks``; or only those named, when
        ``recommended_frameworks`` is false."""
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
        matter.framework_ids = default_frameworks(
            self.ctx, matter, frameworks, recommended=recommended_frameworks
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
                "frameworks": list(matter.framework_ids),
                "parties": len(party_list),
            },
        )
        return matter

    def get(self, matter_id: str, actor_id: str) -> Matter:
        return self.ctx.matter_for(matter_id, actor_id, "matter.read")

    def list_for(self, actor_id: str) -> list[Matter]:
        authn.require(actor_id)
        authz = self.ctx.authorizer()
        return [
            m for m in self.ctx.store.list_matters() if authz.can_matter(m, actor_id, "matter.read")
        ]

    def documents(self, matter_id: str, actor_id: str) -> list[Document]:
        matter = self.ctx.matter_for(matter_id, actor_id, "document.read")
        return self.ctx.store.list(Document, matter.matter_id)

    def passages(self, matter_id: str, document_id: str, actor_id: str) -> list[Chunk]:
        """A document's text as located passages, for reading it in the application."""
        matter = self.ctx.matter_for(matter_id, actor_id, "document.read")
        self.ctx.store.require(Document, matter.matter_id, document_id)
        return self.ctx.store.chunks_for(matter.matter_id, document_id)

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
        authn.require_step_up(actor_id, "close a matter")
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
