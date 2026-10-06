"""The agents: one bounded role per workflow step.

"Agent" here means a step with a fixed mandate, not a free-roaming assistant. Each one reads
named things, writes named things, and is forbidden named things. Most are deterministic; three
may use a model, and only to select or draft from items the system hands them. The last four are
people. This table is what the desktop application's Agents view shows, and what a reviewer needs
in order to understand what the system did on their behalf.
"""

from __future__ import annotations

from dataclasses import dataclass

from eli_legal.workflows.runner import WorkflowDef

DETERMINISTIC = "deterministic"
MODEL_ASSISTED = "model-assisted"
HUMAN = "human"


@dataclass(frozen=True, slots=True)
class AgentSpec:
    step_id: str
    name: str
    role: str
    kind: str
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    may_not: tuple[str, ...]
    controls: tuple[str, ...] = ()


_NO_DECISION = "state or imply an outcome"
_NO_NETWORK = "reach the network"

AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(
        "scope", "Intake officer",
        "Confirms the matter is ready: profile, law, sources, a named human reviewer, a healthy audit ledger.",
        DETERMINISTIC,
        ("matter record", "user register", "source register", "audit ledger"),
        ("run versions (model, prompts, tools, policy)",),
        ("start work without a named reviewer", "use an unapproved source"),
        ("C-14", "C-03", "C-16"),
    ),
    AgentSpec(
        "ingest", "Document reader",
        "Reads every registered document into paragraphs with locators.",
        DETERMINISTIC,
        ("originals in the evidence vault",),
        ("passages", "document status", "injection flags"),
        ("alter an original", "guess at a file it cannot read", _NO_NETWORK),
        ("C-05", "C-07"),
    ),
    AgentSpec(
        "document_coverage", "Coverage checker",
        "Accounts for every document: read, or held until a person accepts the gap.",
        DETERMINISTIC,
        ("document manifest", "passages"),
        ("coverage and injection holds",),
        ("waive a gap itself",),
        ("C-06", "C-07"),
    ),
    AgentSpec(
        "facts", "Fact extractor",
        "Takes factual statements word for word from the documents, with date and party.",
        MODEL_ASSISTED,
        ("passages",),
        ("fact findings with evidence links",),
        ("reword evidence", "read a flagged document into a model", _NO_DECISION),
        ("C-05", "C-07"),
    ),
    AgentSpec(
        "issues", "Issue mapper",
        "Identifies the questions in dispute and attaches the facts that bear on each.",
        MODEL_ASSISTED,
        ("stated issues", "pleadings", "fact findings"),
        ("issues", "fact-to-issue links"),
        ("suggest an answer to any issue", "present its own proposed issue as adopted"),
        ("C-07",),
    ),
    AgentSpec(
        "evidence_mapping", "Evidence mapper",
        "Maps evidence to issues; notes gaps, one-sided issues and statements that conflict.",
        DETERMINISTIC,
        ("issues", "fact findings"),
        ("evidence map", "possible conflicts"),
        ("resolve a conflict of evidence",),
        (),
    ),
    AgentSpec(
        "legal_research", "Legal researcher",
        "Searches approved sources and lists every authority cited anywhere in the papers.",
        DETERMINISTIC,
        ("issues", "passages", "approved sources only"),
        ("authority passages (verbatim)", "party-cited authorities"),
        ("use a source that is not approved for this matter", "paraphrase an authority"),
        ("C-03", "C-08"),
    ),
    AgentSpec(
        "citation_verification", "Citation verifier",
        "Confirms each cited authority exists in an approved source.",
        DETERMINISTIC,
        ("cited authorities", "approved sources"),
        ("citation check results",),
        ("treat existence as proof the authority is good law",),
        ("C-08",),
    ),
    AgentSpec(
        "current_law_check", "Current-law citator",
        "Checks each authority is still good law for the relevant date, independently of who cited it.",
        DETERMINISTIC,
        ("authority status and treatment history", "the matter's relevant date"),
        ("current-law check results",),
        ("accept status information older than the pack allows", "rely on the citing party"),
        ("C-09",),
    ),
    AgentSpec(
        "proposition_verification", "Proposition verifier",
        "Confirms an authority says what it is quoted as saying.",
        DETERMINISTIC,
        ("authority passages", "quotations"),
        ("proposition check results",),
        ("verify a reworded proposition on a model's say-so",),
        ("C-10",),
    ),
    AgentSpec(
        "evidence_verification", "Provenance verifier",
        "Re-checks every finding against unchanged source text.",
        DETERMINISTIC,
        ("evidence vault", "passages", "findings"),
        ("provenance and evidence-support results",),
        ("pass a finding whose source has changed or is missing",),
        ("C-05",),
    ),
    AgentSpec(
        "verification_gate", "Gatekeeper",
        "Holds every finding lacking a required passing check, and everything that relies on it.",
        DETERMINISTIC,
        ("all check results",),
        ("finding statuses", "holds", "tasks for a person"),
        ("average a failure away", "release a hold"),
        ("C-11", "C-12"),
    ),
    AgentSpec(
        "analysis", "Analyst",
        "Sets out the arguments open to each party, from verified findings only.",
        MODEL_ASSISTED,
        ("verified facts", "verified authority passages"),
        ("attributed arguments with their basis",),
        (_NO_DECISION, "introduce a figure or citation not in its basis", "weigh the arguments"),
        ("C-13",),
    ),
    AgentSpec(
        "draft_report", "Report builder",
        "Assembles the report from verified findings; lists what may not be relied on, and the limits.",
        DETERMINISTIC,
        ("findings", "check results", "holds"),
        ("draft report and its hash",),
        ("include an unverified finding in the body", "write free prose"),
        ("C-15", "C-26"),
    ),
    AgentSpec(
        "final_validation", "Final validator",
        "Verifies the audit chain and reconciles the run's record with it.",
        DETERMINISTIC,
        ("audit ledger", "run records"),
        ("completeness result",),
        ("pass a run whose record has a gap",),
        ("C-16", "C-17"),
    ),
    AgentSpec(
        "human_review", "Named reviewer",
        "A named, qualified person approves, rejects or returns the exact report version.",
        HUMAN,
        ("the report", "its stated limits", "findings not relied on"),
        ("review decision with reasons",),
        ("be an agent or system identity",),
        ("C-14", "C-15"),
    ),
    AgentSpec(
        "prepare_release", "Release preparer",
        "Fixes the approved report version and its proposed recipients.",
        HUMAN,
        ("approved report",),
        ("release package",),
        ("release an unapproved or altered report",),
        ("C-20",),
    ),
    AgentSpec(
        "recipient_approval", "Recipient approver",
        "A named person confirms each recipient is entitled to receive it.",
        HUMAN,
        ("release package",),
        ("recipient confirmation",),
        ("release to a party who is not entitled",),
        ("C-20",),
    ),
    AgentSpec(
        "controlled_delivery", "Outbox",
        "Stages the approved report for collection. Nothing is transmitted.",
        HUMAN,
        ("confirmed release package",),
        ("outbox copy and manifest",),
        ("contact a party", "send anything anywhere"),
        ("C-20",),
    ),
)  # fmt: skip

_BY_STEP = {a.step_id: a for a in AGENTS}


def agent_for(step_id: str) -> AgentSpec:
    return _BY_STEP[step_id]


def layers(workflow: WorkflowDef) -> list[list[str]]:
    """Steps grouped by how far they are from the start: every step in layer n depends only on
    steps in earlier layers. This is the left-to-right order the graph view draws."""
    depth: dict[str, int] = {}
    for step in workflow.order():
        depth[step.id] = 1 + max((depth[d] for d in step.depends_on), default=-1)
    out: list[list[str]] = [[] for _ in range(max(depth.values(), default=-1) + 1)]
    for step in workflow.order():
        out[depth[step.id]].append(step.id)
    return out
