"""Deployment profiles.

The same engine serves three different kinds of user, and the difference is not cosmetic: it
changes who may hold a role on a matter, what the output may say, and how the use is likely to be
classified by regulation. A matter is created under exactly one profile and cannot change it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import Profile

# Roles that exist to oversee the system rather than to work a matter. Valid under any profile.
# The people of a party to a dispute: they may join a court's, tribunal's or neutral's matter only
# as that party's people (see ``ProfileSpec.party_roles``).
PARTY_SIDE_ROLES = frozenset(
    {
        "prosecutor",
        "supervising_solicitor",
        "solicitor",
        "barrister",
        "in_house_counsel",
        "paralegal",
        "self_represented",
    }
)

OVERSIGHT_ROLES = frozenset(
    {"legal_admin", "governance_officer", "auditor", "reviewer", "read_only"}
)


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    profile: Profile
    label: str
    roles: frozenset[str]  # matter roles valid under this profile
    reviewer_roles: frozenset[str]  # who may be the named reviewer that approves reliance
    report_template: str
    # "prohibited": the output may not say who should win or what the result should be.
    # "merits_assessment": a party's lawyer may assess strengths and risks of the client's case.
    outcome_policy: str
    audiences: tuple[str, ...]
    regulatory_note: str
    disclaimer: str
    # Who may join as one party's people (prosecution, defence, a claimant's or respondent's
    # lawyers, a party acting for themselves): only in the matter role "party", acting for a
    # named party, and only to file, read what they are cleared for and answer for their filings.
    party_roles: frozenset[str] = frozenset()

    def allows_role(self, role: str) -> bool:
        return role in self.roles or role in OVERSIGHT_ROLES

    def allows_party_role(self, role: str) -> bool:
        return role in self.party_roles


PROFILES: dict[Profile, ProfileSpec] = {
    Profile.ADJUDICATOR: ProfileSpec(
        profile=Profile.ADJUDICATOR,
        label="Court, tribunal or arbitral tribunal",
        roles=frozenset({"judge", "tribunal_member", "arbitrator", "tribunal_secretary"}),
        reviewer_roles=frozenset({"judge", "tribunal_member", "arbitrator"}),
        report_template="bench_memorandum",
        outcome_policy="prohibited",
        audiences=("tribunal",),
        regulatory_note=(
            "Use by or on behalf of a judicial authority, or in a similar way in alternative "
            "dispute resolution, to research and interpret facts and law and apply the law to "
            "concrete facts is listed in EU AI Act Annex III point 8(a). Treat as high-risk "
            "unless a documented Article 6(3) assessment concludes otherwise."
        ),
        disclaimer=(
            "Decision support only. This memorandum does not decide the dispute and proposes no "
            "outcome. The tribunal alone determines the facts, the law and the result."
        ),
        party_roles=PARTY_SIDE_ROLES,
    ),
    Profile.NEUTRAL_FACILITATOR: ProfileSpec(
        profile=Profile.NEUTRAL_FACILITATOR,
        label="Mediator or conciliator",
        roles=frozenset({"mediator", "conciliator", "tribunal_secretary"}),
        reviewer_roles=frozenset({"mediator", "conciliator"}),
        report_template="mediation_brief",
        outcome_policy="prohibited",
        audiences=("neutral", "shared"),
        regulatory_note=(
            "A facilitative neutral does not apply the law to decide the dispute, but where the "
            "tool is used to research and interpret facts and law for the neutral it may still "
            "fall within Annex III point 8(a) ('in a similar way in alternative dispute "
            "resolution'). Record the classification assessment for the actual deployment."
        ),
        disclaimer=(
            "Preparation aid for the neutral. It evaluates no party's position and proposes no "
            "settlement terms. Material received in confidence from one party is not disclosed "
            "in any shared output."
        ),
        party_roles=PARTY_SIDE_ROLES,
    ),
    Profile.PARTY_REPRESENTATIVE: ProfileSpec(
        profile=Profile.PARTY_REPRESENTATIVE,
        label="Party's legal representative",
        roles=frozenset(
            {
                "supervising_solicitor",
                "solicitor",
                "barrister",
                "paralegal",
                "in_house_counsel",
                "prosecutor",
            }
        ),
        reviewer_roles=frozenset(
            {"supervising_solicitor", "solicitor", "barrister", "in_house_counsel"}
        ),
        report_template="case_preparation_memorandum",
        outcome_policy="merits_assessment",
        audiences=("legal_team",),
        regulatory_note=(
            "Use by a party's own lawyers to prepare a case is not use by or on behalf of a "
            "judicial authority, so Annex III point 8(a) is unlikely to apply on that ground. "
            "Professional conduct, privilege, confidentiality and data-protection duties apply "
            "in full. Record the classification assessment for the actual deployment."
        ),
        disclaimer=(
            "Privileged and confidential work product prepared for the legal team. It is not "
            "legal advice to the client until a qualified lawyer has reviewed and adopted it."
        ),
    ),
}


def profile_spec(profile: Profile) -> ProfileSpec:
    return PROFILES[profile]
