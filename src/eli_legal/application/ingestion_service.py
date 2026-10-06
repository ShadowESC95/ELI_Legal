from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from eli_legal.adapters.local.parsers import detect_media_type
from eli_legal.application.container import AppContext
from eli_legal.domain.enums import AccessScope, DocumentStatus, DocumentType
from eli_legal.domain.errors import IngestionError, InvalidState, UnsupportedDocument
from eli_legal.domain.models import Document, Matter
from eli_legal.legal.dates import find_dates
from eli_legal.legal.legal_document_processor import build_chunks, classify_document


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
        try:
            parsed = self.ctx.parser.parse(document.filename, raw)
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
            },
        )
        return document

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
