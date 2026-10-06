"""Analysis: the arguments open to each party on each issue.

This is the last step before human review and the one closest to the decision, so it is the most
constrained. An argument may rely only on findings that have already passed verification, may
introduce no figure or citation of its own, and may not say who should win.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from eli_legal.domain.enums import ClaimKind, ClaimStatus, Profile, VerificationType
from eli_legal.domain.enums import VerificationStatus as V
from eli_legal.domain.models import Claim, Issue, Matter, VerificationResult
from eli_legal.domain.profiles import profile_spec
from eli_legal.legal.citations import CitationExtractor
from eli_legal.legal.dates import find_dates
from eli_legal.legal.llm import PROMPT_VERSIONS, LegalModel, fenced

VERIFIER_ID = "deterministic/analysis-boundary-1"

# Wording that is the decision itself. Never permitted, under any profile.
_DISPOSITIVE = re.compile(
    r"\b(?:i|we|the (?:tribunal|court|arbitrator|panel))\s+(?:hereby\s+)?"
    r"(?:find|finds|hold|holds|award|awards|order|orders|declare|declares|determine|"
    r"determines|conclude|concludes|dismiss|dismisses|grant|grants)\b|"
    r"\b(?:judgment|award)\s+(?:is\s+)?(?:entered\s+)?(?:for|in favou?r of)\b|"
    r"\bit is (?:hereby\s+)?(?:ordered|adjudged|declared|awarded)\b",
    re.I,
)
# Wording that evaluates who should win. Permitted only for a party's own lawyers.
_EVALUATIVE = re.compile(
    r"\b(?:should|must|will|ought to|is likely to|are likely to|is bound to)\s+"
    r"(?:succeed|fail|win|lose|prevail|be (?:dismissed|allowed|upheld|granted|refused|struck out))\b|"
    r"\b(?:claim|defence|defense|appeal|application|counterclaim)\s+(?:must|should|will)\s+"
    r"(?:be\s+)?(?:fail|succeed|dismissed|allowed|upheld|granted|refused)\b|"
    r"\b(?:is|are)\s+(?:therefore\s+|clearly\s+)?(?:liable|not liable|entitled to (?:damages|judgment|succeed))\b|"
    r"\b(?:stronger|weaker|better|more persuasive|unanswerable|hopeless|bound to fail)\s+"
    r"(?:case|argument|position|claim|defence)\b|"
    r"\bthe (?:tribunal|court|arbitrator) should (?:find|hold|award|dismiss|grant|prefer|accept|reject)\b",
    re.I,
)
_NUMBER = re.compile(r"\d[\d,.]*\d|\d")
_MONEY = re.compile(r"[€£$¥]\s?\d[\d,.]*\d|\b\d[\d,.]*\d\s?(?:EUR|GBP|USD|CHF)\b")
_LABEL = re.compile(r"\s*\(?\b[FA]\d{1,3}\b\)?(?:\s*(?:,|and)\s*\(?\b[FA]\d{1,3}\b\)?)*")
# Opening words that are not names, so their capital can be dropped mid-sentence.
_LOWERABLE = frozenset(
    "the a an it its this that these those there time under on in by because although where "
    "if delivery notice both neither no".split()
)


@dataclass(frozen=True, slots=True)
class Figures:
    """The checkable particulars in a sentence: dates, sums of money, and other numbers.

    They are kept apart because the same digit means different things: the 3 in "3 April" does
    not support a statement about "3 containers".
    """

    dates: frozenset[date]
    money: frozenset[str]
    numbers: frozenset[str]

    def missing_from(self, basis: Figures) -> list[str]:
        return [
            *(d.isoformat() for d in sorted(self.dates - basis.dates)),
            *sorted(self.money - basis.money),
            *sorted(self.numbers - basis.numbers),
        ]


def figures(text: str, date_order: str = "dmy") -> Figures:
    mentions = find_dates(text, date_order=date_order)
    rest = text
    for mention in mentions:
        rest = rest.replace(mention.text, " ")
    money = {"".join(m.split()) for m in _MONEY.findall(rest)}
    rest = _MONEY.sub(" ", rest)
    numbers = {n.rstrip(".,") for n in _NUMBER.findall(rest)}
    return Figures(frozenset(m.value for m in mentions), frozenset(money), frozenset(numbers))


def outcome_language(text: str, profile: Profile) -> str | None:
    """Why the text crosses the decision boundary for this profile, or None if it does not."""
    if _DISPOSITIVE.search(text):
        return "wording that states the decision itself"
    if profile_spec(profile).outcome_policy == "prohibited" and _EVALUATIVE.search(text):
        return "wording that says which party should succeed"
    return None


@dataclass(slots=True)
class Analyst:
    model: LegalModel
    extractor: CitationExtractor
    date_order: str = "dmy"

    def arguments_for_issue(
        self,
        *,
        matter: Matter,
        run_id: str,
        issue: Issue,
        verified: Sequence[Claim],
        max_items: int = 30,
    ) -> list[Claim]:
        if not self.model.available:
            return []
        pool = [c for c in verified if issue.issue_id in c.issue_ids][:max_items]
        if not pool:
            return []
        labels: dict[str, Claim] = {}
        lines: list[str] = []
        party_names = {p.party_id: p.name for p in matter.parties}
        for i, claim in enumerate(pool, start=1):
            prefix = "A" if claim.kind is ClaimKind.LEGAL_PROPOSITION else "F"
            label = f"{prefix}{i}"
            labels[label] = claim
            who = party_names.get(claim.party_id or "", "")
            source = f" [{claim.citation}]" if claim.citation else (f" [from {who}]" if who else "")
            lines.append(f"{label}{source}: {claim.text}")
        names = [p.name for p in matter.parties] or ["the parties"]
        prompt = (
            f"Task {PROMPT_VERSIONS['arguments']}. Issue: {issue.label}\n"
            f"Parties: {', '.join(names)}.\n"
            "Using only the verified items below (F = fact from the evidence, A = passage from "
            "an authority), set out the arguments reasonably open to each party on this issue. "
            "For each argument give the party it favours, the item labels it relies on, and "
            "the argument itself written as a clause that completes the sentence '<party> may "
            "argue that ...'. Do not put item labels inside the argument. Do not weigh the "
            "arguments, do not say which is stronger, and do not say how the issue should be "
            "decided. Do not mention any fact, figure, case or statute that is not in the items. "
            'Reply as {"arguments": [{"party": "<name>", "argument": "<clause>", '
            '"relies_on": ["F1", "A2"]}]} with at most 6 arguments.\n'
            + fenced("\n".join(lines), f"issue:{issue.issue_id}")
        )
        answer = self.model.ask("arguments", prompt, max_tokens=1200)
        if not answer or not isinstance(answer.get("arguments"), list):
            return []
        by_name = {p.name.lower(): p for p in matter.parties}
        out: list[Claim] = []
        for item in answer["arguments"][:6]:
            if not isinstance(item, dict):
                self.model.stats.rejected_items += 1
                continue
            party = by_name.get(str(item.get("party") or "").strip().lower())
            content = self._clause(
                str(item.get("argument") or ""), [p.name for p in matter.parties]
            )
            relied = [labels[str(x)] for x in item.get("relies_on") or [] if str(x) in labels]
            # An argument belongs to a named party and rests on something; otherwise it is not one.
            if party is None or not content or not relied:
                self.model.stats.rejected_items += 1
                continue
            # The system, not the model, supplies the attribution, so nothing a model drafts can
            # read as a finding in the system's own voice.
            text = f"{party.name} may argue that {content}"
            # A model often names fewer items than it used. Any particular in the argument that
            # an offered item supplies is added to what the argument relies on; a particular
            # that no offered item supplies stays missing and fails the check below.
            basis = figures(" ".join(c.text for c in relied), self.date_order)
            for particular in figures(content, self.date_order).missing_from(basis):
                for candidate in pool:
                    if candidate not in relied and not figures(
                        particular, self.date_order
                    ).missing_from(figures(candidate.text, self.date_order)):
                        relied.append(candidate)
                        break
            out.append(
                Claim(
                    matter_id=matter.matter_id,
                    run_id=run_id,
                    text=text,
                    kind=ClaimKind.APPLICATION,
                    issue_ids=[issue.issue_id],
                    depends_on=[c.claim_id for c in relied],
                    party_id=party.party_id,
                    origin=f"model:{self.model.model_id}|{PROMPT_VERSIONS['arguments']}",
                    uncertainty="Model-drafted argument for the reviewer's judgement.",
                )
            )
        return out

    @staticmethod
    def _clause(raw: str, party_names: Sequence[str]) -> str:
        """The model's argument reduced to the clause after '... may argue that'."""
        text = _LABEL.sub("", " ".join(raw.split())).strip()
        text = re.sub(r"\s+([,.;])", r"\1", text)
        lead = re.match(
            r"^(?:.{0,80}?\b(?:may|might|could|can|will)\s+argue\s+that\s+)", text, re.I
        )
        if lead:
            text = text[lead.end() :]
        text = text.strip(" .")
        if not text:
            return ""
        first = text.split(" ", 1)[0]
        if first.lower() in _LOWERABLE and not any(n.startswith(first) for n in party_names):
            text = text[0].lower() + text[1:]
        return text + "."

    def check(
        self, claim: Claim, claims_by_id: dict[str, Claim], profile: Profile
    ) -> list[VerificationResult]:
        """Dependency and decision-boundary checks for one argument."""

        def result(vtype: VerificationType, status: V, detail: str) -> VerificationResult:
            return VerificationResult(
                matter_id=claim.matter_id,
                run_id=claim.run_id,
                claim_id=claim.claim_id,
                verification_type=vtype.value,
                status=status,
                verifier=VERIFIER_ID,
                detail=detail,
                evidence_refs=list(claim.depends_on),
            )

        deps = [claims_by_id.get(d) for d in claim.depends_on]
        if not deps or any(d is None for d in deps):
            dependency = result(
                VerificationType.DEPENDENCY,
                V.FAILED,
                "relies on nothing, or on a finding that does not exist",
            )
        elif any(d is not None and d.status is not ClaimStatus.VERIFIED for d in deps):
            dependency = result(
                VerificationType.DEPENDENCY,
                V.FAILED,
                "relies on a finding that has not passed verification",
            )
        else:
            basis = " ".join(d.text + " " + (d.citation or "") for d in deps if d is not None)
            new_numbers = figures(claim.text, self.date_order).missing_from(
                figures(basis, self.date_order)
            )
            new_citations = set(self.extractor.keys(claim.text)) - set(self.extractor.keys(basis))
            if new_citations:
                dependency = result(
                    VerificationType.DEPENDENCY,
                    V.FAILED,
                    "cites an authority that is not among the findings it relies on",
                )
            elif new_numbers:
                dependency = result(
                    VerificationType.DEPENDENCY,
                    V.FAILED,
                    "states a figure that is not in the findings it relies on: "
                    + ", ".join(new_numbers[:4]),
                )
            else:
                dependency = result(
                    VerificationType.DEPENDENCY,
                    V.VERIFIED,
                    "relies only on verified findings and adds no figure or citation",
                )
        crossing = outcome_language(claim.text, profile)
        boundary = (
            result(VerificationType.OUTCOME_BOUNDARY, V.FAILED, crossing)
            if crossing
            else result(VerificationType.OUTCOME_BOUNDARY, V.VERIFIED, "no outcome is stated")
        )
        return [dependency, boundary]
