# Legal overview

**What this is.** A map of the legal questions ELI Legal raises, what the software does about
each, and what is left for whoever builds, sells or deploys it. It was prepared by the
development effort, not by a law firm. It is not legal advice. Statements of law here are
pointers to the primary sources: read those, and have qualified counsel in each jurisdiction
confirm the position before relying on it. Positions were last checked in November 2026.

**The regime.** ELI Legal is built for the European Union's rules: the AI Act, under which it is
a high-risk system (Annex III, point 8(a)); the GDPR; and ISO/IEC 42001 as the management-system
standard. Those are the instruments of the RAIMS use case, and they apply alike in every member
state. National court rules and professional guidance sit on top and differ by state; see
[Jurisdiction notes](06_jurisdiction_notes.md).

**Two roles run through everything.** The **provider** develops the system and puts it on the
market under their name. The **deployer** is the court service, tribunal, chambers or firm that
uses it. Most duties fall on one or the other, and it matters which.

## The concerns, in order of weight

| # | Concern | Why it matters | What the software does | What remains, and whose it is |
|---|---|---|---|---|
| 1 | **A high-risk system under the EU AI Act** | ELI Legal is classified high-risk under Article 6(2) and Annex III, point 8(a); Article 6(3) was considered and is not relied on. The provider and deployer duties of Chapter III apply to Annex III systems from 2 December 2027 (Regulation (EU) 2026/1744), in every member state | Implements the technical measures the Act describes: risk controls, logging, human oversight, instructions for use, and registers mapping each duty to a control | **Provider:** quality management system, technical documentation, conformity assessment, declaration, CE marking, EU-database registration, post-market monitoring. None is done. **Deployer:** oversight by competent people, fundamental-rights impact assessment where required, log retention. See [EU AI Act](02_eu_ai_act.md) |
| 2 | **The decision must remain a human's** | Courts cannot delegate the judicial function; arbitrators' mandates are personal; a neutral must stay neutral | Renders no decision and, for decision-makers and neutrals, no view on outcome; approval is by a named person who must acknowledge every stated limit | **Deployer:** make review real, not a formality. A reviewer who approves without reading defeats the design. See [Professional and judicial duties](04_professional_and_judicial_duties.md) |
| 3 | **Fair procedure** | A decision-maker who relies on a point or authority the parties never saw risks a breach of fair procedures, and in arbitration a challenge to the award | Lists separately every authority found by research that no party cited | **Deployer:** put such material to the parties before relying on it; consider telling the parties the tool is in use |
| 4 | **Accuracy of legal authority** | The Act requires declared accuracy (Art. 15). Courts in several jurisdictions have sanctioned lawyers for false citations, and national court rules increasingly require independent verification under human control (Ireland's practice directions of September 2026 are one example) | Checks existence, current status and quotation separately; holds anything that fails; states what was not verified | **User:** the software's "verified" means "matched an approved source". It does not discharge the practitioner's own duty to verify. **Deployer:** a source that is complete, current and carries status. None ships |
| 5 | **Confidentiality and privilege** | Sending client or court material to a third party can breach duties and risk privilege | Nothing leaves the machine: network denied by default, local models only, matter isolation, access scopes | **Deployer:** encrypted storage, backups, who is given access, a second factor, physical security |
| 6 | **Data protection** | Case papers contain personal data, often special-category and criminal-offence data | Minimises what is logged; supports deletion on closure; keeps data local; role and matter access control | **Deployer (controller):** lawful basis, data-protection impact assessment, records, retention, data-subject rights, breach handling. See [Data protection](03_data_protection.md) |
| 7 | **Disclosing the use of AI** | The Act requires deployers to inform people subject to assisted decisions (Art. 26(11)). Some national courts also require disclosure when directed, and declarations in sworn evidence | Keeps a complete record of what it did; produces no affidavit or witness-statement content | **User:** know the rule in your court; disclose when required |
| 8 | **Licences for legal sources** | Law reports, headnotes and commercial databases are protected and usually forbid loading into other tools | A source cannot be approved until its owner, licence and terms review are recorded | **Deployer:** actually hold the rights. See [Liability, IP and licensing](05_liability_ip_and_licensing.md) |
| 9 | **This product's own licence** | The software is proprietary: `LICENSE` reserves all rights and grants a licence only under the ELI End User Licence Agreement with the ELI Legal Product Schedule, for a purchased licence or an ELI v3 licence that includes it. A public copy of the source gives nobody a right to use it | Installers carry the licence; a licence key is required to run | **Provider:** written terms with each deploying organisation where the standard agreement is not enough (support, data, liability, insurance) |
| 10 | **Third-party software** | The desktop application uses Qt (LGPL-3.0); other components carry their own terms | Generates the notice list at each build; ships Qt as separate, replaceable files | **Provider:** ship the licence texts; do not prevent replacement of the Qt libraries; or buy a commercial Qt licence |
| 11 | **Model licences** | Local models have their own terms, some restricting commercial or professional use | Ships no model; records which model produced what | **Deployer:** read the model's licence and acceptable-use policy |
| 12 | **Liability** | Errors can cause loss to clients and parties. From 9 December 2026 the Product Liability Directive (EU) 2024/2853 treats software, AI included, as a product: liability without proof of fault for damage to natural persons caused by a defect, including one an update brings or the lack of a security update leaves | States limits in every report; binds approval to a named person | **Provider:** contract terms, product-liability cover, a stated security-update period (OA-27). **Deployer:** professional indemnity cover that extends to AI-assisted work. See [Liability, IP and licensing](05_liability_ip_and_licensing.md) |
| 13 | **Product-security law** | The EU Cyber Resilience Act (Regulation (EU) 2024/2847) applies to software supplied in the course of a commercial activity, which ELI Legal is. Its reporting duties have applied since **11 September 2026**, whenever the product was placed on the market: an actively exploited vulnerability or a severe incident is notified through the single reporting platform with an early warning within 24 hours. The essential requirements and conformity steps apply from 11 December 2027 | Network refused by default, matter isolation, a tamper-evident ledger; a list of components and licences at each build | **Provider:** name who watches, decides and reports now (OA-26); a vulnerability process, support period, machine-readable bill of materials and conformity steps by December 2027 (OA-27) |
| 14 | **Accessibility** | The AI Act requires a high-risk system to meet the accessibility requirements of Directives (EU) 2016/2102 and (EU) 2019/882 (Art. 16(l)); courts and other public bodies are bound by the first in their own right | Keyboard operation, zoom on every page, plain words, explanations on hover | **Provider:** an audit against EN 301 549 (WCAG 2.1 AA), screen readers included, has not been done (OA-24) |
| 15 | **Who may use it** | Giving legal advice to the public is restricted to qualified people in most jurisdictions | Built for qualified professionals; roles reflect that | **Provider:** do not market or supply it to the public as a source of legal advice |
| 16 | **Bias and equal treatment** | Models reflect their training; selection of facts can skew a picture | Facts are verbatim and located; no assessment of people or credibility is made; a fact filed under an issue by meaning alone is marked for the reviewer to check | **User:** read the source passage, not only the extract |
| 17 | **Explaining a decision to the person affected** | Under Article 86 of the AI Act a person affected by a decision taken on the basis of the system's output may ask for an explanation of the part the system played; fair-trial guarantees (Art. 6 ECHR, Art. 47 of the Charter) require reasons from the decision-maker in any event | Each run's evidence pack shows what it read, which sources and models, what it checked and who approved what | **Deployer:** a way to give that explanation on request (OA-25) |
| 18 | **Law the system reads may have changed** | An authority relied on must be the law on the relevant date: a section of an Act can be repealed while the Act stays in force, and an EU act is amended without a new number | Each provision relied on is judged on its own status (UK); an amended EU act is read in the consolidated version in force on the date, with the note that only the Official Journal texts are authentic | **User:** a repeal of part of a subsection is not detected, and a consolidated EU text is not authentic: quote the Official Journal where it matters |

## What must be true before a real matter

1. Written terms between provider and deployer (the software's own licence is published in `LICENSE`).
2. Counsel in the jurisdiction has reviewed these documents and the intended use.
3. A dated plan for the provider duties under the EU AI Act (quality management system, Annex IV
   documentation, internal-control conformity assessment, declaration, registration) and for the
   deployer's (oversight, impact assessment, logs).
4. A data-protection impact assessment by the deploying organisation.
5. A legal source the deployer is licensed to use, complete for its citation types, with status.
6. The jurisdiction pack for that legal system validated by a qualified lawyer.
7. Accuracy measured on representative matters, against thresholds set in advance.
8. Encrypted storage, backups including the audit key, and a second factor for every user.
9. Users trained on what the system does and does not check.
10. Insurers told.

11. Someone named to report exploited vulnerabilities and severe incidents under the Cyber
    Resilience Act, which already applies (OA-26).

Items 2, 3, 6, 7 and 11 are not done. The rest are for each deployment.

## Sources checked for this folder (October and November 2026)

Secondary reports were used to confirm dates and recent changes; the primary texts govern.

- Regulation (EU) 2024/2847 (Cyber Resilience Act), reporting duties from 11 September 2026:
  [European Commission, CRA reporting](https://digital-strategy.ec.europa.eu/en/policies/cra-reporting),
  [McCann FitzGerald](https://www.mccannfitzgerald.com/knowledge/data-privacy-and-cyber-risk/cyber-resilience-act-reporting-obligations-apply-from-11-september-2026)
- Directive (EU) 2024/2853 (Product Liability), products placed on the market after 9 December
  2026: [Gibson Dunn](https://www.gibsondunn.com/eu-product-liability-directive-responding-to-software-ai-and-complex-supply-chains),
  [A&L Goodbody](https://www.algoodbody.com/insights-publications/eu-revised-product-liability-directive-what-you-need-to-know)
- Directive (EU) 2022/2555 (NIS2), Art. 6(35), and Regulation (EU) 2024/1689, Art. 74(8):
  read in the Official Journal texts, retrieved from the Publications Office in November 2026
- Ireland, Regulation of Artificial Intelligence Bill 2026:
  [Department of Enterprise, Tourism and Employment](https://enterprise.gov.ie/en/news-and-events/department-news/2026/june/20260617.html),
  [AI Office of Ireland established](https://enterprise.gov.ie/en/news-and-events/department-news/2026/july/20260730.html),
  [William Fry](https://www.williamfry.com/knowledge/irish-ai-office-loses-market-surveillance-role/)
- United Kingdom, Articles 22A to 22D UK GDPR from 5 February 2026:
  [S.I. 2026/82](https://www.legislation.gov.uk/uksi/2026/82),
  [Data (Use and Access) Act 2025, section 80](https://www.legislation.gov.uk/ukpga/2025/18/section/80/enacted);
  the judiciary's position statement of 9 October 2026:
  [LexisNexis](https://www.lexisnexis.co.uk/legal/news/hmcts-publishes-position-statement-on-judicial-use-of-ai)
- Council of Europe Framework Convention on AI (CETS 225): the sources found in November 2026
  do not show it in force (five ratifications, three of them member states, are needed); check
  the [Council of Europe's page](https://www.coe.int/en/web/artificial-intelligence/the-framework-convention-on-artificial-intelligence)
  and its Treaty Office for the current state

- Regulation (EU) 2024/1689 (AI Act) as amended by Regulation (EU) 2026/1744, in force 27 July
  2026: [Steptoe](https://www.steptoe.com/en/news-publications/steptechtoe-blog/eu-ai-act-amendments-enter-into-force.html),
  [Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/),
  [AI Act Monitor](https://www.aiactblog.nl/en/ai-act-monitor/digital-omnibus-2026-1744-in-force)
- [Artificial Intelligence (AI): Judicial Guidance, Courts and Tribunals Judiciary, October 2025](https://www.judiciary.uk/guidance-and-resources/artificial-intelligence-ai-judicial-guidance-october-2025/)
- [Courts Service of Ireland: practice directions on generative AI in court documents](https://courts.ie/news/court-of-appeal---high-court---new-practice-directions-issued-on-the-responsible-use-of-generative-artificial-intelligence-in-court-documents);
  [Law Society Gazette, September 2026](https://www.lawsociety.ie/gazette/top-stories/2026/september/courts-guidance-on-genai-use-takes-effect/);
  [Irish Legal News on HC 142](https://www.irishlegal.com/articles/high-court-practice-direction-imposes-verification-requirement-on-use-of-generative-ai)
- [Law Society of Ireland, Guidelines for the Use of Generative AI by the Legal Profession, December 2025](https://lawsociety.ie/globalassets/documents/cybersecurity/2025-12-generative-ai-guidelines-v4.pdf)
