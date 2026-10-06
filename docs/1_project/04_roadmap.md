# Roadmap

**Done.** The whole lifecycle; three profiles; eight jurisdiction packs; local-corpus source;
optional local model; tamper-evident audit with completeness; evidence pack; proven identity,
lock-out, second factor and step-up for decisions; desktop application, secure server and
browser application, command line; Linux installers including an AppImage; ELI v3 edition pack; registers checked
against code.

**Next, in order of what most limits real use.**

1. A connector to a real legal source with treatment data, for one jurisdiction, with its terms
   reviewed. Without it, "still good law" rests on whatever status the corpus curator recorded.
2. Real evaluation matters with thresholds set in advance, per jurisdiction and profile.
3. Validation of the jurisdiction packs by qualified lawyers; then make validation mandatory.
4. Single sign-on with an organisation's identity provider, and hardware security keys.
5. Encryption at rest for the vault and stores; OCR on ingestion.
6. Semantic retrieval alongside keyword search, matter-scoped.
7. Fact selection beyond dated and monetary statements when no model is configured.
8. In ELI v3: apply the discovery patch and carry edition entitlements in the licence.

**Before anyone else runs it.**

- Choose a licence and write the customer terms.
- Sign the installers, and have a person use the Windows and macOS builds.
- The EU AI Act provider work: classification decision, quality management system, Annex IV
  documentation, conformity assessment. See `docs/5_legal_and_compliance/02_eu_ai_act.md`.
- An independent penetration test of the server, and an accessibility audit of both interfaces.
- A vulnerability-disclosure contact and a declared support period.

**Deliberately not planned.** Drafting decisions or awards; contacting parties; training on
matter data; exposing decisions through a conversational assistant.
