# Models

A model is optional. Without one, facts are selected by rule and no arguments are drafted.

## Choices

| Backend | What it is |
|---|---|
| GGUF file | A model file run inside ELI Legal by llama.cpp, as ELI v2 and v3 run theirs |
| Model server on this machine | Ollama, a llama.cpp server or LM Studio, on this computer only |
| ELI v3's model | When ELI Legal is opened from ELI v3: the model ELI v3 has loaded, as ELI v3 placed it |
| None | Rules only |

Choose in Settings, Model; at the first administrator sign-in; or with `eli-legal model use`.
Changing the model is a decision recorded under your name.

## Where GGUF models are found

ELI Legal's own `models` folder; `ELI_LEGAL_MODELS_DIR` and `ELI_MODELS_DIR`; ELI v3's and ELI v2's
model folders (`~/.local/share/ELI_v3/models`, `~/.local/share/ELI_v2/models`, and the Windows and
macOS equivalents); `~/.local/opt/eli/models`; LM Studio and GPT4All folders; `~/models`; and any
folders an administrator adds (`ELI_LEGAL_MODELS_DIRS`). Vision projectors, embedders and partial
downloads are left out. Browse… picks any other file.

`eli-legal model list` shows what was found.

## How a GGUF model is placed on the machine

Nothing about a model or a machine is assumed. When a model loads, ELI Legal reads:

- **the machine**, as it is at that moment: processor threads, the memory free, the graphics
  card and the graphics memory that is *free* (the desktop, a browser or another model runner
  already hold part of a card), and which other programs hold it;
- **the model's own file**: the size of each of its layers and the memory its context costs per
  token. The first load replaces that second figure with llama.cpp's own measurement.

From those it decides the context length, how many layers go on the graphics card, the batch and
the threads. What gives way when not everything fits: the batch, then layers; the context the
work needs is kept. A mixture-of-experts model that does not fit whole has every layer's shared
weights placed on the card and its experts left in system memory.

If llama.cpp refuses the result for lack of memory, the placement is worked out again from the
memory free then with a wider margin, then on the processor. What is shown and written to the
audit trail (`model_loaded`) is llama.cpp's own account of the load, not the request: the context
it holds, the layers it placed on the card, and the llama.cpp that ran it.

Settings, Model shows the machine and, for the model selected, how it would be placed if loaded
now, with the reasons. `eli-legal model plan <file>` prints the same.

| Setting | Meaning |
|---|---|
| Context length | **automatic** (0): what the steps of the work need, where the machine can hold it. A number is your choice; it is reduced only if it cannot be held |
| Layers on the graphics card | **automatic** (-1): as many as fit. 0: the processor only. A number: at most that many |
| Processor threads | **automatic** (0): all but one where the processor does the work, all but two where a card does |
| Verifier | Optional. A different model, used only to check propositions; the same model cannot check itself. It is placed in the memory the drafting model leaves |

The model is loaded at its first use and kept loaded. A model that is no longer chosen is
unloaded at once. If the configured file is missing at start-up, ELI Legal says so and runs
without a model.

Each step of the work fits its material to the context the model holds. Where not all of it fits,
the step leaves out whole items, never part of one, and says which: in chat, "The model's context
holds 9 of the 14 sources; its summary does not draw on D10, …"; in a run, as a note on the report.
A reply cut off by the token limit is refused, not used.

For this machine only, in `.env` in the data folder or the environment:

| Variable | Meaning |
|---|---|
| `ELI_LEGAL_GGUF_FIT` | `balanced` (default: keep the context, give up layers), `max_gpu` (keep the layers, give up context), `max_ctx` |
| `ELI_LEGAL_VRAM_RESERVE_MB` | Graphics memory left unallocated (default 700; 400 for graphics that share system memory) |
| `ELI_LEGAL_RAM_BUDGET_PERCENT` | Share of the free system memory a model may take, 10 to 75 (default 60; 70 on a processor-only machine of 16 GB or less) |
| `ELI_LEGAL_GPU` | `auto` (default), `own` (only ELI Legal's own graphics pack), `off` (processor only) |

## The graphics card

The llama.cpp inside ELI Legal runs on the processor, so that it starts on every machine. To use a
graphics card it switches on a *graphics pack*: a complete llama.cpp built for the card (CUDA for
NVIDIA; Vulkan for NVIDIA, AMD and Intel). A pack is used only after it has been started in a
process of its own and shown that it can place layers on this machine's card; otherwise the
built-in llama.cpp runs, on the processor, and Settings, Model says why. On macOS the built-in
llama.cpp already uses the card (Metal).

Where a pack comes from, in the order tried. **Nothing is downloaded: ELI Legal makes no
connection for this.**

1. One an administrator installed from a file: Settings, Model, "Install a graphics pack from a
   file…", or `eli-legal gpu install <file>`. A recorded decision.
2. ELI v3's or ELI v2's, if either is installed on the machine and has set up its own.
3. The Vulkan pack shipped inside the Linux and Windows installers, unpacked at first need.

An NVIDIA card is tried with CUDA first and then Vulkan; other cards with Vulkan. The pack files
are the ones published with ELI
(`cuda-llama_cpp_python-<version>-….whl`, `vulkan-llama_cpp_python-<version>-….whl`); an installed
copy uses only a pack of the same llama.cpp version as its built-in one.

On Linux a pack needs a system as new as the one the packs are built on (C library 2.38: Ubuntu
24.04, Debian 13, Fedora 39, or newer). On an older system the pack's own test fails, the reason
is shown in the system's own words, and the model runs on the processor. ELI Legal uses the
system's C++ runtime, not a copy of its own, for the same reason: a pack and the machine's
graphics drivers need the newer one.

`eli-legal gpu status` shows the machine, the llama.cpp in use and the packs found.

## Installing GGUF support from source

`pip install 'eli-legal[gguf]'`. llama.cpp is compiled where no prebuilt package exists, which
needs CMake and a C/C++ compiler, and that build runs on the processor. A source installation
uses a graphics pack in the same way as an installed copy. The installers include llama.cpp where
it built on the release machine; `eli-legal model show` reports `gguf_supported`.

The browser application lists GGUF models by name only; the server never shows their paths.
