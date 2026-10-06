from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

from eli_legal.adapters.local.parsers import Segment
from eli_legal.domain.enums import DocumentType
from eli_legal.domain.models import Chunk
from eli_legal.legal.dates import split_sentences

TARGET_CHARS = 1200
MAX_CHARS = 1800

# First match wins, so the more specific kinds come first.
_TYPE_RULES: tuple[tuple[DocumentType, re.Pattern[str]], ...] = (
    (
        DocumentType.WITNESS_STATEMENT,
        re.compile(r"\b(witness statement|affidavit|sworn statement|statement of truth)\b", re.I),
    ),
    (
        DocumentType.EXPERT_REPORT,
        re.compile(r"\b(expert(?:'s)? report|expert opinion|report of the expert)\b", re.I),
    ),
    (
        DocumentType.ORDER,
        re.compile(
            r"\b(procedural order|it is (?:hereby )?ordered|order of the (?:court|tribunal))\b",
            re.I,
        ),
    ),
    (
        DocumentType.TRANSCRIPT,
        re.compile(
            r"\b(transcript of (?:the )?(?:hearing|proceedings)|day \d+ of the hearing)\b", re.I
        ),
    ),
    (
        DocumentType.PLEADING,
        re.compile(
            r"\b(statement of (?:claim|defence|defense|case|reply)|points of (?:claim|defence)|"
            r"notice of arbitration|request for arbitration|answer to the request|"
            r"plenary summons|originating (?:summons|application)|particulars of claim|"
            r"counterclaim|complaint form|defence and counterclaim)\b"
            # a document headed simply "DEFENCE" or "REPLY"
            r"|^\s*(?:\d+\s+)?(?:(?:re-?)?amended\s+)?(?:defence|defense|reply|rejoinder)"
            r"(?:\s+and\s+counterclaim)?\s*$",
            re.I | re.M,
        ),
    ),
    (
        DocumentType.SUBMISSION,
        re.compile(
            r"\b(written submissions?|skeleton argument|outline submissions?|memorial|"
            r"counter-memorial|closing submissions?|legal submissions?|position paper)\b",
            re.I,
        ),
    ),
    (
        DocumentType.CONTRACT,
        re.compile(
            r"\b(this agreement is made|this agreement \(|agreement dated|hereinafter|"
            r"the parties (?:hereby )?agree|terms and conditions|governing law)\b",
            re.I,
        ),
    ),
    (
        DocumentType.CORRESPONDENCE,
        re.compile(
            r"(^|\b)(dear (?:sir|madam|mr|ms|mrs|dr|\w+)|yours (?:sincerely|faithfully)|kind regards|^from: )",
            re.I | re.M,
        ),
    ),
)


def classify_document(filename: str, media_type: str, head_text: str) -> DocumentType:
    """Best-effort document type from the name and opening text. A human can override it."""
    if media_type == "message/rfc822":
        return DocumentType.CORRESPONDENCE
    sample = f"{Path(filename).stem.replace('_', ' ').replace('-', ' ')}\n{head_text[:3000]}"
    for doc_type, pattern in _TYPE_RULES:
        if pattern.search(sample):
            return doc_type
    return DocumentType.OTHER


def build_chunks(matter_id: str, document_id: str, segments: Sequence[Segment]) -> list[Chunk]:
    """One passage per paragraph, so a finding's locator is the paragraph it came from.

    Passage text is the source text with whitespace collapsed, so any sentence quoted from a
    passage can be found again in it. Only a paragraph too long to handle is split, and its
    parts keep the paragraph's locator.
    """
    chunks: list[Chunk] = []
    for segment in segments:
        pieces = _split_long(segment) if len(segment.text) > MAX_CHARS else [segment]
        for piece in pieces:
            chunks.append(
                Chunk(
                    matter_id=matter_id,
                    document_id=document_id,
                    ordinal=len(chunks),
                    locator=piece.locator,
                    text=piece.text,
                    text_hash=hashlib.sha256(piece.text.encode("utf-8")).hexdigest(),
                )
            )
    return chunks


def _split_long(segment: Segment) -> list[Segment]:
    parts: list[Segment] = []
    current = ""
    for sentence in split_sentences(segment.text):
        if current and len(current) + len(sentence) > TARGET_CHARS:
            parts.append(Segment(segment.locator, current.strip()))
            current = ""
        current = f"{current} {sentence}" if current else sentence
        while len(current) > MAX_CHARS:  # a single run-on sentence
            parts.append(Segment(segment.locator, current[:MAX_CHARS]))
            current = current[MAX_CHARS:]
    if current.strip():
        parts.append(Segment(segment.locator, current.strip()))
    return parts
