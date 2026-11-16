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


def _as_read_by_083(sv, mid, document):
    """What 0.8.3 left behind: processed, page 2 silently missing, no page record."""

    def old(d):
        d.read_with, d.unread_pages, d.ocr_pages, d.blank_pages, d.pictured_pages = (
            "",
            [],
            {},
            [],
            [],
        )
        d.error = ""

    return sv.ctx.store.change(Document, mid, document.document_id, old)


def test_a_pdf_read_by_an_earlier_version_is_read_again_before_the_next_run(demo):
    """Opening a 0.8.3 database: the exhibit's page 2 must not stay silently missing."""
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr(None, None)
    document = _as_read_by_083(sv, mid, _add(sv, mid))
    assert document.status is DocumentStatus.PROCESSED and not document.unread_pages
    run = sv.runs.start(mid, actor_id=A)
    again = sv.ctx.store.get(Document, mid, document.document_id)
    assert again.read_with and again.unread_pages == [2], "read again, page 2 accounted for"
    assert "pages_not_read" in _holds(sv, mid, run.run_id, document.document_id)
    reread = [e for e in sv.ctx.audit.events(matter_id=mid) if e["event_type"] == "document_reread"]
    assert reread and reread[0]["payload"]["read_with_before"] == "unrecorded"
    assert sv.ctx.store.get(type(run), mid, run.run_id).tool_versions["document_reader"]


def test_a_report_approved_before_every_page_was_accounted_for_is_flagged(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr(None, None)
    _add(sv, mid)
    run = sv.runs.start(mid, actor_id=A)

    def approved_by_083(r):
        r.status = type(r.status).APPROVED_FOR_RELIANCE
        r.tool_versions.pop("document_reader", None)

    sv.ctx.store.change(type(run), mid, run.run_id, approved_by_083)
    open_work = {r.check_id: r for r in sv.checks.run().results}["open_work"]
    assert any("read by an earlier version of the reader" in i.text for i in open_work.items)


@pytest.mark.skipif(not HAVE_OCR, reason="Tesseract and Poppler are not installed here")
def test_once_ocr_is_installed_a_document_is_read_again_from_its_original(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr(None, None)
    document = _add(sv, mid)
    assert document.unread_pages == [2]
    sv.ctx.ocr = TesseractOcr.find("auto")
    again = sv.ingestion.reread(mid, document.document_id, actor_id=A, why="OCR installed")
    assert again.unread_pages == [] and set(again.ocr_pages) == {"2"}


BESIDE = Path(__file__).parents[1] / "fixtures" / "exhibit_beside_caption.pdf"


def _add_beside(sv, mid):
    matter = sv.matters.get(mid, A)
    document = sv.ingestion.register(
        matter=matter, actor_id=A, filename="exhibit_c_with_caption.pdf",
        raw=BESIDE.read_bytes(), doc_type=DocumentType.CORRESPONDENCE,
    )  # fmt: skip
    return sv.ingestion.process(document, actor_id=A, type_given=True)


@pytest.mark.skipif(not HAVE_OCR, reason="Tesseract and Poppler are not installed here")
def test_an_invoice_pasted_under_its_caption_is_read_and_marked_as_from_the_image(demo):
    sv, mid = demo
    sv.ctx.ocr = TesseractOcr.find("auto")
    document = _add_beside(sv, mid)
    assert set(document.ocr_pages) == {"1"} and document.pictured_pages == []
    chunks = [c for c in sv.ctx.store.chunks_for(mid) if c.document_id == document.document_id]
    caption = [c for c in chunks if "(OCR" not in c.locator]
    image = " ".join(c.text for c in chunks if c.locator.startswith("p.1 (OCR, image)"))
    assert caption and "Exhibit C: the invoice" in caption[0].text
    assert "INVOICE 4471" in image and "12,400" in image
    assert "Exhibit C: the invoice" not in image, "the caption is not read twice"


def test_without_ocr_an_image_beside_text_is_a_review_task_on_a_real_matter(demo, monkeypatch):
    from tests.governance.test_deployment_gate import _authorise, _validated

    sv, mid = demo
    sv.ctx.ocr = TesseractOcr(None, None)
    practice = _add_beside(sv, mid)
    assert practice.pictured_pages == [1]
    run = sv.runs.start(mid, actor_id=A)
    assert "image_text_unread" not in _holds(sv, mid, run.run_id, practice.document_id), (
        "a practice matter lists it in the report"
    )
    demo_matter = sv.matters.get(mid, A)
    matter = sv.matters.create(
        actor_id=A, name="Real v Matter", purpose="Bench memorandum for the tribunal",
        jurisdiction="XX", profile=demo_matter.profile, real=True, reviewers=[A],
        sources=sorted(demo_matter.approved_source_ids),
    )  # fmt: skip
    _authorise(sv)
    _validated(monkeypatch)
    document = _add_beside(sv, matter.matter_id)
    real_run = sv.runs.start(matter.matter_id, actor_id=A)
    holds = _holds(sv, matter.matter_id, real_run.run_id, document.document_id)
    assert "image_text_unread" in holds and "page(s) 1" in holds["image_text_unread"].detail
