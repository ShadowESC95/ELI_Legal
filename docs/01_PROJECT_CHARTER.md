# Project charter

ELI Legal is a separate product for governed legal case preparation. It serves three kinds of
user — a court or tribunal, a mediator or conciliator, and a party's legal representatives — and
any legal system for which a jurisdiction pack and an approved source exist. ELI v3 can load it
as an edition; it does not depend on ELI to run.

**Output.** A source-linked case analysis: documents considered, chronology, issues, the evidence
on each, the authorities located and those the parties rely on (each with its verification
result), the findings that may not be relied on and why, the limits of the document, and the run
record. The human reviewer keeps the decision and can reject the output completely.

**Boundary.** Everything up to the decision. No verdict, award, order, recommendation on the
merits (for a decision-maker or a neutral), or settlement terms; no contact with parties; no
change to evidence.

**First governance failure scenario.** A stale or invalid authority passes through several steps
and emerges as a confident, verified conclusion. The design makes that failure testable,
stoppable, reviewable and reconstructable, and `tests/evaluation/test_gold_matter.py` tests it.
