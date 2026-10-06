# Data protection

GDPR (Regulation (EU) 2016/679), with notes on the UK. Not legal advice. A deploying organisation
must do its own assessment; this document is a starting point for it.

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
capacity (Article 55(3)); member states arrange that supervision separately (in Ireland, through
a judge assigned under the Data Protection Act 2018). The rest of the GDPR still applies to them.

**Criminal matters.** Processing by competent authorities for criminal-justice purposes falls
under the Law Enforcement Directive (EU) 2016/680 and its national implementation, not the GDPR.

## 3. Lawful basis

| Deployer | Likely basis for ordinary data | For special-category data | For criminal-offence data |
|---|---|---|---|
| Court or tribunal | Article 6(1)(e): task in the public interest or official authority | Article 9(2)(f): courts acting in their judicial capacity | Article 10: under official authority |
| Arbitrator, mediator | Article 6(1)(f) legitimate interests, or (b) contract | Article 9(2)(f): establishment, exercise or defence of legal claims | Article 10 and national law |
| Law firm, barrister | Article 6(1)(f) or (b), sometimes (c) | Article 9(2)(f) | Article 10 and national law (in Ireland, section 55 of the 2018 Act) |

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
| Storage limitation | Closing a matter can delete documents, text and indexes while keeping the decision record | Set retention periods; apply them |
| Integrity and confidentiality | Access by role and matter; proven identity; network denied; tamper-evident ledger | Encrypted storage; backups; a second factor; physical security |
| Accountability | Registers, audit trail, evidence pack | Keep your own records |

## 6. Telling people, and their rights

Controllers must normally tell people how their data is used (Articles 13 and 14) and honour
access, rectification, erasure, restriction and objection. In litigation these are qualified:
by professional secrecy (Article 14(5)(d)), by member-state restrictions for judicial
proceedings and the enforcement of civil claims (Article 23), and by legal privilege (in
Ireland, sections 60 and 162 of the 2018 Act). The deployer's existing privacy notice and
procedures should be checked and, if needed, extended to mention AI-assisted preparation.

Practical points:
- **Access requests.** The system can show which documents and findings mention a name (search
  in Findings and Evidence). It has no dedicated data-subject export.
- **Erasure.** Closing a matter with deletion removes content. The audit ledger is kept by
  design; it holds identifiers and hashes, and user identities.
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
[Server security](../4_security/04_server_security.md). The software does not encrypt data at
rest; the deployer must. A breach must be notified to the supervisory authority within 72 hours
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
Act 2025 changed the rules on automated decision-making and other points; check the provisions
in force. The Information Commissioner's guidance on AI and data protection applies.

## 12. Records the deployer should hold

- An entry in the record of processing activities (Article 30).
- The impact assessment, and the fundamental-rights assessment where required.
- The lawful-basis analysis, including for special-category and criminal-offence data.
- A retention schedule for matters, and for the audit ledger.
- A processor contract, if anyone outside the organisation has access.
- The breach procedure, naming who decides and who notifies.
