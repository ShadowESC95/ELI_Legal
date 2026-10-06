from __future__ import annotations
import os
import secrets
from pathlib import Path

path = Path(os.getenv("ELI_LEGAL_AUDIT_KEY_FILE", "./secrets/audit_hmac.key"))
path.parent.mkdir(parents=True, exist_ok=True)
if path.exists():
    raise SystemExit(f"Refusing to overwrite existing key: {path}")
path.write_text(secrets.token_hex(32), encoding="ascii")
try:
    path.chmod(0o600)
except OSError:
    pass
print(f"Created audit key: {path}")
