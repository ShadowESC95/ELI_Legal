# Data protection

**Regulation (EU) 2016/679 (GDPR).** It applies in every member state, alongside that state's own
implementing law. The RAIMS use case names three articles as shaping the design, Articles 5, 25
and 32, and takes Ireland's Data Protection Act 2018 as its example of national law; a deployer
elsewhere reads its own state's act in the same places. Notes on the United Kingdom follow at
the end. Not legal advice: a deploying organisation must do its own assessment.

## The three articles the use case names

| Article | What it requires | How the system is built to it | Requirement |
|---|---|---|---|
| **Art. 5** Principles | Lawfulness, fairness and transparency; purpose limitation; minimisation; accuracy; storage limitation; integrity and confidentiality; accountability | One matter, one purpose, no memory across matters and no training on matter data; the audit ledger holds identifiers and hashes, never text; facts are quoted word for word with their location; closing a matter can delete its content; access by role and matter | GDPR-05 |
| **Art. 25** Data protection by design and by default | Measures built into the processing itself, with the protective setting as the default | Network denied by default; a model must run on the same machine; matter isolation enforced in the store, not left to the caller; the least access by default (an administrator sees no matter); logs minimised by a guard that refuses content | GDPR-25 |
| **Art. 32** Security of processing | Measures appropriate to the risk | Proven identity, lock-out and a second factor; a decision needs the passphrase again; a hardened server over TLS; originals stored read-only under their hash; a tamper-evident ledger; the databases and case files encrypted at rest. **Full-disk encryption, backup and patching are the deployer's** | GDPR-32 |

Section 5 below takes Article 5 principle by principle.

## 1. What personal data is involved

Everything in a dispute's papers: parties, witnesses, employees, experts, lawyers, third parties
who happen to be mentioned. It will often include special-category data (health, trade-union
membership, religion, ethnicity, sexual orientation) and data about criminal convictions and
offences. The system also holds data about its users: identifiers, roles, sign-in events and the
decisions they record.

## 2. Who is controller and who is processor

| Party | Usual role | Why |
|---|---|---|
| The deploying court, tribunal, chambers or firm | **Controller** | It decides why and how the papers are processed |
| The provider of ELI Legal | **Neither**, for a copy the deployer installs and runs itself | The provider has no access to the data. This changes if the provider hosts it, or gets access for support: then it is a processor and a written contract under Article 28 is needed |
| The maker of a local model | **Neither** | The model runs on the deployer's machine and sends nothing back. ELI Legal refuses a model on another machine |

**Courts.** A supervisory authority is not competent to supervise courts acting in their judicial
capacity (Article 55(3)); each member state arranges that supervision separately under its own law (Ireland, for example,
through a judge assigned under its Data Protection Act 2018). The rest of the GDPR still applies.

**Criminal matters.** Processing by competent authorities for criminal-justice purposes falls
under the Law Enforcement Directive (EU) 2016/680 and its national implementation, not the GDPR.

## 3. Lawful basis

| Deployer | Likely basis for ordinary data | For special-category data | For criminal-offence data |
|---|---|---|---|
| Court or tribunal | Article 6(1)(e): task in the public interest or official authority | Article 9(2)(f): courts acting in their judicial capacity | Article 10: under official authority |
| Arbitrator, mediator | Article 6(1)(f) legitimate interests, or (b) contract | Article 9(2)(f): establishment, exercise or defence of legal claims | Article 10 and national law |
| Law firm, barrister | Article 6(1)(f) or (b), sometimes (c) | Article 9(2)(f) | Article 10 and the member state's law (for example section 55 of Ireland's 2018 Act) |

Using a new tool does not need a new basis if the purpose is the same, but the deployer must
check that the processing stays necessary and proportionate for that purpose.

## 4. Automated decisions (Article 22)

People have a right not to be subject to a decision based solely on automated processing that
has legal or similarly significant effects. ELI Legal makes no decision. But the Court of
Justice has held that an automated output can itself be the "decision" where the human
decision-maker draws strongly on it (*SCHUFA Holding*, C-634/21, 7 December 2023). The design
answers this only if review is real: the reviewer reads, challenges, and can and does depart
from the output. The system monitors approvals made without any challenge; a deployer should
watch that figure.

## 5. The principles, and what the system does for each

| Principle (Article 5) | What the system does | What the deployer must do |
|---|---|---|
| Lawfulness, fairness, transparency | States what it is and what it relied on | Tell data subjects, where the law requires (see 6) |
| Purpose limitation | One matter, one purpose; no memory across matters; no reuse of data to train anything | Do not repurpose a matter's data |
| Data minimisation | The audit ledger holds identifiers and hashes, not text; chat history is not kept | File only what the matter needs |
| Accuracy | Facts are quoted word for word with their location | Correct the source record if a document is wrong |
| Storage limitation | Each kind of a closed matter's content (papers, analysis, reports, evidence packs) is kept for its own period and then deleted, or its archive's key destroyed, by the routine checks; the decision record goes last | Set the periods for each kind (Compliance, OA-09); apply them |
| Integrity and confidentiality | Access by role and matter; proven identity; network denied; tamper-evident ledger; databases (SQLCipher) and case files (AES-256-GCM) encrypted at rest | Full-disk encryption (the keys are on the same machine); backups kept apart from the keys; a second factor; physical security |
| Accountability | Registers, audit trail, evidence pack | Keep your own records |

## 6. Telling people, and their rights

Controllers must normally tell people how their data is used (Articles 13 and 14) and honour
access, rectification, erasure, restriction and objection. In litigation these are qualified:
by professional secrecy (Article 14(5)(d)), by member-state restrictions for judicial
proceedings and the enforcement of civil claims (Article 23), and by legal privilege, each as
implemented in the member state concerned (in Ireland, sections 60 and 162 of the 2018 Act). The deployer's existing privacy notice and
procedures should be checked and, if needed, extended to mention AI-assisted preparation.

Practical points:
- **Access requests.** The system can show which documents and findings mention a name (search
  in Findings and Evidence). It has no dedicated data-subject export.
- **Erasure.** Closing a matter with deletion removes content; a closed matter's archive is
  erased by destroying its key ("Delete its content for good" in Closed cases, or when its
  retention ends), which makes every copy unreadable, backups included. The audit ledger is kept
  by design; it holds identifiers and hashes, and user identities.
- **User data.** Users are data subjects too. Sign-in events and decisions are kept in the
  ledger permanently; tell them.

## 7. Impact assessment (Article 35)

Almost certainly required: new technology, special-category and criminal-offence data, people
who may be vulnerable, and effects on legal rights. Do it before first use. A template ships in
`src/eli_legal/governance/templates/`. It should cover: the purposes; necessity and
proportionality; the risks to the people in the papers; the measures in this folder and in
[Security and privacy](../4_security/01_security_and_privacy.md); and the residual risk. If the
residual risk stays high, consult the supervisory authority first (Article 36).

Under the AI Act, a public-body deployer must also carry out a fundamental-rights impact
assessment; the two can be done together.

## 8. Security (Article 32) and breaches (Articles 33, 34)

The measures are listed in [Security and privacy](../4_security/01_security_and_privacy.md) and
[Server security](../4_security/04_server_security.md). The software encrypts its databases and case
files at rest, but their keys are on the same machine: the deployer must still encrypt the
machine's disk and keep the saved database key apart from the backups. A breach must be notified to the supervisory authority within 72 hours
of becoming aware of it unless it is unlikely to result in a risk to people, and to the people
affected where the risk is high. Incidents can be recorded in the system; the notification
procedure is the deployer's.

## 9. Transfers outside the EEA (Chapter V)

None, by design. Nothing is sent anywhere. If a deployer changes that, for example by placing
the data folder on a cloud service, Chapter V and the processor rules apply to that choice.

## 10. The model

A model that runs locally receives matter text and returns text; it keeps nothing. Two points
remain for the deployer: whether the model was lawfully developed (the European Data Protection
Board's Opinion 28/2024 addresses when a model can be treated as anonymous and the consequences
of unlawful training), and whether the model's licence permits the use.

## 11. United Kingdom

The UK GDPR and Data Protection Act 2018 follow the same structure. The Data (Use and Access)
Act 2025 changed the rules on automated decision-making: from 5 February 2026 (S.I. 2026/82)
Articles 22A to 22D replace Article 22. A significant decision based solely on automated
processing, meaning one with no meaningful human involvement, is allowed with safeguards: the
person is told, may make representations, may obtain human intervention and may contest it.
Special-category data stays under a stricter rule. Decisions taken before that date stay under
the old Article 22.

ELI Legal takes no decision, and a named person must read and approve what it prepares, so it
is not used for a decision based solely on automated processing. That holds only while the
review is meaningful in fact: a reviewer who approves without reading turns the system's
output into the decision. The Information Commissioner's guidance on AI and data protection
applies.

## 12. Records the deployer should hold

- An entry in the record of processing activities (Article 30).
- The impact assessment, and the fundamental-rights assessment where required.
- The lawful-basis analysis, including for special-category and criminal-offence data.
- A retention schedule for matters, and for the audit ledger.
- A processor contract, if anyone outside the organisation has access.
- The breach procedure, naming who decides and who notifies.
