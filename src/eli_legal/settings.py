from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PACKAGED_CONFIG = Path(__file__).resolve().parent / "config"


def _config(name: str) -> Path:
    """A deployment's own ./config/<name> if it exists, else the default shipped in the package."""
    local = Path("./config") / name
    return local if local.exists() else _PACKAGED_CONFIG / name


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ELI_LEGAL_", extra="ignore")

    env: str = "development"
    mode: str = "standalone"  # standalone | eli_v3
    db_path: Path = Path("./data/eli_legal.sqlite3")
    # The audit ledger lives in its own database so its file permissions can differ.
    audit_db_path: Path = Path("./data/audit.sqlite3")
    audit_key_file: Path = Path("./secrets/audit_hmac.key")
    data_dir: Path = Path("./data/matters")
    artifacts_dir: Path = Path("./artifacts")
    policy_file: Path = _config("policy.default.json")
    jurisdictions_dir: Path = _config("jurisdictions")
    workflow_file: Path = _config("workflows/case_preparation.json")
    default_jurisdiction: str = "IE"
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


settings = Settings()
