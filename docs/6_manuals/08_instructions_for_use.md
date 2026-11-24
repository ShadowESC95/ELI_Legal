# Instructions for use

For the people who deploy and review. Adapt to the actual deployment before use.

**Intended purpose.** To help a court or tribunal, a mediator or conciliator, or a party's legal
representatives prepare a dispute: read the papers, set out facts and issues with their sources,
locate and check authorities, and present a draft analysis for a named person to review.

**Not intended for.** Deciding or recommending the outcome; legal advice to a client without a
lawyer's review; use on a legal system with no pack and no approved source; use without a named
human reviewer; unattended use.

## What a reviewer must know

- **Verified means something narrow.** A fact marked verified is a sentence that appears, word for
  word, in an unaltered document. It is not a finding that the sentence is true. An authority
  marked verified exists in an approved source and was in good standing when the source last said
  so. It is not a finding that it governs the case.
- **What the parties' authorities stand for is not checked.** Section 5 of the report shows what a
  party says an authority decides beside the closest passage of the authority, closest in meaning
  when an embedding model is set up and in wording otherwise (the table says which). Compare
  them: the closest passage is a pointer, not a finding that the authority supports the party.
- **Read section 6.** Findings that failed verification are listed there with reasons. An
  overruled case a party relies on is something you need to know, not noise.
- **Read section 8.** It lists every limit of the particular report: documents not read, packs not
  validated, whether a model was used, overrides. Approval requires acknowledging each.
- **Model-drafted arguments are prompts for thought.** They rest on verified items but can be
  misattributed, incomplete or repetitive.
- **Absence is not evidence.** Without a model, facts are selected by rule (dated or monetary
  statements); relevant undated facts can be missing. Research by words alone misses a
  provision put in other words more often: section 8 says whether research also searched by
  meaning. Even with both, on the research benchmark a quarter of the provisions in point were
  not among the first ten found. No source is complete unless it is declared so.

## What the organisation must do

Name reviewers who are qualified and have time to review; approve sources and record their terms;
have each jurisdiction pack validated; set retention periods for each kind of record; keep the
audit key, the databases' key and off-machine checkpoints apart from the data; run the server on
the machine that holds the cases, from the installed program; watch `eli-legal monitor`; assess changes before use; train users; complete the
classification, impact and data-protection assessments that apply to it.

## Signing in

Sign in as yourself. Never share a passphrase or leave a session open on a shared machine: what
is done in your session is recorded as done by you.

## Stopping

Stop on the Progress page (or `eli-legal run stop M R --reason …`) stops a run. The step at work
ends at its next model answer, document or issue, and no later step starts; the page says at once
that the run is stopping. Rejecting or returning a report stops reliance.
If the software cannot be trusted, stop using it and prepare the matter by hand; the originals in
the vault are untouched.
