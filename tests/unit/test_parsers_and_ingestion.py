import io
import os
import zipfile

import pytest

from eli_legal.adapters.local.parsers import LocalDocumentParser
from eli_legal.demo import _docx, _pdf
from eli_legal.domain.enums import DocumentType
from eli_legal.domain.errors import UnsupportedDocument
from eli_legal.legal.legal_document_processor import build_chunks, classify_document

PARSER = LocalDocumentParser()


def test_text_is_split_into_locatable_paragraphs():
    parsed = PARSER.parse("note.txt", b"First paragraph.\n\nSecond paragraph\nwraps here.")
    assert [(s.locator, s.text) for s in parsed.segments] == [
        ("¶1", "First paragraph."),
        ("¶2", "Second paragraph wraps here."),
    ]


def test_docx_and_pdf_keep_their_text_and_pdf_keeps_page_numbers():
    docx = PARSER.parse("a.docx", _docx(["Clause one.", "Clause two."]))
    assert [s.text for s in docx.segments] == ["Clause one.", "Clause two."]
    pdf = PARSER.parse(
        "w.pdf", _pdf(["I, Daniel Okafor, say as follows.", "On 21 March 2023 I telephoned her."])
    )
    assert all(s.locator.startswith("p.1 ") for s in pdf.segments)
    assert "21 March 2023" in " ".join(s.text for s in pdf.segments)


def test_odt_html_rtf_and_email_are_read():
    content = (
        '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
        "<text:h>Heading</text:h><text:p>Body <text:span>text</text:span>.</text:p>"
        "</office:text></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("content.xml", content)
    assert [s.text for s in PARSER.parse("a.odt", buffer.getvalue()).segments] == [
        "Heading",
        "Body text.",
    ]
    html = PARSER.parse(
        "a.html",
        b"<html><head><title>T</title><script>x()</script></head><body><p>Hello</p><p>World</p></body></html>",
    )
    assert [s.text for s in html.segments] == ["Hello", "World"] and html.title == "T"
    rtf = PARSER.parse(
        "a.rtf", rb"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\f0 First line.\par Second line.\par}"
    )
    assert [s.text for s in rtf.segments] == ["First line.", "Second line."]
    eml = PARSER.parse(
        "a.eml", b"From: a@x.example\nTo: b@y.example\nSubject: Late\n\nDear Sir,\n\nIt is late.\n"
    )
    assert eml.segments[0].locator == "headers" and eml.title == "Late"
    assert "It is late." in [s.text for s in eml.segments]


@pytest.mark.parametrize(
    ("name", "raw"),
    [
        ("photo.jpg", b"\xff\xd8\xff\xe0binary"),
        ("blob.bin", b"\x00\x01\x02" * 50),
        ("empty.txt", b"  \n"),
        ("old.doc", b"\xd0\xcf\x11\xe0"),
    ],
)
def test_unreadable_files_are_reported_not_guessed_at(name, raw):
    with pytest.raises(UnsupportedDocument):
        PARSER.parse(name, raw)


def test_a_scanned_pdf_with_no_text_layer_is_unsupported():
    with pytest.raises(UnsupportedDocument, match="text layer"):
        PARSER.parse("scan.pdf", _pdf([""]))


def test_each_paragraph_becomes_one_passage_with_its_own_locator():
    parsed = PARSER.parse("n.txt", b"One.\n\nTwo.\n\nThree.")
    chunks = build_chunks("m", "d", parsed.segments)
    assert [(c.locator, c.text) for c in chunks] == [
        ("¶1", "One."),
        ("¶2", "Two."),
        ("¶3", "Three."),
    ]


def test_document_type_is_inferred_and_can_be_wrong_so_it_is_overridable():
    assert (
        classify_document("soc.txt", "text/plain", "STATEMENT OF CLAIM\n1. The Claimant...")
        is DocumentType.PLEADING
    )
    assert (
        classify_document("ws.pdf", "application/pdf", "WITNESS STATEMENT OF X")
        is DocumentType.WITNESS_STATEMENT
    )
    assert classify_document("x.eml", "message/rfc822", "") is DocumentType.CORRESPONDENCE
    assert classify_document("misc.txt", "text/plain", "nothing recognisable") is DocumentType.OTHER


def test_same_bytes_filed_twice_are_one_document_and_originals_are_immutable(demo):
    sv, mid = demo
    matter = sv.matters.get(mid, "arb.keane")
    before = sv.matters.documents(mid, "arb.keane")
    again = sv.ingestion.register(
        matter=matter,
        actor_id="sec.byrne",
        filename="copy.txt",
        raw=sv.ctx.vault.read(mid, before[0].sha256),
    )
    assert again.document_id == before[0].document_id
    assert len(sv.matters.documents(mid, "arb.keane")) == len(before)
    original = sv.ctx.vault._path(mid, before[0].sha256)
    if os.name != "nt":
        assert oct(original.stat().st_mode & 0o777) == "0o400"
    original.chmod(0o600)
    original.write_bytes(b"altered")
    assert sv.ctx.vault.verify(mid, before[0].sha256) is False


def test_a_pleading_headed_only_defence_is_recognised():
    text = "DEFENCE\n\nIN THE MATTER OF AN ARBITRATION\n\n1. It is admitted that the parties entered into the Supply Agreement dated 12 January 2023."
    assert classify_document("02_defence.txt", "text/plain", text) is DocumentType.PLEADING
    assert (
        classify_document("reply.docx", "application/x", "AMENDED REPLY\n\n1. ...")
        is DocumentType.PLEADING
    )


def test_cited_authorities_are_checked_whatever_type_the_document_was_filed_as(demo):
    """A defence misfiled as a contract must not have its citations skipped."""
    sv, mid = demo
    matter = sv.matters.get(mid, "arb.keane")
    defence = next(
        d for d in sv.matters.documents(mid, "arb.keane") if d.filename == "02_defence.txt"
    )
    defence.doc_type = DocumentType.CONTRACT
    sv.ctx.store.put(defence)
    run = sv.runs.start(matter.matter_id, actor_id="sec.byrne")
    cited = {
        c.citation
        for c in sv.verification.claims(mid, run.run_id, actor_id="arb.keane")
        if c.kind.value == "party_authority"
    }
    assert {"[2022] XXSC 7", "[2019] XXSC 99", "[2018] XXCA 33"} <= cited
