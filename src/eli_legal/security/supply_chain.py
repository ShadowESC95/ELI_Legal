"""What ELI Legal is built from, how a weakness in it is reported, and how a release is audited.

Every release carries a CycloneDX bill of materials of the Python components the installers are
built from, and is built only if a known-vulnerability audit (``pip-audit``) of those components
finds nothing outstanding. A known vulnerability that has no fix yet and does not affect ELI Legal
as it is used may be let through only with its reason written down in
``packaging/audit_exceptions.txt``; this module reads that list for the release build and
refuses an entry without a reason, so nothing is waved through unexplained.

A weakness is reported privately (``SECURITY.md``); one that is actively exploited, or a severe
incident affecting the product's security, is notified as the Cyber Resilience Act requires
(Regulation (EU) 2024/2847, Art. 14).

``python -m eli_legal.security.supply_chain ignore-args FILE`` prints the audit's exceptions as
``--ignore-vuln`` options; ``shipped`` filters ``pip freeze`` (on stdin) to what is shipped.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPORT_URL = "https://github.com/ShadowESC95/ELI_Legal/security/advisories/new"
REPORTING = (
    f"Report a security weakness privately: {REPORT_URL} (see SECURITY.md). An actively "
    "exploited vulnerability is notified within 24 hours, as the Cyber Resilience Act requires."
)
# Build tools, not part of what is shipped: left out of the audited list.
BUILD_TOOLS = frozenset(
    {"pip", "setuptools", "wheel", "pyinstaller", "pyinstaller-hooks-contrib", "altgraph",
     "macholib", "pefile"}
)  # fmt: skip
_ID = re.compile(r"^(PYSEC|GHSA|CVE|OSV)-[A-Za-z0-9-]+$")
MIN_REASON = 30


@dataclass(frozen=True, slots=True)
class AuditException:
    vulnerability_id: str
    reason: str


def read_exceptions(path: str | Path) -> list[AuditException]:
    """The vulnerabilities a release may carry, each with why it does not affect ELI Legal.
    Raises ValueError for an entry with no reason, an unrecognised id or a duplicate."""
    out: list[AuditException] = []
    seen: set[str] = set()
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        vid, _, reason = text.partition(" ")
        reason = reason.strip()
        if not _ID.match(vid):
            raise ValueError(f"line {number}: {vid!r} is not a vulnerability id")
        if len(reason) < MIN_REASON:
            raise ValueError(
                f"line {number}: {vid} needs its reason: why it does not affect ELI Legal"
            )
        if vid in seen:
            raise ValueError(f"line {number}: {vid} is listed twice")
        seen.add(vid)
        out.append(AuditException(vid, reason))
    return out


def shipped(freeze: str) -> list[str]:
    """``pip freeze`` output reduced to the components the installers ship."""
    out = []
    for line in freeze.splitlines():
        line = line.strip()
        if not line or line.startswith(("-e ", "#")):
            continue
        name = re.split(r"[=<>@ ]", line, maxsplit=1)[0].strip().lower().replace("_", "-")
        if name not in BUILD_TOOLS:
            out.append(line)
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["ignore-args"] and len(args) == 2:
        try:
            listed = read_exceptions(args[1])
        except (OSError, ValueError) as exc:
            print(f"audit exceptions: {exc}", file=sys.stderr)
            return 1
        print(" ".join(f"--ignore-vuln {e.vulnerability_id}" for e in listed))
        return 0
    if args == ["shipped"]:
        print("\n".join(shipped(sys.stdin.read())))
        return 0
    print(
        "usage: python -m eli_legal.security.supply_chain ignore-args FILE | shipped",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
