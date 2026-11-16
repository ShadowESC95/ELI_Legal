"""Document parsers.

Each parser returns ordered segments with a locator a human can use to find the passage in the
original (page and paragraph where the format has pages, paragraph otherwise). A file that cannot
be read as text is reported as unsupported; it is never decoded into guesswork.
"""

from __future__ import annotations

import email
import email.policy
import io
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from eli_legal.domain.errors import IngestionError, UnsupportedDocument

MAX_FILE_BYTES = 250 * 1024 * 1024
MAX_UNZIPPED_BYTES = 400 * 1024 * 1024
_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".text"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp", ".heic"}


@dataclass(frozen=True, slots=True)
class Segment:
    locator: str
    text: str


@dataclass(frozen=True, slots=True)
class PdfPage:
    """What one page of a PDF holds: how much text its text layer gave, and how many images."""

    number: int
    chars: int
    images: int


# Fewer characters than this on a page and its text layer did not carry the page: a scan, a
# photographed exhibit, or a page drawn as shapes. It is read by OCR, or reported unread.
MIN_PAGE_CHARS = 20


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    media_type: str
    segments: tuple[Segment, ...]
    title: str = ""
    notes: tuple[str, ...] = ()  # things a reviewer should know, e.g. unprocessed attachments
    pages: tuple[PdfPage, ...] = ()  # a PDF's pages, every one accounted for

    @property
    def image_pages(self) -> list[int]:
        """Pages with an image and no usable text: a scan or a photographed exhibit."""
        return [p.number for p in self.pages if p.chars < MIN_PAGE_CHARS and p.images]

    @property
    def blank_pages(self) -> list[int]:
        """Pages with neither usable text nor an image: blank, or drawn as shapes."""
        return [p.number for p in self.pages if p.chars < MIN_PAGE_CHARS and not p.images]

    @property
    def pictured_pages(self) -> list[int]:
        """Pages with text and also images, whose content is not read."""
        return [p.number for p in self.pages if p.chars >= MIN_PAGE_CHARS and p.images]

    @property
    def char_count(self) -> int:
        return sum(len(s.text) for s in self.segments)


def _paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    out = [" ".join(b.split()) for b in blocks]
    return [b for b in out if b]


def _segments_from_paragraphs(paragraphs: list[str], prefix: str = "") -> list[Segment]:
    return [Segment(f"{prefix}¶{i}", p) for i, p in enumerate(paragraphs, start=1)]


# ── plain text ───────────────────────────────────────────────────────────────
def _parse_text(raw: bytes, suffix: str) -> ParsedDocument:
    if b"\x00" in raw[:8192]:
        raise UnsupportedDocument(f"{suffix or 'file'} looks binary, not text")
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - cp1252 decodes any byte string
        raise UnsupportedDocument("could not decode text")
    return ParsedDocument("text/plain", tuple(_segments_from_paragraphs(_paragraphs(text))))


# ── html ─────────────────────────────────────────────────────────────────────
class _HtmlText(HTMLParser):
    _SKIP = {"script", "style", "head", "noscript", "template"}
    _BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "td"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BREAK:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BREAK:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data.strip()
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(markup: str) -> tuple[str, str]:
    parser = _HtmlText()
    parser.feed(markup)
    return "".join(parser.parts), parser.title


def _parse_html(raw: bytes) -> ParsedDocument:
    text, title = html_to_text(raw.decode("utf-8", errors="replace"))
    return ParsedDocument("text/html", tuple(_segments_from_paragraphs(_paragraphs(text))), title)


# ── e-mail ───────────────────────────────────────────────────────────────────
def _parse_eml(raw: bytes) -> ParsedDocument:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    headers = [
        f"{name}: {msg[name]}" for name in ("From", "To", "Cc", "Date", "Subject") if msg[name]
    ]
    segments = [Segment("headers", " | ".join(headers))] if headers else []
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            content, _ = html_to_text(content)
        segments.extend(_segments_from_paragraphs(_paragraphs(content), "body "))
    attachments = [part.get_filename() or "unnamed" for part in msg.iter_attachments()]
    notes = (
        (f"{len(attachments)} attachment(s) not processed: ingest them as separate documents",)
        if attachments
        else ()
    )
    return ParsedDocument("message/rfc822", tuple(segments), str(msg["Subject"] or ""), notes)


# ── zip-based office formats ─────────────────────────────────────────────────
def _zip_member(raw: bytes, member: str) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            total = sum(info.file_size for info in archive.infolist())
            if total > MAX_UNZIPPED_BYTES:
                raise IngestionError("archive expands beyond the permitted size")
            return archive.read(member)
    except (zipfile.BadZipFile, KeyError) as exc:
        raise UnsupportedDocument(f"not a readable document container: {exc}") from exc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_docx(raw: bytes) -> ParsedDocument:
    root = ElementTree.fromstring(_zip_member(raw, "word/document.xml"))
    paragraphs: list[str] = []
    for node in root.iter():
        if _local(node.tag) != "p":
            continue
        parts: list[str] = []
        for child in node.iter():
            name = _local(child.tag)
            if name == "t" and child.text:
                parts.append(child.text)
            elif name in {"tab", "br", "cr"}:
                parts.append(" ")
        text = " ".join("".join(parts).split())
        if text:
            paragraphs.append(text)
    return ParsedDocument(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        tuple(_segments_from_paragraphs(paragraphs)),
    )


def _odt_text(node: ElementTree.Element) -> str:
    parts: list[str] = [node.text or ""]
    for child in node:
        name = _local(child.tag)
        if name in {"s", "tab", "line-break"}:
            parts.append(" ")
        elif name not in {"note", "annotation"}:
            parts.append(_odt_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _parse_odt(raw: bytes) -> ParsedDocument:
    root = ElementTree.fromstring(_zip_member(raw, "content.xml"))
    paragraphs: list[str] = []
    for node in root.iter():
        if _local(node.tag) in {"p", "h"}:
            text = " ".join(_odt_text(node).split())
            if text:
                paragraphs.append(text)
    return ParsedDocument(
        "application/vnd.oasis.opendocument.text", tuple(_segments_from_paragraphs(paragraphs))
    )


# ── pdf ──────────────────────────────────────────────────────────────────────
def _parse_pdf(raw: bytes) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - pypdf is a declared dependency
        raise UnsupportedDocument("PDF support requires the 'pypdf' package") from exc
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise UnsupportedDocument("PDF is encrypted; supply an unlocked copy")
        pages = [(page.extract_text() or "") for page in reader.pages]
        images = [_image_count(page) for page in reader.pages]
    except UnsupportedDocument:
        raise
    except Exception as exc:
        raise IngestionError(f"PDF could not be read: {type(exc).__name__}") from exc
    segments: list[Segment] = []
    accounted: list[PdfPage] = []
    for number, (text, count) in enumerate(zip(pages, images, strict=True), start=1):
        found = _segments_from_paragraphs(_pdf_paragraphs(text), f"p.{number} ")
        chars = sum(len(s.text) for s in found)
        accounted.append(PdfPage(number, chars, count))
        if chars >= MIN_PAGE_CHARS:
            segments.extend(found)
    # A page without a usable text layer is never silently dropped: the document carries a
    # record of every page, and ingestion reads the image pages by OCR or reports them unread.
    try:
        metadata = reader.metadata
        title = str(metadata.title or "") if metadata is not None else ""
    except Exception:  # metadata is optional and frequently malformed
        title = ""
    return ParsedDocument("application/pdf", tuple(segments), title, pages=tuple(accounted))


def _image_count(page: object) -> int:
    """Images drawn on a page, directly or inside a form it draws; no image is decoded."""
    seen: set[int] = set()

    def count(resources: object, depth: int) -> int:
        try:
            xobjects = resources.get("/XObject") if resources is not None else None  # type: ignore[attr-defined]
            xobjects = xobjects.get_object() if xobjects is not None else None
        except Exception:
            return 0
        if not xobjects or depth > 3:
            return 0
        total = 0
        for ref in xobjects.values():
            try:
                obj = ref.get_object()
            except Exception:
                continue
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            kind = obj.get("/Subtype")
            if kind == "/Image":
                total += 1
            elif kind == "/Form":
                total += count(obj.get("/Resources"), depth + 1)
        return total

    try:
        return count(page.get("/Resources"), 0)  # type: ignore[attr-defined]
    except Exception:
        return 0


def _pdf_paragraphs(text: str) -> list[str]:
    paragraphs = _paragraphs(text)
    if len(paragraphs) > 1:
        return paragraphs
    # Many PDFs give one line per visual line and no blank lines. Rebuild paragraphs from lines
    # that end a sentence.
    out: list[str] = []
    current: list[str] = []
    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        current.append(line)
        if line.endswith((".", ":", ";", "?", "!")) and sum(len(c) for c in current) > 200:
            out.append(" ".join(current))
            current = []
    if current:
        out.append(" ".join(current))
    return out


# ── rtf ──────────────────────────────────────────────────────────────────────
_RTF_GROUP_SKIP = re.compile(
    r"\{\\(?:fonttbl|colortbl|stylesheet|info|pict|\*)[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
)
_RTF_PAR = re.compile(r"\\par[d]?\b ?")
_RTF_HEX = re.compile(r"\\'([0-9a-fA-F]{2})")
_RTF_UNI = re.compile(r"\\u(-?\d+)\??")
_RTF_CTRL = re.compile(r"\\[a-zA-Z]+-?\d* ?|\\[^a-zA-Z]|[{}]")


def _parse_rtf(raw: bytes) -> ParsedDocument:
    text = raw.decode("cp1252", errors="replace")
    text = _RTF_GROUP_SKIP.sub("", text)
    text = _RTF_PAR.sub("\n\n", text)
    text = _RTF_HEX.sub(lambda m: bytes.fromhex(m.group(1)).decode("cp1252", "replace"), text)
    text = _RTF_UNI.sub(lambda m: chr(int(m.group(1)) % 65536), text)
    text = _RTF_CTRL.sub("", text)
    return ParsedDocument("application/rtf", tuple(_segments_from_paragraphs(_paragraphs(text))))


def detect_media_type(filename: str, raw: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if raw.startswith(b"%PDF"):
        return "application/pdf"
    if raw.startswith(b"{\\rtf"):
        return "application/rtf"
    return {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".odt": "application/vnd.oasis.opendocument.text",
        ".eml": "message/rfc822",
        ".html": "text/html",
        ".htm": "text/html",
        ".pdf": "application/pdf",
        ".rtf": "application/rtf",
    }.get(suffix, "text/plain" if suffix in _TEXT_SUFFIXES else "application/octet-stream")


class LocalDocumentParser:
    """Parses the formats that carry legal papers in practice. No network, no external service."""

    version = "local-parsers/1"

    def parse(self, filename: str, raw: bytes, *, image_pages: bool = False) -> ParsedDocument:
        """Parse a file. ``image_pages``: a PDF whose pages are images is returned with those
        pages listed (for ingestion to read by OCR) rather than refused."""
        if len(raw) > MAX_FILE_BYTES:
            raise IngestionError("file exceeds the permitted size")
        if not raw.strip():
            raise UnsupportedDocument("file is empty")
        suffix = Path(filename).suffix.lower()
        if raw.startswith(b"%PDF") or suffix == ".pdf":
            parsed = _parse_pdf(raw)
        elif raw.startswith(b"{\\rtf") or suffix == ".rtf":
            parsed = _parse_rtf(raw)
        elif suffix == ".docx":
            parsed = _parse_docx(raw)
        elif suffix == ".odt":
            parsed = _parse_odt(raw)
        elif suffix == ".eml":
            parsed = _parse_eml(raw)
        elif suffix in {".html", ".htm"}:
            parsed = _parse_html(raw)
        elif suffix in _IMAGE_SUFFIXES:
            raise UnsupportedDocument("image file: OCR it and ingest the text or a searchable PDF")
        elif suffix in {".doc", ".msg", ".xls", ".xlsx", ".ppt", ".pptx", ".zip"}:
            raise UnsupportedDocument(f"{suffix} is not supported; convert to PDF or DOCX")
        elif suffix in _TEXT_SUFFIXES or suffix == "":
            parsed = _parse_text(raw, suffix)
        else:
            parsed = _parse_text(raw, suffix)
        if not parsed.segments and not (image_pages and parsed.image_pages):
            if parsed.pages:
                raise UnsupportedDocument(
                    "PDF has no usable text layer (its pages are images or drawn as shapes, "
                    "likely a scan); OCR it and ingest the result"
                )
            raise UnsupportedDocument("no text could be extracted")
        return parsed
