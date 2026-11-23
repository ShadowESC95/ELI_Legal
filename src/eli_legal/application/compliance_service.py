"""The organisation's side of compliance: recorded, reviewed on time, and shown beside what the
software does, so every requirement reads as met, waiting or due for review rather than as
"partial".

Anyone signed in may read where things stand; it holds no matter content. Recording is a
decision in a named person's name: it needs the right to manage compliance and the person's
passphrase again, and it is written to the audit trail.
"""

from __future__ import annotations

import contextvars
import hashlib
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from eli_legal import __version__
from eli_legal.application.container import AppContext
from eli_legal.domain.enums import ActorType, ClaimKind, ClaimStatus, HoldScope
from eli_legal.domain.errors import InvalidInput, InvalidState, NotFound
from eli_legal.domain.models import Chunk, Claim, Hold, utcnow
from eli_legal.domain.profiles import PROFILES
from eli_legal.governance.compliance import (
    MIN_AUDIT_RETENTION_DAYS,
    ActionStatus,
    ComplianceRecord,
    OrganisationAction,
    RequirementStatus,
    TrainingRecord,
    action_status,
    load_actions,
    requirement_statuses,
    review_date,
    template_title,
)
from eli_legal.governance.registers import load_register
from eli_legal.security import authn
from eli_legal.security.access import account_matter_actions

RECORDS = "compliance_record"
TRAINING = "training_record"
# Thresholds the evaluation is held to unless the provider declares others.
DEFAULT_THRESHOLDS = {"defects_caught": 1.0, "facts_verbatim": 1.0, "unexpected_holds": 0}
# The defects planted in the evaluation matter, and how each must be caught.
_PLANTED = (
    ("An authority overruled before the events", "[2011] XXSC 14", "current_law"),
    ("A citation of a case that does not exist", "[2019] XXSC 99", "citation"),
    ("An authority whose status is too old to rely on", "[2018] XXCA 33", "current_law"),
)


@dataclass(frozen=True, slots=True)
class Retention:
    audit_days: int
    closed_matter_days: int
    recorded_by: str
    recorded_on: date
    # An open matter with no recorded activity for this many days is reported by the routine
    # checks, so it is closed (and its content goes on time) or kept open on purpose. 0: off.
    inactive_matter_days: int = 0


@dataclass(frozen=True, slots=True)
class Overview:
    requirements: list[RequirementStatus]
    actions: list[ActionStatus]

    def count(self, state: str) -> int:
        return sum(1 for r in self.requirements if r.state == state)

    @property
    def headline(self) -> str:
        total = len(self.requirements)
        met = self.count("met") + self.count("software")
        waiting, due = self.count("waiting"), self.count("review_due")
        out = f"{met} of {total} requirements met"
        if waiting:
            out += f"; {waiting} waiting for your organisation"
        if due:
            out += f"; {due} due for review"
        return out + "."


class ComplianceService:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    # ── reading ──────────────────────────────────────────────────────────────
    def actions(self) -> list[OrganisationAction]:
        return load_actions()

    def action(self, action_id: str) -> OrganisationAction:
        found = next((a for a in self.actions() if a.action_id == action_id), None)
        if found is None:
            raise NotFound(f"no organisation action {action_id!r}")
        return found

    def records(self, action_id: str | None = None) -> list[ComplianceRecord]:
        out = self.ctx.store.list_registry(RECORDS, ComplianceRecord)
        return sorted(
            (r for r in out if action_id is None or r.action_id == action_id),
            key=lambda r: r.recorded_at,
        )

    def training(self) -> list[TrainingRecord]:
        return sorted(
            self.ctx.store.list_registry(TRAINING, TrainingRecord), key=lambda r: r.recorded_at
        )

    def untrained(self, today: date | None = None) -> list[str]:
        """People who work on matters and have no current training record."""
        today = today or utcnow().date()
        current = {t.user_id for t in self.training() if t.current(today)}
        return sorted(
            u.user_id
            for u in self.ctx.store.list_users()
            if u.active
            and u.actor_type is ActorType.HUMAN
            and account_matter_actions(u.roles)
            & {"workflow.run", "report.approve", "document.read"}
            and u.user_id not in current
        )

    def overview(self, *, actor_id: str, today: date | None = None) -> Overview:
        """Where every requirement and organisation action stands. Anyone signed in may read
        it: it holds no matter content."""
        authn.require(actor_id)
        return self.status(today=today)

    def status(self, *, today: date | None = None) -> Overview:
        """The same, for the system's own routine checks."""
        today = today or utcnow().date()
        actions = self.actions()
        records = self.records()
        untrained = self.untrained(today)
        by_action: dict[str, list[ComplianceRecord]] = {}
        for r in records:
            by_action.setdefault(r.action_id, []).append(r)
        return Overview(
            requirements=requirement_statuses(
                actions, records, today=today, people_untrained=untrained
            ),
            actions=[
                action_status(
                    a, by_action.get(a.action_id, []), today=today, people_untrained=untrained
                )
                for a in actions
            ],
        )

    def retention(self) -> Retention | None:
        latest = self.records("OA-09")
        if not latest:
            return None
        r = latest[-1]
        return Retention(
            audit_days=int(r.answers["audit_days"]),
            closed_matter_days=int(r.answers["closed_matter_days"]),
            inactive_matter_days=int(r.answers.get("inactive_matter_days", "0") or 0),
            recorded_by=r.recorded_by,
            recorded_on=r.recorded_at.date(),
        )

    def readiness(self, *, actor_id: str) -> list[ActionStatus]:
        """What must be done before the conformity assessment can be recorded: every action
        needed before real use, other than the assessment and what follows it."""
        later = {"OA-11", "OA-12", "OA-13"}
        return [
            a
            for a in self.overview(actor_id=actor_id).actions
            if a.action.before_real_use
            and a.action.action_id not in later
            and a.state in ("waiting", "review_due")
        ]

    # ── recording ────────────────────────────────────────────────────────────
    def _authorise(self, actor_id: str, what: str) -> None:
        authn.require_step_up(actor_id, what)
        self.ctx.authorizer().require_global(actor_id, "compliance.manage")

    def _save(self, record: ComplianceRecord, action: OrganisationAction) -> ComplianceRecord:
        record.review_by = review_date(action, record.recorded_at.date())
        self.ctx.store.put_registry(RECORDS, record.record_id, record)
        self.ctx.log(
            "compliance_recorded",
            actor_id=record.recorded_by,
            matter_id="-",
            action="compliance.manage",
            subject_id=action.action_id,
            outcome="not_applicable" if record.not_applicable else "recorded",
            object_type="compliance_record",
            input_hash=hashlib.sha256(
                repr(sorted(record.answers.items())).encode("utf-8")
            ).hexdigest(),
            payload={
                "record_id": record.record_id,
                "requirements": list(action.requirement_ids),
                "review_by": record.review_by.isoformat() if record.review_by else None,
            },
        )
        return record

    def record(
        self,
        action_id: str,
        *,
        actor_id: str,
        answers: Mapping[str, str] | None = None,
        confirmed: bool = False,
        notes: str = "",
        reference: str = "",
        not_applicable: bool = False,
    ) -> ComplianceRecord:
        """Record that an action was done, in the actor's name. A form needs every question
        answered; a statement needs confirming; a registration needs its number. Anything may
        instead be recorded as not applying, with the reason."""
        action = self.action(action_id)
        self._authorise(actor_id, f"record '{action.title}'")
        answers = {k: " ".join(str(v).split()) for k, v in (answers or {}).items()}
        notes, reference = notes.strip(), reference.strip()
        if not_applicable:
            if len(notes) < 10:
                raise InvalidInput("say why it does not apply (at least a sentence)")
            return self._save(
                ComplianceRecord(
                    action_id=action.action_id,
                    recorded_by=actor_id,
                    summary="Does not apply.",
                    notes=notes,
                    not_applicable=True,
                ),
                action,
            )
        if action.evidence in ("training", "evaluation", "retention", "document"):
            raise InvalidState(
                {
                    "training": "training is recorded person by person",
                    "evaluation": "the evaluation is recorded by running it",
                    "retention": "retention is recorded by setting the periods",
                    "document": "generate the document, then sign it off",
                }[action.evidence]
            )
        if action.evidence == "form":
            missing = [f.label for f in action.form if not answers.get(f.key)]
            if missing:
                raise InvalidInput(
                    f"{len(missing)} question(s) are unanswered, starting with: {missing[0]}"
                )
            summary = f"{template_title(action.template)} completed."
        elif action.evidence == "attestation":
            if not confirmed:
                raise InvalidInput("confirm the statement to record it")
            summary = "Confirmed."
        elif action.evidence == "registration":
            if len(reference) < 3:
                raise InvalidInput("give the registration number")
            summary = f"Registered as {reference}."
        else:  # pragma: no cover - the register check refuses unknown kinds
            raise InvalidState(f"unknown evidence kind {action.evidence!r}")
        return self._save(
            ComplianceRecord(
                action_id=action.action_id,
                recorded_by=actor_id,
                summary=summary,
                answers=dict(answers),
                notes=notes,
                reference=reference,
            ),
            action,
        )

    def set_retention(
        self,
        *,
        actor_id: str,
        audit_days: int,
        closed_matter_days: int,
        notes: str = "",
        inactive_matter_days: int = 0,
    ) -> ComplianceRecord:
        """How long the audit trail and a closed matter's content are kept. The audit trail is
        kept at least six months; the routine checks delete closed matters' content on time."""
        action = self.action("OA-09")
        self._authorise(actor_id, "set the retention periods")
        if audit_days < MIN_AUDIT_RETENTION_DAYS:
            raise InvalidInput(
                f"the audit trail must be kept at least {MIN_AUDIT_RETENTION_DAYS} days "
                "(six months: EU AI Act Art. 19(1) and 26(6))"
            )
        if closed_matter_days < 0:
            raise InvalidInput("a closed matter's content cannot be kept for less than no time")
        if inactive_matter_days < 0:
            raise InvalidInput("give the days without activity as 0 (off) or more")
        return self._save(
            ComplianceRecord(
                action_id=action.action_id,
                recorded_by=actor_id,
                summary=(
                    f"Audit trail kept {audit_days} days; a closed matter's documents kept "
                    f"{closed_matter_days} days"
                    + (
                        f"; an open matter idle for {inactive_matter_days} days is reported."
                        if inactive_matter_days
                        else "."
                    )
                ),
                answers={
                    "audit_days": str(audit_days),
                    "closed_matter_days": str(closed_matter_days),
                    "inactive_matter_days": str(inactive_matter_days),
                },
                notes=notes.strip(),
            ),
            action,
        )

    def record_training(
        self,
        *,
        actor_id: str,
        user_id: str,
        course: str,
        completed_on: date,
        expires_on: date | None = None,
    ) -> TrainingRecord:
        self._authorise(actor_id, f"record training for {user_id}")
        self.ctx.user(user_id)
        if len(course.strip()) < 3:
            raise InvalidInput("name the training")
        if completed_on > utcnow().date():
            raise InvalidInput("training cannot be completed in the future")
        if expires_on is None:
            expires_on = completed_on.replace(year=completed_on.year + 1)
        record = TrainingRecord(
            user_id=user_id,
            course=" ".join(course.split()),
            completed_on=completed_on,
            expires_on=expires_on,
            recorded_by=actor_id,
        )
        self.ctx.store.put_registry(TRAINING, record.record_id, record)
        self.ctx.log(
            "training_recorded",
            actor_id=actor_id,
            matter_id="-",
            action="compliance.manage",
            subject_id=user_id,
            outcome="recorded",
            object_type="training_record",
            payload={"record_id": record.record_id, "expires_on": expires_on.isoformat()},
        )
        return record

    # ── the built-in evaluation (Art. 15) ────────────────────────────────────
    def run_evaluation(
        self, *, actor_id: str, thresholds: Mapping[str, float] | None = None
    ) -> ComplianceRecord:
        """Prepare a matter with known defects planted in it, in a separate workspace that
        touches nothing of this system's, and measure what was caught against the thresholds.
        Rule-based steps only: what a model adds must be measured on representative matters."""
        action = self.action("OA-07")
        self._authorise(actor_id, "run the accuracy evaluation")
        wanted = dict(DEFAULT_THRESHOLDS) | {k: float(v) for k, v in (thresholds or {}).items()}
        # The evaluation plays several people under its own harness, in its own copy of the
        # context, so nothing of the person running it is changed or borrowed.
        metrics = contextvars.copy_context().run(_evaluate)
        passed = (
            metrics["defects_caught"] >= wanted["defects_caught"]
            and metrics["facts_verbatim"] >= wanted["facts_verbatim"]
            and metrics["unexpected_holds"] <= wanted["unexpected_holds"]
        )
        caught = f"{metrics['caught']} of {metrics['planted']} planted defects caught"
        record = ComplianceRecord(
            action_id=action.action_id,
            recorded_by=actor_id,
            summary=(
                f"{caught}; {metrics['facts_verbatim']:.0%} of facts verbatim; "
                f"{metrics['unexpected_holds']} unexpected hold(s). "
                + ("Meets the declared thresholds." if passed else "Falls short of the thresholds.")
            ),
            answers={k: str(v) for k, v in metrics.items() if k != "missed"}
            | {f"threshold_{k}": str(v) for k, v in wanted.items()}
            | {"passed": "yes" if passed else "no", "missed": "; ".join(metrics["missed"])},
            notes=f"ELI Legal {__version__}; rule-based steps; synthetic matter.",
        )
        return self._save(record, action)

    # ── documents the system drafts from its own records ─────────────────────
    def generate(self, kind: str, *, actor_id: str) -> tuple[Path, str]:
        """Draft the Annex IV technical documentation or the EU declaration of conformity from
        the system's own records. Returns the file and its SHA-256, which is what a person signs
        off with ``sign_off``."""
        authn.require(actor_id)
        self.ctx.authorizer().require_global(actor_id, "compliance.manage")
        if kind == "annex_iv":
            text = self._annex_iv(actor_id)
        elif kind == "declaration":
            text = self._declaration(actor_id)
        else:
            raise InvalidInput("a document is 'annex_iv' or 'declaration'")
        folder = Path(self.ctx.settings.artifacts_dir) / "compliance"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
        path = folder / f"{kind}_{stamp}.md"
        path.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.ctx.log(
            "compliance_document_generated",
            actor_id=actor_id,
            matter_id="-",
            action="compliance.manage",
            subject_id=kind,
            outcome="generated",
            object_type="compliance_document",
            output_hash=digest,
        )
        return path, digest

    def sign_off(
        self, action_id: str, *, actor_id: str, sha256: str, notes: str = ""
    ) -> ComplianceRecord:
        """Sign off a generated document by its hash, after completing and reviewing it."""
        action = self.action(action_id)
        if action.evidence != "document":
            raise InvalidState(f"{action.title} is not signed off as a document")
        self._authorise(actor_id, f"sign off '{action.title}'")
        if len(sha256.strip()) != 64:
            raise InvalidInput("give the SHA-256 of the document being signed off")
        return self._save(
            ComplianceRecord(
                action_id=action.action_id,
                recorded_by=actor_id,
                summary=f"Signed off document {sha256[:12]}….",
                answers={"statement": action.statement},
                notes=notes.strip(),
                reference=sha256.strip().lower(),
            ),
            action,
        )

    def _annex_iv(self, actor_id: str) -> str:
        overview, controls = self.overview(actor_id=actor_id), load_register("controls")
        risks = load_register("risks")
        wf = self.ctx.workflow
        latest_eval = self.records("OA-07")
        model = self.ctx.model
        lines = [
            "# Technical documentation (EU AI Act, Annex IV) — draft",
            "",
            f"_Generated by ELI Legal {__version__} on {utcnow().date().isoformat()} from the "
            "system's own records. Parts marked **[provider to complete]** can only be stated "
            "by the provider. This is a working draft, not legal advice._",
            "",
            "## 1. General description",
            "",
            "- Name and version: ELI Legal " + __version__,
            "- Provider: **[provider to complete: name and address]**",
            "- Intended purpose: to assist a person in researching and interpreting the facts "
            "and the law of a dispute and relating them to each other, by or on behalf of a "
            "judicial authority or in a similar way in alternative dispute resolution, and in a "
            "party's own case preparation. It renders no decision.",
            "- Classification: high-risk under Article 6(2) and Annex III, point 8(a); Article "
            "6(3) considered and not relied on.",
            "- Profiles of use: "
            + "; ".join(f"{s.label} ({p.value})" for p, s in PROFILES.items()),
            "- Hardware and software it runs on: a desktop, server or browser deployment on "
            "the deployer's machines; models run locally (GGUF in process, or a model server "
            "on the same machine). **[provider to complete for the deployment]**",
            "",
            "## 2. Elements of the system and how it was developed",
            "",
            f"Workflow `{wf.workflow_id}` version {wf.version}: {wf.purpose}",
            "",
            *[
                f"- `{s.id}`{' (a person)' if s.manual else ''}: {s.description}"
                for s in wf.order()
            ],
            "",
            f"- Language model configured: {model.model_id if model.available else 'none'}. "
            "Model output is validated against its sources and is never itself a finding.",
            f"- Policy version: {self.ctx.policy.version}.",
            "- Design choices, and the trade-offs made: **[provider to complete]**",
            "",
            "## 3. Monitoring, functioning and control",
            "",
            "Controls follow the five controls of the RAIMS control map; each of the system's "
            f"{len(controls)} controls is a numbered part of one, tied to code and tests "
            "(control register):",
            *[
                f"- **{f['family_id']} {f['name']}**: needs {f['what_it_needs'][0].lower()}"
                f"{f['what_it_needs'][1:]} Owner: {f['owner']}"
                for f in load_register("families")
            ],
            "",
            "They operate through the system's lifecycle (RAIMS lifecycle table):",
            "",
            "| Stage | Main control / action | Owner | Evidence | Controls |",
            "|---|---|---|---|---|",
            *[
                f"| {s['stage']} | {s['main_control']} | {s['owner']} | {s['evidence']} | "
                + ", ".join(c["control_id"] for c in controls if c.get("stage") == s["stage"])
                + " |"
                for s in load_register("lifecycle")
            ],
            "",
            "",
            *[f"- {c['control_id']} ({c['type']}): {c['control']}" for c in controls],
            "",
            "## 4. Performance metrics",
            "",
        ]
        if latest_eval:
            r = latest_eval[-1]
            lines += [
                f"Latest built-in evaluation ({r.recorded_at.date().isoformat()}, "
                f"by {r.recorded_by}): {r.summary}",
                "",
                "Accuracy on representative real matters: **[provider to complete]**",
            ]
        else:
            lines.append("No evaluation has been recorded (organisation action OA-07).")
        lines += [
            "",
            "## 5. Risk management system",
            "",
            *[
                f"- {r['risk_id']}: {r['risk']} — controls {r['control_ids'].replace(';', ', ')}; "
                f"residual: {r['residual_risk_and_limits']}"
                for r in risks
            ],
            "",
            "## 6. Changes through the life cycle",
            "",
            "Each run records the workflow, policy, model, prompt and package versions it used; "
            "a change is flagged by monitoring and assessed before use (OA-22). "
            "**[provider to complete: change log]**",
            "",
            "## 7. Standards and specifications applied",
            "",
            "- ISO/IEC 42001:2023 (AI management system), as mapped in the requirements "
            "register. **[provider to complete: harmonised standards or common specifications]**",
            "",
            "## 8. EU declaration of conformity",
            "",
            "See the declaration drafted by the system (OA-12).",
            "",
            "## 9. Post-market monitoring",
            "",
            "Monitoring is computed from control evidence (failed checks, overrides, "
            "unchallenged approvals, incidents, version changes); routine checks run daily; "
            "serious incidents carry their Article 73 reporting deadline. **[provider to "
            "complete: the plan, OA-15]**",
            "",
            "## Where each requirement stands",
            "",
            f"{overview.headline}",
            "",
            *[
                f"- {r.requirement_id} ({r.reference}): {r.requirement} — {r.who}; "
                f"{_state_words(r.state)}"
                for r in overview.requirements
            ],
            "",
        ]
        return "\n".join(lines)

    def _declaration(self, actor_id: str) -> str:
        overview = self.overview(actor_id=actor_id)
        remaining = self.readiness(actor_id=actor_id)
        assessed = self.records("OA-11")
        lines = [
            "# EU declaration of conformity (EU AI Act, Art. 47 and Annex V) — draft",
            "",
        ]
        if not assessed or remaining:
            lines += [
                "> **NOT TO BE ISSUED.** The internal-control conformity assessment (OA-11) "
                "has not been recorded"
                + (
                    f", and {len(remaining)} action(s) needed before real use remain: "
                    + ", ".join(a.action.action_id for a in remaining)
                    if remaining
                    else ""
                )
                + ".",
                "",
            ]
        lines += [
            "1. AI system: ELI Legal, version " + __version__ + ", governed legal case "
            "preparation. **[provider to complete: any further unambiguous reference]**",
            "2. Provider: **[provider to complete: name and address; authorised "
            "representative, where there is one]**",
            "3. This declaration is issued under the sole responsibility of the provider.",
            "4. The AI system is in conformity with Regulation (EU) 2024/1689 as amended by "
            "Regulation (EU) 2026/1744 and, where applicable, with other relevant Union law. "
            "**[provider to confirm]**",
            "5. Where the system processes personal data, it complies with Regulation (EU) "
            "2016/679. **[provider to confirm]**",
            "6. Harmonised standards or common specifications applied: **[provider to complete]**",
            "7. Conformity assessment procedure: internal control (Annex VI); no notified body "
            "is involved.",
            "8. Place and date of issue; name and function of the person signing; signature: "
            "**[provider to complete]**",
            "",
            f"_Drafted by ELI Legal on {utcnow().date().isoformat()}. {overview.headline}_",
            "",
        ]
        return "\n".join(lines)


def _state_words(state: str) -> str:
    from eli_legal.domain import plain

    return plain.state(state).lower()


def _evaluate() -> dict[str, Any]:
    """Run the synthetic matter once, rule-based, and measure what was caught."""
    from eli_legal.application.services import build_services
    from eli_legal.demo import build_demo_workspace
    from eli_legal.demo_run import ARBITRATOR, SECRETARY, demo_settings, setup_demo
    from eli_legal.security import authn as auth

    with (
        tempfile.TemporaryDirectory(prefix="eli_legal_eval_") as tmp,
        auth.harness("evaluation-harness"),
    ):
        root = Path(tmp)
        workspace = build_demo_workspace(root / "demo")
        sv = build_services(
            demo_settings(root, workspace, inference="none"), install_network_guard=False
        )
        mid = setup_demo(sv, workspace)
        run = sv.runs.start(mid, actor_id=SECRETARY)
        rid = run.run_id
        claims = sv.ctx.store.list(Claim, mid, run_id=rid)
        holds: list[Hold] = sv.ctx.holds.open_holds(mid, rid)
        documents = {d.document_id: d for d in sv.matters.documents(mid, ARBITRATOR)}
        caught: list[str] = []
        missed: list[str] = []
        expected_subjects: set[str] = set()
        for label, citation, check in _PLANTED:
            hit = [
                c
                for c in claims
                if c.citation == citation
                and c.status is ClaimStatus.HELD
                and any(check in h.detail for h in holds if h.subject_id == c.claim_id)
            ]
            expected_subjects |= {c.claim_id for c in claims if c.citation == citation}
            (caught if hit else missed).append(label)
        flagged = [d for d in documents.values() if d.injection_flags]
        unread = [d for d in documents.values() if d.status.value == "unsupported"]
        doc_holds = {(h.subject_id, h.reason_code) for h in holds if h.scope is HoldScope.DOCUMENT}
        for label, docs, reason in (
            (
                "A document with text addressed to an AI system",
                flagged,
                "prompt_injection_detected",
            ),
            ("A document the system could not read", unread, "coverage_gap"),
        ):
            ok = bool(docs) and all((d.document_id, reason) in doc_holds for d in docs)
            (caught if ok else missed).append(label)
            expected_subjects |= {d.document_id for d in docs}
        # A finding resting on a held one is held for that reason, which is expected.
        unexpected = [
            h
            for h in holds
            if h.subject_id not in expected_subjects and h.reason_code != "dependency_held"
        ]
        facts = [c for c in claims if c.kind is ClaimKind.FACT]
        chunks: dict[str, list[Chunk]] = {}
        verbatim = 0
        for fact in facts:
            link = fact.evidence[0] if fact.evidence else None
            if link is None:
                continue
            text = chunks.setdefault(link.target_id, sv.ctx.store.chunks_for(mid, link.target_id))
            if any(" ".join(link.quote.split()) in " ".join(c.text.split()) for c in text):
                verbatim += 1
        planted = len(caught) + len(missed)
        sv.ctx.store.close()
        return {
            "planted": planted,
            "caught": len(caught),
            "defects_caught": round(len(caught) / planted, 4) if planted else 0.0,
            "facts": len(facts),
            "facts_verbatim": round(verbatim / len(facts), 4) if facts else 0.0,
            "unexpected_holds": len(unexpected),
            "missed": missed,
        }
