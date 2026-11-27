"""Training the organisation's own model, with people deciding at each point that matters.

    record (each run's model calls, sealed with the matter)
      → examples (from runs a named reviewer approved, of matters whose lead allowed it,
        names replaced) → a person approves, corrects or rejects each (or, in autonomous mode,
        an example the reviewer accepted unchanged is approved by that review)
      → train (a separate environment on this machine: LoRA on a base model the organisation
        chose, merged and written as a GGUF file ELI Legal loads)
      → evaluate (on examples kept back, against the model in use)
      → a second person approves it → it can be used: on practice matters at once, on real
        matters once a deployment authorisation covers it (the authorisation is pinned to the
        model).

Everything a training run learnt from is recorded with it; when a matter's content is erased,
the models trained on it say so.
"""
