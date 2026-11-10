# Liability, intellectual property and licensing

Not legal advice. This is where the commercial and property questions are collected.

## 1. This product's own licence: undecided

**The repository contains no licence file.** Under copyright law that means all rights are
reserved to the author, and no one else has permission to use, copy, modify or distribute the
software. That is a sound default while it is unpublished, and a blocker the moment anyone else
is to run it.

The options, for the owner to choose between:

| Option | Effect |
|---|---|
| Proprietary licence with an end-user agreement | Customers get a right to use, on terms. The usual choice for a paid product |
| Source-available licence | The source can be read, with limits on use. ELI v3 uses one of these alongside a commercial agreement; using the same pair would be consistent |
| Open-source licence | Anyone may use and modify it. Compatible with selling support or hosted service, not with selling licences |

Whatever is chosen should state: the intended purpose and the prohibited uses; that the output
is decision support and not legal advice; who is provider and who is deployer; the limits on
liability; and what support and security updates are promised, and for how long. The installers
pick up a `LICENSE` file automatically once one exists.

## 2. Liability

| Source of liability | Position |
|---|---|
| **The professional's own** | Unchanged. A lawyer answers to the client and the court for their work; a decision-maker for their decision. Using a tool is not a defence |
| **Contract** | Between provider and deployer, the agreement governs. Limits and exclusions are subject to local law on unfair terms and cannot exclude liability for fraud or, in most places, for death or personal injury |
| **Negligence** | A provider can owe a duty of care for defects. Clear instructions for use, stated limits and documented testing are the practical protection |
| **EU product liability** | Directive (EU) 2024/2853 treats software, including AI, as a product, with liability without fault for defects. It applies to products placed on the market or put into service after 8 December 2026 (Article 2(1), as corrected by the [corrigendum published on 7 May 2026](https://eur-lex.europa.eu/eli/dir/2024/2853/corrigendum/2026-05-07/oj), OJ L 2026/90364; the original text said 9 December, which left products placed on 9 December itself under neither directive). Directive 85/374/EEC still governs products placed on the market before 9 December 2026 (Article 21). The damage it covers is death, personal injury, damage to property and loss of data not used for professional purposes; pure financial loss, the likeliest harm from a legal tool, is not covered. National law may go further |
| **AI Act** | Administrative fines for breach of provider or deployer duties: see [EU AI Act](02_eu_ai_act.md) |
| **Data protection** | Compensation and fines under the GDPR, mainly for the controller: see [Data protection](03_data_protection.md) |

**Insurance.** A deploying firm or chambers should tell its professional-indemnity insurer that
AI-assisted tools are used and confirm cover. A provider should hold technology errors-and-
omissions and cyber cover.

**Claims the provider should not make.** Not "verified citations" without saying what verified
means; not "compliant with the AI Act" before a conformity assessment; not "approved by" any
court. Misleading business-to-business advertising is unlawful in the EU (Directive 2006/114/EC)
and elsewhere.

## 3. EU Cyber Resilience Act

Regulation (EU) 2024/2847 applies to products with digital elements made available on the EU
market in the course of a commercial activity. It requires security by design, a vulnerability
handling process, a software bill of materials, security updates for a declared support period,
and conformity steps including CE marking. Reporting of actively exploited vulnerabilities and
severe incidents applies from 11 September 2026; the main obligations from 11 December 2027.
Software supplied free and not monetised is largely outside it. A high-risk AI system that meets
it is treated as meeting the AI Act's cybersecurity requirement.

State of play here: security controls and a component list exist. A vulnerability-disclosure
contact, a handling process and a support-period commitment do not.

## 4. Rights in legal sources

The law itself is generally free to use; the published form of it often is not.

| Material | Typical position | Check |
|---|---|---|
| Legislation, EU law | Reusable. EUR-Lex content is reusable under the Commission's reuse decision | The terms on the official site |
| Judgments from official court sites | Often reusable, sometimes with conditions | In the UK, the National Archives' licence for Find Case Law treats computational analysis separately: confirm whether a specific licence is needed. In Ireland, check the Courts Service's terms |
| Free aggregators | Terms commonly forbid bulk downloading | Their terms of use |
| Commercial law reports and databases | Headnotes, catchwords, summaries and editorial status signals are the publisher's. Licences usually forbid loading content into other tools or using it with AI | Your subscription agreement. Ask the publisher in writing |
| United States | Judicial opinions and statutes cannot be copyrighted (*Georgia v Public.Resource.Org*, 2020), but editorial additions can, and copying headnotes to build a competing tool has been held not to be fair use (*Thomson Reuters v Ross Intelligence*, D. Del., 2025) | |

Databases may also be protected in the EU by the database right (Directive 96/9/EC). Exceptions
for text and data mining exist (Directive (EU) 2019/790, Articles 3 and 4) but the general one
can be reserved by the rightholder, and the UK's is limited to non-commercial research.

**The control.** A source cannot be approved in ELI Legal until its owner, its licence and a
statement that the terms were reviewed are recorded, and the approval is a decision in a named
person's name. Recording "reviewed" without reviewing defeats it.

The status data matters as much as the text: whether an authority is still good law is only as
reliable as the source's treatment information. A source of judgments with no treatment data
cannot support the current-law check, and the system will say so by holding the finding.

## 5. Model licences

ELI Legal ships no model. Whichever local model a deployer runs has its own licence and often an
acceptable-use policy. Some permit commercial use freely; some restrict it, restrict particular
fields, or differ by model size. Read the licence for the exact model and version, keep a copy,
and record the decision. The system records which model produced what.

## 6. Third-party software in an installed copy

`THIRD_PARTY_NOTICES.md` is generated from the build environment at every build and lists each
component and the licence it declares. Most are permissive (MIT, BSD, Apache-2.0, PSF).

**Qt and PySide6 are LGPL-3.0.** Distributing them obliges the distributor to: keep the copyright
and licence notices; give recipients the licence text; make the library's source available or
point to it; and leave recipients able to replace the library with a modified version. The
installers satisfy the last point by shipping Qt as separate files in a folder rather than
fused into one executable, and must stay that way. The alternative is a commercial Qt licence.

Because the software includes cryptography, export rules may apply to shipping it outside the
EU or the US. Publicly available and mass-market cryptography is generally exempt; confirm
before exporting.

## 7. Name and marks

Before selling under the name, check that "ELI Legal" is free to use as a trade mark for
software and legal services in the territories that matter, and consider registering it.

## 8. Accessibility and procurement

- Public-sector bodies in the EU must make their websites and applications accessible
  (Directive (EU) 2016/2102; the standard is EN 301 549, in practice WCAG 2.1 AA). A court
  deploying the browser application will be asked for a conformance statement. The interface has
  keyboard operation, labels and adequate contrast; **no audit has been done**.
- Public buyers must generally tender, and will ask for security, data-protection and
  accessibility documentation. This folder is the start of that pack.

## 9. Electronic approvals

An approval in ELI Legal is an electronic record tied to a person by passphrase, a second factor
where set up, and a tamper-evident log. It is good evidence of who approved what. It is not a
qualified electronic signature under the eIDAS Regulation and should not be described as one.
