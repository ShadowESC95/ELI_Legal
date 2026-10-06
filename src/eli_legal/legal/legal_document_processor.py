from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProcessedDocument:
    document_id: str
    matter_id: str
    text_ref: str
    page_count: int | None = None
    metadata: dict = field(default_factory=dict)


class LegalDocumentProcessor:
    """Format/OCR/structure processing boundary. Preserve original document and page/section locators."""

    def process(self, *, matter_id: str, document_id: str) -> ProcessedDocument:
        raise NotImplementedError("connect to an approved document-processing adapter")
