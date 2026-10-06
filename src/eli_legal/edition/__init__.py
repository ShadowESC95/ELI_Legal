"""ELI Legal as an ELI edition pack.

ELI is one shared core plus domain editions that overlay it. An edition is a manifest, three
policy hooks, and the capabilities it adds. This package is ELI Legal in exactly that shape, so
ELI can load it without ELI Legal being forked into ELI's tree:

* ``manifest.json``            — the edition manifest, in ELI's schema;
* ``policy``                   — ``system_prompt_addendum``, ``output_disclaimer``,
                                 ``blocked_actions``;
* ``capabilities``             — the ``LEGAL_*`` actions;
* ``register(host, entitled)`` — the activation entry point, advertised to ELI through the
                                 ``eli.editions`` entry-point group.

The same shape is the template for any further edition (finance, healthcare, VR): its own
package, its own store and rules, the same four things exposed to the core.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import shutil
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eli_legal import __version__
from eli_legal.domain.errors import EliLegalError, EntitlementDenied
from eli_legal.edition import policy
from eli_legal.edition.capabilities import CAPABILITIES, dispatch
from eli_legal.security import authn

EDITION_NAME = "legal"
CONTRACT_VERSION = 1
_HERE = Path(__file__).resolve().parent

_SHIM_INIT = '''"""ELI Legal edition pack — shim.

The edition lives in the separately installed ``eli-legal`` package. This directory only tells
ELI's edition registry where to find it. Do not add code here.
"""
from eli_legal.edition import register  # noqa: F401
'''
_SHIM_POLICY = '''"""Edition policy hooks for ELI Legal — forwarded to the installed package."""
from eli_legal.edition.policy import (  # noqa: F401
    blocked_actions,
    output_disclaimer,
    system_prompt_addendum,
)
'''


def manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((_HERE / "manifest.json").read_text(encoding="utf-8"))
    data["package_version"] = __version__
    data["capabilities"] = [c.name for c in CAPABILITIES]
    return data


def check_entitlement(entitled: Iterable[str] | None) -> None:
    """Refuse activation when the host's licence does not include this edition.

    ``None`` means the host did not say (standalone use, or a host that has not yet wired
    licence entitlements to editions); that is allowed. A host that does pass the set of
    entitled editions is taken at its word.
    """
    if entitled is None:
        return
    names = {str(e).lower() for e in entitled}
    if EDITION_NAME not in names and "enterprise" not in names:
        raise EntitlementDenied("this ELI licence does not include the Legal edition")


def register(
    host: Any | None = None,
    *,
    entitled: Iterable[str] | None = None,
    services: Any | None = None,
    actor_resolver: Any | None = None,
) -> dict[str, Any]:
    """Activate the edition inside a hosting ELI and return what was registered.

    ``host`` is whatever object ELI passes (unused beyond presence). ``services`` lets a host
    or a test supply prebuilt services; otherwise they are built with ELI's model as the
    inference backend. ``actor_resolver(args)`` maps a capability call to the acting ELI Legal
    user id; by default the call must carry the ``user_id`` the host authenticated.
    """
    check_entitlement(entitled)
    if services is None:
        from eli_legal.adapters.eli_v3.inference import EliV3Inference
        from eli_legal.application.services import build_services
        from eli_legal.settings import Settings

        services = build_services(Settings(mode="eli_v3"), inference=EliV3Inference())

    def resolve_actor(args: Mapping[str, Any]) -> str:
        if actor_resolver is not None:
            return str(actor_resolver(args))
        actor = str(args.get("user_id") or "").strip()
        if not actor:
            raise EliLegalError("no ELI Legal user is identified for this request")
        return actor

    def make_handler(name: str) -> Any:
        def handler(args: Mapping[str, Any] | None = None) -> dict[str, Any]:
            args = args or {}
            try:
                actor = resolve_actor(args)
            except EliLegalError as exc:
                text = f"Refused: {exc}"
                return {"ok": False, "error": "no_actor", "content": text, "response": text}
            # The host authenticated this user; ELI Legal still applies its own roles. No
            # step-up is given, so nothing that is a decision could run even if it were exposed.
            with authn.established(actor, "eli-host"):
                return dispatch(services, name, actor, args)

        return handler

    handlers = {c.name: make_handler(c.name) for c in CAPABILITIES}
    registered_with_host = False
    try:  # advertise the capabilities to the host's registry when there is one
        from eli.tools.registry.capability_registry import register_capability

        for capability in CAPABILITIES:
            register_capability(
                capability.name,
                {
                    "description": capability.description,
                    "category": capability.category,
                    "edition": EDITION_NAME,
                    "example": capability.example,
                    "handler": handlers[capability.name],
                },
            )
        registered_with_host = True
    except ImportError:
        registered_with_host = False
    return {
        "edition": EDITION_NAME,
        "version": __version__,
        "contract_version": CONTRACT_VERSION,
        "capabilities": sorted(handlers),
        "handlers": handlers,
        "blocked_host_actions": sorted(policy.blocked_actions()),
        "registered_with_host": registered_with_host,
        "services": services,
    }


# ── working with an ELI checkout ─────────────────────────────────────────────
def _editions_dir(eli_root: str | Path) -> Path:
    directory = Path(eli_root).expanduser().resolve() / "eli" / "editions"
    if not (directory / "__init__.py").is_file():
        raise EliLegalError(f"no ELI edition registry found at {directory}")
    return directory


def install_into_eli(eli_root: str | Path, *, force: bool = False) -> list[Path]:
    """Point an ELI checkout's ``legal`` edition at this package.

    Writes three small files into ``<eli>/eli/editions/legal/``: the manifest, and two shims
    that forward to this package. Existing files are refused unless ``force`` is given, in
    which case they are first copied into a dated backup directory beside them.
    """
    target = _editions_dir(eli_root) / EDITION_NAME
    files = {
        "manifest.json": json.dumps(
            {k: v for k, v in manifest().items() if k != "capabilities"}, indent=2
        )
        + "\n",
        "__init__.py": _SHIM_INIT,
        "policy.py": _SHIM_POLICY,
    }
    existing = [name for name in files if (target / name).exists()]
    if existing and not force:
        raise EliLegalError(
            f"{target} already contains {', '.join(existing)}; re-run with --force to replace "
            "them (the originals are backed up first)"
        )
    target.mkdir(parents=True, exist_ok=True)
    if existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = target / f".replaced_{stamp}"
        backup.mkdir()
        for name in existing:
            shutil.copy2(target / name, backup / name)
    written = []
    for name, content in files.items():
        (target / name).write_text(content, encoding="utf-8")
        written.append(target / name)
    return written


def verify_against_eli(eli_root: str | Path) -> list[str]:
    """Check this package against the edition contract of an actual ELI checkout.

    Loads the checkout's own edition loader and feeds it this package's manifest, then checks
    the policy hooks and the three host modules the adapters rely on. Read-only.
    """
    root = Path(eli_root).expanduser().resolve()
    editions_dir = _editions_dir(root)
    lines: list[str] = []

    def check(ok: bool, text: str) -> None:
        lines.append(f"{'ok  ' if ok else 'FAIL'} {text}")

    spec = importlib.util.spec_from_file_location(
        "_eli_editions_probe", editions_dir / "__init__.py"
    )
    if spec is None or spec.loader is None:
        raise EliLegalError("could not load the host's edition registry")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    try:
        spec.loader.exec_module(module)
        edition = module._load(_HERE / "manifest.json")
    finally:
        sys.modules.pop(spec.name, None)
    check(edition is not None, "the host's loader accepts this package's manifest.json")
    if edition is not None:
        check(edition.name == EDITION_NAME, f"edition name is '{edition.name}'")
        check(
            edition.policy_module == "eli_legal.edition.policy",
            f"policy module: {edition.policy_module}",
        )
        check(
            bool(edition.capability_categories),
            f"capability categories: {', '.join(edition.capability_categories)}",
        )
        check(
            bool(edition.report_templates),
            f"report templates: {', '.join(edition.report_templates)}",
        )
        check(bool(edition.suggested_tiers), f"licence tiers: {', '.join(edition.suggested_tiers)}")

    host_policy = editions_dir / "base" / "policy.py"
    if host_policy.is_file():
        wanted = re.findall(r"^def (\w+)\(", host_policy.read_text(encoding="utf-8"), re.M)
        for name in wanted:
            hook = getattr(policy, name, None)
            callable_without_args = hook is not None and all(
                p.default is not inspect.Parameter.empty
                for p in inspect.signature(hook).parameters.values()
            )
            check(
                callable_without_args,
                f"policy hook {name}() is present and callable as the host calls it",
            )

    for relative, symbol in (
        ("eli/cognition/gguf_inference.py", "def generate("),
        ("eli/core/netguard.py", "def allow_network("),
        ("eli/tools/registry/capability_registry.py", "def register_capability("),
    ):
        path = root / relative
        present = path.is_file() and symbol in path.read_text(encoding="utf-8", errors="replace")
        check(present, f"host provides {relative} :: {symbol.rstrip('(')}")

    manifest_path = root / "capability_manifest.json"
    if manifest_path.is_file():
        actions = {
            c["action"]
            for c in json.loads(manifest_path.read_text(encoding="utf-8"))["capabilities"]
        }
        unknown = sorted(actions - policy.KNOWN_HOST_ACTIONS)
        blocked = policy.blocked_actions(actions)
        check(
            True,
            f"{len(blocked)} of the host's {len(actions)} actions are refused while Legal is active",
        )
        lines.append(
            f"note {len(unknown)} host action(s) are newer than this package's snapshot; they "
            "are refused by default"
        )
        for dangerous in (
            "RUN_CMD",
            "SHELL_EXEC",
            "COMPUTER_USE",
            "SELF_PATCH",
            "MEMORY_STORE",
            "WEB_SEARCH",
            "READ_FILE",
        ):
            if dangerous in actions:
                check(dangerous in blocked, f"{dangerous} is refused")

    loader_text = (editions_dir / "__init__.py").read_text(encoding="utf-8")
    types_path = root / "eli" / "licensing" / "types.py"
    lines.append(
        "note the host discovers installed edition packages (entry-point group 'eli.editions')"
        if "entry_points" in loader_text
        else "note the host only discovers editions inside its own tree: use 'eli-legal edition "
        "install', or apply integrations/eli_v3/discover-installed-editions.patch"
    )
    if types_path.is_file():
        wired = (
            re.search(r"^\s+editions\s*:", types_path.read_text(encoding="utf-8"), re.M) is not None
        )
        lines.append(
            "note the host's licence carries edition entitlements"
            if wired
            else "note the host's licence does not yet carry edition entitlements (its own TODO); "
            "until it does, pass entitled=... to register() to gate this edition"
        )
    return lines


__all__ = [
    "CONTRACT_VERSION",
    "EDITION_NAME",
    "check_entitlement",
    "install_into_eli",
    "manifest",
    "register",
    "verify_against_eli",
]
