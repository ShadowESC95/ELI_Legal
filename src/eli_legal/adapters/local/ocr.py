"""Reading a page that is only an image: OCR, on this machine.

A PDF page with no text layer (a scan, a photographed exhibit) is rendered to an image by
Poppler's ``pdftoppm`` and read by Tesseract, both run here: nothing leaves the machine. The
document is copied into a private temporary folder for the purpose and the folder is deleted
afterwards, whatever happens.

Tesseract gives a confidence for each word; a page's confidence is their mean. The text read is
marked as OCR wherever it is used, with the engine and the confidence, so that a person checks
a quotation from it against the original page. Where either program is missing, nothing is
guessed: the page is reported unread and the run holds on it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 120


@dataclass(frozen=True, slots=True)
class OcrPage:
    number: int
    paragraphs: tuple[str, ...]
    confidence: float  # 0-100, the mean of the words' confidences
    words: int


@dataclass(slots=True)
class TesseractOcr:
    tesseract: str | None
    pdftoppm: str | None
    language: str = "eng"
    dpi: int = 300

    @classmethod
    def find(cls, setting: str = "auto", language: str = "eng") -> TesseractOcr:
        """``auto``: the programs on the PATH. ``off``: none. Otherwise the path to tesseract."""
        value = (setting or "auto").strip()
        if value.lower() in ("off", "none", ""):
            return cls(None, None, language)
        tesseract = shutil.which("tesseract") if value.lower() == "auto" else value
        if tesseract and not Path(tesseract).exists() and not shutil.which(tesseract):
            tesseract = None
        return cls(tesseract, shutil.which("pdftoppm"), language)

    @property
    def available(self) -> bool:
        return bool(self.tesseract and self.pdftoppm)

    @property
    def can_read_images(self) -> bool:
        """An image file (a photograph, a scan saved as PNG, JPEG or TIFF) needs Tesseract only."""
        return bool(self.tesseract)

    @property
    def image_reason(self) -> str:
        return "" if self.can_read_images else (
            "OCR is not available here: Tesseract is not installed or switched off, so an "
            "image cannot be read"
        )  # fmt: skip

    @property
    def reason(self) -> str:
        if self.available:
            return ""
        missing = [n for n, v in (("Tesseract", self.tesseract), ("Poppler (pdftoppm)",
                                                                  self.pdftoppm)) if not v]  # fmt: skip
        return (
            "OCR is not available here: " + " and ".join(missing) + " not installed or switched "
            "off, so a page that is only an image cannot be read"
        )

    @property
    def version(self) -> str:
        if not self.tesseract:
            return "none"
        try:
            out = subprocess.run(  # noqa: S603 - a fixed program, no shell
                [self.tesseract, "--version"], capture_output=True, text=True, timeout=30,
                check=False,
            )  # fmt: skip
        except OSError:
            return "tesseract (version unknown)"
        first = (out.stdout or out.stderr).splitlines()
        return first[0].strip() if first else "tesseract"

    def read_pdf_pages(self, raw: bytes, pages: Sequence[int]) -> list[OcrPage]:
        """Read the given pages (1-based) of a PDF. A page that yields no words is returned
        with no paragraphs; the caller reports it unread."""
        if not self.available or not pages:
            return []
        out: list[OcrPage] = []
        with tempfile.TemporaryDirectory(prefix="eli-legal-ocr-") as folder:
            work = Path(folder)
            source = work / "document.pdf"
            source.write_bytes(raw)
            source.chmod(0o600)
            for number in pages:
                image = work / f"page-{number}"
                subprocess.run(  # noqa: S603 - fixed programs, no shell
                    [str(self.pdftoppm), "-f", str(number), "-l", str(number),
                     "-r", str(self.dpi), "-gray", "-png", "-singlefile", str(source), str(image)],
                    capture_output=True, timeout=TIMEOUT, check=True,
                )  # fmt: skip
                result = subprocess.run(  # noqa: S603
                    [str(self.tesseract), str(image.with_suffix(".png")), "stdout",
                     "-l", self.language, "tsv"],
                    capture_output=True, text=True, timeout=TIMEOUT, check=True,
                )  # fmt: skip
                out.append(_page_from_tsv(number, result.stdout))
        return out

    def read_image(self, raw: bytes, suffix: str) -> list[OcrPage]:
        """Read an image file: one page, or each page of a multi-page TIFF. An image Tesseract
        cannot open, or that holds no words, gives no pages; the caller reports it unread."""
        if not self.can_read_images:
            return []
        suffix = suffix if suffix.startswith(".") and len(suffix) <= 6 else ".png"
        with tempfile.TemporaryDirectory(prefix="eli-legal-ocr-") as folder:
            source = Path(folder) / f"image{suffix}"
            fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
            try:
                result = subprocess.run(  # noqa: S603 - a fixed program, no shell
                    [str(self.tesseract), str(source), "stdout", "-l", self.language, "tsv"],
                    capture_output=True, text=True, timeout=TIMEOUT, check=True,
                )  # fmt: skip
            except subprocess.CalledProcessError as exc:
                # Tesseract could not open it at all: a damaged file, or not an image.
                said = next(
                    (ln.strip() for ln in (exc.stderr or "").splitlines() if ln.strip()), ""
                )
                raise ImageNotOpened(said[:160]) from exc
            except (OSError, subprocess.SubprocessError):
                return []
        rows = result.stdout.splitlines()
        if not rows:
            return []
        header = rows[0]
        by_page: dict[int, list[str]] = {}
        for row in rows[1:]:
            cells = row.split("\t")
            if len(cells) > 1 and cells[1].isdigit():
                by_page.setdefault(int(cells[1]), []).append(row)
        pages = [
            _page_from_tsv(number, "\n".join([header, *lines]))
            for number, lines in sorted(by_page.items())
        ]
        return [p for p in pages if p.paragraphs]


class ImageNotOpened(Exception):
    """The file could not be opened as an image (damaged, or not what its name says)."""


def _page_from_tsv(number: int, tsv: str) -> OcrPage:
    """Tesseract's TSV: one row per word with its block, paragraph, line and confidence."""
    paragraphs: dict[tuple[int, int], list[list[str]]] = {}
    lines: dict[tuple[int, int, int], list[str]] = {}
    scores: list[float] = []
    for row in tsv.splitlines()[1:]:
        cells = row.split("\t")
        if len(cells) < 12 or cells[0] != "5":
            continue
        word = cells[11].strip()
        try:
            confidence = float(cells[10])
        except ValueError:
            continue
        if not word or confidence < 0:
            continue
        block, para, line = int(cells[2]), int(cells[3]), int(cells[4])
        lines.setdefault((block, para, line), []).append(word)
        scores.append(confidence)
    for (block, para, _line), words in sorted(lines.items()):
        paragraphs.setdefault((block, para), []).append(words)
    text = tuple(
        " ".join(" ".join(words) for words in line_words)
        for _key, line_words in sorted(paragraphs.items())
    )
    mean = sum(scores) / len(scores) if scores else 0.0
    return OcrPage(number, tuple(t for t in text if t.strip()), round(mean, 1), len(scores))
