"""Legal research over approved sources only.

Two kinds of finding come out of this module:

* what the approved sources say on an issue — a passage quoted word for word from an authority;
* what the parties rely on — each citation found in the parties' papers, tied to the sentence in
  which the party cites it.

Nothing here decides whether an authority is good law or supports a proposition; the verifiers do
that afterwards, separately.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from eli_legal.domain.enums import AuthorityKind, ClaimKind
from eli_legal.domain.models import Chunk, Claim, Document, EvidenceLink, Issue
from eli_legal.legal.authority_status import applicable_on
from eli_legal.legal.citations import CitationExtractor
from eli_legal.legal.dates import split_sentences
from eli_legal.legal.issue_mapper import terms
from eli_legal.ports.legal_sources import AuthorityHit, LegalSourcePort
from eli_legal.security.redaction import quote_hash

_MAX_QUOTE = 600


def best_sentence(passage_text: str, query_terms: set[str]) -> str:
    """The sentence of a passage that shares most terms with the query (verbatim)."""
    sentences = split_sentences(passage_text.replace("\n", " ")) or [passage_text]
    ranked = sorted(sentences, key=lambda s: (-len(terms(s) & query_terms), len(s)))
    return ranked[0][:_MAX_QUOTE]


@dataclass(slots=True)
class CaseLawRetriever:
    connectors: Mapping[str, LegalSourcePort]

    def search(
        self, *, jurisdictions: Sequence[str], query: str, limit: int = 20
    ) -> list[AuthorityHit]:
        hits: list[AuthorityHit] = []
        for connector in self.connectors.values():
            hits.extend(connector.search(jurisdictions=jurisdictions, query=query, limit=limit))
        hits.sort(key=lambda h: -h.score)
        return hits[:limit]

    def propositions_for_issue(
        self,
        *,
        matter_id: str,
        run_id: str,
        issue: Issue,
        jurisdictions: Sequence[str],
        per_issue: int = 4,
        relevant_date: date | None = None,
    ) -> list[Claim]:
        query = f"{issue.label} {issue.description}"
        query_terms = terms(query)
        claims: list[Claim] = []
        seen: set[str] = set()
        for hit in self.search(jurisdictions=jurisdictions, query=query, limit=per_issue * 4):
            if hit.authority.authority_id in seen:
                continue  # one passage per authority per issue
            # A dated version of enacted text is only offered if it is the version in force on
            # the relevant date. Case law is always offered; its status is checked afterwards,
            # so an overruled case is shown as held rather than silently left out.
            if (
                relevant_date is not None
                and hit.authority.kind is not AuthorityKind.CASE
                and not applicable_on(hit.authority, relevant_date)
            ):
                continue
            quote = best_sentence(hit.passage.text, query_terms)
            if len(terms(quote) & query_terms) < 2:
                continue
            seen.add(hit.authority.authority_id)
            claims.append(
                Claim(
                    matter_id=matter_id,
                    run_id=run_id,
                    text=quote,
                    kind=ClaimKind.LEGAL_PROPOSITION,
                    issue_ids=[issue.issue_id],
                    authority_id=hit.authority.authority_id,
                    citation=hit.authority.citation,
                    origin=f"retrieval:{hit.authority.source_id}",
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
