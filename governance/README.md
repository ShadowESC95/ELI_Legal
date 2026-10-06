# Governance workspace

| File | What it is |
|---|---|
| `requirements_register.csv` | Each legal or standards requirement, in plain words, the controls that address it, and what remains for the organisation. Status is `implemented` (a tested control does it), `partial` (the software supports it; an organisational step is still needed) or `organisational` (software cannot do it). |
| `control_register.csv` | Each control, the code that implements it, the tests that exercise it, the evidence it produces, and who owns it. |
| `risk_register.csv` | Each risk as cause, event and impact, its controls, and the residual risk stated plainly. |
| `provider_deployer_matrix.csv` | Who is responsible (R), consulted (C) or informed (I): provider, deployer, technical/security owner. |
| `templates/` | Forms to complete for a real deployment. |

`eli-legal governance` (and CI) fails if a control names a file or a test that does not exist, if
a risk or requirement refers to an unknown control, or if a control is linked to nothing.

**Read these as working aids, not as legal advice or as proof of compliance.** The references are
to the EU AI Act, the GDPR and ISO/IEC 42001:2023 as mapping aids; check each against the official
text and the current application dates. A passing test shows a control behaves as designed on the
test inputs. It does not show the control is effective on real matters, and no register here is a
conformity assessment.

Evidence that a control *operated* on a given run is not kept here. It is in that run's evidence
pack (`eli-legal evidence M R`).
