"""Provenance and evidence-support checks.

Provenance asks: does the thing this finding points at exist, unchanged, inside this matter (or
inside a source approved for it)? Evidence support asks: do the quoted words appear there, and is
the finding those words and nothing more?
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection
from dataclasses import dataclass, field

from eli_legal.adapters.local.vault import EvidenceVault
from eli_legal.domain.enums import VerificationStatus as V
from eli_legal.domain.enums import VerificationType
from eli_legal.domain.models import Claim, Document, VerificationResult
from eli_legal.persistence.sqlite import Store
from eli_legal.security.redaction import normalise_ws

VERIFIER_ID = "deterministic/provenance-1"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def contains_verbatim(haystack: str, needle: str) -> bool:
    return bool(needle.strip()) and normalise_ws(needle).lower() in normalise_ws(haystack).lower()


@dataclass(slots=True)
class ProvenanceVerifier:
    store: Store
    vault: EvidenceVault
    approved_source_ids: Collection[str]
    _vault_ok: dict[str, bool] = field(default_factory=dict)

    def _result(
        self, claim: Claim, vtype: VerificationType, status: V, detail: str, refs: list[str]
    ) -> VerificationResult:
        return VerificationResult(
            matter_id=claim.matter_id,
            run_id=claim.run_id,
            claim_id=claim.claim_id,
            verification_type=vtype.value,
            status=status,
            verifier=VERIFIER_ID,
            detail=detail,
            evidence_refs=refs,
        )

    def _original_intact(self, document: Document) -> bool:
        if document.document_id not in self._vault_ok:
            self._vault_ok[document.document_id] = self.vault.verify(
                document.matter_id, document.sha256
            )
        return self._vault_ok[document.document_id]

    def _source_text(self, claim: Claim, link_index: int) -> tuple[str | None, str, str]:
        """(text, reference, problem) for one evidence link; text is None when there is a problem."""
        link = claim.evidence[link_index]
        if link.target_type == "document":
            document = self.store.get(Document, claim.matter_id, link.target_id)
            if document is None:
                return None, link.target_id, "document is not part of this matter"
            if not self._original_intact(document):
                return (
                    None,
                    document.document_id,
                    "original file is missing or altered in the vault",
                )
            chunk = self.store.get_chunk(claim.matter_id, link.chunk_id or "")
            if chunk is None or chunk.document_id != document.document_id:
                return None, document.document_id, "passage not found in the document"
            if _sha(chunk.text) != chunk.text_hash:
                return None, document.document_id, "stored passage text does not match its hash"
            return chunk.text, f"{document.document_id}@{document.sha256[:12]}", ""
        if link.target_type == "authority":
            authority = self.store.get_authority(link.target_id)
            if authority is None:
                return None, link.target_id, "authority is not in any corpus"
            if authority.source_id not in self.approved_source_ids:
                return (
                    None,
                    link.target_id,
                    "authority comes from a source not approved for this matter",
                )
            passage = self.store.get_passage(link.chunk_id or "")
            if passage is None or passage.authority_id != authority.authority_id:
                return None, authority.source_version_id, "passage not found in the authority"
            if _sha(passage.text) != passage.text_hash:
                return (
                    None,
                    authority.source_version_id,
                    "stored authority text does not match its hash",
                )
            return passage.text, authority.source_version_id, ""
        return None, link.target_id, f"unknown evidence type {link.target_type!r}"

    def provenance(self, claim: Claim) -> VerificationResult:
        if not claim.evidence:
            return self._result(
                claim,
                VerificationType.PROVENANCE,
                V.FAILED,
                "no source is linked to this finding",
                [],
            )
        refs: list[str] = []
        for index in range(len(claim.evidence)):
            text, ref, problem = self._source_text(claim, index)
            refs.append(ref)
            if text is None:
                return self._result(claim, VerificationType.PROVENANCE, V.FAILED, problem, refs)
        return self._result(
            claim,
            VerificationType.PROVENANCE,
            V.VERIFIED,
            "every linked source exists unchanged",
            refs,
        )

    def evidence_support(
        self, claim: Claim, *, target_type: str = "document"
    ) -> VerificationResult:
        """The finding must be the quoted words, and the quoted words must be in the source."""
        vtype = (
            VerificationType.EVIDENCE_SUPPORT
            if target_type == "document"
            else VerificationType.PROPOSITION
        )
        links = [i for i, e in enumerate(claim.evidence) if e.target_type == target_type]
        if not links:
            return self._result(claim, vtype, V.FAILED, f"no {target_type} passage is linked", [])
        refs: list[str] = []
        for index in links:
            link = claim.evidence[index]
            text, ref, problem = self._source_text(claim, index)
            refs.append(ref)
            if text is None:
                return self._result(claim, vtype, V.FAILED, problem, refs)
            if not contains_verbatim(text, link.quote):
                return self._result(
                    claim,
                    vtype,
                    V.FAILED,
                    "the quoted words do not appear in the source passage",
                    refs,
                )
            if not contains_verbatim(link.quote, claim.text) and not contains_verbatim(
                text, claim.text
            ):
                return self._result(
                    claim,
                    vtype,
                    V.INCONCLUSIVE,
                    "the finding rewords its source; a person must confirm the source supports it",
                    refs,
                )
        return self._result(claim, vtype, V.VERIFIED, "verbatim from the source passage", refs)
