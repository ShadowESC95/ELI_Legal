from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ELI_LEGAL_", extra="ignore")

    env: str = "development"
    mode: str = "standalone"
    db_path: Path = Path("./data/eli_legal.sqlite3")
    audit_key_file: Path = Path("./secrets/audit_hmac.key")
    policy_file: Path = Path("./config/policy.default.json")
    source_registry: Path = Path("./config/source_registry.example.json")
    default_jurisdiction: str = "IE"
    network_default: str = "deny"
    log_level: str = "INFO"


settings = Settings()
