# ELI Legal documentation

Everything about the project in one place: what it is, what it must do, how it is built, how it
is secured, the legal questions it raises, and how to install and use it.

**Read this first.** ELI Legal is working software that has not been conformity-assessed,
validated on real matters, or reviewed by a lawyer qualified in your jurisdiction. The legal
documents here identify issues and point to the law; they are not legal advice. Have them
reviewed by qualified counsel before you rely on them or deploy the system.

## Where to start

| You are | Read |
|---|---|
| Deciding whether to use it | [Overview](1_project/01_overview.md), then [Legal overview](5_legal_and_compliance/01_legal_overview.md) |
| A judge, tribunal member, arbitrator, mediator, solicitor or barrister | [Quick start](6_manuals/02_quick_start.md), [User manual](6_manuals/03_user_manual.md), [Instructions for use](6_manuals/08_instructions_for_use.md) |
| Installing or running it | [Installation](6_manuals/01_installation.md), [Administrator manual](6_manuals/04_administrator_manual.md), [Server security](4_security/04_server_security.md) |
| A data-protection officer or compliance lead | [Legal and compliance](5_legal_and_compliance/), [Security and privacy](4_security/01_security_and_privacy.md) |
| A developer or auditor | [Architecture](3_architecture/01_architecture.md), [Requirements](2_requirements/01_requirements.md), [Test matrix](2_requirements/03_test_matrix.md) |

## Contents

### 1. Project
| Document | What it covers |
|---|---|
| [01 Overview](1_project/01_overview.md) | What ELI Legal is, who it is for, what it does and does not do, its parts, its status |
| [02 Charter](1_project/02_charter.md) | Purpose, scope and boundaries |
| [03 Decisions](1_project/03_decisions.md) | The design decisions and why they were taken |
| [04 Roadmap](1_project/04_roadmap.md) | What is done and what remains |
| [05 Glossary](1_project/05_glossary.md) | The terms used across the system and these documents |

### 2. Requirements
| Document | What it covers |
|---|---|
| [01 Requirements](2_requirements/01_requirements.md) | Functional, governance, security and other requirements, each tied to a control |
| [02 System requirements](2_requirements/02_system_requirements.md) | Hardware, operating systems, software, network, browsers, sizing |
| [03 Test matrix](2_requirements/03_test_matrix.md) | Which tests prove what |
| [04 Evaluation plan](2_requirements/04_evaluation_plan.md) | How accuracy must be measured before reliance |

### 3. Architecture
| Document | What it covers |
|---|---|
| [01 Architecture](3_architecture/01_architecture.md) | Layers, the workflow, where each control lives |
| [02 Data model](3_architecture/02_data_model.md) | Records and how they relate |
| [03 ELI v3 integration](3_architecture/03_eli_v3_integration.md) | Loading ELI Legal into ELI v3 as an edition |
| [04 Source connector standard](3_architecture/04_source_connector_standard.md) | What a legal-source connector must do |
| [05 Jurisdiction packs](3_architecture/05_jurisdiction_packs.md) | How legal systems are described as data |
| [06 API reference](3_architecture/06_api_reference.md) | Every server operation (generated from the code) |

### 4. Security
| Document | What it covers |
|---|---|
| [01 Security and privacy](4_security/01_security_and_privacy.md) | Controls and their limits |
| [02 Threat model](4_security/02_threat_model.md) | What can go wrong and what stops it |
| [03 Evidence and audit standard](4_security/03_evidence_and_audit_standard.md) | The ledger, its guarantees, the evidence pack |
| [04 Server security](4_security/04_server_security.md) | How the server is protected and how to deploy it safely |

### 5. Legal and compliance
| Document | What it covers |
|---|---|
| [01 Legal overview](5_legal_and_compliance/01_legal_overview.md) | Every legal concern in one table, with status and owner |
| [02 EU AI Act](5_legal_and_compliance/02_eu_ai_act.md) | **The governing regime.** High-risk under Annex III 8(a); every provision named in the use case, article by article, with evidence and state |
| [03 Data protection](5_legal_and_compliance/03_data_protection.md) | GDPR, led by Articles 5, 25 and 32: roles, lawful basis, special categories, impact assessment |
| [04 Professional and judicial duties](5_legal_and_compliance/04_professional_and_judicial_duties.md) | Privilege, confidentiality, competence, court rules on AI, judicial guidance, arbitration, mediation |
| [05 Liability, intellectual property and licensing](5_legal_and_compliance/05_liability_ip_and_licensing.md) | Liability, product rules, source licences, model licences, open-source obligations, this product's own licence |
| [06 Jurisdiction notes](5_legal_and_compliance/06_jurisdiction_notes.md) | The Union layer that applies in every member state; the national layer to find in each; Ireland as the worked example; outside the Union |
| [07 Open questions for counsel](5_legal_and_compliance/07_open_questions_for_counsel.md) | What a qualified lawyer must decide before deployment |
| [08 RAIMS traceability](5_legal_and_compliance/08_raims_traceability.md) | Every instrument named in the use case, traced to requirement rows, controls and tests |
| [09 ISO/IEC 42001](5_legal_and_compliance/09_iso_iec_42001.md) | The management-system clauses and Annex A controls the use case selects |

Working forms for a deploying organisation ship with the software under
`src/eli_legal/governance/templates/`: an impact assessment (fundamental rights and data
protection together), a classification assessment, a change assessment and an incident record.

### 6. Manuals
| Document | What it covers |
|---|---|
| [01 Installation](6_manuals/01_installation.md) | Installers for each system, installing from source, upgrading, removing |
| [02 Quick start](6_manuals/02_quick_start.md) | From nothing to a reviewed report in fifteen minutes, on a synthetic matter |
| [03 User manual](6_manuals/03_user_manual.md) | The work, step by step, for each kind of user |
| [04 Administrator manual](6_manuals/04_administrator_manual.md) | Users, roles, sources, the model, backups, upgrades |
| [05 Desktop application](6_manuals/05_desktop_application.md) | Each tab of the desktop application |
| [06 Web application and server](6_manuals/06_web_application_and_server.md) | Starting the server, signing in from a browser |
| [07 Command-line reference](6_manuals/07_command_line_reference.md) | Every command (generated from the code) |
| [08 Instructions for use](6_manuals/08_instructions_for_use.md) | Intended purpose, limits and what the user must do |
| [09 Operations runbook](6_manuals/09_operations_runbook.md) | Day-to-day operation and incident response |
| [10 Troubleshooting](6_manuals/10_troubleshooting.md) | Common problems and what to do |
| [11 Laws & Standards](6_manuals/11_laws_and_standards.md) | The law, regulation and standards packages applied to each matter, and your own |
| [12 Models](6_manuals/12_models.md) | GGUF files, model servers, ELI v3's model |

## Keeping these documents true

- The API and command-line references are generated: `python scripts/generate_reference_docs.py`.
- The requirement, control and risk registers are data, shipped in the package, and checked
  against the code and tests by `eli-legal governance` on every commit.
- Third-party licences are regenerated at each build: `python scripts/third_party_notices.py`.
- Everything else is written by hand and dated by the commit that last changed it. Where a
  document states a legal position, check the primary source: law and guidance change.
