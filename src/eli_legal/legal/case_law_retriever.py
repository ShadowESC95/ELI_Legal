"""Legal research over approved sources only.

Two kinds of finding come out of this module:

* what the approved sources say on an issue — a passage quoted word for word from an authority;
* what the parties rely on — each citation found in the parties' papers, tied to the sentence in
  which the party cites it.

Nothing here decides whether an authority is good law or supports a proposition; the verifiers do
that afterwards, separately.

Research ranks passages two ways when an embedding model is set up: by the words of the issue
(keyword search, BM25) and by its meaning (``legal/semantic.py``). The two rankings are fused by
weighted reciprocal rank, meaning counting most, so a passage high in either is offered and one
high in both comes first. Which way each passage was found is recorded with it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from eli_legal.domain.enums import AuthorityKind, ClaimKind
from eli_legal.domain.models import (
    AuthorityPassage,
    Chunk,
    Claim,
    Document,
    EvidenceLink,
    Issue,
)
from eli_legal.legal.authority_status import applicable_on
from eli_legal.legal.citations import CitationExtractor
from eli_legal.legal.dates import split_sentences
from eli_legal.legal.issue_mapper import terms
from eli_legal.legal.semantic import SemanticIndex, windows
from eli_legal.ports.legal_sources import AuthorityHit, LegalSourcePort
from eli_legal.security.redaction import quote_hash

_MAX_QUOTE = 600
RRF_K = 60  # reciprocal rank fusion's usual constant: rank 1 and rank 10 differ, gently
# The ranking by words counts a fifth as much as the ranking by meaning. Chosen on half of the
# research benchmark (evaluation/research.py) and checked on the other half; it was the choice
# for both embedding models measured.
KEYWORD_WEIGHT = 0.2
POOL = 50  # how deep each ranking is read before fusing
MEANING_TOP = 10  # a passage this high by meaning is offered even without the issue's words
KEYWORD_TOOL = "sqlite-fts5-bm25/1"


def _flat(text: str) -> str:
    return " ".join(text.split())


def best_sentence(passage_text: str, query_terms: set[str], *, within: str = "") -> str:
    """The sentence of a passage that shares most terms with the query, word for word. With
    ``within`` (the part of the passage that matched by meaning), a sentence from that part,
    the first of them when none shares the query's words."""
    sentences = split_sentences(passage_text.replace("\n", " ")) or [passage_text]
    if within:
        part = _flat(within)
        inside = [s for s in sentences if _flat(s) and _flat(s) in part]
        if inside:
            order = {s: i for i, s in enumerate(inside)}
            ranked = sorted(inside, key=lambda s: (-len(terms(s) & query_terms), order[s]))
            return ranked[0][:_MAX_QUOTE]
    ranked = sorted(sentences, key=lambda s: (-len(terms(s) & query_terms), len(s)))
    return ranked[0][:_MAX_QUOTE]


@dataclass(slots=True)
class Ranked:
    hit: AuthorityHit
    keyword_rank: int | None = None
    meaning_rank: int | None = None
    meaning_part: str = ""  # the window of the passage that matched by meaning

    @property
    def found_by(self) -> str:
        ways = [w for w, r in (("words", self.keyword_rank), ("meaning", self.meaning_rank)) if r]
        return " and ".join(ways)


@dataclass(slots=True)
class CaseLawRetriever:
    connectors: Mapping[str, LegalSourcePort]
    semantic: SemanticIndex | None = None
    mode: str = "hybrid"  # hybrid, keyword or meaning; without a model, keyword
    _parts: dict[str, list[str]] = field(default_factory=dict, repr=False)

    @property
    def by_meaning(self) -> bool:
        return self.mode != "keyword" and self.semantic is not None and self.semantic.available

    @property
    def method(self) -> str:
        """What ranked the passages, as recorded in the audit trail."""
        if not self.by_meaning:
            return KEYWORD_TOOL
        assert self.semantic is not None
        if self.mode == "meaning":
            return f"meaning:{self.semantic.model_id}"
        return f"{KEYWORD_TOOL}+meaning:{self.semantic.model_id};rrf/{RRF_K}/{KEYWORD_WEIGHT}"

    def search(
        self, *, jurisdictions: Sequence[str], query: str, limit: int = 20
    ) -> list[AuthorityHit]:
        return [r.hit for r in self.ranked(jurisdictions=jurisdictions, query=query, limit=limit)]

    def ranked(self, *, jurisdictions: Sequence[str], query: str, limit: int = 20) -> list[Ranked]:
        out: dict[str, Ranked] = {}
        if self.mode != "meaning" or not self.by_meaning:
            keyword: list[AuthorityHit] = []
            for connector in self.connectors.values():
                keyword.extend(
                    connector.search(
                        jurisdictions=jurisdictions, query=query, limit=max(limit, POOL)
                    )
                )
            keyword.sort(key=lambda h: -h.score)
            for rank, hit in enumerate(keyword[: max(limit, POOL)], 1):
                out.setdefault(hit.passage.passage_id, Ranked(hit)).keyword_rank = rank
        if not self.by_meaning:
            return [r for r in out.values()][:limit]
        assert self.semantic is not None
        store = self.semantic.store
        found = self.semantic.search(
            query, list(self.connectors), jurisdictions, limit=max(limit, POOL), with_part=True
        )
        for rank, (passage_id, similarity, part) in enumerate(found, 1):
            entry = out.get(passage_id)
            if entry is None:
                passage = store.get_passage(passage_id)
                authority = store.get_authority(passage.authority_id) if passage else None
                if passage is None or authority is None:
                    continue
                entry = out[passage_id] = Ranked(AuthorityHit(authority, passage, similarity))
            entry.meaning_rank = rank
            entry.meaning_part = self._part(entry.hit.passage, part)

        def fused(r: Ranked) -> float:
            words = KEYWORD_WEIGHT / (RRF_K + r.keyword_rank) if r.keyword_rank else 0.0
            meaning = 1.0 / (RRF_K + r.meaning_rank) if r.meaning_rank else 0.0
            return words + meaning

        ranked = sorted(out.values(), key=lambda r: -fused(r))
        for r in ranked:
            r.hit = AuthorityHit(r.hit.authority, r.hit.passage, fused(r))
        return ranked[:limit]

    def _part(self, passage: AuthorityPassage, part: int) -> str:
        parts = self._parts.get(passage.passage_id)
        if parts is None:
            parts = self._parts[passage.passage_id] = windows(passage)
        text = parts[part] if 0 <= part < len(parts) else ""
        heading = passage.heading.strip()
        return text[len(heading) + 1 :] if heading and text.startswith(f"{heading}\n") else text

    def propositions_for_issue(
        self,
        *,
        matter_id: str,
        run_id: str,
        issue: Issue,
        jurisdictions: Sequence[str],
        per_issue: int = 4,
        relevant_date: date | None = None,
        per_authority: int = 2,
    ) -> list[Claim]:
        query = f"{issue.label} {issue.description}".strip()
        query_terms = terms(query)
        claims: list[Claim] = []
        taken: dict[str, int] = {}
        for entry in self.ranked(jurisdictions=jurisdictions, query=query, limit=per_issue * 6):
            hit = entry.hit
            if taken.get(hit.authority.authority_id, 0) >= per_authority:
                continue  # room for other authorities on the issue
            # A dated version of enacted text is only offered if it is the version in force on
            # the relevant date. Case law is always offered; its status is checked afterwards,
            # so an overruled case is shown as held rather than silently left out.
            if (
                relevant_date is not None
                and hit.authority.kind is not AuthorityKind.CASE
                and not applicable_on(hit.authority, relevant_date)
            ):
                continue
            quote = best_sentence(hit.passage.text, query_terms, within=entry.meaning_part)
            close_in_meaning = entry.meaning_rank is not None and entry.meaning_rank <= MEANING_TOP
            if len(terms(quote) & query_terms) < 2 and not close_in_meaning:
                continue
            taken[hit.authority.authority_id] = taken.get(hit.authority.authority_id, 0) + 1
            claims.append(
                Claim(
                    matter_id=matter_id,
                    run_id=run_id,
                    text=quote,
                    kind=ClaimKind.LEGAL_PROPOSITION,
                    issue_ids=[issue.issue_id],
                    authority_id=hit.authority.authority_id,
                    citation=hit.authority.citation,
                    origin=f"retrieval:{hit.authority.source_id}"
                    + (f"; found by {entry.found_by}" if self.by_meaning else ""),
                    evidence=[
                        EvidenceLink(
                            target_type="authority",
                            target_id=hit.authority.authority_id,
                            locator=hit.passage.locator,
                            quote=quote,
                            quote_hash=quote_hash(quote),
                            chunk_id=hit.passage.passage_id,
                        )
                    ],
                )
            )
            if len(claims) >= per_issue:
                break
        return claims


def party_authorities(
    *,
    matter_id: str,
    run_id: str,
    documents: Sequence[Document],
    chunks: Sequence[Chunk],
    extractor: CitationExtractor,
) -> list[Claim]:
    """One finding per (document, citation): the sentence in which the authority is relied on."""
    # Every document is searched, whatever type it was filed as. A citation is worth checking
    # wherever it appears, and a pleading misfiled as something else must not escape the check.
    by_doc = {d.document_id: d for d in documents}
    out: dict[tuple[str, str], Claim] = {}
    for chunk in chunks:
        document = by_doc.get(chunk.document_id)
        if document is None:
            continue
        for sentence in split_sentences(chunk.text.replace("\n", " ")):
            for match in extractor.extract(sentence):
                key = (chunk.document_id, match.key)
                if key in out:
                    continue
                quote = sentence[:_MAX_QUOTE]
                out[key] = Claim(
                    matter_id=matter_id,
                    run_id=run_id,
                    text=quote,
                    kind=ClaimKind.PARTY_AUTHORITY,
                    party_id=document.party_id,
                    citation=match.raw,
                    origin=f"citation:{match.jurisdiction}/{match.pattern_id}",
                    access_scope=document.access_scope,
                    evidence=[
                        EvidenceLink(
                            target_type="document",
                            target_id=chunk.document_id,
                            locator=chunk.locator,
                            quote=quote,
                            quote_hash=quote_hash(quote),
                            chunk_id=chunk.chunk_id,
                        )
                    ],
                )
    return list(out.values())
