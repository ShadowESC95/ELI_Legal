from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from eli_legal.adapters.local.parsers import ParsedDocument, Segment, detect_media_type
from eli_legal.application.container import AppContext
from eli_legal.domain.enums import AccessScope, DocumentStatus, DocumentType
from eli_legal.domain.errors import IngestionError, InvalidState, UnsupportedDocument
from eli_legal.domain.models import Document, Matter
from eli_legal.legal.dates import find_dates
from eli_legal.legal.legal_document_processor import build_chunks, classify_document

# The reader's version. "pages/1": every page of a PDF is accounted for, image pages read by OCR
# or reported unread (0.8.4). A PDF read by anything earlier may have lost a page silently.
READER_VERSION = "pages/2"
# "pages/2": images beside a page's text are read too, where OCR is available (0.8.6).
IMAGE_TEXT_WORDS = 12
_PAGED = ("application/pdf",)


def _words(text: str) -> set[str]:
    return {w.strip(".,:;()-–—").lower() for w in text.split() if w.strip(".,:;()-–—")}


# Image files (a photograph, a scan saved as PNG, JPEG or TIFF) are read by OCR from "images/1".
# Before that they were refused unread, so one left unread by an earlier reader is read again.
IMAGE_READER_VERSION = "images/1"
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp")


def is_image_file(document: Document) -> bool:
    return document.media_type.startswith("image/") or (
        Path(document.filename).suffix.lower() in _IMAGE_SUFFIXES
    )


def read_by_older_reader(document: Document) -> bool:
    """A PDF last read before every page was accounted for, or an image file left unread before
    images were read by OCR; never a gap a person accepted."""
    if document.status in (DocumentStatus.WAIVED, DocumentStatus.REGISTERED):
        return False
    if document.media_type in _PAGED:
        return document.read_with != READER_VERSION
    if is_image_file(document):
        return (
            document.status is DocumentStatus.UNSUPPORTED
            and document.read_with != IMAGE_READER_VERSION
        )
    return False


@dataclass(slots=True)
class IngestionService:
    """Takes documents into a matter: store the original untouched, then read it into passages."""

    ctx: AppContext

    def register(
        self,
        *,
        matter: Matter,
        actor_id: str,
        filename: str,
        raw: bytes,
        doc_type: DocumentType | None = None,
        party_id: str | None = None,
        access_scope: AccessScope = AccessScope.ALL_PARTIES,
        custodian: str = "",
        title: str = "",
        document_date: date | None = None,
    ) -> Document:
        self.ctx.authorizer().require_matter(matter, actor_id, "document.ingest")
        if party_id and party_id not in {p.party_id for p in matter.parties}:
            raise InvalidState(f"party {party_id} is not a party to this matter")
        sha256, vault_ref = self.ctx.vault.store(matter.matter_id, raw)
        for existing in self.ctx.store.list(Document, matter.matter_id):
            if existing.sha256 == sha256:
                return existing  # the same bytes are one piece of evidence, however often filed
        document = Document(
            matter_id=matter.matter_id,
            filename=Path(filename).name,
            sha256=sha256,
            size_bytes=len(raw),
            media_type=detect_media_type(filename, raw),
            ingested_by=actor_id,
            doc_type=doc_type or DocumentType.OTHER,
            access_scope=access_scope,
            party_id=party_id,
            custodian=custodian,
            title=title,
            document_date=document_date,
            vault_ref=vault_ref,
        )
        self.ctx.store.put(document)
        self.ctx.log(
            "document_registered",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            action="document.ingest",
            subject_id=document.document_id,
            outcome="registered",
            object_type="document",
            input_hash=sha256,
            payload={
                "size_bytes": len(raw),
                "media_type": document.media_type,
                "access_scope": access_scope.value,
                "type_given": doc_type.value if doc_type else None,
            },
        )
        return document

    def process(self, document: Document, *, actor_id: str, type_given: bool = False) -> Document:
        """Parse, classify, scan and index one registered document. Idempotent."""
        raw = self.ctx.vault.read(document.matter_id, document.sha256)
        document.read_with = IMAGE_READER_VERSION if is_image_file(document) else READER_VERSION
        try:
            parsed = self.ctx.parser.parse(document.filename, raw, image_pages=True)
            parsed = self._read_images(document, raw, parsed)
        except UnsupportedDocument as exc:
            document.status, document.error = DocumentStatus.UNSUPPORTED, str(exc)[:240]
            parsed = None
        except IngestionError as exc:
            document.status, document.error = DocumentStatus.FAILED, str(exc)[:240]
            parsed = None
        if parsed is not None:
            full_text = "\n".join(s.text for s in parsed.segments)
            chunks = build_chunks(document.matter_id, document.document_id, parsed.segments)
            self.ctx.store.replace_chunks(document.matter_id, document.document_id, chunks)
            document.status = DocumentStatus.PROCESSED
            document.error = "; ".join(parsed.notes)[:240]
            document.segment_count = len(parsed.segments)
            document.char_count = parsed.char_count
            document.title = document.title or parsed.title
            if not type_given and document.doc_type is DocumentType.OTHER:
                document.doc_type = classify_document(
                    document.filename, document.media_type, full_text
                )
            if document.document_date is None:
                mentions = find_dates(full_text[:1500])
                document.document_date = mentions[0].value if mentions else None
            document.injection_flags = list(self.ctx.detector.assess(full_text).reasons)
        if document.status is DocumentStatus.PROCESSED and document.unread_pages:
            pages = ", ".join(str(n) for n in document.unread_pages)
            document.error = (
                f"page(s) {pages} not read: an image with no text layer"
                + (f" ({self.ctx.ocr.reason})" if not self.ctx.ocr.available else
                   " that OCR could not read")
                + (f"; {document.error}" if document.error else "")
            )[:240]  # fmt: skip
        self.ctx.store.put(document)
        self.ctx.log(
            "document_processed",
            actor_id=actor_id,
            matter_id=document.matter_id,
            action="document.ingest",
            subject_id=document.document_id,
            outcome=document.status.value,
            object_type="document",
            tool_id=self.ctx.parser.version,
            input_hash=document.sha256,
            payload={
                "segments": document.segment_count,
                "doc_type": document.doc_type.value,
                "injection_flags": document.injection_flags,
                "ocr_pages": sorted(document.ocr_pages, key=int),
                "unread_pages": document.unread_pages,
                "ocr_engine": document.ocr_engine,
            },
        )
        return document

    def reread(self, matter_id: str, document_id: str, *, actor_id: str, why: str) -> Document:
        """Read a document again from its stored original: after an upgrade of the reader, or
        once OCR is installed. Its text and indexes are replaced; earlier runs keep theirs."""
        matter = self.ctx.matter_for(matter_id, actor_id, "document.ingest")
        document = self.ctx.store.require(Document, matter.matter_id, document_id)
        if document.status is DocumentStatus.WAIVED:
            raise InvalidState(
                "a person accepted this document as not read or took it out of the analysis; "
                "add it again to read it"
            )
        self.ctx.log(
            "document_reread",
            actor_id=actor_id,
            matter_id=matter.matter_id,
            action="document.ingest",
            subject_id=document_id,
            outcome="reread",
            object_type="document",
            input_hash=document.sha256,
            payload={"why": why[:120], "read_with_before": document.read_with or "unrecorded"},
        )
        return self.process(document, actor_id=actor_id, type_given=True)

    def _read_images(
        self, document: Document, raw: bytes, parsed: ParsedDocument
    ) -> ParsedDocument:
        """Read a PDF's image pages by OCR where it is available, and account for every page:
        what OCR read (with its confidence), what stayed unread, what is blank, and where
        images beside the text were not read. Nothing is dropped without a record."""
        document.ocr_pages, document.ocr_engine = {}, ""
        document.unread_pages = []
        document.blank_pages = list(parsed.blank_pages)
        document.pictured_pages = list(parsed.pictured_pages)
        if parsed.media_type.startswith("image/"):
            return self._read_image_file(document, raw, parsed)
        wanted = parsed.image_pages
        pictured = parsed.pictured_pages
        ocr = self.ctx.ocr
        if not wanted and not (pictured and ocr.available):
            return parsed
        by_page: dict[int, list[Segment]] = {}
        for segment in parsed.segments:
            number = int(segment.locator.split()[0][2:]) if segment.locator.startswith("p.") else 0
            by_page.setdefault(number, []).append(segment)
        read: dict[int, list[Segment]] = {}
        if ocr.available:
            document.ocr_engine = ocr.version
            for page in ocr.read_pdf_pages(raw, wanted):
                if page.paragraphs and page.words >= 3:
                    document.ocr_pages[str(page.number)] = page.confidence
                    read[page.number] = [
                        Segment(f"p.{page.number} (OCR) ¶{i}", text)
                        for i, text in enumerate(page.paragraphs, start=1)
                    ]
            # A page with text and an image: the image may be an exhibit (an invoice pasted
            # under its caption). The page is read whole, and what the text layer lacks is
            # added, marked as read from the image; a logo or a signature adds nothing.
            for page in ocr.read_pdf_pages(raw, pictured):
                layer = _words(" ".join(s.text for s in by_page.get(page.number, [])))
                # A paragraph the text layer already holds (most of its words there) is not
                # read twice; anything else on the page came from the image.
                extra = [
                    t for t in page.paragraphs
                    if len(_words(t) & layer) < 0.8 * max(1, len(_words(t)))
                ]  # fmt: skip
                if sum(len(t.split()) for t in extra) >= IMAGE_TEXT_WORDS:
                    document.ocr_pages[str(page.number)] = page.confidence
                    document.pictured_pages.remove(page.number)
                    read[page.number] = by_page.get(page.number, []) + [
                        Segment(f"p.{page.number} (OCR, image) ¶{i}", text)
                        for i, text in enumerate(extra, start=1)
                    ]
        document.unread_pages = [n for n in wanted if n not in read]
        if not read:
            if not parsed.segments:
                raise UnsupportedDocument(
                    "every page is an image with no text layer, and "
                    + (ocr.reason.split(": ", 1)[-1] if not ocr.available else "OCR read none")
                )
            return parsed
        # Keep the pages in order: the text layer's pages and OCR's in one sequence.
        by_page.update(read)
        ordered = tuple(s for n in sorted(by_page) for s in by_page[n])
        return replace(parsed, segments=ordered)

    def _read_image_file(
        self, document: Document, raw: bytes, parsed: ParsedDocument
    ) -> ParsedDocument:
        """An image file (a photographed exhibit, a scan saved as an image) is read by OCR on
        this machine, page by page for a multi-page TIFF, each passage marked (OCR) with the
        page's confidence. An image OCR cannot read, or reads too little of, is reported unread
        and holds the run like any other unread document; nothing is guessed."""
        ocr = self.ctx.ocr
        if not ocr.can_read_images:
            raise UnsupportedDocument("image file, and " + ocr.image_reason.split(": ", 1)[-1])
        document.ocr_engine = ocr.version
        segments: list[Segment] = []
        for page in ocr.read_image(raw, Path(document.filename).suffix.lower()):
            if page.words < 3:
                continue
            document.ocr_pages[str(page.number)] = page.confidence
            segments.extend(
                Segment(f"p.{page.number} (OCR) ¶{i}", text)
                for i, text in enumerate(page.paragraphs, start=1)
            )
        if not segments:
            document.unread_pages = [1]
            raise UnsupportedDocument("image file that OCR could not read: no text found in it")
        return replace(parsed, segments=tuple(segments))

    def ingest_path(
        self,
        *,
        matter: Matter,
        actor_id: str,
        path: str | Path,
        doc_type: DocumentType | None = None,
        party_id: str | None = None,
        access_scope: AccessScope = AccessScope.ALL_PARTIES,
        custodian: str = "",
    ) -> list[Document]:
        """Ingest a file, or every file under a directory."""
        root = Path(path).expanduser()
        files = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]
        out: list[Document] = []
        for file in files:
            if file.name.startswith("."):
                continue
            document = self.register(
                matter=matter,
                actor_id=actor_id,
                filename=file.name,
                raw=file.read_bytes(),
                doc_type=doc_type,
                party_id=party_id,
                access_scope=access_scope,
                custodian=custodian,
            )
            if document.status is DocumentStatus.REGISTERED:
                document = self.process(
                    document, actor_id=actor_id, type_given=doc_type is not None
                )
            out.append(document)
        return out
