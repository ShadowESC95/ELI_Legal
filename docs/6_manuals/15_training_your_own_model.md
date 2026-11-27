# Training your own model

An organisation that uses ELI Legal can teach the AI model from its own approved work. It
learns how the organisation chooses facts, frames issues, links them and sets out arguments.
Training happens on the organisation's own machine; nothing is sent anywhere. Every step is
taken by the person the law expects to take it, and every decision is recorded in the audit
ledger.

Training is **off** until the compliance officer switches it on. Read this guide, and
[the law that applies](#the-law-that-applies), before they do.

Open it in the desktop application under **Set-up → Train your own model**. The page has
seven steps, one tab each. On a server or a terminal, the same steps are
`eli-legal training …` ([commands](#the-commands)).

## Who does what

| Step | Who | Role in ELI Legal | Needs the passphrase again |
|---|---|---|---|
| Switch training on; choose what may be learnt | Compliance officer | governance officer (`training.approve`) | yes |
| Allow a case to teach, or stop it | The case's lead (or the compliance officer) | the case's owner | yes |
| Approve, correct or reject each example | A lawyer | supervising solicitor or legal administrator (`training.data`) | no (each decision is recorded) |
| Set up the machine; train; check the model | Technical officer | system or legal administrator (`training.run`) | to start training |
| Approve or retire a trained model | Compliance officer, **never the person who trained it** | governance officer (`training.approve`) | yes |
| Put an approved model into use | Whoever manages the configuration | `config.manage` | yes |

The technical officer never sees case content: examples are for lawyers only. Someone who holds
both the technical and the compliance role still cannot approve a model they trained.

## Human or autonomous

- **Human** (the default): a lawyer approves every example before it can train.
- **Autonomous**: when a run's reviewer approved the report and took nothing out, that run's
  examples count as approved by that review. Examples from a run where the reviewer took
  findings out wait for a lawyer, as in human mode. Training starts by itself once enough new
  approved examples are waiting, and each model is checked when it finishes. The technical
  officer's standing instruction (step 6) says which base model and recipe it uses. The
  autonomous step runs:
  - every ten minutes while the desktop application is open;
  - with the daily routine checks (`eli-legal checks timer --install`);
  - with `eli-legal training auto` on a schedule of your own.

  **Autonomous mode never approves a model and never puts one into use.** A named person does
  both.

## What may be learnt, and what never is

A model cannot forget what it learnt, and it may repeat it later. So each example keeps only
what the task needs:

- **Always taken out:**
  - **names:** the parties', their representatives', and anyone the text names with a title or
    as a witness or signatory. They become `[PARTY 1]`, `[PERSON]`;
  - **contact details and identifying numbers:** email, telephone, IBAN, card, PPSN, Eircode.
- **Taken out unless the compliance officer keeps them, with a reason:** amounts, dates, case
  and invoice references, street addresses.
- **Never kept at all:** a model call about any of the following is not stored even as a
  candidate. It is only counted.
  - health;
  - racial or ethnic origin;
  - political opinions;
  - religious or philosophical beliefs;
  - trade union membership;
  - genetic or biometric data;
  - sex life or sexual orientation (GDPR Art. 9);
  - criminal offences (Art. 10);
  - a child.

Text is matched by words and patterns, which cannot catch everything, so a lawyer still reads
each example in human mode. A lawyer's own correction is cleaned the same way. A rejected
example keeps only the decision; its text is deleted.

**Which cases teach.** By default, only practice cases teach. Real cases teach only when all
of these hold:

1. the compliance officer allows real cases, acknowledging the risk below;
2. the case's lead allows that case;
3. the lead records where and when the client consented to training.

**One client's material in another client's work.** One model learns from every case it is
trained on, and it could repeat one client's facts in another client's report. So:

- no real case may give more than the policy's share of a model (25% by default);
- every model is tested for exactly this before anyone may approve it
  ([step 7](#7-check-approve-and-use)).

The test samples; it cannot prove a model holds nothing. Keep real cases off unless your
solicitor and your data protection officer agree.

**Erasure and withdrawal.** A case's examples are deleted with its content. When a case is
erased, or stopped from teaching, every model trained on it is flagged. A flagged model cannot
be approved, chosen in Settings or put into use. The daily checks name it, and say if it is in
use, so that someone chooses another model.

## The steps

### 1. Before you start

The page sets out the law and the roles. The compliance officer presses **Set the training
policy…** and records:

- that training is on;
- human or autonomous;
- which cases may teach;
- the **impact assessment** that covers training on case material (GDPR Art. 35);
- the **legal basis** for using case material to train;
- the acknowledgement that training **may make the organisation the provider** of the changed
  system (EU AI Act Art. 25);
- what else to take out, and why anything is kept;
- the largest share one real case may give;
- how many approved examples a run needs (40 by default);
- how many are kept back to test each model (10% by default).

### 2. This machine

ELI Legal shows what this machine can train on and exactly what setting up will install. It
then installs it into a folder of its own, `<data folder>/training/env`. ELI Legal itself is
never changed, and **Remove them** deletes the folder.

| This machine has | Training uses | PyTorch comes from |
|---|---|---|
| An NVIDIA card | CUDA (the build matching the driver: 13.0, 12.8, 12.6 or 11.8) | download.pytorch.org |
| An AMD card, on Linux | ROCm 6.4 | download.pytorch.org |
| Apple silicon | Metal | the Python Package Index |
| A dedicated Intel card | XPU | download.pytorch.org |
| None of these | the processor (slow: small models, short runs) | download.pytorch.org |
| An Intel Mac | cannot train: PyTorch is no longer built for it. Train elsewhere and copy the model here | — |

What is installed, in order:

1. **Python 3.12.** uv is used when it is installed, and fetches Python itself. Otherwise a
   Python 3.10–3.12 found on the machine is used.
2. **PyTorch 2.6 or later,** built for the accelerator above.
3. **The training libraries:** transformers 4.57.6, peft 0.17.1, accelerate, safetensors,
   sentencepiece, protobuf, numpy and huggingface_hub. These versions work together and with
   llama.cpp's converter.
4. **bitsandbytes,** on NVIDIA cards only: 4-bit training for bases too large for the card.
5. **llama.cpp's converter,** taken from the source of the llama-cpp-python release ELI Legal
   runs, so the model file it writes is one ELI Legal can load.
6. **A check** of what was installed and what it can train on.

Setting up downloads 3–6 GB once, and needs about 8 GB of disk. Allow as much again for each run
(a base model, its merged copy and the model file it makes).

### 3. The base model

Choose the folder of a model in Hugging Face form: `config.json`, the weights (`.safetensors`)
and the tokenizer. A GGUF file cannot be trained.

- **Licence.** Choose an instruct model whose licence allows fine-tuning and use in your work.
- **Memory.** ELI Legal estimates the memory the run needs from the weights' size and says
  whether the card has it. As a rule of thumb:
  - 1–4 billion weights suits an 8 GB card;
  - larger models need 4-bit, on NVIDIA.
- **Recipe:**
  - **Light:** one pass;
  - **Standard:** two passes;
  - **Thorough:** three passes, longer texts.
- **The model file it makes:**
  - **Q4_K_M:** smallest, suits an 8 GB card;
  - **Q5_K_M:** a little larger and closer to the original;
  - **Q8_0:** near the original;
  - **F16:** full size.

### 4. Which cases teach

With a case open, its lead presses **Allow this case to teach…**. They give the basis, and for a
real case the client's consent. **Stop this case teaching…** deletes its examples and flags any
model trained on it.

### 5. Training examples

**Take examples from approved runs** turns each model call of an approved run into a candidate.
Only these steps give examples:

- choosing facts;
- proposing issues;
- linking facts to issues;
- arguments;
- support checks.

The chat never does. Each candidate shows what the model was asked, the answer to learn, and
what was taken out. A lawyer chooses **Approve**, **Correct the answer…** (JSON, as the step
expects, with a reason) or **Reject…**.

### 6. Train

The technical officer names the model and presses **Start training**. The trainer:

1. loads the base model on the accelerator;
2. trains a LoRA adapter on the answers only (the question is context, never learnt);
3. merges it into the base;
4. writes the GGUF with llama.cpp's converter;
5. makes it smaller with ELI Legal's own llama.cpp;
6. records its SHA-256.

The page shows each step and the loss as it falls. **Cancel the run** stops it between steps.
The examples given to the trainer are deleted when the run ends, however it ends. A run
continues if the window closes, and the page picks it up again.

For autonomous mode, **Use step 3's choices for autonomous runs** records the standing
instruction. Runs it starts are recorded in the technical officer's name.

### 7. Check, approve and use

**Check it** puts every kept-back example to the trained model, through the same loader ELI
Legal uses. It then puts three questions with no case material at all. The model must:

- give **usable** answers (95% at least);
- **never say who should win**;
- **agree** with the approved answers at least as well as the model in use;
- **repeat nothing it learnt**:
  - no wording distinctive to another case;
  - no real name of anyone in the cases it learnt from;
  - nothing of either when asked with no case material.

If any check fails, the model cannot be approved. Each model's **datasheet** records what it
learnt from:

- each case, with its basis, its consent and who allowed it;
- who approved the examples;
- what was taken out, and what was never kept;
- the largest share any case gave;
- the gaps: steps with few or no examples, one jurisdiction, one case.

Read it before approving. It is the data part of the technical documentation (EU AI Act
Annex IV) and of ISO/IEC 42001's records (A.7).

The compliance officer presses **Approve it…** and gives reasons. **Put it into use…** makes it
the drafting model for every case. **Real cases then need a new deployment authorisation,**
because the one in force is pinned to the model it was given for. **Retire it…** withdraws a
model.

## The law that applies

- **EU AI Act** (Regulation (EU) 2024/1689, as amended by Regulation (EU) 2026/1744).
  - **Risk class.** Preparing cases for a court or tribunal is high-risk (Annex III
    point 8(a)).
  - **Becoming the provider.** Training the model is a substantial modification of the
    system: the organisation may become its provider (Art. 25(1)(b)).
  - **The provider's duties:**
    - data governance (Art. 10);
    - technical documentation (Art. 11, Annex IV);
    - logs (Art. 12);
    - human oversight (Art. 14);
    - accuracy and robustness (Art. 15);
    - a quality management system (Art. 17);
    - a new conformity assessment (Art. 43(4)).
  - **Dates.** Annex III obligations apply from 2 December 2027.
- **GDPR.**
  - **A new purpose.** Training is a new purpose for case material. It needs a legal basis
    (Art. 6, with the compatibility test of Art. 6(4) or consent) and an impact assessment
    (Art. 35).
  - **Minimisation.** The examples are minimised (Art. 5(1)(c), Art. 25), and special
    categories and criminal-offence data are never kept (Arts. 9, 10).
  - **Erasure and objection.** These reach the models trained on the data (Arts. 17, 21).
  - **Not anonymous.** A trained model is not anonymous while what it learnt can be drawn
    back out of it (EDPB Opinion 28/2024). That is what the recall test looks for.
- **Professional confidentiality.**
  - **Mixing clients.** One model serving every client is the risk to manage.
  - **Before real cases teach:** ask your professional body's guidance and the client's
    consent.
- **ISO/IEC 42001.** The policy, the roles, the datasheet, the checks and the approvals are
  the records an AI management system expects:
  - A.2: policy;
  - A.3: roles;
  - A.5: impact assessment;
  - A.6.2: life cycle, verification and validation;
  - A.7: data.

Before training on real cases, do **OA-28** under Compliance: extend the impact assessment,
decide the basis and the consent wording, and take on the provider's duties. The controls are
DG-01.47 to DG-01.51, MO-01.11 and HO-01.15. The risks are R-25 to R-28.

## The commands

```
eli-legal training status                        # the policy, the examples, the models
eli-legal training policy --dpia DPIA-2026-07 --legal-basis "…" --acknowledge-provider \
                          [--mode autonomous] [--scope consented --acknowledge-cross-matter] \
                          [--keep dates --keep-reason "…"]          # compliance officer
eli-legal training allow MATTER --basis "…" [--consent "…"]          # the case's lead
eli-legal training allow MATTER --stop
eli-legal training build                                             # a lawyer
eli-legal training examples [--status candidate] [--full]
eli-legal training decide EXAMPLE approve|correct|reject [--reason "…"] [--answer-file a.json]
eli-legal training machine                                           # technical officer
eli-legal training setup
eli-legal training train --name "Firm model 1" --base /models/Qwen2.5-3B-Instruct \
                         [--recipe light|standard|thorough] [--four-bit] [--quantize q4_k_m] [--wait]
eli-legal training evaluate MODEL
eli-legal training show MODEL                                        # checks and datasheet
eli-legal training approve MODEL --reasons "…"                      # compliance officer
eli-legal training use MODEL                                         # config.manage
eli-legal training retire MODEL --reason "…"
eli-legal training instruct --base /models/… [--recipe …] [--quantize …]   # autonomous mode
eli-legal training auto                                              # a schedule's step
```

`--python PATH` (on `train` and `auto`) uses a Python that already has PyTorch, transformers,
peft, accelerate, safetensors and sentencepiece, in place of the environment of step 2.

## When something goes wrong

| What you see | What to do |
|---|---|
| "No Python 3.10, 3.11 or 3.12 was found" | Install uv (docs.astral.sh/uv) or Python 3.12, then check again |
| "missing: sentencepiece" (or another package) | Set the components up again (step 2) |
| "the converter failed" | Read the run's log (step 6): an architecture llama.cpp does not convert, or a missing package |
| The run stops with "out of memory" | Use the light recipe, 4-bit (NVIDIA), a smaller base, or close what else uses the card |
| "has said nothing for 2 hours and left no outcome" | The machine restarted or the trainer was ended: start the run again |
| "its evaluation does not support approval" | Read the reasons in step 7: more or better examples, fewer passes, or a different base |
| "trained on matter … which may no longer teach" | The case was erased, withdrawn or is outside the scope now: retire the model and train another |

The run's own folder holds everything about it:
`<data folder>/training/models/<model id>/`, with `trainer.log`, `outcome.json`, the
adapter and the model file.
