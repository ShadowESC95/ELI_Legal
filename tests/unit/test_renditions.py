"""A Word or PDF copy of a report: what each holds, and never a blank PDF."""

from __future__ import annotations

import io
import zipfile

import pytest

from eli_legal.adapters.local import renditions

REPORT = "# Memorandum\n\nThe **claimant** says:\n\n- one\n- two\n\n| Issue | Finding |\n|---|---|\n| A | B |\n"


def test_a_word_copy_has_the_stamp_headings_lists_and_tables():
    data = renditions.to_docx(REPORT, ["Collected by Someone", "release r"], title="t")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        body = z.read("word/document.xml").decode()
    assert "Collected by Someone" in body and 'w:val="Heading1"' in body
    assert "• one" in body and "<w:tbl>" in body and "<w:b/>" in body


def test_on_windows_the_windowless_toolkit_is_given_the_system_fonts(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("WINDIR", r"C:\Windows")
    monkeypatch.delenv("QT_QPA_FONTDIR", raising=False)
    renditions.windowless_fonts()
    assert __import__("os").environ["QT_QPA_FONTDIR"].endswith("Fonts")


def test_a_pdf_with_no_text_is_never_given_out(monkeypatch):
    renditions.ensure_typesetter()
    assert renditions.to_pdf(REPORT, ["Collected by Someone"]).startswith(b"%PDF")
    # A PDF typeset without any font carries no font descriptor; that copy is refused.
    from PySide6.QtCore import QByteArray

    assert b"/FontDescriptor" in renditions.to_pdf(REPORT, ["x"])
    monkeypatch.setattr(QByteArray, "data", lambda self: b"%PDF-1.4 no fonts here")
    with pytest.raises(renditions.RenditionUnavailable, match="could not find a font"):
        renditions.to_pdf(REPORT, ["x"])
