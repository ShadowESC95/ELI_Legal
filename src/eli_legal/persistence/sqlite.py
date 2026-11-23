"""Matter-scoped SQLite store.

Isolation rule: there is no method that reads or writes a matter record without a ``matter_id``,
and every statement filters on it. A record id that belongs to another matter behaves as absent
for reads and is refused for writes.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from eli_legal.domain.errors import MatterAccessDenied, NotFound
from eli_legal.domain.models import (
    Authority,
    AuthorityPassage,
    Chunk,
    Claim,
    Document,
    Hold,
    HumanReview,
    Incident,
    Issue,
    Matter,
    Notification,
    PreservationHold,
    RelianceBlock,
    Report,
    Run,
    RunStep,
    User,
    VerificationResult,
    VerificationTask,
    utcnow,
)
from eli_legal.domain.release import ReleasePackage
from eli_legal.persistence import codec
from eli_legal.persistence.migrations import MIGRATIONS

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class _Spec:
    table: str
    id_attr: str
    run_attr: str | None = None
    kind_attr: str | None = None
    status_attr: str | None = None
    created_attr: str | None = None


_SPECS: dict[type, _Spec] = {
    Document: _Spec("documents", "document_id", None, "doc_type", "status", "ingested_at"),
    Claim: _Spec("claims", "claim_id", "run_id", "kind", "status", "created_at"),
    Issue: _Spec("issues", "issue_id", "run_id", "kind"),
    VerificationResult: _Spec(
        "verifications", "verification_id", "run_id", "verification_type", "status", "created_at"
    ),
    Run: _Spec("runs", "run_id", "run_id", None, "status", "created_at"),
    RunStep: _Spec("run_steps", "record_id", "run_id", "step_id", "status", "started_at"),
    Hold: _Spec("holds", "hold_id", "run_id", "scope", "status", "created_at"),
    VerificationTask: _Spec(
        "tasks", "task_id", "run_id", "verification_type", "status", "created_at"
    ),
    HumanReview: _Spec("reviews", "review_id", "run_id", None, "decision", "created_at"),
    Report: _Spec("reports", "report_id", "run_id", "template", "release_status", "created_at"),
    Incident: _Spec("incidents", "incident_id", "run_id", "category", "status", "created_at"),
    ReleasePackage: _Spec("releases", "release_id", "run_id", None, "status", "created_at"),
    RelianceBlock: _Spec("reliance_blocks", "block_id", "run_id", "cause", "status", "opened_at"),
    PreservationHold: _Spec("preservation_holds", "hold_id", None, "scope", "status", "opened_at"),
    Notification: _Spec(
        "notifications", "notification_id", "run_id", "kind", "status", "created_at"
    ),
}

# Accountability records: ids, hashes and decisions, never content. A matter's purge keeps them.
_KEPT_ON_PURGE = frozenset(
    {"runs", "reviews", "releases", "holds", "incidents", "reliance_blocks", "preservation_holds"}
)

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
# Words that carry no subject. Searching for them finds every passage that uses them: a question
# "whether the buyer could keep them" matches any provision that says "them". The fuller list
# (0.8) raised the research benchmark's MRR from 0.54 to 0.60 for research by words.
_STOPWORDS = frozenset(
    "a an and are as at be been by for from has have in is it its of on or that the to was were "
    "which with this these those not no under shall may must will would should can could "
    "them they their theirs his her hers him she he whether any all other such than then there "
    "where when what who whom whose also being having did does do had into our we you your me "
    "my so if but because about still very just only own same each both".split()
)


def fts_query(text: str, *, max_terms: int = 24) -> str:
    """Turn free text into a safe FTS5 OR-query. Returns '' when nothing searchable remains."""
    terms: list[str] = []
    for word in _WORD.findall(text.lower()):
        if len(word) > 2 and word not in _STOPWORDS and word not in terms:
            terms.append(word)
        if len(terms) >= max_terms:
            break
    return " OR ".join(f'"{t}"' for t in terms)


def _col(value: Any) -> Any:
    encoded = codec.to_jsonable(value)
    return encoded if encoded is None or isinstance(encoded, (str, int, float)) else str(encoded)


# The class below has a method named `list`; this is the builtin, for annotations.
_List = list


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._con.execute("PRAGMA foreign_keys=ON")
        if str(db_path) != ":memory:":
            self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=FULL")
        self._migrate()

    # ── infrastructure ───────────────────────────────────────────────────────
    def _migrate(self) -> None:
        with self._tx() as con:
            con.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = con.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current = int(row[0] or 0)
            for index, script in enumerate(MIGRATIONS, start=1):
                if index > current:
                    for statement in _split_sql(script):
                        con.execute(statement)
                    con.execute("INSERT INTO schema_version(version) VALUES (?)", (index,))

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._con.execute("BEGIN IMMEDIATE")
            try:
                yield self._con
            except BaseException:
                self._con.execute("ROLLBACK")
                raise
            else:
                self._con.execute("COMMIT")

    def _all(self, sql: str, params: Sequence[Any] = ()) -> _List[tuple[Any, ...]]:
        with self._lock:
            return self._con.execute(sql, params).fetchall()

    def close(self) -> None:
        with self._lock:
            self._con.close()

    def schema_version(self) -> int:
        return int(self._all("SELECT MAX(version) FROM schema_version")[0][0] or 0)

    # ── matters ──────────────────────────────────────────────────────────────
    def put_matter(self, matter: Matter) -> None:
        with self._tx() as con:
            con.execute(
                "INSERT INTO matters(matter_id, status, data) VALUES (?,?,?) "
                "ON CONFLICT(matter_id) DO UPDATE SET status=excluded.status, data=excluded.data",
                (matter.matter_id, matter.status.value, codec.dumps(matter)),
            )

    def get_matter(self, matter_id: str) -> Matter | None:
        rows = self._all("SELECT data FROM matters WHERE matter_id=?", (matter_id,))
        return codec.loads(Matter, rows[0][0]) if rows else None

    def list_matters(self) -> _List[Matter]:
        rows = self._all("SELECT data FROM matters ORDER BY rowid")
        return [codec.loads(Matter, r[0]) for r in rows]

    # ── matter-scoped records ────────────────────────────────────────────────
    def _put(self, con: sqlite3.Connection, obj: Any) -> None:
        spec = _SPECS[type(obj)]
        record_id = getattr(obj, spec.id_attr)
        row = (
            record_id,
            obj.matter_id,
            getattr(obj, spec.run_attr) if spec.run_attr else None,
            _col(getattr(obj, spec.kind_attr)) if spec.kind_attr else None,
            _col(getattr(obj, spec.status_attr)) if spec.status_attr else None,
            _col(getattr(obj, spec.created_attr)) if spec.created_attr else None,
            codec.dumps(obj),
        )
        owner = con.execute(
            f"SELECT matter_id FROM {spec.table} WHERE id=?", (record_id,)
        ).fetchone()
        if owner is not None and owner[0] != obj.matter_id:
            raise MatterAccessDenied(f"{spec.table} record {record_id} belongs to another matter")
        con.execute(
            f"INSERT INTO {spec.table}(id, matter_id, run_id, kind, status, created_at, data) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET run_id=excluded.run_id, "
            "kind=excluded.kind, status=excluded.status, created_at=excluded.created_at, "
            "data=excluded.data",
            row,
        )

    def put(self, obj: Any) -> None:
        with self._tx() as con:
            self._put(con, obj)

    def put_many(self, objects: Iterable[Any]) -> None:
        """Write several records in one transaction (all or nothing)."""
        with self._tx() as con:
            for obj in objects:
                self._put(con, obj)

    def get(self, cls: type[T], matter_id: str, record_id: str) -> T | None:
        spec = _SPECS[cls]
        rows = self._all(
            f"SELECT data FROM {spec.table} WHERE id=? AND matter_id=?", (record_id, matter_id)
        )
        return codec.loads(cls, rows[0][0]) if rows else None

    def change(self, cls: type[T], matter_id: str, record_id: str, edit: Callable[[T], None]) -> T:
        """Read a record, change it and write it back as one step: no other thread's write
        can fall between the read and the write."""
        with self._lock:
            record = self.require(cls, matter_id, record_id)
            edit(record)
            self.put(record)
            return record

    def require(self, cls: type[T], matter_id: str, record_id: str) -> T:
        found = self.get(cls, matter_id, record_id)
        if found is None:
            raise NotFound(f"{cls.__name__} {record_id} not found in matter {matter_id}")
        return found

    def owner_matter(self, cls: type, record_id: str) -> str | None:
        """Which matter owns a record id. Used only to detect and log cross-matter attempts."""
        spec = _SPECS[cls]
        rows = self._all(f"SELECT matter_id FROM {spec.table} WHERE id=?", (record_id,))
        return str(rows[0][0]) if rows else None

    def list(
        self,
        cls: type[T],
        matter_id: str,
        *,
        run_id: str | None = None,
        status: str | None = None,
        kind: str | None = None,
    ) -> _List[T]:
        spec = _SPECS[cls]
        sql = f"SELECT data FROM {spec.table} WHERE matter_id=?"
        params: _List[Any] = [matter_id]
        for column, value in (("run_id", run_id), ("status", status), ("kind", kind)):
            if value is not None:
                sql += f" AND {column}=?"
                params.append(value)
        sql += " ORDER BY created_at, rowid"
        return [codec.loads(cls, r[0]) for r in self._all(sql, params)]

    def delete_ids(self, cls: type, matter_id: str, record_ids: Iterable[str]) -> int:
        spec = _SPECS[cls]
        removed = 0
        with self._tx() as con:
            for record_id in record_ids:
                removed += con.execute(
                    f"DELETE FROM {spec.table} WHERE id=? AND matter_id=?", (record_id, matter_id)
                ).rowcount
        return removed

    def delete_records(self, cls: type, matter_id: str, *, run_id: str | None = None) -> int:
        spec = _SPECS[cls]
        sql = f"DELETE FROM {spec.table} WHERE matter_id=?"
        params: _List[Any] = [matter_id]
        if run_id is not None:
            sql += " AND run_id=?"
            params.append(run_id)
        with self._tx() as con:
            return int(con.execute(sql, params).rowcount)

    # ── chunks and matter retrieval ──────────────────────────────────────────
    def replace_chunks(self, matter_id: str, document_id: str, chunks: Sequence[Chunk]) -> None:
        with self._tx() as con:
            con.execute(
                "DELETE FROM chunks_fts WHERE matter_id=? AND document_id=?",
                (matter_id, document_id),
            )
            con.execute(
                "DELETE FROM chunks WHERE matter_id=? AND document_id=?", (matter_id, document_id)
            )
            for c in chunks:
                if c.matter_id != matter_id or c.document_id != document_id:
                    raise MatterAccessDenied("chunk does not belong to this matter/document")
                con.execute(
                    "INSERT INTO chunks(chunk_id, matter_id, document_id, ordinal, locator, text, "
                    "text_hash) VALUES (?,?,?,?,?,?,?)",
                    (c.chunk_id, matter_id, document_id, c.ordinal, c.locator, c.text, c.text_hash),
                )
                con.execute(
                    "INSERT INTO chunks_fts(text, chunk_id, matter_id, document_id) "
                    "VALUES (?,?,?,?)",
                    (c.text, c.chunk_id, matter_id, document_id),
                )

    def chunks_for(self, matter_id: str, document_id: str | None = None) -> _List[Chunk]:
        sql = (
            "SELECT matter_id, document_id, ordinal, locator, text, text_hash, chunk_id "
            "FROM chunks WHERE matter_id=?"
        )
        params: _List[Any] = [matter_id]
        if document_id is not None:
            sql += " AND document_id=?"
            params.append(document_id)
        sql += " ORDER BY document_id, ordinal"
        return [Chunk(*row) for row in self._all(sql, params)]

    def get_chunk(self, matter_id: str, chunk_id: str) -> Chunk | None:
        rows = self._all(
            "SELECT matter_id, document_id, ordinal, locator, text, text_hash, chunk_id "
            "FROM chunks WHERE matter_id=? AND chunk_id=?",
            (matter_id, chunk_id),
        )
        return Chunk(*rows[0]) if rows else None

    def chunk_document_counts(self, matter_id: str) -> dict[str, int]:
        rows = self._all(
            "SELECT document_id, COUNT(*) FROM chunks WHERE matter_id=? GROUP BY document_id",
            (matter_id,),
        )
        return {str(r[0]): int(r[1]) for r in rows}

    def search_chunks(
        self, matter_id: str, query: str, limit: int = 10
    ) -> _List[tuple[Chunk, float]]:
        match = fts_query(query)
        if not match:
            return []
        rows = self._all(
            "SELECT c.matter_id, c.document_id, c.ordinal, c.locator, c.text, c.text_hash, "
            "c.chunk_id, bm25(chunks_fts) FROM chunks_fts JOIN chunks c "
            "ON c.chunk_id = chunks_fts.chunk_id "
            "WHERE chunks_fts MATCH ? AND chunks_fts.matter_id = ? AND c.matter_id = ? "
            "ORDER BY bm25(chunks_fts) LIMIT ?",
            (match, matter_id, matter_id, limit),
        )
        return [(Chunk(*r[:7]), -float(r[7])) for r in rows]

    # ── retention ────────────────────────────────────────────────────────────
    def purge_matter_content(
        self, matter_id: str, *, keep_document_ids: Sequence[str] = ()
    ) -> dict[str, int]:
        """Delete documents, text, indexes and analysis for a matter. Audit events are not here.
        Documents in ``keep_document_ids`` (under a preservation hold) keep their record and
        their text."""
        counts: dict[str, int] = {}
        keep = list(dict.fromkeys(keep_document_ids))
        marks = ",".join("?" * len(keep))
        spare = f" AND document_id NOT IN ({marks})" if keep else ""
        with self._tx() as con:
            counts["chunks"] = con.execute(
                f"DELETE FROM chunks WHERE matter_id=?{spare}", (matter_id, *keep)
            ).rowcount
            con.execute(f"DELETE FROM chunks_fts WHERE matter_id=?{spare}", (matter_id, *keep))
            for spec in _SPECS.values():
                if spec.table in _KEPT_ON_PURGE:
                    continue  # accountability records are kept; they hold ids and decisions only
                if spec.table == "documents" and keep:
                    counts[spec.table] = con.execute(
                        f"DELETE FROM documents WHERE matter_id=? AND id NOT IN ({marks})",
                        (matter_id, *keep),
                    ).rowcount
                    continue
                counts[spec.table] = con.execute(
                    f"DELETE FROM {spec.table} WHERE matter_id=?", (matter_id,)
                ).rowcount
        return counts

    # ── global registries (users, sources) ───────────────────────────────────
    def put_registry(self, kind: str, record_id: str, obj: Any) -> None:
        with self._tx() as con:
            con.execute(
                "INSERT INTO registry(kind, id, data) VALUES (?,?,?) "
                "ON CONFLICT(kind, id) DO UPDATE SET data=excluded.data",
                (kind, record_id, codec.dumps(obj)),
            )

    def get_registry(self, kind: str, record_id: str, cls: type[T]) -> T | None:
        rows = self._all("SELECT data FROM registry WHERE kind=? AND id=?", (kind, record_id))
        return codec.loads(cls, rows[0][0]) if rows else None

    def delete_registry(self, kind: str, record_id: str) -> int:
        with self._tx() as con:
            return int(
                con.execute(
                    "DELETE FROM registry WHERE kind=? AND id=?", (kind, record_id)
                ).rowcount
            )

    def list_registry(self, kind: str, cls: type[T]) -> _List[T]:
        rows = self._all("SELECT data FROM registry WHERE kind=? ORDER BY id", (kind,))
        return [codec.loads(cls, r[0]) for r in rows]

    def put_user(self, user: User) -> None:
        self.put_registry("user", user.user_id, user)

    def get_user(self, user_id: str) -> User | None:
        return self.get_registry("user", user_id, User)

    def list_users(self) -> _List[User]:
        return self.list_registry("user", User)

    # ── API tokens (only hashes are stored) ──────────────────────────────────
    def add_token(self, token: str, user_id: str, label: str = "") -> None:
        with self._tx() as con:
            con.execute(
                "INSERT INTO api_tokens(token_hash, user_id, label, created_at) VALUES (?,?,?,?)",
                (_token_hash(token), user_id, label, utcnow().isoformat()),
            )

    def user_for_token(self, token: str) -> str | None:
        rows = self._all(
            "SELECT user_id FROM api_tokens WHERE token_hash=? AND revoked_at IS NULL",
            (_token_hash(token),),
        )
        return str(rows[0][0]) if rows else None

    def revoke_tokens(self, user_id: str) -> int:
        with self._tx() as con:
            return int(
                con.execute(
                    "UPDATE api_tokens SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                    (utcnow().isoformat(), user_id),
                ).rowcount
            )

    # ── signed-in sessions (only hashes are stored) ──────────────────────────
    def add_session(self, token: str, user_id: str, method: str, expires_at: datetime) -> None:
        with self._tx() as con:
            con.execute(
                "INSERT INTO sessions(token_hash, user_id, method, created_at, expires_at) "
                "VALUES (?,?,?,?,?)",
                (_token_hash(token), user_id, method, utcnow().isoformat(), expires_at.isoformat()),
            )

    def session_user(
        self, token: str, *, method: str | None = None, idle_minutes: float | None = None
    ) -> str | None:
        """The user a session token belongs to, if it is not expired, revoked, idle for too long,
        or opened by a different kind of front end than the one presenting it."""
        key = _token_hash(token)
        rows = self._all(
            "SELECT user_id, expires_at, method, created_at, last_seen_at FROM sessions "
            "WHERE token_hash=? AND revoked_at IS NULL",
            (key,),
        )
        now = utcnow()
        if not rows or datetime.fromisoformat(rows[0][1]) <= now:
            return None
        if method is not None and rows[0][2] != method:
            return None
        seen = datetime.fromisoformat(rows[0][4] or rows[0][3])
        if idle_minutes is not None and (now - seen).total_seconds() > idle_minutes * 60:
            return None
        if (now - seen).total_seconds() > 20:  # not on every request: it is a write
            with self._tx() as con:
                con.execute(
                    "UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (now.isoformat(), key)
                )
        return str(rows[0][0])

    # ── failed sign-ins, lock-out and the second factor ──────────────────────
    def auth_state(self, user_id: str) -> dict[str, Any]:
        rows = self._all(
            "SELECT failures, locked_until, totp_secret, totp_pending, totp_last_step "
            "FROM auth_state WHERE user_id=?",
            (user_id,),
        )
        if not rows:
            return {
                "failures": 0,
                "locked_until": None,
                "totp_secret": None,
                "totp_pending": None,
                "totp_last_step": 0,
            }
        failures, locked, secret, pending, step = rows[0]
        return {
            "failures": int(failures),
            "locked_until": datetime.fromisoformat(locked) if locked else None,
            "totp_secret": secret,
            "totp_pending": pending,
            "totp_last_step": int(step or 0),
        }

    def set_auth_state(self, user_id: str, **values: Any) -> None:
        allowed = {
            "failures",
            "last_failure_at",
            "locked_until",
            "totp_secret",
            "totp_pending",
            "totp_last_step",
        }
        if not values or set(values) - allowed:
            raise ValueError(f"unknown auth_state column(s): {sorted(set(values) - allowed)}")
        stored = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in values.items()}
        with self._tx() as con:
            con.execute("INSERT OR IGNORE INTO auth_state(user_id) VALUES (?)", (user_id,))
            con.execute(
                f"UPDATE auth_state SET {', '.join(f'{k}=?' for k in stored)} WHERE user_id=?",  # noqa: S608
                (*stored.values(), user_id),
            )

    def record_auth_failure(
        self, user_id: str, *, threshold: int, lock_minutes: float
    ) -> datetime | None:
        """Count a failed attempt. Returns when the lock ends if this attempt caused one."""
        now = utcnow()
        with self._tx() as con:
            con.execute("INSERT OR IGNORE INTO auth_state(user_id) VALUES (?)", (user_id,))
            con.execute(
                "UPDATE auth_state SET failures=failures+1, last_failure_at=? WHERE user_id=?",
                (now.isoformat(), user_id),
            )
            failures = int(
                con.execute(
                    "SELECT failures FROM auth_state WHERE user_id=?", (user_id,)
                ).fetchone()[0]
            )
            if failures < threshold:
                return None
            until = now + timedelta(minutes=lock_minutes)
            con.execute(
                "UPDATE auth_state SET locked_until=?, failures=0 WHERE user_id=?",
                (until.isoformat(), user_id),
            )
            return until

    def revoke_session(self, token: str) -> int:
        with self._tx() as con:
            return int(
                con.execute(
                    "UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                    (utcnow().isoformat(), _token_hash(token)),
                ).rowcount
            )

    def revoke_sessions(self, user_id: str) -> int:
        with self._tx() as con:
            return int(
                con.execute(
                    "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                    (utcnow().isoformat(), user_id),
                ).rowcount
            )

    # ── authorities (approved legal-source corpus; not matter data) ──────────
    def put_authority(
        self,
        authority: Authority,
        passages: Sequence[AuthorityPassage],
        citation_keys: Iterable[str],
    ) -> None:
        with self._tx() as con:
            aid = authority.authority_id
            con.execute("DELETE FROM passages_fts WHERE authority_id=?", (aid,))
            con.execute(
                "DELETE FROM passage_vectors WHERE passage_id IN "
                "(SELECT passage_id FROM passages WHERE authority_id=?)",
                (aid,),
            )
            con.execute("DELETE FROM passages WHERE authority_id=?", (aid,))
            con.execute("DELETE FROM authority_citations WHERE authority_id=?", (aid,))
            con.execute(
                "INSERT INTO authorities(authority_id, source_id, jurisdiction, kind, citation, "
                "data) VALUES (?,?,?,?,?,?) ON CONFLICT(authority_id) DO UPDATE SET "
                "source_id=excluded.source_id, jurisdiction=excluded.jurisdiction, "
                "kind=excluded.kind, citation=excluded.citation, data=excluded.data",
                (
                    aid,
                    authority.source_id,
                    authority.jurisdiction,
                    authority.kind.value,
                    authority.citation,
                    codec.dumps(authority),
                ),
            )
            for key in set(citation_keys):
                con.execute(
                    "INSERT OR IGNORE INTO authority_citations(citation_key, authority_id) "
                    "VALUES (?,?)",
                    (key, aid),
                )
            for p in passages:
                con.execute(
                    "INSERT INTO passages(passage_id, authority_id, ordinal, locator, text, "
                    "text_hash, heading) VALUES (?,?,?,?,?,?,?)",
                    (p.passage_id, aid, p.ordinal, p.locator, p.text, p.text_hash, p.heading),
                )
                # The heading is searched with the words under it.
                con.execute(
                    "INSERT INTO passages_fts(text, passage_id, authority_id) VALUES (?,?,?)",
                    (f"{p.heading}\n{p.text}" if p.heading else p.text, p.passage_id, aid),
                )

    def get_authority(self, authority_id: str) -> Authority | None:
        rows = self._all("SELECT data FROM authorities WHERE authority_id=?", (authority_id,))
        return codec.loads(Authority, rows[0][0]) if rows else None

    def list_authorities(self, source_ids: Iterable[str] | None = None) -> _List[Authority]:
        if source_ids is None:
            rows = self._all("SELECT data FROM authorities ORDER BY citation")
        else:
            ids = sorted(set(source_ids))
            if not ids:
                return []
            marks = ",".join("?" for _ in ids)
            rows = self._all(
                f"SELECT data FROM authorities WHERE source_id IN ({marks}) ORDER BY citation", ids
            )
        return [codec.loads(Authority, r[0]) for r in rows]

    def authorities_by_citation(
        self, citation_key: str, source_ids: Iterable[str]
    ) -> _List[Authority]:
        ids = sorted(set(source_ids))
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        rows = self._all(
            "SELECT a.data FROM authority_citations c JOIN authorities a "
            "ON a.authority_id = c.authority_id "
            f"WHERE c.citation_key=? AND a.source_id IN ({marks})",
            [citation_key, *ids],
        )
        return [codec.loads(Authority, r[0]) for r in rows]

    def passages_for(self, authority_id: str) -> _List[AuthorityPassage]:
        rows = self._all(
            "SELECT authority_id, ordinal, locator, text, text_hash, passage_id, heading "
            "FROM passages WHERE authority_id=? ORDER BY ordinal",
            (authority_id,),
        )
        return [AuthorityPassage(*r) for r in rows]

    def get_passage(self, passage_id: str) -> AuthorityPassage | None:
        rows = self._all(
            "SELECT authority_id, ordinal, locator, text, text_hash, passage_id, heading "
            "FROM passages WHERE passage_id=?",
            (passage_id,),
        )
        return AuthorityPassage(*rows[0]) if rows else None

    def search_passages(
        self,
        query: str,
        source_ids: Iterable[str],
        *,
        jurisdictions: Iterable[str] | None = None,
        limit: int = 10,
    ) -> _List[tuple[AuthorityPassage, Authority, float]]:
        match = fts_query(query)
        ids = sorted(set(source_ids))
        if not match or not ids:
            return []
        marks = ",".join("?" for _ in ids)
        sql = (
            "SELECT p.authority_id, p.ordinal, p.locator, p.text, p.text_hash, p.passage_id, "
            "p.heading, a.data, bm25(passages_fts) FROM passages_fts "
            "JOIN passages p ON p.passage_id = passages_fts.passage_id "
            "JOIN authorities a ON a.authority_id = p.authority_id "
            f"WHERE passages_fts MATCH ? AND a.source_id IN ({marks})"
        )
        params: _List[Any] = [match, *ids]
        if jurisdictions is not None:
            js = sorted(set(jurisdictions))
            if not js:
                return []
            sql += f" AND a.jurisdiction IN ({','.join('?' for _ in js)})"
            params.extend(js)
        sql += " ORDER BY bm25(passages_fts) LIMIT ?"
        params.append(limit)
        return [
            (AuthorityPassage(*r[:7]), codec.loads(Authority, r[7]), -float(r[8]))
            for r in self._all(sql, params)
        ]

    # ── vectors for searching by meaning (legal/semantic.py) ────────────────
    def _passage_scope(
        self, source_ids: Iterable[str], jurisdictions: Iterable[str] | None
    ) -> tuple[str, _List[Any]]:
        ids = sorted(set(source_ids))
        where = f"a.source_id IN ({','.join('?' for _ in ids)})" if ids else "0"
        params: _List[Any] = list(ids)
        if jurisdictions is not None:
            js = sorted(set(jurisdictions))
            where += f" AND a.jurisdiction IN ({','.join('?' for _ in js)})" if js else " AND 0"
            params.extend(js)
        return where, params

    def count_passages(
        self, source_ids: Iterable[str], jurisdictions: Iterable[str] | None = None
    ) -> int:
        where, params = self._passage_scope(source_ids, jurisdictions)
        rows = self._all(
            "SELECT count(*) FROM passages p JOIN authorities a ON a.authority_id = p.authority_id "
            f"WHERE {where}",
            params,
        )
        return int(rows[0][0])

    def passages_without_vectors(
        self,
        model: str,
        source_ids: Iterable[str],
        jurisdictions: Iterable[str] | None = None,
        *,
        limit: int = 1000,
    ) -> _List[AuthorityPassage]:
        where, params = self._passage_scope(source_ids, jurisdictions)
        rows = self._all(
            "SELECT p.authority_id, p.ordinal, p.locator, p.text, p.text_hash, p.passage_id, "
            "p.heading FROM passages p JOIN authorities a ON a.authority_id = p.authority_id "
            f"WHERE {where} AND NOT EXISTS (SELECT 1 FROM passage_vectors v "
            "WHERE v.passage_id = p.passage_id AND v.model = ?) "
            "ORDER BY a.citation, p.authority_id, p.ordinal LIMIT ?",
            [*params, model, limit],
        )
        return [AuthorityPassage(*r) for r in rows]

    def put_passage_vectors(self, model: str, rows: Iterable[tuple[str, int, bytes]]) -> None:
        with self._tx() as con:
            con.executemany(
                "INSERT OR REPLACE INTO passage_vectors(passage_id, model, part, vector) "
                "VALUES (?,?,?,?)",
                [(pid, model, part, blob) for pid, part, blob in rows],
            )

    def passage_vectors(
        self, model: str, source_ids: Iterable[str], jurisdictions: Iterable[str] | None = None
    ) -> _List[tuple[str, int, bytes]]:
        where, params = self._passage_scope(source_ids, jurisdictions)
        return [
            (r[0], int(r[1]), bytes(r[2]))
            for r in self._all(
                "SELECT v.passage_id, v.part, v.vector FROM passage_vectors v "
                "JOIN passages p ON p.passage_id = v.passage_id "
                "JOIN authorities a ON a.authority_id = p.authority_id "
                f"WHERE v.model = ? AND {where} ORDER BY v.passage_id, v.part",
                [model, *params],
            )
        ]

    def vectors_for_passages(
        self, model: str, passage_ids: Iterable[str]
    ) -> _List[tuple[str, int, bytes]]:
        ids = sorted(set(passage_ids))
        if not ids:
            return []
        return [
            (r[0], int(r[1]), bytes(r[2]))
            for r in self._all(
                "SELECT passage_id, part, vector FROM passage_vectors WHERE model = ? AND "
                f"passage_id IN ({','.join('?' for _ in ids)}) ORDER BY passage_id, part",
                [model, *ids],
            )
        ]

    def vector_version(self, model: str) -> tuple[int, int]:
        """Changes whenever a vector of this model is added or a passage is replaced."""
        rows = self._all(
            "SELECT (SELECT count(*) FROM passage_vectors WHERE model = ?), "
            "(SELECT coalesce(max(rowid), 0) FROM passages)",
            (model,),
        )
        return int(rows[0][0]), int(rows[0][1])


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _split_sql(script: str) -> _List[str]:
    return [s.strip() for s in script.split(";") if s.strip()]
