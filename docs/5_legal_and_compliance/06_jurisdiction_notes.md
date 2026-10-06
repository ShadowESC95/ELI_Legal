# Jurisdiction notes

ELI Legal is built for the **European Union's** regime: the AI Act (a high-risk system under
Annex III, point 8(a)), the GDPR, and ISO/IEC 42001 as the management-system standard. That
regime is the same in all twenty-seven member states. What differs from state to state is the
national layer on top of it. This document sets out the Union layer, what to find in any member
state, Ireland as the worked example the use case takes, and then the position outside the Union.

Pointers as known in October 2026. Starting points for the user's own check, not a statement of
the law. Items marked *(reported)* were confirmed from secondary sources only.

## The European Union: applies in every member state

| Instrument | What it is | Where it is covered |
|---|---|---|
| Regulation (EU) 2024/1689 (AI Act), as amended by Regulation (EU) 2026/1744 | High-risk classification under Annex III 8(a); requirements, provider and deployer duties, conformity, monitoring | [EU AI Act](02_eu_ai_act.md) |
| Regulation (EU) 2016/679 (GDPR) | Personal data in case papers | [Data protection](03_data_protection.md) |
| Directive (EU) 2016/680 | Processing by competent authorities in criminal justice, in place of the GDPR | [Data protection](03_data_protection.md) |
| Regulation (EU) 2024/2847 (Cyber Resilience Act) | Security duties for commercial software | [Liability, IP and licensing](05_liability_ip_and_licensing.md) |
| Directive (EU) 2024/2853 (Product Liability) | Software as a product | [Liability, IP and licensing](05_liability_ip_and_licensing.md) |
| Directive 2008/52/EC (Mediation) | Confidentiality of mediation in cross-border disputes | [Professional and judicial duties](04_professional_and_judicial_duties.md) |
| Directive (EU) 2016/2102 (web accessibility of public bodies) | A court's browser application | [Liability, IP and licensing](05_liability_ip_and_licensing.md) |
| ISO/IEC 42001:2023 | The management-system standard chosen in the use case | [ISO/IEC 42001](09_iso_iec_42001.md) |
| CCBE guidance on generative AI for lawyers (2025) *(reported)*; CEPEJ European Ethical Charter (2018) | European bars' and the Council of Europe's positions | |

**In the software.** The `EU` jurisdiction pack is the default. It recognises Union legislation,
Court of Justice case numbers, and the European Case Law Identifier (ECLI) of a decision from
any member state. National packs exist for Ireland, Germany and France (`IE`, `DE`, `FR`), each
of which also applies the `EU` pack. For another member state, open the matter under `EU`: its
decisions are recognised by ECLI, but citations in a purely national form are not, until a pack
for that state is written. Every pack is structural and unvalidated until a lawyer qualified in
that system signs it off.

## What to find in any member state

The Union layer leaves these to national law and national bodies. Before use in a member state,
identify each:

| National layer | Why it matters |
|---|---|
| The market surveillance authority designated under the AI Act | Where serious incidents are reported (Art. 73) and who supervises |
| Rules or practice directions of the courts and tribunals on the use of AI | Verification, disclosure and declarations, with sanctions |
| Guidance of the bar and the law society, and of the judiciary | Professional and judicial duties |
| The act implementing the GDPR | Criminal-offence data, restrictions in legal proceedings, privilege, supervision of courts |
| The arbitration law of the seat, and the mediation statute | Challenges to awards; confidentiality |
| Who may give legal advice | The product is for qualified professionals |
| Terms of the official and commercial legal sources | Whether they may be loaded into the tool |

## Ireland: the local jurisdiction taken in the use case

The use case places a hypothetical EU law firm in Ireland. What follows is the national layer
there, as an example of what the table above produces for one member state.

| Source | What it is |
|---|---|
| Practice Direction HC 142 (High Court) and CA 16 (Court of Appeal), in force 1 September 2026 *(reported)* | Responsible use of generative AI in court documents. Everyone is responsible for their documents. AI-generated material must be independently verified under human control; all authorities, citations and quotations independently verified. Disclosure of use, and its nature and extent, where the court directs. A declaration in affidavits and witness statements that generative AI was not used to generate their substantive content. Sanctions include costs, disregarding documents, strike-out and referral to the regulator |
| Law Society of Ireland, *Guidelines for the Use of Generative Artificial Intelligence by the Legal Profession in Ireland* (December 2025) | Solicitors' duties when using AI: confidentiality, competence, supervision, verification |
| The Bar of Ireland, *Ethical Toolkit: Ethical Use and Use Cases for AI in Legal Practice* (April 2025) *(reported)* | Barristers' duties |
| Guidelines for judges issued through the Judicial Council *(reported)* | Use of AI by the judiciary |
| A Court of Appeal decision reported as pointing to an obligation on parties to disclose AI use | Identify and read it before relying on the point |
| Data Protection Act 2018 | Sections 55 (criminal-offence data), 60 and 162 (restrictions; privilege), and the provisions on supervision of courts acting judicially |
| Mediation Act 2017 | Confidentiality of mediation |
| Legal Services Regulation Act 2015; Solicitors Acts | Who may practise; the regulator |

**For a user in Ireland:** sections 2 and 3 of
[Professional and judicial duties](04_professional_and_judicial_duties.md) are written with these
directions in mind. The jurisdiction pack `IE` is structural and unvalidated.

## Germany and France

National packs `DE` and `FR` ship, structural and unvalidated. Both states' bars and courts have
issued their own guidance on AI in legal work; a user there must find and follow it, using the
table above.

## Outside the Union

The AI Act still reaches a provider who places the system on the Union market, and output used
in the Union, wherever the provider is.

### England and Wales

| Source | What it is |
|---|---|
| Courts and Tribunals Judiciary, *Artificial Intelligence (AI): Guidance for Judicial Office Holders* (refreshed 8 October 2025, replacing April 2025) | Risks and responsibilities for judges, their clerks and assistants: confidentiality, accuracy, bias, security, personal responsibility for what is produced in the judge's name |
| *Ayinde v London Borough of Haringey* [2025] EWHC 1383 (Admin) | The court's response to false citations: professional consequences up to contempt |
| Solicitors Regulation Authority; Bar Standards Board; Law Society and Bar Council guidance on generative AI | Professional duties |
| Civil Justice Council work on AI in preparing court documents | Check its current output |
| UK GDPR; Data Protection Act 2018; Data (Use and Access) Act 2025 | Data protection |
| Legal Services Act 2007 | Reserved legal activities |
| Copyright, Designs and Patents Act 1988, section 29A | Text and data mining only for non-commercial research |

The pack `GB-EAW` is structural and unvalidated.

### United States

| Source | What it is |
|---|---|
| ABA Formal Opinion 512 (July 2024) | Competence, confidentiality, communication with clients, candour to the tribunal, supervision and fees when using generative AI |
| State bar opinions and rules | Vary; several states have issued their own |
| Court standing orders | Many judges require disclosure or certification of AI use. Check the judge's page |
| *Mata v Avianca* (S.D.N.Y. 2023) and the many cases since | Sanctions for fabricated citations |
| Proposed Federal Rule of Evidence 707 on machine-generated evidence | Published for comment in 2025; check its status |
| State privacy statutes; no general federal privacy law | |
| Unauthorised-practice statutes, by state | |

The pack `US-FED` covers federal citation forms only and is unvalidated. No state pack ships.

## International arbitration

| Source | What it is |
|---|---|
| UNCITRAL Model Law, Articles 18 and 34; New York Convention, Article V | Equal treatment, the right to present one's case, and the grounds on which an award can be set aside or refused enforcement |
| Chartered Institute of Arbitrators, guideline on the use of AI in arbitration (2025) *(reported)* | Tribunal and party use; disclosure; procedural orders |
| Silicon Valley Arbitration and Mediation Center, *Guidelines on the Use of AI in Arbitration* (2024) | The same ground; includes model clauses |
| Institutional rules and notes on tribunal secretaries | Check the institution administering the case |
| The law of the seat | Governs challenges |

The pack `INT-ARB` covers instruments and citation forms, not the law of any seat.

## Anywhere else

Use the `GENERIC` pack only as a last resort. It knows no citation forms, so the citation and
current-law checks depend entirely on the source you load. Before using ELI Legal in a
jurisdiction not listed here, find: the court's or tribunal's rules on AI; the regulator's
guidance; the data-protection law; and whether your legal sources may be used this way.
