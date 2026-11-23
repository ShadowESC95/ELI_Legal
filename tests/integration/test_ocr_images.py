"""An image file (a photographed exhibit, a scan saved as PNG, JPEG or TIFF) is read by OCR on
this machine and marked as such, or reported unread and held; it is never guessed or dropped."""

from __future__ import annotations

from pathlib import Path

import pytest

from eli_legal.adapters.local.ocr import TesseractOcr
from eli_legal.adapters.local.parsers import LocalDocumentParser, detect_media_type
from eli_legal.application.ingestion_service import IMAGE_READER_VERSION
from eli_legal.domain.enums import DocumentStatus, DocumentType, HoldScope
from eli_legal.domain.errors import UnsupportedDocument
from eli_legal.domain.models import Document, Hold

A = "arb.keane"
PHOTO = Path(__file__).parents[1] / "fixtures" / "exhibit_photo.png"
HAVE_TESSERACT = TesseractOcr.find("auto").can_read_images


def _add(sv, mid, name="exhibit_c7_photo.png", raw=None):
    matter = sv.matters.get(mid, A)
    document = sv.ingestion.register(
        matter=matter, actor_id=A, filename=name, raw=raw or PHOTO.read_bytes(),
        doc_type=DocumentType.EXHIBIT,
    )  # fmt: skip
    return sv.ingestion.process(document, actor_id=A, type_given=True)


def _holds(sv, mid, rid, document_id):
    return {h.reason_code: h for h in sv.ctx.store.list(Hold, mid, run_id=rid)
            if h.scope is HoldScope.DOCUMENT and h.subject_id == document_id}  # fmt: skip


def test_an_image_is_known_by_its_bytes_and_still_refused_where_ocr_is_not_asked_for():
    raw = PHOTO.read_bytes()
    assert detect_media_type("photo.png", raw) == "image/png"
    assert detect_media_type("scan.bin", raw) == "image/png", "its bytes, not its name"
    with pytest.raises(UnsupportedDocument, match="image file"):
        LocalDocumentParser().parse("photo.png", raw)
    parsed = LocalDocumentParser().parse("photo.png", raw, image_pages=True)
    assert parsed.media_type == "image/png" and parsed.segments == ()


def test_a_text_file_that_happens_to_start_like_an_image_stays_text():
    raw = b"BM Holdings v Carter: notes of the hearing on 3 May 2023, taken by the secretary."
    parsed = LocalDocumentParser().parse("notes.txt", raw, image_pages=True)
    assert parsed.segments and "BM Holdings" in parsed.segments[0].text


def test_without_ocr_an_image_is_reported_unread_and_holds_the_run(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr(None, None)
    document = _add(sv, mid)
    assert document.status is DocumentStatus.UNSUPPORTED
    assert "Tesseract is not installed" in document.error
    run = sv.runs.start(mid, actor_id=A)
    assert "coverage_gap" in _holds(sv, mid, run.run_id, document.document_id)


@pytest.mark.skipif(not HAVE_TESSERACT, reason="Tesseract is not installed here")
def test_an_image_is_read_by_ocr_marked_as_such_and_relied_on_only_with_its_confidence(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr.find("auto")
    document = _add(sv, mid)
    assert document.status is DocumentStatus.PROCESSED, document.error
    assert document.media_type == "image/png" and document.read_with == IMAGE_READER_VERSION
    assert set(document.ocr_pages) == {"1"} and document.ocr_pages["1"] >= 80
    assert document.ocr_engine.startswith("tesseract")
    read = [c for c in sv.ctx.store.chunks_for(mid) if c.document_id == document.document_id]
    assert read and all(c.locator.startswith("p.1 (OCR)") for c in read)
    text = " ".join(c.text for c in read)
    assert "22 refrigerated containers" in text and "14 April 2023" in text
    run = sv.runs.start(mid, actor_id=A)
    holds = _holds(sv, mid, run.run_id, document.document_id)
    assert "coverage_gap" not in holds and "ocr_low_confidence" not in holds


@pytest.mark.skipif(not HAVE_TESSERACT, reason="Tesseract is not installed here")
def test_an_image_read_with_too_little_confidence_holds_until_checked(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr.find("auto")
    sv.ctx.settings.ocr_min_confidence = 99.9
    document = _add(sv, mid)
    run = sv.runs.start(mid, actor_id=A)
    assert "ocr_low_confidence" in _holds(sv, mid, run.run_id, document.document_id)


@pytest.mark.skipif(not HAVE_TESSERACT, reason="Tesseract is not installed here")
def test_an_image_ocr_cannot_read_is_reported_unread_not_guessed(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr.find("auto")
    document = _add(sv, mid, "broken.jpg", b"\xff\xd8\xff\xe0" + bytes(range(256)) * 4)
    assert document.status is DocumentStatus.UNSUPPORTED
    assert "could not read" in document.error


@pytest.mark.skipif(not HAVE_TESSERACT, reason="Tesseract is not installed here")
def test_an_image_left_unread_by_an_earlier_version_is_read_again_before_the_next_run(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr.find("auto")
    document = _add(sv, mid)

    def as_left_by_087(d):
        d.status, d.error, d.read_with = DocumentStatus.UNSUPPORTED, "image file", "pages/2"
        d.media_type, d.ocr_pages = "application/octet-stream", {}

    sv.ctx.store.change(Document, mid, document.document_id, as_left_by_087)
    sv.runs.start(mid, actor_id=A)
    again = sv.ctx.store.get(Document, mid, document.document_id)
    assert again.status is DocumentStatus.PROCESSED and set(again.ocr_pages) == {"1"}
    assert again.read_with == IMAGE_READER_VERSION
