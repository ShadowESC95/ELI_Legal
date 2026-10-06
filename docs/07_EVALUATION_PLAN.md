# Evaluation

Legal competence has to be shown separately from the general competence of whatever model is used.

## What exists

A synthetic dispute (`src/eli_legal/demo.py`) in a fictional jurisdiction, with one planted defect
per control, and tests that assert each is caught for the stated reason
(`tests/evaluation/test_gold_matter.py`). The scorecard test requires every planted defect to be
held and nothing planted as sound to be held. `tests/evaluation/test_model_mode.py` scripts a
model that misbehaves in each known way.

A run with a real 8-billion-parameter local model completed the lifecycle with every drafted
argument attributed and none stating an outcome. It also misattributed some arguments to the
wrong party. That is the kind of error the software cannot detect and the reviewer must; a larger
model will do better, and the report labels the arguments accordingly.

## What does not exist yet

- Representative **real** matters with known answers, per jurisdiction and profile.
- Thresholds fixed before testing, for: document coverage; citation recognition recall per pack;
  stale-authority detection; false holds; fact-selection recall; argument attribution accuracy;
  reviewer correction rate.
- A reviewer study measuring whether reviewers actually check what they approve.
- Testing against a live legal source with real treatment data.

Keep failed and inconclusive cases in the evidence set; do not discard them.
