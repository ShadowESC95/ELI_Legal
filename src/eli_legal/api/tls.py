"""A certificate for a server that has none.

A firm or court will normally install a certificate from its own authority. Where there is none,
the server can make a self-signed one so that traffic is still encrypted. Browsers will warn,
rightly: check the fingerprint printed at start-up against the one the browser shows before
trusting it.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import shutil
import socket
import ssl
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path


def fingerprint(cert_file: Path) -> str:
    der = ssl.PEM_cert_to_DER_cert(Path(cert_file).read_text(encoding="ascii"))
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def local_names() -> list[str]:
    """The names and addresses other machines might use to reach this one."""
    names = {"localhost", "127.0.0.1", "::1", socket.gethostname().lower()}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))  # no packet is sent; this only picks a route
            names.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(n for n in names if n)


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def ensure_self_signed(cert_file: Path, key_file: Path, names: list[str], days: int = 365) -> bool:
    """Create the pair if either file is missing. Returns True if a new one was made."""
    if cert_file.is_file() and key_file.is_file():
        return False
    try:
        _with_cryptography(cert_file, key_file, names, days)
    except ImportError:
        _with_openssl(cert_file, key_file, names, days)
    return True


def _with_cryptography(cert_file: Path, key_file: Path, names: list[str], days: int) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ELI Legal (self-signed)")])
    alt: list[x509.GeneralName] = []
    for name in names:
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            alt.append(x509.DNSName(name))
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    _write_private(
        key_file,
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )
    cert_file.parent.mkdir(parents=True, exist_ok=True)
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _with_openssl(cert_file: Path, key_file: Path, names: list[str], days: int) -> None:
    openssl = shutil.which("openssl")
    if openssl is None:
        raise RuntimeError(
            "cannot create a certificate: install the 'cryptography' package "
            "(pip install 'eli-legal[server]') or OpenSSL, or supply --tls-cert and --tls-key"
        )
    alt = []
    for name in names:
        try:
            ipaddress.ip_address(name)
            alt.append(f"IP:{name}")
        except ValueError:
            alt.append(f"DNS:{name}")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    cert_file.parent.mkdir(parents=True, exist_ok=True)
    _write_private(key_file, b"")
    subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [
            openssl, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
            "-nodes", "-keyout", str(key_file), "-out", str(cert_file), "-days", str(days),
            "-subj", "/CN=ELI Legal (self-signed)", "-addext", "subjectAltName=" + ",".join(alt),
            "-addext", "basicConstraints=critical,CA:FALSE",
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    os.chmod(key_file, 0o600)
