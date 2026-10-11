from __future__ import annotations

from dataclasses import dataclass

from eli_legal.domain.enums import VerificationStatus as V
from eli_legal.domain.enums import VerificationType
from eli_legal.domain.models import Claim, VerificationResult
from eli_legal.legal.llm import (
    MAX_ITEM_CHARS,
    PROMPT_VERSIONS,
    STEP_TEXT_CHARS,
    LegalModel,
    declare_step,
    fenced,
)
from eli_legal.legal.provenance import ProvenanceVerifier, contains_verbatim

_REPLY_TOKENS = 60
# a proposition and the passages cited for it
declare_step(
    "support_check", chars=4 * MAX_ITEM_CHARS + STEP_TEXT_CHARS, reply_tokens=_REPLY_TOKENS
)


@dataclass(frozen=True, slots=True)
class PropositionCheck:
    status: V
    rationale: str
    evidence_refs: tuple[str, ...] = ()


class PropositionVerifier:
    """Does the cited source support the proposition?

    A verbatim quotation is verified deterministically. Anything reworded cannot be confirmed by
    string comparison, and a second model agreeing with the first is not independent
    verification. So a reworded proposition is held for a person, with one exception: a deployer
    may record, after testing against known matters, that a named independent verifier model is
    validated for this purpose (``model_verification_validated``). Even then the verifier must
    be a different model from the one that drafted the proposition. Without that record a
    model's opinion can only make the result stricter, never more favourable.
    """

    def __init__(
        self,
        *,
        provenance: ProvenanceVerifier | None = None,
        verifier_model: LegalModel | None = None,
        generator_model_id: str = "none",
        model_verification_validated: bool = False,
    ) -> None:
        self.provenance = provenance
        self.verifier_model = verifier_model or LegalModel(None)
        self.generator_model_id = generator_model_id
        self.model_verification_validated = model_verification_validated

    def verify(self, claim_text: str, source_text: str) -> PropositionCheck:
        if not claim_text.strip() or not source_text.strip():
            return PropositionCheck(V.INCONCLUSIVE, "missing claim/source text")
        if contains_verbatim(source_text, claim_text):
            return PropositionCheck(V.VERIFIED, "verbatim from the source")
        return PropositionCheck(
            V.INCONCLUSIVE, "the proposition rewords its source; needs independent confirmation"
        )

    def verify_claim(self, claim: Claim) -> VerificationResult:
        if self.provenance is None:
            raise RuntimeError("verify_claim needs a ProvenanceVerifier")
        base = self.provenance.evidence_support(claim, target_type="authority")
        if base.status is not V.INCONCLUSIVE:
            return base
        independent = (
            self.verifier_model.available
            and self.verifier_model.model_id != self.generator_model_id
        )
        if not independent:
            base.detail += "; no independent verifier is configured"
            return base
        opinion = self._model_opinion(claim)
        base.verifier = f"model:{self.verifier_model.model_id}"
        if opinion == "not_supported":
            base.status = V.CONFLICT
            base.detail = "an independent verifier model found the source does not support this"
        elif opinion == "supported" and self.model_verification_validated:
            base.status = V.VERIFIED
            base.detail = (
                "supported according to an independent verifier model validated for this use"
            )
        elif opinion == "supported":
            base.detail += "; an independent verifier model considered it supported (advisory only)"
        else:
            base.detail += "; the independent verifier model could not decide"
        return base

    def _model_opinion(self, claim: Claim) -> str:
        if self.provenance is None:
            return "unclear"
        passages: list[str] = []
        for index, link in enumerate(claim.evidence):
            if link.target_type == "authority":
                text, _ref, _problem = self.provenance._source_text(claim, index)
                if text:
                    passages.append(text)
        if not passages:
            return "unclear"
        prompt = (
            f"Task {PROMPT_VERSIONS['support_check']}. Decide whether the source passage below "
            "supports the proposition. Judge only from the passage. If the passage is silent, "
            "ambiguous, or supports only part of the proposition, answer unclear. "
            'Reply as {"verdict": "supported" | "not_supported" | "unclear"}.\n'
            f"Proposition: {claim.text}\n" + fenced("\n\n".join(passages), "authority")
        )
        answer = self.verifier_model.ask("support_check", prompt, max_tokens=_REPLY_TOKENS)
        verdict = str((answer or {}).get("verdict", "unclear")).lower()
        return verdict if verdict in {"supported", "not_supported", "unclear"} else "unclear"


__all__ = ["PropositionCheck", "PropositionVerifier", "VerificationType"]
