"""Who may do what on one matter, and what each person may see of it.

Access to a matter has three layers, and all three must agree:

1. **Account role** (``rbac``): what a person may do anywhere, because of who they are: a judge,
   a paralegal, an auditor.
2. **Matter role** (here): what they do *on this matter*: lead it, decide it, work on it, assist,
   observe or audit. A judge can be an observer on a colleague's matter; a paralegal can never
   be its decision-maker. The two are intersected: a matter role never adds a permission the
   account role lacks.
3. **Clearance** (here): which material on the matter they may read. Material is marked when it
   is filed: before all parties, for the neutral only, in confidence from one party, or
   privileged. Anything a person is not cleared for is withheld from them everywhere: in lists,
   passages, findings, chat and the report. They are told that something was withheld and why,
   never what it says.

A person aligned with one party (``Matter.member_parties``) never sees what another party gave
in confidence, whatever their role.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass

from eli_legal.domain.enums import AccessScope
from eli_legal.domain.models import Chunk, Claim, Document, EvidenceLink, Matter
from eli_legal.security.rbac import (
    _AUDIT,
    _CONTROL,
    _OPERATE,
    _READ,
    _RELEASE,
    _REVIEW,
    _VERIFY,
    DEFAULT_ROLE_ACTIONS,
)
from eli_legal.security.redaction import mask_personal_data

WITHHELD = "[withheld]"
ALL_SCOPES = frozenset(AccessScope)

# Every action that is decided matter by matter. Anything else (managing people, sources,
# settings, packages, opening a matter) is decided by account role alone.
MATTER_ACTIONS: frozenset[str] = frozenset(
    _READ
    | _OPERATE
    | _VERIFY
    | _REVIEW
    | _RELEASE
    | _CONTROL
    | _AUDIT
    | {"matter.manage", "matter.close"}
)


@dataclass(frozen=True, slots=True)
class MatterRole:
    code: str
    label: str
    summary: str
    actions: frozenset[str]
    clearance: frozenset[AccessScope]
    masks_personal_data: bool = False


def _role(
    code: str,
    label: str,
    summary: str,
    actions: Iterable[str],
    clearance: Iterable[AccessScope],
    *,
    masks: bool = False,
) -> MatterRole:
    return MatterRole(code, label, summary, frozenset(actions), frozenset(clearance), masks)


# From the widest to the narrowest. The order is used to pick the narrowest role that still
# covers what an account may do (see ``covering_role``).
MATTER_ROLES: dict[str, MatterRole] = {
    r.code: r
    for r in (
        _role(
            "lead",
            "Lead",
            "Runs the matter: chooses its team, sources and laws, and can do everything a "
            "decision-maker can. Sees all of its material.",
            MATTER_ACTIONS,
            ALL_SCOPES,
        ),
        _role(
            "decision_maker",
            "Decision-maker",
            "Resolves holds, reviews, approves and releases the report, and can stop the work. "
            "Sees all of the matter's material.",
            MATTER_ACTIONS - {"matter.manage", "matter.close"},
            ALL_SCOPES,
        ),
        _role(
            "case_worker",
            "Case worker",
            "Adds documents, runs the analysis and records checks. Cannot approve, release, "
            "resolve holds or overrule a check. Does not see the neutral's own notes.",
            _READ
            | _OPERATE
            | _VERIFY
            | {
                "report.review",
                "report.export",
                "report.prepare_release",
                "workflow.hold",
                "workflow.stop",
                "incident.manage",
                "audit.read",
            },
            {AccessScope.ALL_PARTIES, AccessScope.PARTY_CONFIDENTIAL, AccessScope.PRIVILEGED},
        ),
        _role(
            "assistant",
            "Assistant",
            "Adds documents and starts the analysis. Records no checks and decides nothing. "
            "Sees material before all parties and privileged work, nothing given in confidence.",
            _READ | _OPERATE | {"workflow.hold", "report.export"},
            {AccessScope.ALL_PARTIES, AccessScope.PRIVILEGED},
        ),
        _role(
            "observer",
            "Observer",
            "Reads what is before all parties, with personal contact details masked. Changes "
            "nothing; confidential and privileged material is withheld.",
            {"matter.read", "document.read"},
            {AccessScope.ALL_PARTIES},
            masks=True,
        ),
        _role(
            "auditor",
            "Auditor",
            "Reads and verifies the matter's audit trail and exports its evidence pack. Sees no "
            "document content or findings.",
            {"matter.read", "audit.read", "audit.verify", "evidence.export"},
            (),
            masks=True,
        ),
    )
}
_NARROWEST_FIRST = ("auditor", "observer", "assistant", "case_worker", "decision_maker", "lead")


def account_matter_actions(account_roles: Iterable[str]) -> frozenset[str]:
    """What a person's account roles allow on any matter they are on."""
    out: set[str] = set()
    for code in account_roles:
        out |= DEFAULT_ROLE_ACTIONS.get(code, set())
    return frozenset(out & MATTER_ACTIONS)


def covering_role(account_roles: Iterable[str], *, allow_lead: bool) -> str:
    """The narrowest matter role that takes away nothing the account roles allow.

    Used for anyone added to a matter before matter roles existed, so that no one loses a
    permission they already had (``allow_lead=True``), and as the suggested role for someone
    newly added (``allow_lead=False``: only the person who opened the matter, or someone the
    lead chooses, leads it)."""
    wanted = account_matter_actions(account_roles)
    for code in _NARROWEST_FIRST:
        if code == "lead" and not allow_lead:
            break
        if wanted <= MATTER_ROLES[code].actions:
            return code
    return "lead" if allow_lead else "decision_maker"


def matter_role(matter: Matter, user_id: str, account_roles: Iterable[str]) -> str:
    """The person's role on this matter. Empty if they are not on it."""
    if user_id == matter.owner_user_id:
        return "lead"
    if user_id not in matter.authorised_user_ids:
        return ""
    explicit = matter.member_roles.get(user_id)
    if explicit in MATTER_ROLES:
        return explicit
    return covering_role(account_roles, allow_lead=True)


def permits(matter: Matter, user_id: str, account_roles: Iterable[str], action: str) -> bool:
    """Whether the matter role allows the action. Actions not decided per matter pass."""
    if action not in MATTER_ACTIONS:
        return True
    code = matter_role(matter, user_id, account_roles)
    return bool(code) and action in MATTER_ROLES[code].actions


@dataclass(frozen=True, slots=True)
class Visibility:
    """What one person may read of one matter, and how anything else is shown to them."""

    matter: Matter
    user_id: str
    role: str
    scopes: frozenset[AccessScope]
    party_id: str | None = None
    masks: bool = False

    @classmethod
    def of(cls, matter: Matter, user_id: str, account_roles: Iterable[str]) -> Visibility:
        account_roles = set(account_roles)
        code = matter_role(matter, user_id, account_roles)
        spec = MATTER_ROLES.get(code)
        explicit = matter.member_clearance.get(user_id)
        scopes = (
            frozenset(AccessScope(s) for s in explicit)
            if explicit is not None and code != "lead"
            else (spec.clearance if spec else frozenset())
        )
        if not account_matter_actions(account_roles) & {"document.read"}:
            scopes = frozenset()  # an account that may not read documents reads none here
        return cls(
            matter=matter,
            user_id=user_id,
            role=code,
            scopes=scopes,
            party_id=matter.member_parties.get(user_id),
            masks=bool(spec and spec.masks_personal_data),
        )

    @property
    def sees_everything(self) -> bool:
        return self.scopes == ALL_SCOPES and self.party_id is None and not self.masks

    def party_name(self, party_id: str | None) -> str:
        return next((p.name for p in self.matter.parties if p.party_id == party_id), "one party")

    def can_see(self, scope: AccessScope, party_id: str | None = None) -> bool:
        if scope not in self.scopes:
            return False
        if scope is AccessScope.PARTY_CONFIDENTIAL and self.party_id is not None:
            return party_id == self.party_id
        return True

    def why_withheld(self, scope: AccessScope, party_id: str | None = None) -> str:
        if scope is AccessScope.PARTY_CONFIDENTIAL:
            return f"given in confidence by {self.party_name(party_id)}"
        if scope is AccessScope.NEUTRAL_ONLY:
            return "for the neutral only"
        if scope is AccessScope.PRIVILEGED:
            return "privileged"
        return "outside your role on this matter"

    def marker(self, scope: AccessScope, party_id: str | None = None) -> str:
        return f"{WITHHELD} {self.why_withheld(scope, party_id)}"

    def text(self, text: str) -> str:
        """Visible text, with personal contact details masked for roles that call for it."""
        return mask_personal_data(text) if self.masks else text

    # ── records, as this person may see them ─────────────────────────────────
    def document(self, document: Document) -> Document:
        if self.can_see(document.access_scope, document.party_id):
            if not self.masks:
                return document
            return dataclasses.replace(document, custodian=self.text(document.custodian))
        mark = self.marker(document.access_scope, document.party_id)
        return dataclasses.replace(
            document,
            filename=mark,
            title=mark,
            custodian="",
            vault_ref="",
            error="",
            injection_flags=[],
            waiver_reason="",
        )

    def document_visible(self, document: Document) -> bool:
        return self.can_see(document.access_scope, document.party_id)

    def chunk(self, chunk: Chunk, document: Document) -> Chunk:
        if self.can_see(document.access_scope, document.party_id):
            return (
                chunk if not self.masks else dataclasses.replace(chunk, text=self.text(chunk.text))
            )
        return dataclasses.replace(
            chunk, text=self.marker(document.access_scope, document.party_id)
        )

    def claim(self, claim: Claim) -> Claim:
        if self.can_see(claim.access_scope, claim.party_id):
            if not self.masks:
                return claim
            return dataclasses.replace(
                claim,
                text=self.text(claim.text),
                evidence=[dataclasses.replace(e, quote=self.text(e.quote)) for e in claim.evidence],
            )
        mark = self.marker(claim.access_scope, claim.party_id)
        return dataclasses.replace(
            claim,
            text=mark,
            citation=None,
            uncertainty=None,
            status_reason="",
            origin="",
            evidence=[
                EvidenceLink(target_type=e.target_type, target_id="", locator="", quote="")
                for e in claim.evidence
            ],
        )

    def claim_visible(self, claim: Claim) -> bool:
        return self.can_see(claim.access_scope, claim.party_id)

    def scrub(
        self, text: str, *, documents: Iterable[Document] = (), claims: Iterable[Claim] = ()
    ) -> str:
        """Free text (a rendered report, a list of warnings) with every withheld document's
        name and every withheld finding's words replaced by the reason they are withheld.
        Matching ignores differences of spacing, and the escaping of ``|`` in a table cell."""
        if self.sees_everything:
            return text
        swaps: list[tuple[str, str]] = []
        for d in documents:
            if not self.document_visible(d):
                mark = self.marker(d.access_scope, d.party_id)
                swaps += [(name, mark) for name in {d.title, d.filename} if len(name) > 3]
        for c in claims:
            if not self.claim_visible(c):
                mark = self.marker(c.access_scope, c.party_id)
                words = [c.text, *(e.quote for e in c.evidence)]
                swaps += [(w, mark) for w in words if len(w.strip()) > 12]
        out = text
        for old, new in sorted(swaps, key=lambda pair: -len(pair[0])):
            compact = " ".join(old.split())
            for variant in {old, compact, compact.replace("|", "\\|")}:
                out = out.replace(variant, new)
        return self.text(out)


def strictest_scope(claims: Iterable[Claim]) -> AccessScope:
    """The scope of something built from these findings (a drafted argument): public only if
    all of them are; one shared restriction if they agree on it; otherwise, and whenever one
    party's confidence is involved, the neutral's alone. Nothing built from confidential
    material is ever shown more widely than that material."""
    restricted = {c.access_scope for c in claims} - {AccessScope.ALL_PARTIES}
    if not restricted:
        return AccessScope.ALL_PARTIES
    if len(restricted) == 1 and AccessScope.PARTY_CONFIDENTIAL not in restricted:
        return next(iter(restricted))
    return AccessScope.NEUTRAL_ONLY


def is_withheld(text: str | None) -> bool:
    return bool(text) and str(text).startswith(WITHHELD)
