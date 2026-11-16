"""Builds exhibit_scan.pdf: page 1 has a text layer; page 2 is only an image of an exhibit (an
invoice), as a scanned or photographed exhibit is. Run once with Poppler installed:

    python tests/fixtures/make_exhibit_pdf.py

The exhibit page is drawn as text in a throwaway PDF, rendered to grey pixels by pdftoppm, and
placed on page 2 as an image, so page 2 carries no text layer at all.
"""

from __future__ import annotations

import subprocess
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).parent
EXHIBIT = [
    "EXHIBIT C - INVOICE 4471",
    "Northwind Logistics Ltd to Harbour Freight Ltd",
    "Date of invoice: 3 March 2025",
    "Carriage of 14 containers, Port Varen to Kestrel Bay",
    "Amount due: 12,400 euros, payable within 30 days",
]
COVER = [
    "Witness statement of Ines Calloway",
    "1. I am the operations manager of Harbour Freight Ltd.",
    "2. The invoice we received is exhibited to this statement as Exhibit C.",
]


def _pdf(objects: list[bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


def _stream(data: bytes, extra: str = "") -> bytes:
    return f"<< /Length {len(data)} {extra}>>\nstream\n".encode() + data + b"\nendstream"


def _text(lines: list[str], size: int = 14) -> bytes:
    ops = [f"BT /F1 {size} Tf 72 760 Td {size + 8} TL"]
    ops += [f"({line}) Tj T*" for line in lines]
    return ("\n".join(ops) + "\nET").encode()


def _text_page_pdf(lines: list[str]) -> bytes:
    return _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            _stream(_text(lines)),
        ]
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "exhibit.pdf"
        source.write_bytes(_text_page_pdf(EXHIBIT))
        subprocess.run(["pdftoppm", "-r", "150", "-gray", "-singlefile", str(source),
                        str(Path(folder) / "exhibit")], check=True)  # fmt: skip
        pgm = (Path(folder) / "exhibit.pgm").read_bytes()
    # P5 <width> <height> <maxval> then the pixels
    header, _, rest = pgm.partition(b"\n")
    parts = (header + b"\n" + rest).split(maxsplit=4)
    width, height, pixels = int(parts[1]), int(parts[2]), parts[4]
    image = zlib.compress(pixels, 9)
    pdf = _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            _stream(_text(COVER)),
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /XObject << /Im1 7 0 R >> >> /Contents 8 0 R >>",
            _stream(
                image,
                f"/Type /XObject /Subtype /Image /Width {width} /Height {height} "
                "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode ",
            ),
            _stream(b"q 612 0 0 792 0 0 cm /Im1 Do Q"),
        ]
    )
    (HERE / "exhibit_scan.pdf").write_bytes(pdf)
    print(f"exhibit_scan.pdf: {len(pdf)} bytes, page 2 an image {width}x{height}")
    # One page: a caption in the text layer, and the invoice beneath it as an image.
    caption = b"BT /F1 14 Tf 72 740 Td (Exhibit C: the invoice, as received by email.) Tj ET\n"
    beside = _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> /XObject << /Im1 6 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            _stream(caption + b"q 612 0 0 792 0 -60 cm /Im1 Do Q"),
            _stream(
                image,
                f"/Type /XObject /Subtype /Image /Width {width} /Height {height} "
                "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode ",
            ),
        ]
    )
    (HERE / "exhibit_beside_caption.pdf").write_bytes(beside)
    print(f"exhibit_beside_caption.pdf: {len(beside)} bytes")


if __name__ == "__main__":
    main()
