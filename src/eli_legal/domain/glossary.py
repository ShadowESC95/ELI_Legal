"""Plain explanations of the words the application uses, for people who do not work in IT.

Shown when the pointer rests on a word, a column heading or a field, and listed in full on the
How to use page. One place, so a term means the same thing wherever it appears.
"""

from __future__ import annotations

import re

TERMS: dict[str, str] = {
    # the case
    "Matter": "A case: the dispute or file you are working on, with its parties, its team, the "
    "questions to decide and its documents.",
    "Profile": "The kind of work the case is for (a court or tribunal, a mediator, a party's "
    "lawyer, …). It sets what the report may and may not say.",
    "Party": "A person or organisation on one side of the dispute.",
    "Issue": 'A question the decision-maker has to answer, such as "whether the contract was '
    'validly ended".',
    "Relevant date": "The date the law is judged at: usually when the events happened. Law that "
    "changed later is shown as changed.",
    "Evidence": "The case papers: pleadings, statements, contracts, letters and the like.",
    "Document": "One file in the case papers. The original is kept unchanged; what was read from "
    "it is kept beside it.",
    "Fact": "A statement taken word for word from the case papers, with who said it and where.",
    "Finding": "Anything the system found: a fact, a passage of law, or an authority a party "
    "relies on. Each is checked before it can be relied on.",
    "Proposition": "What a passage of law is quoted as saying.",
    "Chronology": "The facts in date order.",
    # the law
    "Authority": "A source of law relied on: an Act, a regulation or a judgment.",
    "Citation": 'How an authority is referred to, such as "[2019] UKSC 41" or '
    '"Regulation (EU) 2016/679".',
    "Locator": "Where in a document or authority something is: a page and paragraph, or a section.",
    "Passage": "A part of an authority, such as one section of an Act or one paragraph of a judgment.",
    "Jurisdiction": "The legal system whose law applies, such as England and Wales (GB-EAW), "
    "Ireland (IE) or the European Union (EU).",
    "Legal source": "Where the law comes from: an official database, or a collection of Acts and "
    "judgments you load yourself. Only approved sources are ever read.",
    "Approved source": "A legal source a named person has approved for use, after reading its "
    "licence. Nothing else is read.",
    "Licence": "The terms on which a source's material may be used. Many commercial databases "
    "forbid use by software like this; read them before approving.",
    "Good law": "Still in force and not overruled or repealed.",
    "Current law": "Whether an authority was in force on the relevant date and still is today.",
    "Overruled": "A judgment a later, higher court has said was wrong. It is no longer good law.",
    "Repealed": "An Act or regulation that has been withdrawn. It is no longer in force.",
    "Corpus": "A collection of legal texts loaded from your own files.",
    "Law and standards package": "The rules and duties that apply to a kind of case, prepared for "
    "this software from official texts. Each one says when it was last checked.",
    "Jurisdiction pack": "What the system knows about one legal system: how its citations look "
    "and how old a check may be.",
    # checking
    "Verified": "Every check this kind of finding needs has passed: the words are in the original "
    "unaltered, and an authority exists and was good law. It does not mean a statement is true.",
    "Held": "Stopped until a named person looks at it. Nothing that relies on it can be used.",
    "Hold": "A stop placed on a finding or on the run, until a named person resolves it.",
    "Provenance": "Where something came from, and proof that it has not changed since.",
    "Check": "One of the tests a finding must pass: that its words are in the original "
    "unaltered, that an authority exists, that it is still good law.",
    "Stated by": "The party whose papers say it.",
    "Status": "Where something stands now.",
    "Run": "One pass of the analysis over the case papers, from reading to the draft report.",
    "Step": "One stage of the analysis, such as reading the documents or checking citations.",
    "DAG": 'The map of the analysis steps and the order they run in (a "directed acyclic '
    'graph"). The Progress page shows it.',
    "Report": "The document the analysis produces for the decision-maker, with its sources and "
    "its limits. It can be relied on only once a named reviewer approves it.",
    "Reviewer": "The named person who reads the report and approves it, or sends it back.",
    "Decision-maker": "The person who decides the case. The system never decides.",
    "Release": "Making an approved report available to the people it is for. Nothing is sent "
    "by the system itself.",
    # people and access
    "Role": "What a person may do: in the whole system (their account), and on each case "
    "(lead, decision-maker, case worker, assistant, observer or auditor).",
    "Clearance": "Which confidential material a person on a case may read.",
    "Withheld": "Hidden from you because your role on the case does not allow you to read it. "
    "The reason is shown instead.",
    "Redaction": "Hiding material a person is not cleared to read.",
    # oversight and compliance
    "Audit trail": "The record of everything anyone and the system did, in order. It is sealed "
    "so that any later change is detected.",
    "Audit verified": "The record of actions has been checked and nothing in it was changed.",
    "Events": "Entries in the record of actions.",
    "Ledger": "The audit trail's sealed store.",
    "Hash": "A fingerprint of a file: if one character changes, the fingerprint changes.",
    "SHA-256": "A standard way of taking a file's fingerprint (its hash).",
    "Routine checks": "Checks the system runs every day: whether law relied on is still good law, "
    "files unchanged, people trained, deadlines met.",
    "Incident": "Something that went wrong and must be looked into, and perhaps reported.",
    "Requirement": "Something a law or standard requires of an AI system like this one, or of "
    "the organisation using it.",
    "Control": "A safeguard built into the system to meet a requirement or reduce a risk.",
    "Risk": "Something that could go wrong, why, and what it would harm.",
    "Organisation action": "Something only your organisation can do to meet a requirement (a "
    "decision, an assessment, training), recorded here in a named person's name.",
    "Waiting for your organisation": "The software does its part, but the law also needs your "
    "organisation to record something. The Organisation actions tab says what.",
    "Met by the software": "The software meets this requirement on its own; nothing is needed "
    "from you.",
    "Due for review": "Recorded once, but old enough that it must be looked at again.",
    "Provider": "Who makes the AI system and places it on the market: the maker of ELI Legal.",
    "Deployer": "Who uses the AI system in their work: your organisation.",
    "Responsible": "Does the work.",
    "Accountable": "Answers for it being done.",
    "Consulted": "Is asked before it is done.",
    "Informed": "Is told once it is done.",
    "EU AI Act": "The European Union's law on artificial intelligence. Software that helps a court "
    'or tribunal research and interpret facts and law is "high-risk" under it.',
    "High-risk AI system": "An AI system the EU AI Act treats with the most care, with duties for "
    "its maker and its users.",
    "Annex III": "The list in the EU AI Act of uses that make an AI system high-risk. Point 8(a) "
    "covers helping courts and tribunals.",
    "Conformity assessment": "The check, required by the EU AI Act, that a high-risk system meets "
    "the Act before it is used. It has not been done for this software.",
    "GDPR": "The EU's General Data Protection Regulation: the rules on personal data.",
    "ISO/IEC 42001": "An international standard for managing AI systems responsibly.",
    "Instrument": "The law or standard a requirement comes from.",
    "Provision": "The article or section of the law the requirement comes from.",
    # technology
    "Model": "The AI language model on this computer that can draft and select. Optional: "
    "without one, everything else still works.",
    "Embedding model": "A small AI model on this computer that finds text by meaning, not just "
    "by matching words.",
    "GGUF": "The file format of AI models that run on this computer.",
    "Network denied by default": "The program cannot reach the internet unless a legal source "
    "that needs it has been approved, and then only that source.",
    "Hard offline": "The computer's operating system blocks every internet connection from the "
    "program, whatever asks for one.",
    "Checks": "The routine checks: whether law relied on is still good law, files unchanged, "
    "people trained and deadlines met.",
    "Identifier": "A short name the system uses for something, without spaces, such as "
    "eu_official or my_judgments.",
    "CELEX": "The number the EU's Publications Office gives each act and judgment.",
    "ECLI": "The European Case Law Identifier: a standard reference for a judgment.",
    "Neutral citation": "A court's own reference for a judgment, such as [2019] UKSC 41.",
}

_KEYS = {k.lower(): k for k in TERMS}
_EMOJI = re.compile(r"^[^\w(\[]+")


def explain(word: str) -> str:
    """The plain explanation of a term, a column heading or a label; '' when there is none."""
    text = _EMOJI.sub("", (word or "").strip()).strip(" :?").lower()
    if not text:
        return ""
    if text in _KEYS:
        return TERMS[_KEYS[text]]
    singular = text[:-1] if text.endswith("s") else text
    if singular in _KEYS:
        return TERMS[_KEYS[singular]]
    return ""


def tooltip(word: str, extra: str = "") -> str:
    """Rich text for a hover box: the explanation, wrapped to a readable width."""
    said = explain(word) or extra
    if not said:
        return ""
    if extra and extra != said:
        said = f"{said}<br><br>{extra}"
    return f"<p style='white-space:pre-wrap; max-width: 420px'>{said}</p>"


def items() -> list[tuple[str, str]]:
    return sorted(TERMS.items(), key=lambda kv: kv[0].lower())
