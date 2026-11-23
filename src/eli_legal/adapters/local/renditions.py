"""An approved report, as a Word document or a PDF, for the person who collects it.

The authoritative text is the Markdown report whose SHA-256 the reviewer approved; a Word or
PDF copy is a rendition of it, made at the moment it is collected, and says so. Each copy is
stamped with who collected it, when, from which release, and the approved report's SHA-256, so a
copy that turns up where it should not can be traced to the person who took it.

Word documents are written directly (a .docx is a zip of XML); PDFs are typeset by Qt, which
ELI Legal already carries. No other library is needed.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape


class RenditionUnavailable(RuntimeError):
    """This installation cannot make that kind of copy."""


# ── a small reading of the Markdown the report builder writes ────────────────
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBER = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def blocks(markdown: str) -> list[tuple[str, object]]:
    """Headings, paragraphs, list items, quotes, code and tables, in order."""
    out: list[tuple[str, object]] = []
    lines = markdown.replace("\r\n", "\n").split("\n")
    i = 0
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(("p", " ".join(s.strip() for s in para)))
            para.clear()

    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            flush()
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append(("code", "\n".join(code)))
        elif not line.strip():
            flush()
        elif m := _HEADING.match(line):
            flush()
            out.append((f"h{len(m.group(1))}", m.group(2).strip()))
        elif _RULE.match(line):
            flush()
        elif line.lstrip().startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                if not _TABLE_SEPARATOR.match(lines[i]):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append(("table", rows))
            continue
        elif line.lstrip().startswith(">"):
            flush()
            out.append(("quote", line.lstrip()[1:].strip()))
        elif m := _BULLET.match(line):
            flush()
            out.append(("bullet", m.group(1)))
        elif m := _NUMBER.match(line):
            flush()
            out.append(("number", f"{m.group(1)}. {m.group(2)}"))
        else:
            para.append(line)
        i += 1
    flush()
    return out


_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|_[^_\s][^_]*_)")


def _runs(text: str) -> list[tuple[str, str]]:
    """Text split into (style, words): bold, italic, code or plain."""
    out = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            out.append(("b", part[2:-2]))
        elif part.startswith("`") and part.endswith("`"):
            out.append(("code", part[1:-1]))
        elif (part.startswith("*") and part.endswith("*")) or (
            part.startswith("_") and part.endswith("_") and len(part) > 2
        ):
            out.append(("i", part[1:-1]))
        else:
            out.append(("", part))
    return out


# ── Word ─────────────────────────────────────────────────────────────────────
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _wrun(style: str, text: str, *, size: int | None = None) -> str:
    props = []
    if style == "b":
        props.append("<w:b/>")
    if style == "i":
        props.append("<w:i/>")
    if style == "code":
        props.append('<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New"/>')
    if size:
        props.append(f'<w:sz w:val="{size}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _wpara(
    text: str, *, style: str = "", indent: int = 0, shade: bool = False, size: int | None = None
) -> str:
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if shade:
        ppr.append('<w:shd w:val="clear" w:color="auto" w:fill="EDEDED"/>')
    if indent:
        ppr.append(f'<w:ind w:left="{indent}"/>')
    runs = "".join(_wrun(s, t, size=size) for s, t in _runs(text))
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{runs}</w:p>"


def _wtable(rows: list[list[str]]) -> str:
    border = '<w:{0} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
    borders = "".join(
        border.format(b) for b in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    out = [
        f'<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:tblBorders>{borders}</w:tblBorders></w:tblPr>'
    ]
    for n, row in enumerate(rows):
        cells = "".join(
            "<w:tc><w:tcPr/>"
            + _wpara(f"**{c}**" if n == 0 and c and not c.startswith("**") else c, size=18)
            + "</w:tc>"
            for c in row
        )
        out.append(f"<w:tr>{cells}</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {_W}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="240"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="200"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
</w:styles>"""


def to_docx(markdown: str, stamp: list[str], *, title: str = "") -> bytes:
    """The report as a Word document, with the collection stamp at the top of every copy."""
    body = [
        _wpara(f"**{line}**" if n == 0 else line, shade=True, size=18)
        for n, line in enumerate(stamp)
    ]
    for kind, value in blocks(markdown):
        if kind.startswith("h"):
            level = min(int(kind[1]), 3)
            body.append(_wpara(str(value), style=f"Heading{level}"))
        elif kind == "bullet":
            body.append(_wpara(f"• {value}", indent=360))
        elif kind == "number":
            body.append(_wpara(str(value), indent=360))
        elif kind == "quote":
            body.append(_wpara(str(value), indent=360, shade=True))
        elif kind == "code":
            body += [
                _wpara(f"`{line}`" if line.strip() else "", indent=240)
                for line in str(value).split("\n")
            ]
        elif kind == "table":
            body.append(_wtable(value))  # type: ignore[arg-type]
            body.append(_wpara(""))
        else:
            body.append(_wpara(str(value)))
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W}><w:body>'
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="567" w:footer="567" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        "</Types>",
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        "</Relationships>",
        "word/_rels/document.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>",
        "word/document.xml": document,
        "word/styles.xml": _STYLES,
        "docProps/core.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{escape(title)}</dc:title><dc:creator>ELI Legal</dc:creator>"
        "</cp:coreProperties>",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            z.writestr(name, text)
    return buf.getvalue()


# ── PDF ──────────────────────────────────────────────────────────────────────
def pdf_available() -> bool:
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return False
    return QGuiApplication.instance() is not None


def to_pdf(markdown: str, stamp: list[str], *, title: str = "") -> bytes:
    """The report as an A4 PDF, typeset by Qt, with the collection stamp at the top and page
    numbers at the foot of each page."""
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMarginsF
        from PySide6.QtGui import QGuiApplication, QPageLayout, QPageSize, QPdfWriter, QTextDocument
    except ImportError as exc:  # a server installed without the desktop components
        raise RenditionUnavailable(
            "PDF copies need the desktop components; collect it as Word or Markdown"
        ) from exc
    if QGuiApplication.instance() is None:
        raise RenditionUnavailable(
            "PDF copies are made by the desktop application or by `eli-legal serve`; collect it "
            "as Word or Markdown here"
        )
    head = "\n".join(f"> **{line}**" if n == 0 else f"> {line}" for n, line in enumerate(stamp))
    document = QTextDocument()
    document.setMarkdown(head + "\n\n" + markdown)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer)
    writer.setTitle(title)
    writer.setCreator("ELI Legal")
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(18, 16, 18, 16), QPageLayout.Unit.Millimeter)
    document.print_(writer)
    buffer.close()
    return bytes(data.data())


def ensure_typesetter() -> object | None:
    """For a server with no window: a windowless Qt application, made once on the main thread,
    so PDF copies can be typeset. Returns it (keep a reference), or None without Qt."""
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return None
    existing = QGuiApplication.instance()
    if existing is not None:
        return existing
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QGuiApplication(["eli-legal"])
