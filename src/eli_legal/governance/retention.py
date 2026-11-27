"""The retention schedule: each kind of information a matter holds, why it is kept, and for how
long once the matter is closed. Each kind is kept for its own period and is archived, when the
matter is, under a key of its own, so one kind can be destroyed while another is still kept.

The periods are the organisation's to set (Compliance, OA-09; at set-up), and a matter may keep
its papers for a period of its own. The suggestions and their reasons are given here once, so the
first-run window, Compliance, the command line and the browser all offer the same ones.
"""

from __future__ import annotations

from dataclasses import dataclass

SIX_YEARS = 2190
TEN_YEARS = 3650


@dataclass(frozen=True, slots=True)
class Kind:
    code: str
    name: str
    holds: str
    why: str
    suggested_days: int | None  # None: as long as the papers
    tables: tuple[str, ...] = ()  # rows in the working database
    vault: bool = False  # the original documents
    files: tuple[str, ...] = ()  # kinds of file ELI Legal made (see preservation_service)


# What a closed matter's content consists of, kind by kind. The decision record (RECORD, below)
# is not content: it holds identifiers, hashes and decisions, and outlives the content.
CONTENT: tuple[Kind, ...] = (
    Kind(
        "papers",
        "Case papers",
        "the original documents, the text read from them and the search index",
        "the professional rules and limitation periods that apply to case files (often six years "
        "after the matter ends); GDPR Art. 5(1)(e): no longer than necessary",
        SIX_YEARS,
        tables=("documents", "chunks"),
        vault=True,
    ),
    Kind(
        "analysis",
        "The analysis",
        "findings, checks and their results, verification tasks, the steps of each run, "
        "notices about the matter, and the examples taken from its approved runs to train the "
        "organisation's own model",
        "it quotes the papers, so it is kept as long as they are unless set otherwise",
        None,
        tables=(
            "claims",
            "issues",
            "verifications",
            "tasks",
            "run_steps",
            "notifications",
            "training_examples",
        ),
    ),
    Kind(
        "reports",
        "Reports",
        "each version of the report, the approved one and its released copies, and the record "
        "of the model calls each run made",
        "what was relied on; it may need to be kept longer than the papers it quotes",
        None,
        tables=("reports",),
        files=("reports", "outbox"),
    ),
    Kind(
        "evidence",
        "Evidence packs",
        "the evidence packs exported into ELI Legal's own folder",
        "they show how each result was reached: EU AI Act Art. 18 (documentation kept ten "
        "years) and Art. 26(6) (logs kept at least six months)",
        TEN_YEARS,
        files=("evidence",),
    ),
)
RECORD = Kind(
    "record",
    "Decision record",
    "the matter itself, its runs, reviews and approvals, releases, holds, incidents, reliance "
    "blocks and preservation holds: identifiers, hashes and decisions, no document content",
    "it shows that a named person decided, and on what: EU AI Act Arts. 12, 14 and 19; it is "
    "kept at least as long as anything it accounts for",
    TEN_YEARS,
    tables=(
        "runs",
        "reviews",
        "releases",
        "holds",
        "incidents",
        "reliance_blocks",
        "preservation_holds",
    ),
)
KINDS: dict[str, Kind] = {k.code: k for k in (*CONTENT, RECORD)}


def kind_of_file(relative: str) -> str:
    """Which kind a file ELI Legal made belongs to, from its place under the artifacts folder."""
    first = relative.replace("\\", "/").split("/", 1)[0]
    return {"runs": "reports", "outbox": "reports", "evidence": "evidence"}.get(first, "reports")


def kind_of_table(table: str) -> str:
    for kind in (*CONTENT, RECORD):
        if table in kind.tables:
            return kind.code
    raise KeyError(table)
