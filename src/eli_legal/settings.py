from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from eli_legal.paths import home_dir

_PACKAGED_CONFIG = Path(__file__).resolve().parent / "config"


HOME = home_dir()
BASE = HOME if HOME is not None else Path(".")
ENV_FILE = BASE / ".env"


def _config(name: str) -> Path:
    """A deployment's own config/<name> if it exists, else the default shipped in the package."""
    local = BASE / "config" / name
    return local if local.exists() else _PACKAGED_CONFIG / name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE), env_prefix="ELI_LEGAL_", extra="ignore"
    )

    env: str = "development"
    mode: str = "standalone"  # standalone | eli_v3
    db_path: Path = BASE / "data" / "eli_legal.sqlite3"
    # The audit ledger lives in its own database so its file permissions can differ.
    audit_db_path: Path = BASE / "data" / "audit.sqlite3"
    audit_key_file: Path = BASE / "secrets" / "audit_hmac.key"
    data_dir: Path = BASE / "data" / "matters"
    artifacts_dir: Path = BASE / "artifacts"
    policy_file: Path = _config("policy.default.json")
    jurisdictions_dir: Path = _config("jurisdictions")
    workflow_file: Path = _config("workflows/case_preparation.json")
    law_calendar_file: Path = _config("law_calendar.json")
    # How often the routine checks run on their own, in hours, and after how many days a law
    # package summary is due to be checked against the official text again.
    checks_every_hours: float = 24.0
    # Hard offline at every start: the kernel refuses every network connection (see
    # security/hard_offline.py). Live legal sources and a model server cannot be used.
    hard_offline: bool = False
    law_review_days: int = 180
    # Offered first when a matter is opened. EU: Union law, and any member state's decisions by
    # their European Case Law Identifier. Choose a national pack where one exists.
    default_jurisdiction: str = "EU"
    network_default: str = "deny"
    log_level: str = "INFO"

    # Inference. "none" runs every step that does not need a model.
    #   gguf           a GGUF model file run in this process by llama.cpp (as ELI v2 and v3 do)
    #   openai_compat  a model server on this machine (Ollama, llama.cpp server, LM Studio)
    #   eli_v3         ELI v3's own loaded model, when ELI Legal is launched from ELI v3
    inference: str = "none"
    inference_url: str = "http://127.0.0.1:11434/v1"
    inference_model: str = ""  # a model name for a server; a file path for gguf
    inference_api_key: str = ""
    verifier_model: str = ""  # a different model, used only to check propositions
    inference_timeout: float = 300.0
    # GGUF. Context: 0 sizes it to the model and to this machine as they are when the model
    # loads; a number is a choice, reduced only if it cannot be held. Layers on the graphics
    # card: -1 as many as fit, 0 the processor only, a number at most that many. Threads: 0
    # chooses. gguf_fit says what gives way first when not everything fits: balanced (the
    # layers, keeping the context), max_gpu (the context, keeping the layers) or max_ctx.
    gguf_context: int = 0
    gguf_gpu_layers: int = -1
    gguf_threads: int = 0
    gguf_fit: str = "balanced"
    # Extra folders to look for GGUF models in, separated as on PATH.
    models_dirs: str = ""
    # Offer to choose a model when an administrator signs in and none is set.
    model_prompt: bool = True
    # Searching by meaning (legal/semantic.py). "auto": the first embedding model found in the
    # model folders (a GGUF whose name says it embeds, such as bge-small-en-v1.5 or
    # nomic-embed-text-v1.5); a path names one; "none" switches it off. It changes which passages
    # research offers and in what order, never what is verified. Runs on this machine.
    embedding_model: str = "auto"
    # At most this many passages are embedded during one run; the rest are found by their words
    # until a later run, or "eli-legal source index", embeds them.
    embedding_budget: int = 20000

    # How long a command-line sign-in lasts before the passphrase is needed again.
    session_hours: float = 8.0
    # After this many wrong passphrases or codes in a row, the account is refused for a while.
    lockout_threshold: int = 5
    lockout_minutes: float = 15.0

    # The server. It listens on this machine only unless told otherwise, and will not listen
    # beyond it without TLS.
    server_host: str = "127.0.0.1"
    server_port: int = 8443
    server_tls_cert: Path | None = None
    server_tls_key: Path | None = None
    server_allowed_hosts: str = ""  # extra names this server answers to, comma-separated
    server_session_hours: float = 8.0
    server_idle_minutes: float = 30.0
    # auto: required whenever the server is reachable from other machines.
    server_require_second_factor: str = "auto"  # auto | true | false
    server_max_upload_mb: int = 250
    # A corpus is loaded from a folder on the server, and only from inside this one.
    import_root: Path = BASE / "imports"


settings = Settings()
