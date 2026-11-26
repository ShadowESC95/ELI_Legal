"""Report assembly.

The report is rendered from the verified findings, not written freely by a model, so nothing can
appear in the body that did not pass the gates. Findings that were held or excluded are shown in
their own section with the reason, never mixed with those that may be relied on.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from eli_legal.domain import plain
from eli_legal.domain.enums import (
    AccessScope,
    ClaimKind,
    ClaimStatus,
    DocumentStatus,
    Profile,
)
from eli_legal.domain.models import (
    Authority,
    AuthorityPassage,
    Claim,
    Document,
    Hold,
    Issue,
    Matter,
    Run,
    VerificationResult,
    utcnow,
)
from eli_legal.domain.profiles import profile_spec
from eli_legal.governance.gates import effective_results
from eli_legal.legal.citations import normalise_citation
from eli_legal.legal.evidence_mapper import IssueEvidence, PotentialConflict
from eli_legal.legal.frameworks import FrameworkPack, Requirement
from eli_legal.legal.issue_mapper import stems
from eli_legal.legal.jurisdictions import JurisdictionPack
from eli_legal.persistence import codec

_AUDIENCE_SCOPES: dict[str, frozenset[AccessScope]] = {
    "shared": frozenset({AccessScope.ALL_PARTIES}),
}
# A number together with what it counts ("14 days", "€5,000"). Bare numbers are not compared:
# a section number and a notice period can share a digit and mean unrelated things.
_QUANTITY = re.compile(
    r"\b\d[\d,.]*\s?(?:days?|weeks?|months?|years?|hours?|per cent|percent|%)"
    r"|[€£$¥]\s?\d[\d,.]*\d",
    re.I,
)
_TITLES = {
    "bench_memorandum": "Case analysis memorandum for the tribunal",
    "mediation_brief": "Mediation preparation brief",
    "case_preparation_memorandum": "Case preparation memorandum",
}


def closest_in_wording(text: str, passages: Sequence[AuthorityPassage]) -> AuthorityPassage | None:
    """The passage sharing most word stems with ``text``; None when none shares any."""
    wanted = stems(text)
    best = max(passages, key=lambda p: (len(stems(p.text) & wanted), -p.ordinal), default=None)
    return best if best is not None and stems(best.text) & wanted else None


@dataclass(slots=True)
class ReportContext:
    matter: Matter
    run: Run
    documents: Sequence[Document]
    issues: Sequence[Issue]
    claims: Sequence[Claim]
    verifications: Sequence[VerificationResult]
    holds: Sequence[Hold]
    authorities: dict[str, Authority]
    authority_passages: Mapping[str, Sequence[AuthorityPassage]] = field(default_factory=dict)
    evidence_maps: Sequence[IssueEvidence] = ()
    conflicts: Sequence[PotentialConflict] = ()
    packs: Sequence[JurisdictionPack] = ()
    # The law and standards packages the run was prepared under, and each one's standing.
    frameworks: Sequence[FrameworkPack] = ()
    framework_standing: Mapping[str, str] = field(default_factory=dict)
    framework_validated: Mapping[str, bool] = field(default_factory=dict)
    audience: str = ""
    model_notes: Sequence[str] = ()
    approved_by: str | None = None
    approved_at: datetime | None = None
    audit_head: str = ""
    built_at: datetime | None = None


@dataclass(slots=True)
class BuiltReport:
    markdown: str
    data: dict[str, Any]
    claim_ids: list[str]
    excluded_claim_ids: list[str]
    warnings: list[str]
    template: str
    audience: str


@dataclass(slots=True)
class DraftReport:  # retained name for callers of the earlier scaffold
    matter_id: str
    run_id: str
    text: str
    claim_ids: list[str]
    release_status: str = "NOT_FOR_RELIANCE"
    warnings: list[str] = field(default_factory=list)


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_None._", ""]
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return [*out, ""]


def _why_not(claim: Claim) -> str:
    """Why a finding may not be relied on, said once: "Taken out of reliance by arb.keane: …"."""
    reason = claim.status_reason
    who, sep, rest = reason.partition(": ")
    if who.startswith("excluded by ") and sep:
        return f"{plain.state(claim.status)} by {who.removeprefix('excluded by ')}: {rest}"
    return f"{plain.state(claim.status)}: {reason}" if reason else plain.state(claim.status)


# The limits a reviewer acknowledges, in the groups a reader takes them in. Each warning keeps
# its reference, which is what an approval records.
_LIMIT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Confirm before approving", ("framework_confirm",)),
    (
        "About the material",
        (
            "coverage_waived",
            "pages_not_read",
            "pages_read_by_ocr",
            "pages_unchecked_images",
            "injection_flagged",
            "content_withheld",
            "findings_not_relied_on",
            "possible_conflicts",
            "ambiguous_dates",
        ),
    ),
    (
        "About the law applied",
        (
            "no_legal_sources",
            "no_relevant_date",
            "jurisdiction_pack_missing",
            "jurisdiction_pack_unvalidated",
            "no_frameworks",
            "framework_unvalidated",
        ),
    ),
    (
        "About how it was prepared",
        (
            "no_model",
            "model_used",
            "research_by_words",
            "research_by_meaning",
            "research_partial",
            "model_drafted_arguments",
            "human_overrides",
            "model_note",
        ),
    ),
)
_UNVALIDATED = re.compile(
    r"^(?P<title>.+?) is a summary prepared for this software, checked against its source as at (?P<when>[^,]+), and not validated by a qualified lawyer\. Check the official text\.$"
)


def limits_section(warnings: Sequence[str]) -> list[str]:
    """Section 8 as a reader takes it in: grouped, each limit once. Packages that are all
    unvalidated summaries are named in one sentence rather than one each."""
    by_group: dict[str, list[str]] = {title: [] for title, _ in _LIMIT_GROUPS}
    other: list[str] = []
    unvalidated: list[tuple[str, str, str]] = []
    for w in warnings:
        ident, _, text = w.partition(": ")
        kind = ident.split(":", 1)[0]
        text = text.strip() or w
        match = _UNVALIDATED.match(text) if kind == "framework_unvalidated" else None
        if match:
            unvalidated.append((match["title"], match["when"], ident))
            continue
        group = next((t for t, kinds in _LIMIT_GROUPS if kind in kinds), None)
        (by_group[group] if group else other).append(f"- {text} _({ident})_")
    if unvalidated:
        dates = sorted({when for _, when, _ in unvalidated})
        by_group["About the law applied"].append(
            "- These law and standards packages are summaries prepared for this software, "
            f"checked against their sources as at {', '.join(dates)}, and not validated by a "
            "qualified lawyer; check the official texts: "
            + "; ".join(title for title, _, _ in unvalidated)
            + ". _("
            + ", ".join(ident for _, _, ident in unvalidated)
            + ")_"
        )
    out: list[str] = []
    for title, _ in _LIMIT_GROUPS:
        if by_group[title]:
            out += [f"**{title}**", "", *by_group[title], ""]
    if other:
        out += ["**Other**", "", *other, ""]
    return out


class LegalReportBuilder:
    def build(self, ctx: ReportContext) -> BuiltReport:
        matter, run = ctx.matter, ctx.run
        spec = profile_spec(matter.profile)
        audience = ctx.audience or spec.audiences[0]
        if audience not in spec.audiences:
            raise ValueError(
                f"audience {audience!r} is not valid for profile {matter.profile.value}"
            )
        allowed_scopes = _AUDIENCE_SCOPES.get(audience)

        def visible(scope: AccessScope) -> bool:
            return allowed_scopes is None or scope in allowed_scopes

        docs = [d for d in ctx.documents if visible(d.access_scope)]
        doc_ref = {d.document_id: f"D{i}" for i, d in enumerate(docs, start=1)}
        claims = [c for c in ctx.claims if visible(c.access_scope)]
        withheld = len(ctx.claims) - len(claims)
        by_id = {c.claim_id: c for c in claims}
        results_by_claim: dict[str, list[VerificationResult]] = {}
        for r in ctx.verifications:
            results_by_claim.setdefault(r.claim_id, []).append(r)
        party = {p.party_id: p.name for p in matter.parties}

        prefix = {
            ClaimKind.FACT: "F",
            ClaimKind.PROCEDURAL: "F",
            ClaimKind.LEGAL_PROPOSITION: "A",
            ClaimKind.PARTY_AUTHORITY: "P",
            ClaimKind.APPLICATION: "X",
        }
        counters: dict[str, int] = {}
        ref: dict[str, str] = {}
        for c in claims:
            p = prefix[c.kind]
            counters[p] = counters.get(p, 0) + 1
            ref[c.claim_id] = f"{p}-{counters[p]:03d}"

        def source_of(c: Claim) -> str:
            parts = []
            for link in c.evidence:
                if link.target_type == "document":
                    parts.append(f"{doc_ref.get(link.target_id, 'D?')} {link.locator}")
                else:
                    authority = ctx.authorities.get(link.target_id)
                    parts.append(
                        f"{authority.citation if authority else 'authority'} {link.locator}"
                    )
            return "; ".join(parts)

        verified = [c for c in claims if c.status is ClaimStatus.VERIFIED]
        # An authority the system found that no party cited is new to the dispute. Whoever
        # decides must not rely on it without the parties having had the chance to address it.
        party_cited = {
            normalise_citation(c.citation)
            for c in claims
            if c.kind is ClaimKind.PARTY_AUTHORITY and c.citation
        }
        not_cited = (
            "**No**: found by research only"
            if spec.profile is Profile.PARTY_REPRESENTATIVE
            else "**No**: put it to the parties before relying on it"
        )
        not_relied = [c for c in claims if c.status is not ClaimStatus.VERIFIED and c.material]
        warnings = self._warnings(ctx, claims, withheld, verified)
        approved = bool(ctx.approved_by)
        lines: list[str] = []
        add = lines.append

        add(f"# {_TITLES.get(spec.report_template, 'Case analysis')}")
        add("")
        # One status, never two that contradict each other: a practice matter's report is never
        # "approved for reliance", only reviewed as practice.
        practice = not ctx.matter.real
        if approved and ctx.approved_at and practice:
            add(
                f"> **PRACTICE REVIEW COMPLETE — NOT FOR RELIANCE.** Reviewed by "
                f"{ctx.approved_by} on {ctx.approved_at.date().isoformat()} on a practice matter "
                "(demonstration, training or testing): it holds no real case material and "
                "nothing in it is to be relied on."
            )
        elif approved and ctx.approved_at:
            add(
                f"> **APPROVED FOR RELIANCE** by {ctx.approved_by} on "
                f"{ctx.approved_at.date().isoformat()}. The approval covers the findings in "
                "sections 3–5 only."
            )
        elif practice:
            add(
                "> **PRACTICE MATTER — DRAFT, NOT FOR RELIANCE.** Opened for demonstration, "
                "training or testing: it holds no real case material and nothing in it is to be "
                "relied on, reviewed or not."
            )
        else:
            add(
                "> **DRAFT — NOT FOR RELIANCE.** No finding in this document may be relied on "
                "until a named reviewer has approved it."
            )
        add(">")
        add(f"> {spec.disclaimer}")
        add("")
        lines += self._at_a_glance(
            ctx, spec.label, docs, claims, verified, not_relied, warnings, party_cited
        )

        add("## 1. Matter")
        add("")
        lines += _table(
            ["Item", "Value"],
            [
                ["Matter", matter.name],
                ["Purpose", matter.purpose],
                ["Prepared for", f"{spec.label} ({audience})"],
                ["Forum", matter.forum or "not recorded"],
                [
                    "Jurisdiction / governing law",
                    f"{matter.jurisdiction} / {matter.governing_law or matter.jurisdiction}",
                ],
                ["Procedural rules", matter.procedural_rules or "not recorded"],
                [
                    "Law assessed as at",
                    matter.relevant_date.isoformat() if matter.relevant_date else "not set",
                ],
                [
                    "Parties",
                    "; ".join(f"{p.name} ({p.role})" for p in matter.parties) or "not recorded",
                ],
            ],
        )

        add("## 2. Documents considered")
        add("")
        lines += _table(
            ["Ref", "Document", "Type", "From", "Status", "SHA-256"],
            [
                [
                    doc_ref[d.document_id],
                    d.title or d.filename,
                    plain.kind(d.doc_type),
                    party.get(d.party_id or "", d.custodian or "—"),
                    plain.state(d.status)
                    + (f" — {d.error}" if d.error else "")
                    + (f" ({d.waived_by}: {d.waiver_reason})" if d.waived_by else ""),
                    d.sha256[:16],
                ]
                for d in docs
            ],
        )
        gaps = [d for d in docs if d.status is not DocumentStatus.PROCESSED]
        if gaps:
            add(
                f"**{plain.count(len(gaps), 'document was', 'documents were')} not read by the "
                f"system** and {'is' if len(gaps) == 1 else 'are'} not reflected in anything below."
            )
            add("")

        add("## 3. Chronology")
        add("")
        dated = sorted(
            (c for c in verified if c.kind is ClaimKind.FACT and c.event_date),
            key=lambda c: (c.event_date, ref[c.claim_id]),
        )
        lines += _table(
            ["Date", "Ref", "Stated by", "Statement (verbatim)", "Source"],
            [
                [
                    c.event_date.isoformat() if c.event_date else "",
                    ref[c.claim_id],
                    party.get(c.party_id or "", "—"),
                    f"“{c.text}”" + (f" _({c.uncertainty})_" if c.uncertainty else ""),
                    source_of(c),
                ]
                for c in dated
            ],
        )

        add("## 4. Issues")
        add("")
        maps = {m.issue_id: m for m in ctx.evidence_maps}
        if not ctx.issues:
            add("_No issues were stated at intake or identified in the papers._")
            add("")
        for number, issue in enumerate(ctx.issues, start=1):
            label = {"stated": "stated at intake", "extracted": "taken from the papers"}.get(
                issue.source, "proposed by the model — confirm or discard"
            )
            add(f"### 4.{number} {issue.label}")
            add("")
            add(f"_{issue.kind.capitalize()} issue; {label}._")
            add("")
            mine = [c for c in verified if issue.issue_id in c.issue_ids]
            facts = [c for c in mine if c.kind in (ClaimKind.FACT, ClaimKind.PROCEDURAL)]
            add("**Evidence**")
            add("")
            by_meaning = any(issue.issue_id in c.meaning_issue_ids for c in facts)
            lines += _table(
                ["Ref", "Stated by", "Statement (verbatim)", "Source"]
                + (["Linked to this issue"] if by_meaning else []),
                [
                    [ref[c.claim_id], party.get(c.party_id or "", "—"), f"“{c.text}”", source_of(c)]
                    + (
                        [
                            "by meaning only: check it bears on this issue"
                            if issue.issue_id in c.meaning_issue_ids
                            else "by its words"
                        ]
                        if by_meaning
                        else []
                    )
                    for c in facts
                ],
            )
            entry = maps.get(issue.issue_id)
            if entry and entry.gap:
                add("No evidence bearing on this issue was located in the documents read.")
                add("")
            elif entry and entry.one_sided:
                add("The evidence located on this issue comes from one party only.")
                add("")
            props = [c for c in mine if c.kind is ClaimKind.LEGAL_PROPOSITION]
            add("**Authorities located in the approved sources**")
            add("")
            lines += _table(
                [
                    "Ref",
                    "Authority",
                    "Passage (verbatim)",
                    "Where",
                    "Status check",
                    "Cited by a party",
                ],
                [
                    [
                        ref[c.claim_id],
                        c.citation or "",
                        f"“{c.text}”",
                        "; ".join(e.locator for e in c.evidence if e.target_type == "authority"),
                        self._check_detail(results_by_claim.get(c.claim_id, []), "current_law"),
                        "yes" if normalise_citation(c.citation or "") in party_cited else not_cited,
                    ]
                    for c in props
                ],
            )
            arguments = [c for c in mine if c.kind is ClaimKind.APPLICATION]
            if arguments:
                add(
                    "**Arguments open to the parties** — drafted by a model from the verified items cited; for the reviewer's judgement, not a finding."
                )
                add("")
                lines += _table(
                    ["Ref", "Favours", "Argument", "Relies on"],
                    [
                        [
                            ref[c.claim_id],
                            party.get(c.party_id or "", "—"),
                            c.text,
                            ", ".join(ref.get(d, "?") for d in c.depends_on),
                        ]
                        for c in arguments
                    ],
                )

        if ctx.conflicts:
            add("### Statements by the parties that appear to differ")
            add("")
            lines += _table(
                ["First", "Second", "Why flagged"],
                [
                    [ref.get(k.claim_a, "?"), ref.get(k.claim_b, "?"), k.reason]
                    for k in ctx.conflicts
                    if k.claim_a in by_id and k.claim_b in by_id
                ],
            )

        add("## 5. Authorities relied on by the parties")
        add("")
        add(
            "The system confirms that each authority exists in an approved source and reports "
            "its current status. **It has not checked that an authority supports the "
            "proposition for which a party cites it** unless the last column says a person did."
        )
        add("")
        lines += _table(
            [
                "Ref",
                "Cited by",
                "Authority",
                "What the party says (verbatim)",
                "Source",
                "Closest passage in the authority (verbatim)",
                "Status check",
                "Support checked by a person",
            ],
            [
                [
                    ref[c.claim_id],
                    party.get(c.party_id or "", "—"),
                    c.citation or "",
                    f"“{c.text}”",
                    source_of(c),
                    self._closest_passage(c, ctx.authority_passages.get(c.authority_id or "", ())),
                    self._check_detail(results_by_claim.get(c.claim_id, []), "current_law"),
                    self._human_support(results_by_claim.get(c.claim_id, [])),
                ]
                for c in verified
                if c.kind is ClaimKind.PARTY_AUTHORITY
            ],
        )

        add("## 6. Findings not to be relied on")
        add("")
        add(
            "These were held by a verification gate or removed by a named person. They are listed so that nothing is silently dropped."
        )
        add("")
        lines += _table(
            ["Ref", "Kind", "Finding", "Authority", "Source", "Why"],
            [
                [
                    ref[c.claim_id],
                    plain.kind(c.kind),
                    f"“{c.text}”",
                    c.citation or "—",
                    source_of(c),
                    _why_not(c),
                ]
                for c in not_relied
            ],
        )

        add("## 7. Verification summary")
        add("")
        tally: dict[tuple[str, str], int] = {}
        human: list[list[str]] = []
        for c in claims:
            for vtype, r in effective_results(results_by_claim.get(c.claim_id, [])).items():
                tally[(vtype, r.status.value)] = tally.get((vtype, r.status.value), 0) + 1
                if r.by_human:
                    human.append(
                        [
                            ref[c.claim_id],
                            plain.check_name(vtype),
                            plain.state(r.status),
                            r.verifier,
                            "yes" if r.override else "no",
                            r.reason,
                        ]
                    )
        lines += _table(
            ["Check", "Result", "Findings"],
            [[plain.check_name(k[0]), plain.state(k[1]), str(v)] for k, v in sorted(tally.items())],
        )
        if human:
            add("### Checks decided by a person")
            add("")
            lines += _table(
                ["Finding", "Check", "Result", "By", "Overrides the system", "Reason given"], human
            )

        add("## 8. Limits of this document")
        add("")
        add(
            "The reviewer acknowledges each of these before approving. The reference in "
            "brackets is what the approval records."
        )
        add("")
        lines += limits_section(warnings)
        if not warnings:
            add("_None recorded._")
        add("")
        add(f"_Regulatory note for this profile:_ {spec.regulatory_note}")
        add("")

        self._frameworks_section(ctx, add, lines)

        add("## 10. Run record")
        add("")
        lines += _table(
            ["Item", "Value"],
            [
                ["Run", run.run_id],
                ["Started by", run.initiated_by],
                ["Workflow", f"{run.workflow_id} {run.workflow_version}"],
                ["Policy version", run.policy_version],
                [
                    "Models",
                    ", ".join(f"{k}={v}" for k, v in sorted(run.model_versions.items())) or "none",
                ],
                ["Prompts", ", ".join(sorted(run.prompt_versions.values())) or "none"],
                [
                    "Law and standards",
                    ", ".join(f"{k}={v}" for k, v in sorted(run.framework_versions.items()))
                    or "none",
                ],
                [
                    "Tools",
                    ", ".join(f"{k}={v}" for k, v in sorted(run.tool_versions.items())) or "none",
                ],
                ["Audit chain head at build", ctx.audit_head[:24] or "—"],
                ["Built", (ctx.built_at or utcnow()).isoformat(timespec="seconds")],
            ],
        )

        markdown = "\n".join(lines).rstrip() + "\n"
        data = {
            "matter_id": matter.matter_id,
            "run_id": run.run_id,
            "template": spec.report_template,
            "audience": audience,
            "release_status": "APPROVED_FOR_RELIANCE" if approved else "NOT_FOR_RELIANCE",
            "refs": ref,
            "documents": {
                doc_ref[d.document_id]: {"document_id": d.document_id, "sha256": d.sha256}
                for d in docs
            },
            "claims": [codec.to_jsonable(c) for c in claims],
            "verifications": [
                codec.to_jsonable(r) for c in claims for r in results_by_claim.get(c.claim_id, [])
            ],
            "open_holds": [codec.to_jsonable(h) for h in ctx.holds if h.status.value == "open"],
            "warnings": warnings,
        }
        return BuiltReport(
            markdown=markdown,
            data=data,
            claim_ids=[c.claim_id for c in verified],
            excluded_claim_ids=[c.claim_id for c in not_relied],
            warnings=warnings,
            template=spec.report_template,
            audience=audience,
        )

    @staticmethod
    def _at_a_glance(
        ctx: ReportContext,
        prepared_for: str,
        docs: Sequence[Document],
        claims: Sequence[Claim],
        verified: Sequence[Claim],
        not_relied: Sequence[Claim],
        warnings: Sequence[str],
        party_cited: set[str],
    ) -> list[str]:
        """The report in a few lines, for a reader who has a minute: what it is, what it rests
        on, what may be relied on, and what must be done before relying on it. It sits before
        the body, so it may say whether the report has been approved."""
        read = sum(1 for d in docs if d.status is DocumentStatus.PROCESSED)
        kinds: dict[ClaimKind, int] = {}
        for c in verified:
            kinds[c.kind] = kinds.get(c.kind, 0) + 1
        named: list[tuple[ClaimKind, str, str]] = [
            (ClaimKind.FACT, "fact", "facts"),
            (ClaimKind.PROCEDURAL, "procedural fact", "procedural facts"),
            (
                ClaimKind.PARTY_AUTHORITY,
                "authority cited by a party",
                "authorities cited by a party",
            ),
            (ClaimKind.LEGAL_PROPOSITION, "passage of law", "passages of law"),
            (ClaimKind.APPLICATION, "drafted argument", "drafted arguments"),
        ]
        parts = [plain.count(kinds[k], one, many) for k, one, many in named if kinds.get(k)]
        new_law = [
            c
            for c in verified
            if c.kind is ClaimKind.LEGAL_PROPOSITION
            and normalise_citation(c.citation or "") not in party_cited
        ]
        confirm = [w for w in warnings if w.startswith("framework_confirm:")]
        approved = bool(ctx.approved_by)
        when = f" on {ctx.approved_at.date().isoformat()}" if ctx.approved_at else ""
        # The same single status as the banner above: a practice matter is reviewed, never relied on.
        practice = not ctx.matter.real
        if practice:
            status = (
                f"Practice review complete: reviewed by {ctx.approved_by}{when}. Not for "
                "reliance: a practice matter."
                if approved
                else "Practice matter, draft. Not for reliance, reviewed or not."
            )
            kept = "- **Passed its checks (practice, not for reliance):** "
        else:
            status = (
                f"Approved for reliance by {ctx.approved_by}{when}."
                if approved
                else "Draft. Not to be relied on until a named reviewer approves it."
            )
            kept = "- **May be relied on" + ("" if approved else " once approved") + ":** "
        out = [
            "## At a glance",
            "",
            f"- **What this is:** prepared for {prepared_for.lower()}; it decides nothing.",
            f"- **Status:** {status}",
            f"- **Documents:** {read} of {len(docs)} read"
            + (f"; {len(docs) - read} not read (see section 2)." if read < len(docs) else "."),
            kept + (", ".join(parts) if parts else "nothing") + " (sections 3 to 5).",
            f"- **Not to be relied on:** {plain.count(len(not_relied), 'finding')}, each with "
            "the reason (section 6).",
        ]
        if new_law:
            out.append(
                f"- **Law no party cited:** {plain.count(len(new_law), 'passage')} found by "
                "research alone. Put "
                + ("it" if len(new_law) == 1 else "them")
                + " to the parties before relying on "
                + ("it." if len(new_law) == 1 else "them.")
                if ctx.matter.profile is not Profile.PARTY_REPRESENTATIVE
                else f"- **Law no party cited:** {plain.count(len(new_law), 'passage')} found "
                "by research alone."
            )
        if confirm:
            out.append(
                f"- **The reviewer confirms:** {plain.count(len(confirm), 'statement')} required "
                "by the law and standards that apply (section 8)."
            )
        out.append(
            f"- **Limits to read first:** {plain.count(len(warnings), 'point')} (section 8)."
        )
        if len(claims) != len(ctx.claims):
            out.append(
                "- **Shared version:** material given in confidence is left out of this copy."
            )
        return [*out, ""]

    @staticmethod
    def _check_detail(results: Sequence[VerificationResult], vtype: str) -> str:
        r = effective_results(results).get(vtype)
        if r is None:
            return "Not checked."
        said = plain.check_result(vtype, r.status, r.detail)
        return f"{said} (confirmed by {r.verifier})" if r.by_human else said

    @staticmethod
    def _closest_passage(claim: Claim, passages: Sequence[AuthorityPassage]) -> str:
        """The passage of the cited authority nearest in meaning (chosen during the run, with an
        embedding model) or, failing that, in wording to what the party says of it.

        Shown so a person can compare the two at a glance. A figure the party states that the
        passage does not contain is pointed out; that is a prompt to look, not a finding.
        """
        if not passages:
            return "—"
        by_meaning = [p for p in passages if p.passage_id == claim.closest_passage_id]
        if by_meaning:
            best, how = by_meaning[0], "closest in meaning"
        else:
            found = closest_in_wording(claim.text, passages)
            if found is None:
                return "no passage with similar wording was found"
            best, how = found, "closest in wording"

        def quantities(text: str) -> set[str]:
            return {" ".join(q.lower().split()) for q in _QUANTITY.findall(text)}

        absent = sorted(quantities(claim.text) - quantities(best.text))
        note = (
            f" — note: “{'”, “'.join(absent)}” appears in the party's sentence but not in this passage"
            if absent
            else ""
        )
        return f"“{best.text}” ({best.locator}; {how}){note}"

    @staticmethod
    def _human_support(results: Sequence[VerificationResult]) -> str:
        r = effective_results(results).get("proposition")
        if r and r.by_human:
            return f"{plain.state(r.status)} by {r.verifier}"
        return "no"

    @staticmethod
    def _frameworks_section(
        ctx: ReportContext, add: Callable[[str], None], lines: list[str]
    ) -> None:
        profile = ctx.matter.profile.value
        add("## 9. Law and standards applied")
        add("")
        if not ctx.frameworks:
            add("_No law or standards package was applied to this matter._")
            add("")
            return
        add(
            "Chosen for this matter and recorded with the run. Each requirement is met in one of "
            "five ways: by the system's own controls; as a rule given to the model in every call; "
            "by a reviewer's confirmation (listed in section 8 and acknowledged at approval); by a "
            "disclosure below; or, for an obligation of an organisation rather than of this "
            "work, by noting it here. Nothing here says the work complies: people decide that."
        )
        add("")
        how: dict[str, Callable[[Requirement], str]] = {
            "enforced": lambda r: "Enforced by " + ", ".join(r.controls),
            "instruction": lambda r: "Given to the model as a rule",
            "attestation": lambda r: "Reviewer confirms",
            "disclosure": lambda r: "Disclosed below",
            "note": lambda r: "For the " + " / ".join(r.addressed_to),
        }
        disclosures: list[str] = []
        for pack in ctx.frameworks:
            add(f"### {pack.title}")
            add("")
            add(
                f"_{pack.instrument or pack.issuer}. Version {pack.version}; "
                f"{ctx.framework_standing.get(pack.pack_id, '')}._"
            )
            add("")
            rows = []
            for r in pack.applicable(profile):
                rows.append([r.reference or r.req_id, r.title, how[r.effect](r)])
                if r.effect == "disclosure":
                    disclosures.append(
                        f"{r.confirmation} ({pack.short_title}, {r.reference or r.title})"
                    )
            lines.extend(_table(["Provision", "Requirement", "How it is met"], rows))
            limits = []
            if pack.rules.status_max_age_days:
                limits.append(
                    f"an authority's status must have been confirmed within {pack.rules.status_max_age_days} days"
                )
            if pack.rules.forbidden_terms:
                limits.append(
                    "model-drafted text containing "
                    + ", ".join(f"“{t}”" for t in pack.rules.forbidden_terms)
                    + " is discarded"
                )
            if limits:
                add("Tightens the system: " + "; ".join(limits) + ".")
                add("")
        if disclosures:
            add("### Disclosures")
            add("")
            for d in dict.fromkeys(disclosures):
                add(f"> {d}")
                add("")

    @staticmethod
    def _warnings(
        ctx: ReportContext, claims: Sequence[Claim], withheld: int, verified: Sequence[Claim]
    ) -> list[str]:
        w: list[str] = []
        profile = ctx.matter.profile.value
        if not ctx.frameworks:
            w.append(
                "no_frameworks: No law or standards package was applied to this matter, so the model was given no rules beyond the system's own and no compliance confirmations were asked for."
            )
        for fw in ctx.frameworks:
            if fw.origin == "shipped" and not ctx.framework_validated.get(fw.pack_id):
                w.append(
                    f"framework_unvalidated:{fw.pack_id}: {fw.title} is a summary prepared for this software, checked against its source as at {fw.as_at or 'an unrecorded date'}, and not validated by a qualified lawyer. Check the official text."
                )
            for r in fw.applicable(profile):
                if r.effect == "attestation":
                    w.append(
                        f"framework_confirm:{fw.pack_id}/{r.req_id}: {r.confirmation} ({fw.short_title}, {r.reference or r.title})"
                    )
        for pack in ctx.packs:
            if pack.pack_status == "fallback":
                w.append(
                    f"jurisdiction_pack_missing:{pack.code}: No jurisdiction pack exists for this legal system; citation recognition is minimal and cited authorities may have gone undetected."
                )
            elif not pack.validated:
                w.append(
                    f"jurisdiction_pack_unvalidated:{pack.code}: The {pack.name} pack has not been validated by a lawyer qualified in that jurisdiction."
                )
        if ctx.matter.relevant_date is None:
            w.append(
                "no_relevant_date: No date was set for assessing the law, so legislation was judged as it stands today."
            )
        if not ctx.matter.approved_source_ids:
            w.append(
                "no_legal_sources: No legal source is approved for this matter. No legal research was done and no cited authority could be checked."
            )
        else:
            ranked_by = ctx.run.tool_versions.get("retrieval", "")
            if "meaning:" in ranked_by:
                embedder = ranked_by.split("meaning:", 1)[1].split(";", 1)[0].split("@", 1)[0]
                w.append(
                    f"research_by_meaning: Research found passages by their meaning as well as their words, with the embedding model {embedder} on this machine. That decides only which passages were offered and in what order: each is quoted word for word and checked like any other."
                )
            elif ranked_by:
                w.append(
                    "research_by_words: Research found passages by the words of each issue only, so a provision put in other words may have been missed."
                )
            if ctx.run.tool_versions.get("retrieval_note"):
                w.append(f"research_partial: {ctx.run.tool_versions['retrieval_note']}")
        models = {k: v for k, v in ctx.run.model_versions.items() if v != "none"}
        if not models:
            w.append(
                "no_model: No language model was used. Facts were selected by rule (dated or monetary statements) and no arguments were drafted."
            )
        else:
            w.append(
                f"model_used: Selection, linking and argument drafting used {', '.join(sorted(set(models.values())))}. Model output was validated against the source items but can still omit relevant material."
            )
        for d in ctx.documents:
            if d.status is DocumentStatus.WAIVED:
                w.append(
                    f"coverage_waived:{d.document_id}: “{d.title or d.filename}” was not read; {d.waived_by} accepted that gap ({d.waiver_reason})."
                )
            name = d.title or d.filename
            if d.unread_pages:
                pages = ", ".join(map(str, d.unread_pages))
                w.append(
                    f"pages_not_read:{d.document_id}: “{name}”, page(s) {pages}: only an image "
                    "with no text layer, not read; nothing on them is in this report"
                    + (f" ({d.waived_by or 'a person'} checked them against the original)."
                       if set(d.unread_pages) <= set(d.pages_checked) else ".")
                )  # fmt: skip
            if d.ocr_pages:
                read = ", ".join(f"{n} ({conf:g}%)" for n, conf in
                                 sorted(d.ocr_pages.items(), key=lambda kv: int(kv[0])))  # fmt: skip
                w.append(
                    f"pages_read_by_ocr:{d.document_id}: “{name}”, page(s) {read} were images "
                    f"read by OCR ({d.ocr_engine}). OCR can misread figures, dates and names: "
                    "check anything quoted from them, marked (OCR), against the original page."
                )
            if d.pictured_pages or d.blank_pages:
                said = []
                if d.pictured_pages:
                    said.append("page(s) " + ", ".join(map(str, d.pictured_pages))
                                + " hold images beside their text that were not read")  # fmt: skip
                if d.blank_pages:
                    said.append("page(s) " + ", ".join(map(str, d.blank_pages))
                                + " have no text and no image (blank, or drawn as shapes)")  # fmt: skip
                w.append(f"pages_unchecked_images:{d.document_id}: “{name}”: "
                         + "; ".join(said) + ". Look at them in the original.")  # fmt: skip
            if d.injection_flags:
                w.append(
                    f"injection_flagged:{d.document_id}: “{d.title or d.filename}” contains text that looks addressed to an AI system ({', '.join(d.injection_flags)}). It was treated as evidence only."
                )
        overrides = [r for r in ctx.verifications if r.override]
        if overrides:
            w.append(
                f"human_overrides: {plain.count(len(overrides), 'automated check result was', 'automated check results were')} overridden by a person; see section 7."
            )
        not_relied = [c for c in claims if c.status is not ClaimStatus.VERIFIED and c.material]
        if not_relied:
            w.append(
                f"findings_not_relied_on: {plain.count(len(not_relied), 'finding')} failed or lacked verification and {'is' if len(not_relied) == 1 else 'are'} excluded from sections 3–5; see section 6."
            )
        if any(c.kind is ClaimKind.APPLICATION for c in verified):
            w.append(
                "model_drafted_arguments: The arguments in section 4 were drafted by a model. They rest on verified items but are not verified conclusions, and a model can attribute an argument to the wrong party or repeat itself."
            )
        if any(c.uncertainty for c in verified if c.kind is ClaimKind.FACT):
            w.append(
                "ambiguous_dates: At least one numeric date could be read two ways; it is marked in the chronology."
            )
        if withheld:
            w.append(
                f"content_withheld: {plain.count(withheld, 'finding rests', 'findings rest')} on material confidential to one party or to the neutral and {'is' if withheld == 1 else 'are'} omitted from this shared version."
            )
        if ctx.conflicts:
            w.append(
                f"possible_conflicts: {plain.count(len(ctx.conflicts), 'pair')} of statements may conflict; see section 4."
            )
        w.extend(f"model_note: {n}" for n in ctx.model_notes)
        return w
