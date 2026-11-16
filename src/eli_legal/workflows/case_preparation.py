"""The case-preparation workflow: one handler per step of ``config/workflows/case_preparation.json``.

Handlers are stateless. Each reads what it needs from the store and writes what it produced, so a
run can be resumed from any step. Finding ids are derived from their content, so re-running a
step reproduces the same findings and a person's earlier decisions about them survive.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from eli_legal.application.container import AppContext
from eli_legal.application.ingestion_service import IngestionService
from eli_legal.domain import plain
from eli_legal.domain.enums import (
    ActorType,
    ClaimKind,
    ClaimStatus,
    DocumentStatus,
    HoldResolution,
    HoldScope,
    HoldStatus,
    TaskStatus,
    VerificationType,
)
from eli_legal.domain.errors import EliLegalError, HoldRaised
from eli_legal.domain.models import (
    Authority,
    Chunk,
    Claim,
    Document,
    EvidenceLink,
    Hold,
    HumanReview,
    Issue,
    Matter,
    Report,
    Run,
    RunStep,
    VerificationResult,
    VerificationTask,
    utcnow,
)
from eli_legal.domain.profiles import profile_spec
from eli_legal.domain.stopping import check_stop
from eli_legal.governance.completeness import check_run_completeness, verification_digest
from eli_legal.governance.gates import (
    apply_decision,
    evaluate_claim,
    propagate_dependencies,
)
from eli_legal.legal import analysis as analysis_mod
from eli_legal.legal import citation_verifier as citation_mod
from eli_legal.legal import current_law_citator as current_law_mod
from eli_legal.legal import provenance as provenance_mod
from eli_legal.legal.analysis import Analyst
from eli_legal.legal.case_law_retriever import CaseLawRetriever, party_authorities
from eli_legal.legal.citation_verifier import CitationVerifier
from eli_legal.legal.citations import CitationExtractor
from eli_legal.legal.current_law_citator import CurrentLawCitator
from eli_legal.legal.evidence_mapper import EvidenceMapper
from eli_legal.legal.fact_extractor import FactExtractor
from eli_legal.legal.frameworks import (
    Rules,
    combined_rules,
    compile_context,
    tighten_status_age,
)
from eli_legal.legal.issue_mapper import MEANING_Z, IssueMapper, stems, terms
from eli_legal.legal.llm import PROMPT_VERSIONS, LegalModel
from eli_legal.legal.proposition_verifier import PropositionVerifier
from eli_legal.legal.provenance import ProvenanceVerifier
from eli_legal.legal.report_builder import BuiltReport, LegalReportBuilder, ReportContext
from eli_legal.security.redaction import normalise_ws, quote_hash
from eli_legal.workflows.runner import StepContext, StepHandler

_LEGAL_KINDS = (ClaimKind.LEGAL_PROPOSITION, ClaimKind.PARTY_AUTHORITY)
_SOURCE_KINDS = (ClaimKind.FACT, ClaimKind.PROCEDURAL, *_LEGAL_KINDS)
_REMOVED = (ClaimStatus.EXCLUDED, ClaimStatus.REJECTED)

_QUESTIONS = {
    VerificationType.CITATION.value: "Confirm this authority exists and is correctly cited.",
    VerificationType.CURRENT_LAW.value: "Confirm this authority is still good law for this matter.",
    VerificationType.PROPOSITION.value: "Confirm the cited source supports this proposition.",
    VerificationType.EVIDENCE_SUPPORT.value: "Confirm the document supports this statement.",
    VerificationType.PROVENANCE.value: "Confirm the source of this finding.",
}


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:32]}"


@dataclass(slots=True)
class CasePreparation:
    ctx: AppContext
    ingestion: IngestionService
    model: LegalModel
    verifier: LegalModel
    # What the matter's law and standards packages require of this run; set before each step.
    rules: Rules = field(default_factory=Rules)

    @classmethod
    def for_run(cls, ctx: AppContext) -> CasePreparation:
        # Fresh model wrappers so call statistics belong to this run alone.
        return cls(
            ctx=ctx,
            ingestion=IngestionService(ctx),
            model=LegalModel(ctx.model.inference),
            verifier=LegalModel(ctx.verifier_model.inference),
        )

    def handlers(self) -> dict[str, StepHandler]:
        steps: dict[str, StepHandler] = {
            "scope": self.scope,
            "ingest": self.ingest,
            "document_coverage": self.document_coverage,
            "facts": self.facts,
            "issues": self.issues,
            "evidence_mapping": self.evidence_mapping,
            "legal_research": self.legal_research,
            "citation_verification": self.citation_verification,
            "current_law_check": self.current_law_check,
            "proposition_verification": self.proposition_verification,
            "evidence_verification": self.evidence_verification,
            "verification_gate": self.verification_gate,
            "analysis": self.analysis,
            "draft_report": self.draft_report,
            "final_validation": self.final_validation,
        }
        return {name: self._briefed(name, step) for name, step in steps.items()}

    def _briefed(self, name: str, step: StepHandler) -> StepHandler:
        """Every step after the first runs under the law and standards the run was prepared
        under: the model is told them, and their tightening rules apply."""

        def run(c: StepContext) -> Mapping[str, Any] | None:
            if name != "scope":
                self._brief(c)
            return step(c)

        return run

    def _brief(self, c: StepContext) -> None:
        packs = self.ctx.frameworks.for_run(c.run.framework_versions)
        context = compile_context(packs, c.matter.profile.value)
        self.model.compliance = self.verifier.compliance = context
        self.rules = combined_rules(packs)

    # ── shared helpers ───────────────────────────────────────────────────────
    def _claims(self, c: StepContext, kinds: Iterable[ClaimKind] | None = None) -> list[Claim]:
        claims = self.ctx.store.list(Claim, c.matter.matter_id, run_id=c.run.run_id)
        wanted = set(kinds) if kinds is not None else None
        return [x for x in claims if wanted is None or x.kind in wanted]

    def _documents(self, c: StepContext) -> list[Document]:
        return [
            d
            for d in self.ctx.store.list(Document, c.matter.matter_id)
            if d.status is DocumentStatus.PROCESSED
        ]

    def _chunks(self, c: StepContext, documents: list[Document]) -> list[Chunk]:
        """Passages of the given documents in reading order: documents as ingested, then by
        position. The order is fixed so that the same papers always yield the same report."""
        position = {d.document_id: i for i, d in enumerate(documents)}
        chunks = [
            k for k in self.ctx.store.chunks_for(c.matter.matter_id) if k.document_id in position
        ]
        chunks.sort(key=lambda k: (position[k.document_id], k.ordinal))
        return chunks

    def _upsert_claims(self, c: StepContext, new: list[Claim], kinds: set[ClaimKind]) -> None:
        """Replace this run's findings of ``kinds`` with ``new``, keeping human removals."""
        store, mid = self.ctx.store, c.matter.matter_id
        existing = {x.claim_id: x for x in self._claims(c, kinds)}
        for claim in new:
            old = existing.get(claim.claim_id)
            if old is not None and old.status in _REMOVED and old.kind is not ClaimKind.APPLICATION:
                claim.status, claim.status_reason = old.status, old.status_reason
        store.put_many(new)
        stale = set(existing) - {x.claim_id for x in new}
        if stale:
            store.delete_ids(Claim, mid, stale)
            results = store.list(VerificationResult, mid, run_id=c.run.run_id)
            store.delete_ids(
                VerificationResult, mid, [r.verification_id for r in results if r.claim_id in stale]
            )

    def _clear_results(self, c: StepContext, types: set[VerificationType]) -> None:
        """Drop earlier automated results of these types; results recorded by people are kept."""
        wanted = {t.value for t in types}
        results = self.ctx.store.list(VerificationResult, c.matter.matter_id, run_id=c.run.run_id)
        self.ctx.store.delete_ids(
            VerificationResult,
            c.matter.matter_id,
            [
                r.verification_id
                for r in results
                if r.verification_type in wanted and not r.by_human
            ],
        )

    def _model_excluded_documents(self, c: StepContext) -> frozenset[str]:
        """Documents with an unresolved injection flag are never placed in a model prompt."""
        open_flags = {
            h.subject_id
            for h in self.ctx.holds.open_holds(c.matter.matter_id, c.run.run_id)
            if h.reason_code == "prompt_injection_detected"
        }
        return frozenset(open_flags)

    def _log_verification_batch(self, c: StepContext, step: str) -> str:
        results = self.ctx.store.list(VerificationResult, c.matter.matter_id, run_id=c.run.run_id)
        digest = verification_digest(results)
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status.value] = counts.get(r.status.value, 0) + 1
        self.ctx.log(
            "verification_batch",
            actor_id=c.actor_id,
            matter_id=c.matter.matter_id,
            run_id=c.run.run_id,
            action=f"workflow.step.{step}",
            subject_id=c.run.run_id,
            outcome="recorded",
            object_type="verification_set",
            output_hash=digest,
            payload={"results": len(results), "by_status": counts},
        )
        return digest

    # ── steps ────────────────────────────────────────────────────────────────
    def scope(self, c: StepContext) -> Mapping[str, Any]:
        ctx, matter, run = self.ctx, c.matter, c.run
        ctx.audit.verify_chain()
        spec = profile_spec(matter.profile)
        users = {u.user_id: u for u in ctx.store.list_users()}
        reviewers = [
            uid
            for uid in sorted(matter.reviewer_user_ids)
            if (u := users.get(uid)) is not None
            and u.active
            and u.actor_type is ActorType.HUMAN
            and (u.roles & spec.reviewer_roles)
            and (uid == matter.owner_user_id or uid in matter.authorised_user_ids)
        ]
        if not reviewers:
            raise HoldRaised(
                "missing_reviewer",
                f"nobody named on this matter may approve its report. A matter for "
                f"{spec.label.lower()} needs one whose account is "
                f"{plain.approvers(spec.reviewer_roles)}, on it as decision-maker and named "
                "under Named reviewers on the Case page",
            )
        packs = ctx.jurisdictions.for_matter(matter)
        unvalidated = [p.code for p in packs if not p.validated]
        if unvalidated and ctx.policy.require_validated_jurisdiction_packs:
            raise HoldRaised("jurisdiction_pack_unvalidated", ", ".join(unvalidated))
        unapproved = [
            sid
            for sid in sorted(matter.approved_source_ids)
            if (s := ctx.sources.get(sid)) is None or not s.approved
        ]
        if unapproved:
            raise HoldRaised("unapproved_source", ", ".join(unapproved))
        connectors = ctx.connectors_for(matter)
        try:
            frameworks = ctx.frameworks.usable(matter.framework_ids)
        except EliLegalError as exc:
            raise HoldRaised("framework_unusable", str(exc)) from exc
        run.framework_versions = {p.pack_id: p.fingerprint for p in frameworks}
        context = compile_context(frameworks, matter.profile.value)
        self.model.compliance = self.verifier.compliance = context
        self.rules = combined_rules(frameworks)
        run.workflow_id = ctx.workflow.workflow_id
        run.workflow_version = ctx.workflow.version
        run.policy_version = ctx.policy.version
        run.model_versions = {"generator": self.model.model_id, "verifier": self.verifier.model_id}
        run.prompt_versions = dict(PROMPT_VERSIONS) if self.model.available else {}
        if self.model.available and context:
            digest = hashlib.sha256(context.encode("utf-8")).hexdigest()[:12]
            run.prompt_versions["compliance"] = f"compliance/{digest}"
        run.tool_versions = {
            "parser": ctx.parser.version,
            "retrieval": "sqlite-fts5-bm25/1",
            "provenance": provenance_mod.VERIFIER_ID,
            "citation": citation_mod.VERIFIER_ID,
            "current_law": current_law_mod.VERIFIER_ID,
            "analysis_boundary": analysis_mod.VERIFIER_ID,
        }
        self._save_run(run)
        return {
            "profile": matter.profile.value,
            "jurisdiction_packs": [p.code for p in packs],
            "unvalidated_packs": unvalidated,
            "sources": sorted(connectors),
            "reviewers": len(reviewers),
            "model": self.model.model_id,
            "relevant_date": matter.relevant_date.isoformat() if matter.relevant_date else None,
            "frameworks": dict(run.framework_versions),
            "framework_rules": {
                "status_max_age_days": self.rules.status_max_age_days,
                "forbidden_terms": len(self.rules.forbidden_terms),
            },
        }

    def _save_run(self, run: Run) -> None:
        """Save what a step recorded on the run (its tools, versions, report), never its state:
        a person may have stopped it meanwhile, and that must stand."""

        def keep_state(stored: Run) -> None:
            run.status, run.finished_at = stored.status, stored.finished_at
            for name in ("tool_versions", "model_versions", "prompt_versions",
                         "framework_versions", "workflow_id", "workflow_version",
                         "policy_version", "report_id"):  # fmt: skip
                setattr(stored, name, getattr(run, name))

        self.ctx.store.change(Run, run.matter_id, run.run_id, keep_state)

    def ingest(self, c: StepContext) -> Mapping[str, Any]:
        documents = self.ctx.store.list(Document, c.matter.matter_id)
        pending = [d for d in documents if d.status is DocumentStatus.REGISTERED]
        for document in pending:
            check_stop()
            self.ingestion.process(document, actor_id=c.actor_id)
        return {"documents": len(documents), "processed_now": len(pending)}

    def document_coverage(self, c: StepContext) -> Mapping[str, Any]:
        ctx, mid, rid = self.ctx, c.matter.matter_id, c.run.run_id
        documents = ctx.store.list(Document, mid)
        if not documents:
            raise HoldRaised("no_documents", "no document has been ingested into this matter")
        counts = ctx.store.chunk_document_counts(mid)
        accepted = {
            h.subject_id
            for h in ctx.holds.all_holds(mid, rid)
            if h.reason_code == "prompt_injection_detected"
            and h.status is HoldStatus.RESOLVED
            and h.resolution is HoldResolution.WAIVED
        }
        keep: set[tuple[str, str]] = set()
        gaps = flagged = 0
        for d in documents:
            read = d.status is DocumentStatus.PROCESSED and counts.get(d.document_id, 0) > 0
            if not read and d.status is not DocumentStatus.WAIVED:
                gaps += 1
                keep.add((d.document_id, "coverage_gap"))
                ctx.holds.raise_hold(
                    matter_id=mid,
                    run_id=rid,
                    scope=HoldScope.DOCUMENT,
                    subject_id=d.document_id,
                    reason_code="coverage_gap",
                    detail=f"document was not read ({d.status.value})",
                    actor_id=c.actor_id,
                )
            if read:
                # A page that is only an image and was not read, or was read by OCR with low
                # confidence, holds the document until a person checks it against the original.
                for code, pages, said in (
                    ("pages_not_read", [n for n in d.unread_pages if n not in d.pages_checked],
                     "an image with no text layer, not read"),
                    ("ocr_low_confidence",
                     sorted(int(n) for n, conf in d.ocr_pages.items()
                            if conf < ctx.settings.ocr_min_confidence
                            and int(n) not in d.pages_checked),
                     f"read by OCR with less than {ctx.settings.ocr_min_confidence:g}% confidence; "
                     "check it against the original"),
                ):  # fmt: skip
                    if not pages:
                        continue
                    gaps += 1
                    keep.add((d.document_id, code))
                    ctx.holds.raise_hold(
                        matter_id=mid,
                        run_id=rid,
                        scope=HoldScope.DOCUMENT,
                        subject_id=d.document_id,
                        reason_code=code,
                        detail=f"page(s) {', '.join(map(str, pages))}: {said}",
                        actor_id=c.actor_id,
                    )
            if read and d.injection_flags and d.document_id not in accepted:
                flagged += 1
                keep.add((d.document_id, "prompt_injection_detected"))
                ctx.holds.raise_hold(
                    matter_id=mid,
                    run_id=rid,
                    scope=HoldScope.DOCUMENT,
                    subject_id=d.document_id,
                    reason_code="prompt_injection_detected",
                    detail=", ".join(d.injection_flags),
                    actor_id=c.actor_id,
                )
        ctx.holds.close_superseded(
            mid, rid, scope=HoldScope.DOCUMENT, keep=keep, actor_id=c.actor_id
        )
        return {
            "expected": len(documents),
            "read": sum(1 for d in documents if d.status is DocumentStatus.PROCESSED),
            "waived": sum(1 for d in documents if d.status is DocumentStatus.WAIVED),
            "gaps": gaps,
            "injection_flagged": flagged,
        }

    def facts(self, c: StepContext) -> Mapping[str, Any]:
        ctx, mid, rid = self.ctx, c.matter.matter_id, c.run.run_id
        documents = self._documents(c)
        by_doc = {d.document_id: d for d in documents}
        chunks = self._chunks(c, documents)
        pack = ctx.jurisdictions.for_matter(c.matter)[0]
        extractor = FactExtractor(self.model, max_model_chunks=ctx.policy.max_model_chunks)
        candidates = extractor.extract(
            documents=documents,
            chunks=chunks,
            date_order=pack.date_order,
            model_excluded_document_ids=self._model_excluded_documents(c),
        )
        claims = [
            Claim(
                matter_id=mid,
                run_id=rid,
                text=f.text,
                kind=ClaimKind.FACT,
                material=False,
                claim_id=stable_id("clm", rid, "fact", f.document_id, normalise_ws(f.text)),
                evidence=[
                    EvidenceLink(
                        target_type="document",
                        target_id=f.document_id,
                        locator=f.locator,
                        quote=f.text,
                        quote_hash=quote_hash(f.text),
                        chunk_id=f.chunk_id,
                    )
                ],
                party_id=f.party_id,
                event_date=f.event_date,
                origin=f.origin,
                access_scope=by_doc[f.document_id].access_scope,
                uncertainty=(
                    f"“{f.date_text}” read day-first; it could also be read month-first"
                    if f.date_ambiguous and pack.date_order == "dmy"
                    else (
                        f"“{f.date_text}” read month-first; it could also be read day-first"
                        if f.date_ambiguous
                        else None
                    )
                ),
            )
            for f in candidates
        ]
        self._upsert_claims(c, claims, {ClaimKind.FACT})
        return {
            "facts": len(claims),
            "dated": sum(1 for x in claims if x.event_date),
            "model_passages": extractor.model_chunks_used,
            "passages": len(chunks),
        }

    def issues(self, c: StepContext) -> Mapping[str, Any]:
        ctx, mid, rid = self.ctx, c.matter.matter_id, c.run.run_id
        documents = self._documents(c)
        excluded = self._model_excluded_documents(c)
        chunks = self._chunks(c, [d for d in documents if d.document_id not in excluded])
        mapper = IssueMapper(self.model, semantic=ctx.semantic)
        issues = mapper.identify(matter=c.matter, run_id=rid, documents=documents, chunks=chunks)
        for issue in issues:
            issue.issue_id = stable_id("iss", rid, " ".join(sorted(terms(issue.label))))
        facts = [f for f in self._claims(c, {ClaimKind.FACT}) if f.status not in _REMOVED]
        for fact in facts:
            fact.issue_ids = []
            fact.meaning_issue_ids = []
        mapper.link_facts(
            issues=issues,
            facts=facts,
            model_excluded_claim_ids=frozenset(
                f.claim_id for f in facts if any(e.target_id in excluded for e in f.evidence)
            ),
        )
        for fact in facts:
            # With no issues to organise by, the chronology itself is the product.
            fact.material = bool(fact.issue_ids) or not issues
        semantic = mapper.semantic
        c.run.tool_versions["linking"] = (
            f"words+meaning:{semantic.model_id};z{MEANING_Z}"
            if semantic is not None and semantic.available
            else "words"
        )
        self._save_run(c.run)
        ctx.store.delete_records(Issue, mid, run_id=rid)
        ctx.store.put_many([*issues, *facts])
        return {
            "issues": len(issues),
            "stated": sum(1 for i in issues if i.source == "stated"),
            "from_papers": sum(1 for i in issues if i.source == "extracted"),
            "model_proposed": sum(1 for i in issues if i.source == "model_proposed"),
            "facts_linked": sum(1 for f in facts if f.issue_ids),
        }

    def evidence_mapping(self, c: StepContext) -> Mapping[str, Any]:
        issues = self.ctx.store.list(Issue, c.matter.matter_id, run_id=c.run.run_id)
        facts = [f for f in self._claims(c, {ClaimKind.FACT}) if f.status not in _REMOVED]
        mapper = EvidenceMapper()
        maps = mapper.build(issues=issues, facts=facts)
        return {
            "issues_without_evidence": sum(1 for m in maps if m.gap),
            "one_sided_issues": sum(1 for m in maps if m.one_sided),
            "possible_conflicts": len(mapper.conflicts(facts)),
        }

    def legal_research(self, c: StepContext) -> Mapping[str, Any]:
        ctx, matter, rid = self.ctx, c.matter, c.run.run_id
        mid = matter.matter_id
        connectors = ctx.connectors_for(matter)
        codes = ctx.jurisdictions.jurisdiction_codes(matter)
        extractor = CitationExtractor(ctx.jurisdictions.for_matter(matter))
        issues = ctx.store.list(Issue, mid, run_id=rid)
        found: dict[str, Claim] = {}

        def add(claim: Claim, anchor: str) -> None:
            claim.claim_id = stable_id(
                "clm", rid, claim.kind.value, anchor, normalise_ws(claim.text), claim.citation or ""
            )
            if claim.claim_id in found:
                merged = found[claim.claim_id]
                merged.issue_ids = sorted(set(merged.issue_ids) | set(claim.issue_ids))
            else:
                found[claim.claim_id] = claim

        retriever = CaseLawRetriever(connectors)
        note = ""
        if connectors:
            semantic = ctx.semantic
            if semantic is not None:
                # Passages not yet embedded are embedded now, up to the budget; the rest are
                # found by their words alone, and the report says so.
                try:
                    coverage = semantic.ensure(
                        list(connectors), codes, budget=ctx.settings.embedding_budget
                    )
                    if not coverage.complete:
                        note = (
                            f"Searching by meaning covered {coverage.total - coverage.missing} of "
                            f"{coverage.total} passages; the rest were found by their words only."
                        )
                except Exception as exc:  # any failure of the model leaves research by words
                    semantic = None
                    note = (
                        f"Searching by meaning could not run ({type(exc).__name__}: "
                        f"{str(exc)[:160]}); passages were found by their words only."
                    )
            retriever = CaseLawRetriever(connectors, semantic=semantic)
            for issue in issues:
                check_stop()
                for proposition in retriever.propositions_for_issue(
                    matter_id=mid,
                    run_id=rid,
                    issue=issue,
                    jurisdictions=codes,
                    per_issue=ctx.policy.research_passages_per_issue,
                    relevant_date=matter.relevant_date,
                ):
                    add(proposition, proposition.authority_id or "")
        documents = self._documents(c)
        chunks = self._chunks(c, documents)
        cited = party_authorities(
            matter_id=mid, run_id=rid, documents=documents, chunks=chunks, extractor=extractor
        )
        issue_terms = {i.issue_id: stems(i.label) for i in issues}
        for claim in cited:
            claim_terms = stems(claim.text)
            claim.issue_ids = [i for i, t in issue_terms.items() if len(claim_terms & t) >= 2]
            add(claim, claim.evidence[0].target_id)
        claims = list(found.values())
        # What ranked the passages is a tool of the run: a change of it between runs is a change
        # to reassess (monitoring), and the report states it.
        c.run.tool_versions["retrieval"] = retriever.method
        if note:
            c.run.tool_versions["retrieval_note"] = note
        else:
            c.run.tool_versions.pop("retrieval_note", None)
        self._save_run(c.run)
        self._upsert_claims(c, claims, set(_LEGAL_KINDS))
        every = self._claims(c)
        for issue in issues:
            issue.claim_ids = [x.claim_id for x in every if issue.issue_id in x.issue_ids]
        ctx.store.put_many(issues)
        ctx.log(
            "legal_research",
            actor_id=c.actor_id,
            matter_id=mid,
            run_id=rid,
            action="research.run",
            subject_id=rid,
            outcome="completed",
            object_type="run",
            source_ids=sorted(connectors),
            tool_id=retriever.method,
            payload={"jurisdictions": codes, "findings": len(claims)},
        )
        return {
            "sources": sorted(connectors),
            "passages_from_sources": sum(
                1 for x in claims if x.kind is ClaimKind.LEGAL_PROPOSITION
            ),
            "party_citations": sum(1 for x in claims if x.kind is ClaimKind.PARTY_AUTHORITY),
            "ranked_by": retriever.method,
            **({"note": note} if note else {}),
        }

    def citation_verification(self, c: StepContext) -> Mapping[str, Any]:
        self._clear_results(c, {VerificationType.CITATION})
        verifier = CitationVerifier(
            self.ctx.connectors_for(c.matter), relevant_date=c.matter.relevant_date
        )
        results: list[VerificationResult] = []
        changed: list[Claim] = []
        for claim in self._claims(c, _LEGAL_KINDS):
            if claim.status in _REMOVED:
                continue
            result, authority = verifier.verify(claim)
            results.append(result)
            if authority is not None and claim.authority_id != authority.authority_id:
                claim.authority_id = authority.authority_id
                changed.append(claim)
            if authority is not None and claim.kind is ClaimKind.PARTY_AUTHORITY:
                closest = self._closest_in_meaning(claim, authority.authority_id)
                if closest != claim.closest_passage_id:
                    claim.closest_passage_id = closest
                    if claim not in changed:
                        changed.append(claim)
        self.ctx.store.put_many([*results, *changed])
        return _tally(results)

    def _closest_in_meaning(self, claim: Claim, authority_id: str) -> str:
        """The passage of the cited authority closest in meaning to what the party says of it,
        for the reader to compare; '' without an embedding model or if it cannot run."""
        semantic = self.ctx.semantic
        if semantic is None:
            return ""
        try:
            found = semantic.closest(claim.text, self.ctx.store.passages_for(authority_id))
        except Exception:  # the model failing leaves the passage closest in wording
            return ""
        return found[0] if found else ""

    def current_law_check(self, c: StepContext) -> Mapping[str, Any]:
        ctx = self.ctx
        self._clear_results(c, {VerificationType.CURRENT_LAW})
        connectors = ctx.connectors_for(c.matter)
        citator = CurrentLawCitator(connectors)
        default_pack = ctx.jurisdictions.for_matter(c.matter)[0]
        results: list[VerificationResult] = []
        for claim in self._claims(c, _LEGAL_KINDS):
            if claim.status in _REMOVED:
                continue
            authority = ctx.store.get_authority(claim.authority_id) if claim.authority_id else None
            if authority is not None and authority.source_id not in connectors:
                authority = None
            pack = ctx.jurisdictions.get(authority.jurisdiction) if authority else default_pack
            pack = tighten_status_age(pack, self.rules)
            results.append(
                citator.verify(claim, authority, pack=pack, relevant_date=c.matter.relevant_date)
            )
        ctx.store.put_many(results)
        return _tally(results)

    def proposition_verification(self, c: StepContext) -> Mapping[str, Any]:
        ctx = self.ctx
        self._clear_results(c, {VerificationType.PROPOSITION})
        provenance = ProvenanceVerifier(ctx.store, ctx.vault, set(ctx.connectors_for(c.matter)))
        verifier = PropositionVerifier(
            provenance=provenance,
            verifier_model=self.verifier,
            generator_model_id=self.model.model_id,
            model_verification_validated=ctx.policy.model_proposition_verification_validated,
        )
        results = [
            verifier.verify_claim(claim)
            for claim in self._claims(c, {ClaimKind.LEGAL_PROPOSITION})
            if claim.status not in _REMOVED
        ]
        ctx.store.put_many(results)
        return _tally(results)

    def evidence_verification(self, c: StepContext) -> Mapping[str, Any]:
        ctx = self.ctx
        self._clear_results(c, {VerificationType.PROVENANCE, VerificationType.EVIDENCE_SUPPORT})
        provenance = ProvenanceVerifier(ctx.store, ctx.vault, set(ctx.connectors_for(c.matter)))
        results: list[VerificationResult] = []
        for claim in self._claims(c, _SOURCE_KINDS):
            if claim.status in _REMOVED:
                continue
            results.append(provenance.provenance(claim))
            if claim.kind is not ClaimKind.LEGAL_PROPOSITION:
                results.append(provenance.evidence_support(claim))
        ctx.store.put_many(results)
        return _tally(results)

    def verification_gate(self, c: StepContext) -> Mapping[str, Any]:
        ctx, mid, rid = self.ctx, c.matter.matter_id, c.run.run_id
        claims = [x for x in self._claims(c, _SOURCE_KINDS) if x.status not in _REMOVED]
        by_claim: dict[str, list[VerificationResult]] = {}
        for r in ctx.store.list(VerificationResult, mid, run_id=rid):
            by_claim.setdefault(r.claim_id, []).append(r)
        open_tasks = {
            (t.claim_id, t.verification_type): t
            for t in ctx.store.list(VerificationTask, mid, run_id=rid, status=TaskStatus.OPEN.value)
        }
        keep: set[tuple[str, str]] = set()
        wanted_tasks: set[tuple[str, str]] = set()
        new_tasks: list[VerificationTask] = []
        for claim in claims:
            decision = evaluate_claim(claim, by_claim.get(claim.claim_id, []))
            apply_decision(claim, decision)
            if not (claim.material and claim.status is ClaimStatus.HELD):
                continue
            keep.add((claim.claim_id, decision.reason_code))
            ctx.holds.raise_hold(
                matter_id=mid,
                run_id=rid,
                scope=HoldScope.CLAIM,
                subject_id=claim.claim_id,
                reason_code=decision.reason_code,
                detail=decision.detail,
                actor_id=c.actor_id,
            )
            for vtype in (*decision.failed, *decision.needs_human):
                wanted_tasks.add((claim.claim_id, vtype))
                if (claim.claim_id, vtype) not in open_tasks:
                    new_tasks.append(
                        VerificationTask(
                            matter_id=mid,
                            run_id=rid,
                            claim_id=claim.claim_id,
                            verification_type=vtype,
                            question=_QUESTIONS.get(vtype, "Confirm this check."),
                        )
                    )
        for dependent in propagate_dependencies(claims):
            if dependent.material:
                keep.add((dependent.claim_id, "dependency_held"))
                ctx.holds.raise_hold(
                    matter_id=mid,
                    run_id=rid,
                    scope=HoldScope.CLAIM,
                    subject_id=dependent.claim_id,
                    reason_code="dependency_held",
                    detail=dependent.status_reason,
                    actor_id=c.actor_id,
                )
        cancelled = []
        for key, task in open_tasks.items():
            if key not in wanted_tasks:
                task.status = TaskStatus.CANCELLED
                cancelled.append(task)
        ctx.store.put_many([*claims, *new_tasks, *cancelled])
        ctx.holds.close_superseded(mid, rid, scope=HoldScope.CLAIM, keep=keep, actor_id=c.actor_id)
        self._log_verification_batch(c, "verification_gate")
        return {
            "findings": len(claims),
            "verified": sum(1 for x in claims if x.status is ClaimStatus.VERIFIED),
            "held": sum(1 for x in claims if x.status is ClaimStatus.HELD),
            "unverified_not_material": sum(1 for x in claims if x.status is ClaimStatus.UNVERIFIED),
            "tasks_opened": len(new_tasks),
        }

    def analysis(self, c: StepContext) -> Mapping[str, Any]:
        ctx, matter, rid = self.ctx, c.matter, c.run.run_id
        if not self.model.available:
            self._upsert_claims(c, [], {ClaimKind.APPLICATION})
            self._clear_results(c, {VerificationType.DEPENDENCY, VerificationType.OUTCOME_BOUNDARY})
            self._log_verification_batch(c, "analysis")
            return {"arguments": 0, "skipped": "no model is configured"}
        every = self._claims(c)
        withheld = self._model_excluded_documents(c)
        verified = [
            x
            for x in every
            if x.status is ClaimStatus.VERIFIED
            and x.kind in (ClaimKind.FACT, ClaimKind.LEGAL_PROPOSITION)
            and not any(e.target_id in withheld for e in x.evidence)
        ]
        packs = ctx.jurisdictions.for_matter(matter)
        analyst = Analyst(
            self.model,
            CitationExtractor(packs),
            date_order=packs[0].date_order,
            rules=self.rules,
        )
        drafted: dict[str, Claim] = {}
        for issue in ctx.store.list(Issue, matter.matter_id, run_id=rid):
            check_stop()
            if issue.source == "model_proposed":
                continue  # an issue only a model suggested gets no arguments until a person adopts it
            for argument in analyst.arguments_for_issue(
                matter=matter, run_id=rid, issue=issue, verified=verified
            ):
                argument.claim_id = stable_id(
                    "clm", rid, "application", normalise_ws(argument.text).lower()
                )
                earlier = drafted.get(argument.claim_id)
                if earlier is None:
                    drafted[argument.claim_id] = argument
                else:  # the same argument offered under another issue is one argument
                    earlier.issue_ids = sorted({*earlier.issue_ids, *argument.issue_ids})
                    earlier.depends_on = sorted({*earlier.depends_on, *argument.depends_on})
        by_id = {x.claim_id: x for x in every} | drafted
        results: list[VerificationResult] = []
        rejected = 0
        for argument in drafted.values():
            checks = analyst.check(argument, by_id, matter.profile)
            results.extend(checks)
            decision = evaluate_claim(argument, checks)
            if decision.status is ClaimStatus.VERIFIED:
                argument.status = ClaimStatus.VERIFIED
            else:
                # A drafted argument that fails its checks is discarded, not queued for a person.
                argument.status, argument.material = ClaimStatus.REJECTED, False
                argument.status_reason = f"{decision.reason_code} — {decision.detail}"
                rejected += 1
        self._clear_results(c, {VerificationType.DEPENDENCY, VerificationType.OUTCOME_BOUNDARY})
        self._upsert_claims(c, list(drafted.values()), {ClaimKind.APPLICATION})
        ctx.store.put_many(results)
        self._log_verification_batch(c, "analysis")
        return {
            "arguments": len(drafted) - rejected,
            "rejected": rejected,
            "model_calls": self.model.stats.calls,
            "model_failures": self.model.stats.failures,
            "model_items_rejected": self.model.stats.rejected_items,
        }

    def draft_report(self, c: StepContext) -> Mapping[str, Any]:
        ctx, mid, rid = self.ctx, c.matter.matter_id, c.run.run_id
        notes = []
        if self.model.stats.failures:
            notes.append(
                f"{self.model.stats.failures} model call(s) failed and contributed nothing."
            )
        if self.model.stats.rejected_items:
            notes.append(
                f"{self.model.stats.rejected_items} model answer item(s) referred to things that "
                "do not exist and were discarded."
            )
        # Head and timestamp are fixed here so the approved copy can be rebuilt byte for byte.
        head = ctx.audit.last_signature()
        built_at = utcnow().replace(microsecond=0)
        built = build_report(
            ctx, c.matter, c.run, model_notes=notes, audit_head=head, built_at=built_at
        )
        version = len(ctx.store.list(Report, mid, run_id=rid)) + 1
        report = write_report(ctx, c.matter, c.run, built, version=version)
        report.audit_head, report.created_at = head, built_at
        ctx.store.put(report)
        c.run.report_id = report.report_id
        self._save_run(c.run)
        ctx.log(
            "report_drafted",
            actor_id=c.actor_id,
            matter_id=mid,
            run_id=rid,
            action="report.draft",
            subject_id=report.report_id,
            outcome="drafted",
            object_type="report",
            output_hash=report.sha256,
            payload={
                "version": version,
                "template": built.template,
                "findings_relied_on": len(built.claim_ids),
                "findings_not_relied_on": len(built.excluded_claim_ids),
                "warnings": len(built.warnings),
            },
        )
        return {
            "report_id": report.report_id,
            "version": version,
            "sha256": report.sha256,
            "findings_relied_on": len(built.claim_ids),
            "findings_not_relied_on": len(built.excluded_claim_ids),
        }

    def final_validation(self, c: StepContext) -> Mapping[str, Any]:
        ctx, mid, rid = self.ctx, c.matter.matter_id, c.run.run_id
        ctx.audit.verify_chain()
        completeness = check_run_completeness(
            events=ctx.audit.events(matter_id=mid, run_id=rid),
            steps=ctx.store.list(RunStep, mid, run_id=rid),
            holds=ctx.holds.all_holds(mid, rid),
            reviews=ctx.store.list(HumanReview, mid, run_id=rid),
            verifications=ctx.store.list(VerificationResult, mid, run_id=rid),
        )
        if not completeness.ok:
            raise HoldRaised("audit_gap", "; ".join(completeness.gaps[:3]))
        return {
            "audit_events": completeness.events_checked,
            "open_holds": len(ctx.holds.open_holds(mid, rid)),
        }


def _tally(results: list[VerificationResult]) -> dict[str, int]:
    out: dict[str, int] = {"checked": len(results)}
    for r in results:
        out[r.status.value] = out.get(r.status.value, 0) + 1
    return out


# ── report assembly shared by the draft step and by approval ─────────────────
def build_report(
    ctx: AppContext,
    matter: Matter,
    run: Run,
    *,
    audience: str = "",
    model_notes: Iterable[str] = (),
    audit_head: str = "",
    built_at: datetime | None = None,
    approved_by: str | None = None,
    approved_at: datetime | None = None,
) -> BuiltReport:
    mid, rid = matter.matter_id, run.run_id
    claims = ctx.store.list(Claim, mid, run_id=rid)
    issues = ctx.store.list(Issue, mid, run_id=rid)
    facts = [x for x in claims if x.kind is ClaimKind.FACT and x.status is ClaimStatus.VERIFIED]
    mapper = EvidenceMapper()
    authorities: dict[str, Authority] = {}
    for claim in claims:
        if claim.authority_id and claim.authority_id not in authorities:
            authority = ctx.store.get_authority(claim.authority_id)
            if authority is not None:
                authorities[claim.authority_id] = authority
    holds: list[Hold] = ctx.holds.all_holds(mid, rid)
    passages = {
        authority_id: ctx.store.passages_for(authority_id)
        for authority_id in {
            x.authority_id for x in claims if x.kind is ClaimKind.PARTY_AUTHORITY and x.authority_id
        }
        if authority_id in authorities
    }
    frameworks = ctx.frameworks.for_run(run.framework_versions)
    states = {p.pack_id: ctx.frameworks.state(p) for p in frameworks}
    return LegalReportBuilder().build(
        ReportContext(
            matter=matter,
            run=run,
            documents=ctx.store.list(Document, mid),
            issues=issues,
            claims=claims,
            verifications=ctx.store.list(VerificationResult, mid, run_id=rid),
            holds=holds,
            authorities=authorities,
            authority_passages=passages,
            evidence_maps=mapper.build(issues=issues, facts=facts),
            conflicts=mapper.conflicts(facts),
            packs=ctx.jurisdictions.for_matter(matter),
            frameworks=frameworks,
            framework_standing={k: s.why for k, s in states.items()},
            framework_validated={k: s.validated for k, s in states.items()},
            audience=audience,
            model_notes=list(model_notes),
            approved_by=approved_by,
            approved_at=approved_at,
            audit_head=audit_head,
            built_at=built_at,
        )
    )


def write_report(
    ctx: AppContext,
    matter: Matter,
    run: Run,
    built: BuiltReport,
    *,
    version: int,
    final: bool = False,
) -> Report:
    directory = ctx.run_dir(matter.matter_id, run.run_id)
    stem = f"report_v{version}" + ("_approved" if final else "")
    markdown_path = directory / f"{stem}.md"
    data_path = directory / f"{stem}.json"
    # Bytes, not text: the hash below is of exactly these bytes, and a text write would change
    # the line endings on Windows and break every later comparison with it.
    markdown_path.write_bytes(built.markdown.encode("utf-8"))
    data_path.write_bytes(
        json.dumps(built.data, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    )
    return Report(
        matter_id=matter.matter_id,
        run_id=run.run_id,
        template=built.template,
        audience=built.audience,
        sha256=hashlib.sha256(built.markdown.encode("utf-8")).hexdigest(),
        artifact_ref=str(markdown_path),
        version=version,
        release_status="APPROVED_FOR_RELIANCE" if final else "NOT_FOR_RELIANCE",
        claim_ids=built.claim_ids,
        excluded_claim_ids=built.excluded_claim_ids,
        warnings=built.warnings,
        data_ref=str(data_path),
    )


def warning_id(warning: str) -> str:
    """The stable part of a warning, which a reviewer acknowledges."""
    return warning.split(": ", 1)[0]
