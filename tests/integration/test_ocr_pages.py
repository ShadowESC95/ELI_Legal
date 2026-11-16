"""A page that is only an image is never dropped without a word (EL-017). With OCR it is read
and marked as OCR, with its confidence; without OCR, or with too little confidence, the
document holds the run until a person checks the page against the original."""

from __future__ import annotations

from pathlib import Path

import pytest

from eli_legal.adapters.local.ocr import TesseractOcr
from eli_legal.domain.enums import DocumentStatus, DocumentType, HoldScope
from eli_legal.domain.models import Document, Hold

A = "arb.keane"
EXHIBIT = Path(__file__).parents[1] / "fixtures" / "exhibit_scan.pdf"
HAVE_OCR = TesseractOcr.find("auto").available


def _add(sv, mid):
    matter = sv.matters.get(mid, A)
    document = sv.ingestion.register(
        matter=matter, actor_id=A, filename="statement_with_exhibit.pdf",
        raw=EXHIBIT.read_bytes(), doc_type=DocumentType.WITNESS_STATEMENT,
    )  # fmt: skip
    return sv.ingestion.process(document, actor_id=A, type_given=True)


def _holds(sv, mid, rid, document_id):
    return {h.reason_code: h for h in sv.ctx.store.list(Hold, mid, run_id=rid)
            if h.scope is HoldScope.DOCUMENT and h.subject_id == document_id}  # fmt: skip


def test_an_image_only_exhibit_page_is_reported_unread_and_holds_the_run(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr(None, None)  # no OCR on this machine
    document = _add(sv, mid)
    assert document.status is DocumentStatus.PROCESSED, "page 1 was read"
    assert document.unread_pages == [2] and "page(s) 2 not read" in document.error
    assert "OCR is not available" in document.error or "not installed" in document.error
    chunks = [c for c in sv.ctx.store.chunks_for(mid) if c.document_id == document.document_id]
    assert chunks and all(c.locator.startswith("p.1 ") for c in chunks)
    run = sv.runs.start(mid, actor_id=A)
    holds = _holds(sv, mid, run.run_id, document.document_id)
    assert "pages_not_read" in holds and "page(s) 2" in holds["pages_not_read"].detail
    report = sv.runs.summary(mid, run.run_id, actor_id=A)["report"]
    text = Path(report["path"]).read_text(encoding="utf-8")
    assert "page(s) 2: only an image with no text layer, not read" in text
    sv.holds.resolve(mid, holds["pages_not_read"].hold_id, actor_id=A, action="waive",
                     reason="Checked the original: page 2 is Exhibit C, the invoice, which "
                            "both parties quote in full in their pleadings.")  # fmt: skip
    assert sv.ctx.store.get(Document, mid, document.document_id).pages_checked == [2]


@pytest.mark.skipif(not HAVE_OCR, reason="Tesseract and Poppler are not installed here")
def test_an_image_only_exhibit_page_is_read_by_ocr_and_marked_as_such(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr.find("auto")
    document = _add(sv, mid)
    assert document.unread_pages == [] and set(document.ocr_pages) == {"2"}
    assert document.ocr_pages["2"] >= 80 and document.ocr_engine.startswith("tesseract")
    read = [c for c in sv.ctx.store.chunks_for(mid) if c.document_id == document.document_id
            and c.locator.startswith("p.2 (OCR)")]  # fmt: skip
    text = " ".join(c.text for c in read)
    assert "INVOICE 4471" in text and "3 March 2025" in text and "12,400" in text
    run = sv.runs.start(mid, actor_id=A)
    assert "pages_not_read" not in _holds(sv, mid, run.run_id, document.document_id)
    report = Path(sv.runs.summary(mid, run.run_id, actor_id=A)["report"]["path"])
    assert "were images read by OCR" in report.read_text(encoding="utf-8")


@pytest.mark.skipif(not HAVE_OCR, reason="Tesseract and Poppler are not installed here")
def test_a_page_read_with_too_little_confidence_holds_until_checked(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr.find("auto")
    sv.ctx.settings.ocr_min_confidence = 99.9
    document = _add(sv, mid)
    run = sv.runs.start(mid, actor_id=A)
    holds = _holds(sv, mid, run.run_id, document.document_id)
    assert "ocr_low_confidence" in holds and "page(s) 2" in holds["ocr_low_confidence"].detail
