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

**D-09 No decision through a conversational assistant.** See `04_ELI_V3_INTEGRATION.md`.

**D-10 Legal systems are data.** A jurisdiction pack holds structure and citation grammar, never
rules of law, and ships unvalidated.

**D-11 Legislation is judged on the relevant date; case law as it stands today.** A pack can
change how treatments are weighed (civil-law packs treat a contrary later decision as a conflict
for a person, not a failure).

**D-12 No training on matter data.**

**D-13 One profile per matter.** Tribunal-side and party-side use are different deployments with
different users, outputs and regulatory posture.
