"""Matter chat: questions about one matter, answered from its sources.

The chat is a way of reading the matter, not a second route to findings. It retrieves passages
from the matter's documents, the run's findings (with their verification state) and the approved
legal sources, and shows them with their locators. Where a model is configured it may add a short
summary, sentence by sentence, each sentence tied to the sources it rests on and checked against
them; a sentence that adds a figure or citation of its own, or says who should succeed, is
dropped. Nothing said in chat is a finding, and no decision can be taken here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from eli_legal.application.container import AppContext
from eli_legal.domain.enums import ClaimStatus, DocumentStatus
from eli_legal.domain.enums import VerificationStatus as V
from eli_legal.domain.errors import NotFound
from eli_legal.domain.models import Claim, Document, Matter, Report, Run, VerificationTask
from eli_legal.domain.profiles import profile_spec
from eli_legal.legal.analysis import figures, outcome_language
from eli_legal.legal.case_law_retriever import CaseLawRetriever
from eli_legal.legal.citations import CitationExtractor
from eli_legal.legal.current_law_citator import CurrentLawCitator
from eli_legal.legal.frameworks import (
    FrameworkPack,
    Rules,
    combined_rules,
    compile_context,
    contains_forbidden,
    search,
)
from eli_legal.legal.issue_mapper import stems
from eli_legal.legal.llm import PROMPT_VERSIONS, LegalModel, fenced
from eli_legal.security.redaction import content_hash

_REPLY_TOKENS = 700

# A question that asks for the decision itself.
_ASKS_OUTCOME = re.compile(
    r"\b(?:who|which (?:party|side))\b[^?]{0,60}\b(?:win|wins|succeed|prevail|right|liable|at fault|stronger)\b"
    r"|\bshould (?:i|we|the (?:tribunal|court|arbitrator|judge|mediator|panel))\b[^?]{0,60}"
    r"\b(?:find|decide|award|rule|dismiss|grant|hold|order)\b"
    r"|\bwhat (?:should|will|would) (?:be )?(?:the )?(?:outcome|result|decision|verdict|award|ruling)\b"
    r"|\bhow (?:should|would|will) (?:this|the) (?:case|dispute|issue|claim|matter) be decided\b"
    r"|\bwhat (?:is|are) (?:the|my|our|their) (?:chances|prospects)\b"
    r"|\b(?:recommend|suggest|propose)\b[^?]{0,40}\b(?:outcome|decision|award|settlement|verdict|ruling)\b"
    r"|\bdraft (?:the|an?|my) (?:award|judgment|decision|ruling|order)\b",
    re.I,
)

HELP = (
    "Ask about this matter in your own words, for example “when was the notice received?” or "
    "“what do the sources say about notice of termination?”. I answer from the matter's "
    "documents, this run's findings, the approved legal sources and the law and standards that "
    "apply, and show where each passage comes from.\n\nCommands: /status  /holds  /tasks  /limits  /law  /help\n\nI do not say who should "
    "succeed or how anything should be decided, and no hold, verification, approval or release "
    "can be made from chat. Use the Review tab for those."
)


@dataclass(slots=True)
class ChatSource:
    label: str  # D1, F2, A3
    kind: str  # document | finding | authority
    title: str
    locator: str
    text: str  # verbatim
    note: str = ""
    usable: bool = True  # may support a model-written sentence


@dataclass(slots=True)
class ChatAnswer:
    question: str
    mode: str  # passages | model | command | refused
    lines: list[tuple[str, list[str]]] = field(default_factory=list)
    sources: list[ChatSource] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    dropped: int = 0
    model_id: str = "none"


@dataclass(slots=True)
class ChatService:
    ctx: AppContext

    def _latest_run(self, matter: Matter, run_id: str | None) -> Run | None:
        if run_id:
            run = self.ctx.store.get(Run, matter.matter_id, run_id)
            if run is None:
                raise NotFound(f"run not found in this matter: {run_id}")
            return run
        runs = self.ctx.store.list(Run, matter.matter_id)
        return runs[-1] if runs else None

    def ask(
        self,
        matter_id: str,
        *,
        actor_id: str,
        question: str,
        run_id: str | None = None,
        use_model: bool = True,
    ) -> ChatAnswer:
        ctx = self.ctx
        matter = ctx.matter_for(matter_id, actor_id, "document.read")
        question = " ".join(question.split())
        run = self._latest_run(matter, run_id)
        if question.startswith("/"):
            answer = self._command(matter, run, question)
        else:
            answer = self._answer(matter, run, question, use_model)
        ctx.log(
            "chat_query",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            run_id=run.run_id if run else None,
            action="document.read",
            subject_id=matter.matter_id,
            outcome=answer.mode,
            object_type="chat",
            model_id=answer.model_id if answer.mode == "model" else None,
            prompt_version=PROMPT_VERSIONS["chat_answer"] if answer.mode == "model" else None,
            input_hash=content_hash(question),
            payload={
                "sources": len(answer.sources),
                "sentences": len(answer.lines),
                "sentences_dropped": answer.dropped,
            },
        )
        return answer

    # ── commands: state of the run, never content ────────────────────────────
    def _command(self, matter: Matter, run: Run | None, question: str) -> ChatAnswer:
        command = question.split()[0].lower()
        answer = ChatAnswer(question=question, mode="command")
        if command == "/help":
            answer.notes.append(HELP)
            return answer
        if command == "/law":
            for pack in self._packs(matter):
                state = self.ctx.frameworks.state(pack)
                answer.notes.append(f"{pack.title} ({pack.version}): {state.why}")
            if not matter.framework_ids:
                answer.notes.append("No law or standards package applies to this matter.")
            return answer
        if run is None:
            answer.notes.append("No run has been started on this matter yet.")
            return answer
        mid, rid = matter.matter_id, run.run_id
        holds = self.ctx.holds.open_holds(mid, rid)
        if command == "/status":
            answer.notes.append(
                f"Run {rid[-8:]} is {run.status.value.replace('_', ' ')}. "
                f"{len(holds)} hold(s) open."
            )
            claims = self.ctx.store.list(Claim, mid, run_id=rid)
            tally: dict[str, int] = {}
            for claim in claims:
                tally[claim.status.value] = tally.get(claim.status.value, 0) + 1
            answer.notes.append(
                "Findings: " + ", ".join(f"{n} {s}" for s, n in sorted(tally.items()))
                if tally
                else "No findings yet."
            )
        elif command == "/holds":
            if not holds:
                answer.notes.append("No holds are open.")
            for hold in holds:
                answer.notes.append(f"{hold.scope.value} hold — {hold.reason_code}: {hold.detail}")
        elif command == "/tasks":
            tasks = self.ctx.store.list(VerificationTask, mid, run_id=rid, status="open")
            by_id = {c.claim_id: c for c in self.ctx.store.list(Claim, mid, run_id=rid)}
            if not tasks:
                answer.notes.append("No checks are waiting for a person.")
            for task in tasks:
                about = by_id.get(task.claim_id)
                subject = (about.citation or about.text[:80]) if about else task.claim_id
                answer.notes.append(f"{task.verification_type}: {task.question} — {subject}")
        elif command == "/limits":
            report = self.ctx.store.get(Report, mid, run.report_id or "")
            if report is None:
                answer.notes.append("No report has been drafted yet.")
            else:
                answer.notes.extend(report.warnings or ["The current report states no limits."])
        else:
            answer.notes.append(f"Unknown command {command}. Try /help.")
        return answer

    # ── questions ────────────────────────────────────────────────────────────
    def _answer(
        self, matter: Matter, run: Run | None, question: str, use_model: bool
    ) -> ChatAnswer:
        answer = ChatAnswer(question=question, mode="passages")
        spec = profile_spec(matter.profile)
        if spec.outcome_policy == "prohibited" and _ASKS_OUTCOME.search(question):
            answer.mode = "refused"
            answer.notes.append(
                "That asks for the decision. I do not say who should succeed or how an issue "
                "should be decided; that is for you. Here is the material that bears on it."
            )
        packs = self._packs(matter)
        answer.sources = self._sources(matter, run, question) + self._law(matter, packs, question)
        if not answer.sources:
            answer.notes.append(
                "Nothing in the matter's documents, findings or approved sources matched that. "
                "Absence here is not evidence of absence: try other words."
            )
            return answer
        model = LegalModel(
            self.ctx.model.inference, compliance=compile_context(packs, matter.profile.value)
        )
        if answer.mode != "refused" and use_model and model.available:
            usable = [s for s in answer.sources if s.usable]
            if usable:
                self._summarise(matter, question, usable, model, answer, combined_rules(packs))
        return answer

    def _packs(self, matter: Matter) -> list[FrameworkPack]:
        return [p for i in matter.framework_ids if (p := self.ctx.frameworks.get(i)) is not None]

    def _law(self, matter: Matter, packs: list[FrameworkPack], question: str) -> list[ChatSource]:
        """Requirements of the law and standards that apply, where the question is about them."""
        words = re.findall(r"[a-z0-9]+", question.lower())
        out = []
        for n, (pack, req, _score) in enumerate(
            search(packs, words, matter.profile.value, limit=4), start=1
        ):
            out.append(
                ChatSource(
                    label=f"L{n}",
                    kind="law",
                    title=f"{pack.short_title} · {req.title}",
                    locator=req.reference,
                    text=req.text,
                    note=self.ctx.frameworks.state(pack).why if pack.origin == "shipped" else "",
                    usable=True,
                )
            )
        return out

    def _sources(self, matter: Matter, run: Run | None, question: str) -> list[ChatSource]:
        ctx, mid = self.ctx, matter.matter_id
        out: list[ChatSource] = []
        documents = {d.document_id: d for d in ctx.store.list(Document, mid)}
        flagged = (
            {
                h.subject_id
                for h in ctx.holds.open_holds(mid, run.run_id)
                if h.reason_code == "prompt_injection_detected"
            }
            if run
            else {d.document_id for d in documents.values() if d.injection_flags}
        )
        seen_text: set[str] = set()
        for chunk, _score in ctx.store.search_chunks(mid, question, limit=6):
            document = documents.get(chunk.document_id)
            if document is None or document.status is not DocumentStatus.PROCESSED:
                continue
            is_flagged = chunk.document_id in flagged
            out.append(
                ChatSource(
                    label=f"D{sum(1 for s in out if s.kind == 'document') + 1}",
                    kind="document",
                    title=document.title or document.filename,
                    locator=chunk.locator,
                    text=chunk.text,
                    note=(
                        "from a file flagged for text addressed to an AI system: shown to you, "
                        "not given to the model"
                        if is_flagged
                        else ""
                    ),
                    usable=not is_flagged,
                )
            )
            seen_text.add(" ".join(chunk.text.split()))
        wanted = stems(question)
        if run is not None and wanted:
            claims = ctx.store.list(Claim, mid, run_id=run.run_id)
            ranked = sorted(
                ((len(stems(c.text + " " + (c.citation or "")) & wanted), c) for c in claims),
                key=lambda pair: -pair[0],
            )
            count = 0
            for overlap, claim in ranked:
                if overlap < 2 or count >= 6:
                    break
                if (
                    claim.status is ClaimStatus.VERIFIED
                    and " ".join(claim.text.split()) in seen_text
                ):
                    continue  # already shown as the passage it was taken from
                count += 1
                locator = claim.evidence[0].locator if claim.evidence else ""
                state = claim.status.value.upper()
                note = (
                    ""
                    if claim.status is ClaimStatus.VERIFIED
                    else f"{state} — {claim.status_reason}"
                )
                out.append(
                    ChatSource(
                        label=f"F{count}",
                        kind="finding",
                        title=f"{claim.kind.value.replace('_', ' ')}"
                        + (f" · {claim.citation}" if claim.citation else ""),
                        locator=locator,
                        text=claim.text,
                        note=note,
                        usable=claim.status is ClaimStatus.VERIFIED
                        and not any(e.target_id in flagged for e in claim.evidence),
                    )
                )
        connectors = ctx.connectors_for(matter)
        if connectors:
            codes = ctx.jurisdictions.jurisdiction_codes(matter)
            seen_authority: set[str] = set()
            for hit in CaseLawRetriever(connectors).search(
                jurisdictions=codes, query=question, limit=8
            ):
                authority = hit.authority
                if authority.authority_id in seen_authority or len(seen_authority) >= 4:
                    continue
                seen_authority.add(authority.authority_id)
                finding = connectors[authority.source_id].status(
                    authority=authority, as_of=matter.relevant_date
                )
                status, detail = CurrentLawCitator.assess(
                    authority,
                    finding,
                    pack=ctx.jurisdictions.get(authority.jurisdiction),
                    relevant_date=matter.relevant_date,
                )
                good = status is V.VERIFIED
                out.append(
                    ChatSource(
                        label=f"A{len(seen_authority)}",
                        kind="authority",
                        title=f"{authority.citation} — {authority.title}",
                        locator=hit.passage.locator,
                        text=hit.passage.text,
                        note=("" if good else "NOT TO BE RELIED ON — ") + detail,
                        usable=good,
                    )
                )
        return out

    def _summarise(
        self,
        matter: Matter,
        question: str,
        usable: list[ChatSource],
        model: LegalModel,
        answer: ChatAnswer,
        rules: Rules,
    ) -> None:
        def build(count: int) -> str:
            listing = "\n".join(
                f"{s.label} [{s.title} {s.locator}]: {s.text}" for s in usable[:count]
            )
            return (
                f"Task {PROMPT_VERSIONS['chat_answer']}. Question from an authorised user: "
                f"{question}\n"
                "Answer in at most five short sentences using only the numbered sources below "
                "(D = passage of a document in the matter, F = a verified finding, A = passage of "
                "an authority, L = a requirement of the law and standards that apply). Give the "
                "labels each sentence relies on. If the sources do not answer the question, reply "
                "with an empty list. Do not add any fact, figure, case or statute that is not in "
                "the sources. Do not say who should succeed or how anything should be decided. "
                'Reply as {"sentences": [{"text": "...", "cites": ["D1"]}]}.\n'
                + fenced(listing, "sources")
            )

        # The model is given as many of the sources as leave it room to answer. Every source
        # is still shown to the person; the note says which the summary did not draw on.
        kept = model.fitting(build, len(usable), reply_tokens=_REPLY_TOKENS)
        if kept < len(usable):
            left_out = ", ".join(s.label for s in usable[kept:])
            answer.notes.append(
                f"The model's context holds {kept} of the {len(usable)} sources; its summary "
                f"does not draw on {left_out}."
            )
        if kept <= 0:
            return
        by_label = {s.label: s for s in usable[:kept]}
        reply = model.ask("chat_answer", build(kept), max_tokens=_REPLY_TOKENS)
        items = reply.get("sentences") if reply else None
        if isinstance(items, list) and not items:
            answer.notes.append(
                "The model read the sources and reported that they do not answer the question."
            )
        if not isinstance(items, list):
            if model.stats.failures:
                why = model.problem.partition(": ")[2]
                answer.notes.append(
                    "The model did not return a usable answer"
                    + (f" ({why})" if why else "")
                    + "; showing the sources."
                )
            return
        extractor = CitationExtractor(self.ctx.jurisdictions.for_matter(matter))
        date_order = self.ctx.jurisdictions.for_matter(matter)[0].date_order
        for item in items[:5]:
            if not isinstance(item, dict):
                answer.dropped += 1
                continue
            text = " ".join(str(item.get("text") or "").split())
            cites = [str(c) for c in item.get("cites") or [] if str(c) in by_label]
            if not text or not cites:
                answer.dropped += 1
                continue
            basis = " ".join(f"{by_label[c].text} {by_label[c].title}" for c in cites)
            invented = figures(text, date_order).missing_from(figures(basis, date_order))
            new_citations = set(extractor.keys(text)) - set(extractor.keys(basis))
            forbidden = contains_forbidden(text, rules)
            if invented or new_citations or forbidden or outcome_language(text, matter.profile):
                answer.dropped += 1
                continue
            answer.lines.append((text, cites))
        if answer.lines:
            answer.mode = "model"
            answer.model_id = model.model_id
        if answer.dropped:
            answer.notes.append(
                f"{answer.dropped} sentence(s) drafted by the model were discarded because they "
                "cited nothing, added something not in the sources, or stated an outcome."
            )
