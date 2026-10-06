from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PACKAGED_CONFIG = Path(__file__).resolve().parent / "config"


def home_dir() -> Path | None:
    """Where an installed copy keeps its databases, key and settings.

    ``ELI_LEGAL_HOME`` wins. An installed (frozen) build uses the per-user application data
    directory of the operating system. A source checkout returns None and keeps using the
    working directory, so a developer's data stays beside the code.
    """
    explicit = os.environ.get("ELI_LEGAL_HOME", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    if getattr(sys, "frozen", False):
        if os.name == "nt":
            root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            return Path(root) / "ELI Legal"
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "ELI Legal"
        root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return Path(root) / "eli-legal"
    return None


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
    # Offered first when a matter is opened. EU: Union law, and any member state's decisions by
    # their European Case Law Identifier. Choose a national pack where one exists.
    default_jurisdiction: str = "EU"
    network_default: str = "deny"
    log_level: str = "INFO"

    # Inference. "none" runs every step that does not need a model.
    inference: str = "none"  # none | openai_compat (ELI v3 supplies its own when hosting)
    inference_url: str = "http://127.0.0.1:11434/v1"
    inference_model: str = ""
    inference_api_key: str = ""
    verifier_model: str = ""  # a different model, used only to check propositions
    inference_timeout: float = 300.0

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
