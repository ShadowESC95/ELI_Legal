"""How to use ELI Legal, in plain words: the pages, what each is for, and a case from start to
finish. Shared by the desktop application and the browser, so both say the same thing."""

from __future__ import annotations

from typing import Any

INTRO = (
    "ELI Legal helps you prepare a case for the person who decides it. It reads the case papers, "
    "notes what each side says and where, finds and checks the law, and drafts a report in which "
    "every statement points to its source. It decides nothing: a named reviewer reads and "
    "approves every report before anyone may rely on it."
)
READING = (
    "To make everything larger, press Ctrl and + (Ctrl and − for smaller, Ctrl and 0 for normal "
    "size), or hold Ctrl and turn the mouse wheel. Rest the pointer on a heading, a field or a "
    "button and a small box explains it. Every word the application uses is explained at the "
    "foot of this page."
)

# (what to do, who does it, what it involves, the page and the button that takes you there)
STEPS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "Set up where the law comes from",
        "Once, by an administrator",
        "On the Legal sources page, add the official EU or UK database, or load your own "
        "collection of Acts and judgments. Read its licence, then approve it: nothing that is not "
        "approved is ever read.",
        "sources",
        "Open Legal sources",
    ),
    (
        "Start a case",
        "The person leading the case",
        "A short form asks, one step at a time: the case's name and the kind of work, the parties, "
        "the questions to be decided, who works on it and in what role, who reviews the report, "
        "which legal sources it uses, and the date the law is judged at.",
        "new_matter",
        "Start a new case",
    ),
    (
        "Add the case papers",
        "Anyone working on the case",
        "On the Documents page, add the files: pleadings, statements, contracts, letters. Each is "
        "read into numbered passages; anything that could not be read is listed, never guessed at.",
        "evidence",
        "Open Documents",
    ),
    (
        "Run the analysis",
        "Anyone working on the case",
        "On the Progress page, press Start a run. The steps run in order: facts, questions, the "
        "law, the checks, the draft report. A step that needs a person stops and says so.",
        "workflow",
        "Open Progress",
    ),
    (
        "Deal with anything on hold",
        "A named person on the case",
        "Anything that did not check out is put on hold with the reason: a case that was "
        "overruled, a quotation that does not match, a document not read. The Findings page lists "
        "them; for each, verify it by hand, take it out, or keep it on hold.",
        "findings",
        "Open Findings",
    ),
    (
        "Review and approve the report",
        "The named reviewer",
        "On the Review page, read the report in full and its limits, then approve it, return it "
        "for correction, or reject it. Only an approved report may be relied on.",
        "review",
        "Open Review",
    ),
    (
        "Release it",
        "The decision-maker or lead",
        "Choose who receives the approved report and confirm. It is made ready for them to "
        "collect; the system itself sends nothing to anyone.",
        "review",
        "Open Review",
    ),
    (
        "Keep the system in order",
        "Your organisation's compliance lead",
        "The law asks things of your organisation as well as of the software: a classification, "
        "an assessment, training. The Compliance page lists each, and you record it there. "
        "Routine checks run every day and say if anything needs attention.",
        "governance",
        "Open Compliance",
    ),
)


# Each page: its name and what it is for, by the key both applications use for it.
PAGES: dict[str, tuple[str, str]] = {
    "help": ("How to use", "Step by step, and what the words mean"),
    "home": ("Home", "Where this case stands and what to do next"),
    "matter": ("Case details", "Parties, team and the questions to decide"),
    "evidence": ("Documents", "The case papers, and what was read"),
    "chat": ("Ask about the case", "Questions answered from the case papers"),
    "workflow": ("Progress", "Each step of the analysis, and what waits for a person"),
    "agents": ("Who does each step", "Rules, the AI model, or a person"),
    "findings": ("Findings", "Everything found, and whether it checked out"),
    "review": ("Review and approve", "Read the report, then approve or return it"),
    "audit": ("Record of actions", "Who did what and when; it cannot be altered"),
    "governance": ("Compliance", "What the law asks of this system and of you"),
    "sources": ("Legal sources", "Where the law comes from"),
    "laws": ("Laws and standards", "The rules applied to each kind of case"),
    "settings": ("Settings", "People, the AI model, the network and more"),
}


def as_dict() -> dict[str, Any]:
    return {
        "intro": INTRO,
        "reading": READING,
        "steps": [
            {"what": what, "who": who, "how": how, "page": page, "button": button}
            for what, who, how, page, button in STEPS
        ],
        "pages": {key: {"name": name, "about": about} for key, (name, about) in PAGES.items()},
    }
