"""Fact extraction.

Every fact is a sentence taken word for word from a document, with its locator. The system never
rephrases evidence, so a reader can always check a fact against the page it came from. Selection
is rule-based (dated or monetary statements) and, where a model is configured, widened by letting
the model pick further sentences by number; it cannot supply wording of its own.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from eli_legal.domain.models import Chunk, Document
from eli_legal.legal.dates import find_dates, split_sentences
from eli_legal.legal.llm import (
    MAX_ITEM_CHARS,
    PROMPT_VERSIONS,
    STEP_TEXT_CHARS,
    LegalModel,
    declare_step,
    fenced,
    numbered,
)

_MONEY = re.compile(
    r"(?:[€£$¥]\s?\d[\d,.]*\d|\b\d[\d,.]*\d\s?(?:EUR|GBP|USD|CHF|euro|euros|pounds|dollars)\b)",
    re.I,
)
_MIN_WORDS = 6
_MAX_CHARS = MAX_ITEM_CHARS
_BATCH_CHARS = 2400
_REPLY_TOKENS = 300
declare_step(
    "fact_select", chars=_BATCH_CHARS + _MAX_CHARS + STEP_TEXT_CHARS, reply_tokens=_REPLY_TOKENS
)


@dataclass(frozen=True, slots=True)
class FactCandidate:
    text: str  # verbatim sentence
    chunk_id: str
    document_id: str
    locator: str
    event_date: date | None
    date_text: str
    date_ambiguous: bool
    party_id: str | None
    origin: str


def _eligible(sentence: str) -> bool:
    return len(sentence.split()) >= _MIN_WORDS and len(sentence) <= _MAX_CHARS


class FactExtractor:
    def __init__(self, model: LegalModel | None = None, *, max_model_chunks: int = 200) -> None:
        self.model = model or LegalModel(None)
        self.max_model_chunks = max_model_chunks
        self.model_chunks_used = 0

    def extract(
        self,
        *,
        documents: Sequence[Document],
        chunks: Sequence[Chunk],
        date_order: str = "dmy",
        model_excluded_document_ids: frozenset[str] = frozenset(),
    ) -> list[FactCandidate]:
        by_doc = {d.document_id: d for d in documents}
        # (chunk, sentence) pairs in reading order, with how each came to be selected.
        sentences: list[tuple[Chunk, str]] = []
        selected: dict[int, str] = {}
        for chunk in chunks:
            if chunk.document_id not in by_doc:
                continue
            for sentence in split_sentences(chunk.text.replace("\n", " ")):
                if not _eligible(sentence):
                    continue
                if find_dates(sentence, date_order=date_order) or _MONEY.search(sentence):
                    selected[len(sentences)] = "rule:dated_or_monetary"
                sentences.append((chunk, sentence))
        if self.model.available:
            for index in self._model_select(sentences, by_doc, model_excluded_document_ids):
                selected.setdefault(index, f"model:{self.model.model_id}")
        out: dict[tuple[str, str], FactCandidate] = {}
        for index, origin in sorted(selected.items()):
            chunk, sentence = sentences[index]
            mentions = find_dates(sentence, date_order=date_order)
            out.setdefault(
                (chunk.document_id, " ".join(sentence.split())),
                FactCandidate(
                    text=sentence,
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    locator=chunk.locator,
                    event_date=mentions[0].value if mentions else None,
                    date_text=mentions[0].text if mentions else "",
                    date_ambiguous=bool(mentions and mentions[0].ambiguous),
                    party_id=by_doc[chunk.document_id].party_id,
                    origin=origin,
                ),
            )
        return list(out.values())

    def _model_select(
        self,
        sentences: list[tuple[Chunk, str]],
        by_doc: dict[str, Document],
        excluded: frozenset[str],
    ) -> list[int]:
        """Let the model pick further sentences by number, a batch of paragraphs at a time."""
        picked: list[int] = []
        batch: list[int] = []
        size = 0

        def flush() -> None:
            nonlocal batch, size
            if not batch or self.model_chunks_used >= self.max_model_chunks:
                batch, size = [], 0
                return
            self.model_chunks_used += 1
            document = by_doc[sentences[batch[0]][0].document_id]
            prompt = (
                f"Task {PROMPT_VERSIONS['fact_select']}. The numbered sentences below come "
                f"from a {document.doc_type.value.replace('_', ' ')} in a legal dispute. Select "
                "the sentences that state a fact that could matter to the dispute: an event, a "
                "payment, a communication, an obligation, an admission or a denial. Ignore "
                "headings, formalities and argument about the law. "
                'Reply as {"selected": [numbers]}. Select nothing if none qualify.\n'
                + fenced(numbered([sentences[i][1] for i in batch], "S"), document.document_id)
            )
            answer = self.model.ask("fact_select", prompt, max_tokens=_REPLY_TOKENS)
            items = answer.get("selected") if answer else None
            for item in items if isinstance(items, list) else []:
                try:
                    number = int(str(item).lstrip("Ss"))
                except ValueError:
                    self.model.stats.rejected_items += 1
                    continue
                if 1 <= number <= len(batch):
                    picked.append(batch[number - 1])
                else:
                    self.model.stats.rejected_items += 1
            batch, size = [], 0

        current_doc = ""
        for index, (chunk, sentence) in enumerate(sentences):
            if chunk.document_id in excluded:
                continue
            if chunk.document_id != current_doc or size + len(sentence) > _BATCH_CHARS:
                flush()
                current_doc = chunk.document_id
            batch.append(index)
            size += len(sentence)
        flush()
        return picked
