# Decision log

**D-01 Separate product, loadable by ELI v3 as an edition.** No dependency on ELI to run.

**D-02 Holds are state, not prose.** A failure creates a hold record the workflow consumes.

**D-03 Audit fails closed.** No key, no run; no downgrade to an unkeyed chain.

**D-04 Status checking is separate from generation.** A generator agreeing with itself is not
verification, and neither is a second model agreeing with the first.

**D-05 Findings are verbatim.** Facts and passages are the source's own words. This gives up
fluent summary for something a reader can check against the page.

**D-06 The system does not vouch for what a party says an authority decides.** It reports the
reliance, checks existence and status, and shows the closest passage for a person to compare.

**D-07 Orchestration stays in ELI Legal.** A host scheduler is not used, because the guarantees
(stop downstream on failure, log every outcome, stop if the log cannot be written) must hold
identically standalone and hosted.

**D-08 ELI Legal's own parser, not the host's.** Locators are needed for every finding.

**D-09 No decision through a conversational assistant.** See `../3_architecture/03_eli_v3_integration.md`.

**D-10 Legal systems are data.** A jurisdiction pack holds structure and citation grammar, never
rules of law, and ships unvalidated.

**D-11 Legislation is judged on the relevant date; case law as it stands today.** A pack can
change how treatments are weighed (civil-law packs treat a contrary later decision as a conflict
for a person, not a failure).

**D-12 No training on matter data.**

**D-13 One profile per matter.** Tribunal-side and party-side use are different deployments with
different users, outputs and regulatory posture.

**D-14 A role on each matter narrows an account role; it never widens it.** Who someone is
(their account role) and what they do on one matter (lead, decision-maker, case worker, assistant,
observer, auditor) are separate, and both must allow an action. People already on matters when
roles on a matter were introduced keep exactly what their account allowed, so nobody lost access.

**D-15 Withhold, do not hide.** Material a person is not cleared for is listed as withheld, with
the reason, rather than left out, so nobody is misled about what a matter holds; its words are
never shown, and anything built from it (a drafted argument) is no more widely visible than it.

**D-16 A requirement's status says whether it is met.** The register records what the software
does; an organisation's duties are actions recorded in the application in a named person's name
and reviewed on time. "Partial" described the software, not the requirement, and is no longer
shown.

**D-17 The forms are the templates.** In-application forms are read from the governance
templates, so the questions cannot drift between paper and screen.

**D-18 The system checks itself every day, and acts only where acting is certain.** It opens an
incident when an approved report's law changes or a stored original is altered, and deletes a
closed matter's content when its retention ends; everything else is reported for a person.
Currency of the law comes from the approved sources and a named person's confirmation against the
official text, because the network is denied by default.

**D-19 One vocabulary.** Every state, reason, check, action and role a person is shown is worded
once (`domain/plain.py`) and used by the desktop application, the reports, the command line and,
through `/v1/words`, the browser application.

**D-20 Hard offline is enforced by the kernel, not by Python.** Intercepting Python's sockets
stops Python code only; native libraries, io_uring and child processes go round it. A seccomp
filter (Linux), the kernel sandbox (macOS) or a firewall rule (Windows) cannot be bypassed from
inside the program, and on Linux cannot be removed until it exits, so switching it off takes
effect only at the next start.
