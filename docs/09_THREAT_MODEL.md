# Threat model

Each threat maps to controls in `governance/control_register.csv` and risks in
`governance/risk_register.csv`, where the tests are named.

| Threat | Controls |
|---|---|
| Stale, overruled or superseded authority | C-09, C-11 |
| Invented or mis-cited authority | C-08, C-11 |
| Real authority cited for something it does not say | C-10 |
| Instruction hidden in a matter file | C-07, C-21, C-25 |
| Poisoned or unlicensed source | C-03 |
| Leakage between matters | C-01, C-02 |
| Over-broad tools; shell, web or desktop access | C-04, C-24, C-25 |
| Approval by an unauthorised person or by the system | C-14, C-28 |
| Report altered between review and release | C-15, C-20 |
| Audit record edited, truncated or rolled back | C-16, C-17 |
| Model states the outcome or invents particulars | C-13 |
| Confidential mediation material disclosed | C-20 |
| Silent change of model, prompt, tool or corpus | C-22 |
| Reviewer approves without reviewing | C-14, C-22 (signal only) |
| Disk theft | not controlled by the software (R-14) |
