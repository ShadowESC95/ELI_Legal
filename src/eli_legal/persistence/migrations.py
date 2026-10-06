"""Ordered, append-only schema migrations. Never edit a published entry; add a new one."""

from __future__ import annotations

_RECORD_TABLES = (
    "documents",
    "claims",
    "issues",
    "verifications",
    "runs",
    "run_steps",
    "holds",
    "tasks",
    "reviews",
    "reports",
    "incidents",
    "releases",
)


def _record_table(name: str) -> str:
    # Every matter-scoped record carries matter_id in an indexed column so isolation is enforced
    # in SQL, not left to the caller.
    return f"""
    CREATE TABLE IF NOT EXISTS {name} (
        id TEXT PRIMARY KEY,
        matter_id TEXT NOT NULL,
        run_id TEXT,
        kind TEXT,
        status TEXT,
        created_at TEXT,
        data TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_{name}_matter ON {name}(matter_id, run_id);
    """


MIGRATIONS: list[str] = [
    # 1 — initial schema
    "\n".join(_record_table(t) for t in _RECORD_TABLES)
    + """
    CREATE TABLE IF NOT EXISTS matters (
        matter_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        data TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS registry (
        kind TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (kind, id)
    );
    CREATE TABLE IF NOT EXISTS api_tokens (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        revoked_at TEXT
    );
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id TEXT PRIMARY KEY,
        matter_id TEXT NOT NULL,
        document_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        locator TEXT NOT NULL,
        text TEXT NOT NULL,
        text_hash TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(matter_id, document_id, ordinal);
    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
        text, chunk_id UNINDEXED, matter_id UNINDEXED, document_id UNINDEXED,
        tokenize = 'porter unicode61'
    );
    CREATE TABLE IF NOT EXISTS authorities (
        authority_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        jurisdiction TEXT NOT NULL,
        kind TEXT NOT NULL,
        citation TEXT NOT NULL,
        data TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_authorities_source ON authorities(source_id, jurisdiction);
    CREATE TABLE IF NOT EXISTS authority_citations (
        citation_key TEXT NOT NULL,
        authority_id TEXT NOT NULL,
        PRIMARY KEY (citation_key, authority_id)
    );
    CREATE TABLE IF NOT EXISTS passages (
        passage_id TEXT PRIMARY KEY,
        authority_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        locator TEXT NOT NULL,
        text TEXT NOT NULL,
        text_hash TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_passages_authority ON passages(authority_id, ordinal);
    CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
        text, passage_id UNINDEXED, authority_id UNINDEXED,
        tokenize = 'porter unicode61'
    );
    """,
    # 2 — signed-in sessions. Only the hash of a session token is stored.
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        method TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT
    );
    CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
    """,
    # 3 — idle time-out for sessions; failed sign-ins and lock-out; the second factor.
    """
    ALTER TABLE sessions ADD COLUMN last_seen_at TEXT;
    CREATE TABLE IF NOT EXISTS auth_state (
        user_id TEXT PRIMARY KEY,
        failures INTEGER NOT NULL DEFAULT 0,
        last_failure_at TEXT,
        locked_until TEXT,
        totp_secret TEXT,
        totp_pending TEXT,
        totp_last_step INTEGER NOT NULL DEFAULT 0
    );
    """,
]
