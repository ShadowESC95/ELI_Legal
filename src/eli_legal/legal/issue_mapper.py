"""Issue identification and fact-to-issue linking.

Issues come from three places, kept distinguishable: stated by a human at intake, lifted from the
parties' own papers (a heading or a question they framed), or proposed by a model. Proposed issues
are labelled as such so a reviewer can confirm or discard them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from eli_legal.domain.enums import DocumentType
from eli_legal.domain.models import Chunk, Claim, Document, Issue, Matter
from eli_legal.legal.dates import split_sentences
from eli_legal.legal.llm import (
    MAX_ITEM_CHARS,
    PROMPT_VERSIONS,
    STEP_TEXT_CHARS,
    LegalModel,
    declare_step,
    fenced,
    numbered,
)
from eli_legal.persistence.sqlite import _STOPWORDS, _WORD

_EXCERPT_CHARS = 9000
_EXCERPT_CHUNKS = 8
_PROPOSE_REPLY_TOKENS = 600
_LINK_BATCH = 25
_LINK_REPLY_TOKENS = 900
declare_step(
    "issue_propose",
    chars=_EXCERPT_CHARS + STEP_TEXT_CHARS,
    reply_tokens=_PROPOSE_REPLY_TOKENS,
)
declare_step(
    "fact_issue_link",
    chars=_LINK_BATCH * MAX_ITEM_CHARS + 2 * STEP_TEXT_CHARS,
    reply_tokens=_LINK_REPLY_TOKENS,
)

_ISSUE_LINE = re.compile(
    r"^\s*(?:issue|question)\s*(?:no\.?\s*)?\d*\s*[:.\-–]\s*(?P<label>.{12,300})$", re.I
)
_WHETHER = re.compile(r"\bwhether\b.{15,280}", re.I)
_PLEADING_TYPES = {DocumentType.PLEADING, DocumentType.SUBMISSION, DocumentType.ORDER}
_LEGAL_HINTS = re.compile(
    r"\b(lawful|unlawful|breach|liab|jurisdiction|enforceab|valid|void|statut|limitation|"
    r"time-barred|duty|negligen|entitle|terminate|rescind|remed|damages|interpret|constru|"
    r"arbitrab|estoppel|waiver|frustrat|misrepresent|implied term|penalty|causation)\w*",
    re.I,
)


# Words that name the roles in any dispute; they link everything to everything.
_ROLE_WORDS = frozenset(
    "claimant respondent applicant defendant plaintiff appellant party parties agreement "
    "contract whether".split()
)


def terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 3 and w not in _STOPWORDS}


def stems(text: str) -> set[str]:
    """Crude stems (first seven letters) so 'terminated' meets 'termination'."""
    return {t[:7] for t in terms(text) if t not in _ROLE_WORDS}


def _kind(label: str) -> str:
    # A question framed for a tribunal usually mixes fact and law; say "legal" only on a cue.
    return "legal" if _LEGAL_HINTS.search(label) else "mixed"


@dataclass(slots=True)
class IssueMapper:
    model: LegalModel
    min_overlap: int = 2

    def identify(
        self, *, matter: Matter, run_id: str, documents: Sequence[Document], chunks: Sequence[Chunk]
    ) -> list[Issue]:
        issues: list[Issue] = []
        seen: set[str] = set()

        def add(label: str, source: str) -> None:
            label = " ".join(label.split()).strip(" .;:-–")
            key = " ".join(sorted(terms(label)))
            if len(label) < 12 or not key or key in seen:
                return
            seen.add(key)
            issues.append(
                Issue(
                    matter_id=matter.matter_id,
                    run_id=run_id,
                    label=label[:300],
                    kind=_kind(label),
                    source=source,
                )
            )

        for stated in matter.stated_issues:
            add(stated, "stated")

        pleading_ids = {d.document_id for d in documents if d.doc_type in _PLEADING_TYPES}
        pleading_chunks = [c for c in chunks if c.document_id in pleading_ids]
        for chunk in pleading_chunks:
            for line in chunk.text.splitlines():
                m = _ISSUE_LINE.match(line)
                if m:
                    add(m.group("label"), "extracted")
            for sentence in split_sentences(chunk.text.replace("\n", " ")):
                m2 = _WHETHER.search(sentence)
                if m2 and re.search(
                    r"\b(issue|question|dispute|determin|decid)\w*", sentence, re.I
                ):
                    add(m2.group(0)[0].upper() + m2.group(0)[1:], "extracted")

        if self.model.available and pleading_chunks:
            for label in self._model_propose(matter, pleading_chunks, [i.label for i in issues]):
                add(label, "model_proposed")
        return issues

    def _model_propose(
        self, matter: Matter, chunks: Sequence[Chunk], known: list[str]
    ) -> list[str]:
        def build(count: int) -> str:
            excerpt = "\n\n".join(c.text for c in chunks[:count])[:_EXCERPT_CHARS]
            return (
                f"Task {PROMPT_VERSIONS['issue_propose']}. From the parties' papers below, list "
                "the questions the decision-maker will have to resolve. Phrase each as a neutral "
                "question beginning with 'Whether'. Do not suggest any answer. Do not repeat these "
                f"already-identified issues: {known or 'none'}. "
                'Reply as {"issues": ["Whether ...", ...]} with at most 8 items.\n'
                + fenced(excerpt, "pleadings")
            )

        offered = min(len(chunks), _EXCERPT_CHUNKS)
        kept = self.model.fitting(build, offered, reply_tokens=_PROPOSE_REPLY_TOKENS)
        if kept < offered:
            self.model.stats.notes.append(
                f"issue_propose: {kept} of {offered} passages of the parties' papers fit the "
                "model's context"
            )
        if kept <= 0:
            return []
        answer = self.model.ask("issue_propose", build(kept), max_tokens=_PROPOSE_REPLY_TOKENS)
        if not answer or not isinstance(answer.get("issues"), list):
            return []
        return [str(x) for x in answer["issues"][:8] if isinstance(x, str)]

    def link_facts(
        self,
        *,
        issues: Sequence[Issue],
        facts: Sequence[Claim],
        model_excluded_claim_ids: frozenset[str] = frozenset(),
    ) -> None:
        """Attach facts to the issues they bear on. Mutates the issues and the facts.

        Facts named in ``model_excluded_claim_ids`` are linked by wording only; their text is
        never shown to the model.
        """
        issue_terms = {i.issue_id: stems(f"{i.label} {i.description}") for i in issues}
        if len(issues) > 1:
            # A term every issue shares (the contract's name, say) tells the issues apart no
            # better than a stopword does.
            shared = set.intersection(*issue_terms.values())
            issue_terms = {k: v - shared for k, v in issue_terms.items()}
        by_id = {i.issue_id: i for i in issues}
        linked_by_model: dict[str, set[str]] = {}
        for_model = [f for f in facts if f.claim_id not in model_excluded_claim_ids]
        if self.model.available and issues and for_model:
            linked_by_model = self._model_link(issues, for_model)
        for fact in facts:
            fact_terms = stems(fact.text)
            for issue in issues:
                wanted = issue_terms[issue.issue_id]
                lexical = len(fact_terms & wanted) >= min(self.min_overlap, max(1, len(wanted)))
                modelled = issue.issue_id in linked_by_model.get(fact.claim_id, set())
                if lexical or modelled:
                    if issue.issue_id not in fact.issue_ids:
                        fact.issue_ids.append(issue.issue_id)
                    if fact.claim_id not in by_id[issue.issue_id].claim_ids:
                        by_id[issue.issue_id].claim_ids.append(fact.claim_id)

    def _model_link(self, issues: Sequence[Issue], facts: Sequence[Claim]) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        issue_list = numbered([i.label for i in issues], "I")
        limit = min(len(facts), 300)
        start = 0
        while start < limit:
            window = list(facts[start : min(limit, start + _LINK_BATCH)])

            def build(count: int, window: list[Claim] = window) -> str:
                return (
                    f"Task {PROMPT_VERSIONS['fact_issue_link']}. Match each numbered fact to the "
                    "issues it is relevant to. A fact may match none, one or several. "
                    'Reply as {"links": [{"fact": <number>, "issues": [<numbers>]}]}.\n'
                    f"Issues:\n{issue_list}\n"
                    + fenced(numbered([f.text for f in window[:count]], "F"), "facts")
                )

            # A batch is as many facts as leave the model room to answer; the rest wait for
            # the next batch.
            kept = self.model.fitting(build, len(window), reply_tokens=_LINK_REPLY_TOKENS)
            if kept <= 0:
                self.model.stats.notes.append(
                    "fact_issue_link: the issues and one fact do not fit the model's context "
                    "together; the remaining facts are linked by wording only"
                )
                break
            batch = window[:kept]
            start += kept
            answer = self.model.ask("fact_issue_link", build(kept), max_tokens=_LINK_REPLY_TOKENS)
            if not answer or not isinstance(answer.get("links"), list):
                continue
            for link in answer["links"]:
                try:
                    f_index = int(str(link.get("fact")).lstrip("Ff")) - 1
                    i_numbers = [int(str(x).lstrip("Ii")) - 1 for x in link.get("issues", [])]
                except (ValueError, AttributeError, TypeError):
                    self.model.stats.rejected_items += 1
                    continue
                if not 0 <= f_index < len(batch):
                    self.model.stats.rejected_items += 1
                    continue
                for i_index in i_numbers:
                    if 0 <= i_index < len(issues):
                        out.setdefault(batch[f_index].claim_id, set()).add(issues[i_index].issue_id)
                    else:
                        self.model.stats.rejected_items += 1
        return out
