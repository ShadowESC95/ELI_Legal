# Models

A model is optional. Without one, facts are selected by rule and no arguments are drafted.

## Choices

| Backend | What it is |
|---|---|
| GGUF file | A model file run inside ELI Legal by llama.cpp, as ELI v2 and v3 run theirs |
| Model server on this machine | Ollama, a llama.cpp server or LM Studio, on this computer only |
| ELI v3's model | When ELI Legal is opened from ELI v3: the model ELI v3 has loaded |
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

## Settings

| Setting | Meaning |
|---|---|
| Context length | Tokens the model can hold; 8192 by default |
| Layers on the graphics card | 0 runs on the processor; -1 puts every layer on the card |
| Processor threads | 0 chooses for you |
| Verifier | Optional. A different model, used only to check propositions; the same model cannot check itself |

The model is loaded on first use and kept loaded. If the configured file is missing at start-up,
ELI Legal says so and runs without a model.

The browser application lists GGUF models by name only; the server never shows their paths.

## Installing GGUF support from source

`pip install 'eli-legal[gguf]'`. llama.cpp is compiled where no prebuilt package exists, which
needs CMake and a C/C++ compiler. The installers include it where it built on the release
machine; `eli-legal model show` reports `gguf_supported`.
