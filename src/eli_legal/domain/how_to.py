"""How to use ELI Legal, in plain words: the pages, what each is for, and a case from start to
finish. Shared by the desktop application and the browser, so both say the same thing."""

from __future__ import annotations

from dataclasses import dataclass
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
    "start": ("Start a new case", "A guided walkthrough of every part, in order"),
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
    "released": ("Released to me", "Approved reports released to you, to read or save"),
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
        "new_case": {
            "intro": NEW_CASE_INTRO,
            "parts": [
                {
                    "key": p.key,
                    "title": p.title,
                    "summary": p.summary,
                    "what": p.what,
                    "questions": [list(q) for q in p.questions],
                    "tips": list(p.tips),
                    "who": p.who,
                    "page": p.page,
                    "button": p.button,
                }
                for p in NEW_CASE
            ],
        },
    }


# ── Starting a new case: the structure, and a walkthrough of every part ─────────────────
NEW_CASE_INTRO = (
    "A case in ELI Legal is built in eleven parts, always in this order. The first six are one "
    "short form (Start a new case), which creates nothing until you press Finish; the rest are "
    "done on their own pages once the case exists. Choose a part to see what it is, every "
    "question you will be asked, what each answer means, and an example. With a case open, a "
    "tick shows each part that is already done."
)


@dataclass(frozen=True, slots=True)
class Part:
    key: str
    title: str
    summary: str  # one line, for the map
    what: str  # what this part is and why it matters
    questions: tuple[tuple[str, str, str], ...]  # (question, what it means, example)
    tips: tuple[str, ...]
    who: str
    page: str  # where it is done: "new_matter" for the form, or a page key
    button: str


NEW_CASE: tuple[Part, ...] = (
    Part(
        "for",
        "Who the work is for",
        "Court or tribunal, mediator, or a party's lawyer",
        "The first question decides who may work on the case, what the report may and may not "
        "say, and how the law classifies the use. It cannot be changed later, so choose by who "
        "will read the report.",
        (
            (
                "Court, tribunal or arbitral tribunal",
                "The person deciding the dispute will use "
                "it. The report never says who should succeed.",
                "A judge, arbitrator or adjudicator",
            ),
            (
                "Mediator or conciliator",
                "A neutral helping the parties settle will use it. It never "
                "says who should succeed.",
                "A commercial mediator",
            ),
            (
                "Party's legal representative",
                "A lawyer acting for one side will use it. It may "
                "assess the merits for its own client, but never words a decision.",
                "A solicitor or barrister for the claimant",
            ),
        ),
        ("If you are not sure, ask who will read the report and rely on it.",),
        "The person starting the case",
        "new_matter",
        "Start a new case",
    ),
    Part(
        "case",
        "The case itself",
        "Its name, purpose, legal system and date",
        "What the case is called, what the work is for, which legal system's law applies, and the "
        "date the law is judged at.",
        (
            (
                "Name (required)",
                "A name everyone on the case will recognise.",
                "Harbour Freight Ltd v Northwind Logistics Ltd",
            ),
            (
                "Purpose (required)",
                "What the work is for, in a line.",
                "Case analysis for the tribunal ahead of the hearing",
            ),
            (
                "Legal system",
                "Whose rules are used to recognise citations and judge whether law is current.",
                "GB-EAW (England and Wales), IE (Ireland), EU",
            ),
            (
                "Governing law",
                "Only if the contract chose another country's law.",
                "Leave as the same as the legal system unless a clause says otherwise",
            ),
            (
                "Forum",
                "Where and under what the case is heard.",
                "Arbitration seated in Dublin under the 2010 Act",
            ),
            ("Procedural rules", "The rules of procedure that apply, if any.", "ICC Rules 2021"),
            (
                "Assess the law as it stood on",
                "The relevant date: usually when the events "
                "happened. Law that changed later is shown as changed.",
                "28 April 2023",
            ),
        ),
        (
            "Without a relevant date, legislation is judged as it stands today, and the report "
            "says so.",
        ),
        "The person starting the case",
        "new_matter",
        "Start a new case",
    ),
    Part(
        "parties",
        "Parties and the questions to decide",
        "Each side, and each issue as a question",
        "Each party once, with its role, and the questions the decision-maker must answer. The "
        "questions organise everything the analysis finds.",
        (
            (
                "Party and role",
                "Each person or organisation in the dispute, with its role.",
                "Harbour Freight Ltd — claimant; Northwind Logistics Ltd — respondent",
            ),
            (
                "We act for",
                "Asked only of a party's representative: which party is your client.",
                "Harbour Freight Ltd",
            ),
            (
                "Issues",
                "One per line, as a neutral question beginning with “Whether”.",
                "Whether time for delivery was of the essence of the agreement",
            ),
        ),
        (
            "Word each issue neutrally: it must not suggest an answer.",
            "Issues can also be found in the papers, and proposed by the AI model if one is set up; "
            "those are labelled so you can confirm or discard them.",
        ),
        "The person starting the case",
        "new_matter",
        "Start a new case",
    ),
    Part(
        "team",
        "The team and the reviewer",
        "Who works on it, in what role, and who approves",
        "Tick who works on the case and choose each person's role on it. You lead it. The role on "
        "the case can only narrow what a person's account allows. At least one named reviewer is "
        "needed before the analysis can start.",
        (
            (
                "Decision-maker",
                "Resolves holds, reviews, approves and releases the report, and can stop the work.",
                "The arbitrator",
            ),
            (
                "Case worker",
                "Adds documents, runs the analysis and records checks; cannot approve or release.",
                "The tribunal secretary",
            ),
            (
                "Assistant",
                "Adds documents and starts the analysis; decides nothing.",
                "A paralegal",
            ),
            (
                "Observer",
                "Reads what is before all parties, with contact details masked; changes nothing.",
                "A trainee",
            ),
            (
                "Auditor",
                "Reads and verifies the record of actions; sees no documents.",
                "Your compliance officer",
            ),
            (
                "Acts for",
                "For someone who works for one party: which one. They then see that "
                "party's confidential material.",
                "Harbour Freight Ltd",
            ),
            (
                "Reviews",
                "Tick for the named person who reads and approves the report. Only an account "
                "that decides this kind of case can approve (for a court or tribunal: a judge, "
                "tribunal member or arbitrator); the page says so where an account cannot.",
                "The arbitrator",
            ),
        ),
        (
            "Only people whose account fits this kind of case are listed.",
            "Someone missing, or whose account cannot approve? An administrator can press Add a "
            "person… or Change their account… on this page, and Change my account… for their "
            "own, without leaving it.",
            "You can change the team and the reviewers later on the Case details page.",
        ),
        "The person starting the case",
        "new_matter",
        "Start a new case",
    ),
    Part(
        "law",
        "Legal sources, law and standards",
        "Where the law is read from, and the rules applied",
        "Tick the approved legal sources this case may read. The law and standards packages "
        "recommended for this kind of case and legal system are ticked for you.",
        (
            (
                "Approved legal sources",
                "Where research finds the law and where cited authorities "
                "are checked. Only sources an administrator approved are listed.",
                "UK law (legislation.gov.uk and Find Case Law)",
            ),
            (
                "Law and standards",
                "The rules and duties applied to this kind of case, each "
                "checked against its official text.",
                "The EU AI Act; the GDPR",
            ),
        ),
        (
            "Without a source no legal research is done and no cited authority can be checked; "
            "you can add one later.",
            "If the list of sources is empty, an administrator must add and approve one first, on "
            "the Legal sources page.",
        ),
        "The person starting the case",
        "new_matter",
        "Start a new case",
    ),
    Part(
        "open",
        "Check and open",
        "Read the summary, then press Finish",
        "A summary of everything you chose. Nothing is created until you press Finish; then the "
        "case opens and its Home page says what to do next.",
        (),
        ("Use Back to change anything before you finish.",),
        "The person starting the case",
        "new_matter",
        "Start a new case",
    ),
    Part(
        "documents",
        "Add the case papers",
        "Every document, with who filed it and who may see it",
        "On the Documents page, add the files. For each you can say what it is, who filed it and "
        "who may see it. Each is read into numbered passages; anything that could not be read is "
        "listed, never guessed at.",
        (
            (
                "What it is",
                "The kind of document, or let the system work it out.",
                "Pleading, witness statement, expert report, contract, letter, exhibit",
            ),
            ("Filed by", "Which party's document it is.", "Northwind Logistics Ltd"),
            (
                "Who may see it",
                "Everyone in the case; the neutral only; one party's confidential "
                "material; or privileged.",
                "Everyone in the case",
            ),
        ),
        (
            "A scanned document with no text cannot be read: convert it to text first.",
            "Text inside a document is evidence, never an instruction to the system.",
        ),
        "Anyone working on the case except an observer or auditor",
        "evidence",
        "Open Documents",
    ),
    Part(
        "analysis",
        "Run the analysis",
        "Facts, issues, the law and the checks, in order",
        "On the Progress page, press Start a run. The steps run in order: reading, facts, issues, "
        "legal research, the checks on every citation, the draft report. It runs in the "
        "background and can be stopped.",
        (),
        (
            "A step that needs a person stops and says so.",
            "Run it again after adding documents or changing the issues.",
        ),
        "A case worker, assistant, decision-maker or the lead",
        "workflow",
        "Open Progress",
    ),
    Part(
        "holds",
        "Deal with anything on hold",
        "What did not check out, and why",
        "Anything that did not check out is put on hold with the reason: an authority overruled, a "
        "quotation that does not match, a document not read. Nothing that relies on it can be "
        "used until a named person resolves it.",
        (
            ("Verify by hand", "You checked it yourself and it is right.", "You read the judgment"),
            ("Take out of reliance", "It is left out of the report.", "A case that was overruled"),
        ),
        ("Every decision is recorded with your name and reasons.",),
        "A decision-maker or the lead",
        "findings",
        "Open Findings",
    ),
    Part(
        "review",
        "Review and approve",
        "Read the report and its limits, then decide",
        "On the Review page the named reviewer reads the report in full and each of its stated "
        "limits, then approves it, returns it for correction, or rejects it. Only an approved "
        "report may be relied on.",
        (
            ("Approve for reliance", "The report may be relied on.", ""),
            ("Return for correction", "Something must be fixed and the analysis run again.", ""),
            ("Reject", "The report is not to be used.", ""),
        ),
        ("You must tick each stated limit and give your reasons.",),
        "The named reviewer",
        "review",
        "Open Review",
    ),
    Part(
        "release",
        "Release it",
        "To the people it is for; nothing is sent automatically",
        "Choose who receives the approved report and confirm. It is made ready for them to "
        "collect; the system itself sends nothing to anyone.",
        (),
        ("Anyone on the case can put the report on hold, which stops its release.",),
        "The decision-maker or the lead",
        "review",
        "Open Review",
    ),
)
