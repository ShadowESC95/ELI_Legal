"""Every server route, called by every kind of person: nothing leaks, and nobody acts beyond
their role.

The case has papers of every clearance, each carrying a marker: served on all parties, given in
confidence by the claimant, given in confidence by the respondent, the tribunal's privileged
work, and for the neutral only. A second case, on which only its owner sits, has a secret name.
Then each person (the tribunal's own, each party's people, an auditor, a governance officer and
a judge not on the case, a technical administrator) calls every route the server has, with a
valid request and their passphrase. The test fails if any response carries a marker that person
is not cleared for, or if any change to the case or the system is accepted from someone whose
role does not allow it. New routes are swept automatically.
"""

from __future__ import annotations

import base64
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from eli_legal.api.app import create_app
from eli_legal.application.matter_service import hash_passphrase
from eli_legal.domain.enums import AccessScope, Profile

ARB, SEC = "arb.keane", "sec.byrne"
C_SOL, R_BAR, R_SELF = "sol.harbour", "bl.northwind", "pip.northwind"
AUDITOR, GOV, TECH, OUTSIDE = "aud.flynn", "gov.hale", "tech.ops", "judge.other"
LEGAL = "legal.admin"
CLAIMANT, RESPONDENT = "Harbour Freight Ltd", "Northwind Logistics Ltd"

MARK = {
    "served": "CANARYSERVEDALLPARTIES",
    "claimant": "CANARYCLAIMANTCONFIDENTIAL",
    "respondent": "CANARYRESPONDENTCONFIDENTIAL",
    "privileged": "CANARYTRIBUNALPRIVILEGED",
    "neutral": "CANARYNEUTRALONLY",
    "secret_case": "CANARYSECRETCASENAME",
}

# What each person may ever see, of the markers above.
MAY_SEE = {
    ARB: set(MARK),  # the tribunal sees all of its case, and owns the second one
    LEGAL: set(MARK) - {"secret_case"},  # decides on this case; not on the second one
    C_SOL: {"served", "claimant"},
    R_BAR: {"served", "respondent"},
    R_SELF: {"served", "respondent"},
    AUDITOR: set(),
    GOV: set(),
    TECH: set(),
    OUTSIDE: set(),
}
PHRASE = "a passphrase for the sweep"

# Routes anyone signed in may use for themselves (their own session, passphrase, second factor,
# tokens and notifications), and a party's own pages, which their service checks.
SELF_SERVICE = {
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/logout"),
    ("POST", "/v1/auth/passphrase"),
    ("POST", "/v1/auth/second-factor/begin"),
    ("POST", "/v1/auth/second-factor/confirm"),
    ("DELETE", "/v1/auth/second-factor"),
    ("POST", "/v1/auth/tokens"),
    ("POST", "/v1/notifications/read"),
    ("POST", "/v1/matters/{matter_id}/notifications/{notification_id}/read"),
}
PARTY_ROUTES = {
    ("POST", "/v1/party/cases/{matter_id}/filings"),
    ("POST", "/v1/party/cases/{matter_id}/holds/{hold_id}/answer"),
}


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Any:
    import eli_legal.settings as settings_module
    from eli_legal.application.services import build_services
    from eli_legal.demo import build_demo_workspace
    from eli_legal.demo_run import demo_settings, setup_demo
    from eli_legal.security import authn, hard_offline

    root = tmp_path_factory.mktemp("sweep")
    # The sweep really calls every route, so nothing it is allowed to do may reach beyond its own
    # folder or outlive it: settings a route would save go to the sweep's own file, and hard
    # offline (allowed to the technical administrator) is recorded but not applied to the process.
    patch = pytest.MonkeyPatch()
    patch.setattr(settings_module, "ENV_FILE", root / ".env")
    patch.setattr(
        hard_offline,
        "go_offline",
        lambda: hard_offline.OfflineState(False, "nothing (the sweep)", "not applied in a test"),
    )
    authn.install_harness("sweep")
    ws = build_demo_workspace(root / "demo")
    sv = build_services(demo_settings(root, ws), install_network_guard=False)
    mid = setup_demo(sv, ws)
    for uid, name, roles in (
        (C_SOL, "Claimant's solicitor", ["solicitor"]),
        (R_BAR, "Respondent's barrister", ["barrister"]),
        (R_SELF, "Respondent in person", ["self_represented"]),
        (AUDITOR, "Auditor", ["auditor"]),
        (TECH, "Technical administrator", ["system_admin"]),
        (OUTSIDE, "A judge on other cases", ["judge"]),
        (LEGAL, "Legal administrator", ["legal_admin"]),
    ):
        sv.users.add_user(actor_id="admin", user_id=uid, display_name=name, roles=roles)
    sv.matters.grant(mid, actor_id=ARB, user_id=C_SOL, party=CLAIMANT)
    sv.matters.grant(mid, actor_id=ARB, user_id=R_BAR, party=RESPONDENT)
    sv.matters.grant(mid, actor_id=ARB, user_id=R_SELF, party=RESPONDENT)
    sv.matters.grant(mid, actor_id=ARB, user_id=AUDITOR, matter_role="auditor")
    sv.matters.grant(mid, actor_id=ARB, user_id=LEGAL, matter_role="decision_maker")
    matter = sv.matters.get(mid, ARB)
    party = {p.name: p.party_id for p in matter.parties}
    for key, scope, side in (
        ("served", AccessScope.ALL_PARTIES, CLAIMANT),
        ("claimant", AccessScope.PARTY_CONFIDENTIAL, CLAIMANT),
        ("respondent", AccessScope.PARTY_CONFIDENTIAL, RESPONDENT),
        ("privileged", AccessScope.PRIVILEGED, None),
        ("neutral", AccessScope.NEUTRAL_ONLY, None),
    ):
        doc = sv.ingestion.register(
            matter=matter,
            actor_id=ARB,
            filename=f"{MARK[key].lower()}.txt",
            raw=(
                f"{MARK[key]}. The Claimant says the containers arrived on 3 April 2023 "
                f"({MARK[key]}). The Respondent paid nothing ({MARK[key]})."
            ).encode(),
            party_id=party[side] if side else None,
            access_scope=scope,
            title=MARK[key],
            custodian=MARK[key],
        )
        sv.ingestion.process(doc, actor_id=ARB)
    other = sv.matters.create(
        actor_id=ARB,
        name=f"{MARK['secret_case']} v Somebody",
        purpose=MARK["secret_case"],
        jurisdiction="XX",
        profile=Profile.ADJUDICATOR,
    )
    run = sv.runs.start(mid, actor_id=ARB)
    for uid in MAY_SEE:
        user = sv.ctx.user(uid)
        user.passphrase_hash = hash_passphrase(PHRASE)
        sv.ctx.store.put_user(user)
    tokens = {uid: sv.users.issue_token(actor_id=uid, user_id=uid) for uid in MAY_SEE}
    authn.remove_harness()
    docs = sv.ctx.store.list(
        __import__("eli_legal.domain.models", fromlist=["Document"]).Document, mid
    )
    holds = sv.ctx.holds.open_holds(mid, run.run_id)
    claims = sv.ctx.store.list(__import__("eli_legal.domain.models", fromlist=["Claim"]).Claim, mid)
    ids = {
        "matter_id": mid,
        "run_id": run.run_id,
        "document_id": next(d.document_id for d in docs if d.title == MARK["respondent"]),
        "hold_id": holds[0].hold_id,
        "claim_id": claims[0].claim_id,
        "user_id": SEC,
        "release_id": "rel_" + "0" * 32,
        "notification_id": "ntf_" + "0" * 32,
        "incident_id": "inc_" + "0" * 32,
        "block_id": "blk_" + "0" * 32,
        "authorisation_id": "dep_" + "0" * 32,
        "action_id": "OA-01",
        "kind": "annex_iv",
        "source_id": "examplia-law-reports",
        "authority_id": "auth_x",
        "pack_id": "eu_ai_act",
        "name": "control_register",
        "ref": "model_x",
    }
    yield {
        "sv": sv,
        "mid": mid,
        "other": other.matter_id,
        "ids": ids,
        "tokens": tokens,
        "root": root,
    }
    patch.undo()


def _routes(app: Any) -> list[tuple[str, str]]:
    out = []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        if methods and r.path.startswith("/v1"):
            out += [(m, r.path) for m in sorted(methods - {"HEAD", "OPTIONS"})]
    return out


# Fields whose value must be one of a fixed set: a valid one, so a refusal is the rules' own.
NAMED = {
    "profile": "adjudicator",
    "decision": "approve",
    "result": "verified",
    "severity": "high",
    "scope": "all_parties",
    "check": "current_law",
    "action": "waive",
    "kind": "explain",
    "backend": "none",
    "category": "other",
    "jurisdiction": "XX",
    "jurisdictions": "XX",
    "profiles": "adjudicator",
}


def _value(schema: dict[str, Any], spec: dict[str, Any], name: str) -> Any:
    if name in NAMED and schema.get("type") in ("string", None):
        return NAMED[name]
    if "$ref" in schema:
        return _body(spec, schema["$ref"])
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            return _value(next(s for s in schema[key] if s.get("type") != "null"), spec, name)
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "string":
        if schema.get("format") == "date":
            return "2023-04-28"
        if schema.get("format") == "date-time":
            return "2026-11-23T10:00:00Z"
        if "pattern" in schema:
            return "sweep_probe"
        text = "A reason long enough for every check that asks for one, recorded by the sweep."
        return text[: schema.get("maxLength", len(text))].ljust(schema.get("minLength", 0), "a")
    if kind == "integer":
        return max(1, schema.get("minimum", 1))
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return False
    if kind == "array":
        return [
            _value(schema.get("items", {}), spec, name) for _ in range(schema.get("minItems", 0))
        ]
    return {}


def _body(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    schema = spec["components"]["schemas"][ref.rsplit("/", 1)[1]]
    return {
        name: _value(prop, spec, name)
        for name, prop in schema.get("properties", {}).items()
        if name in schema.get("required", [])
    }


def _call(client, spec, uid, tokens, method, path, ids):
    url = re.sub(r"{(\w+)}", lambda m: str(ids[m.group(1)]), path)
    op = spec["paths"][path][method.lower()]
    query = {
        p["name"]: _value(p.get("schema", {}), spec, p["name"])
        for p in op.get("parameters", [])
        if p.get("in") == "query" and p.get("required")
    }
    headers = {
        "Authorization": f"Bearer {tokens[uid]}",
        "X-ELI-Passphrase-B64": base64.b64encode(PHRASE.encode()).decode(),
    }
    content = op.get("requestBody", {}).get("content", {})
    kwargs: dict[str, Any] = {"params": query, "headers": headers}
    if "application/json" in content:
        ref = content["application/json"]["schema"].get("$ref")
        kwargs["json"] = _body(spec, ref) if ref else {}
    elif method in ("POST", "PUT", "PATCH") and "upload" in op.get("operationId", "") + url:
        kwargs["content"] = b"A probe file from the sweep."
    return client.request(method, url, **kwargs)


def test_no_route_shows_anyone_what_they_are_not_cleared_for(world):
    sv, ids, tokens = world["sv"], world["ids"], world["tokens"]
    app = create_app(sv)
    spec = app.openapi()
    client = TestClient(app, base_url="http://localhost", raise_server_exceptions=False)
    leaks = []
    for uid, allowed in MAY_SEE.items():
        for method, path in _routes(app):
            if (
                method != "GET"
                or "{" in path
                and not all(p in ids for p in re.findall(r"{(\w+)}", path))
            ):
                continue
            got = _call(client, spec, uid, tokens, method, path, ids)
            body = got.text
            for key, marker in MARK.items():
                if marker in body and key not in allowed:
                    leaks.append(f"{uid} {method} {path} -> {got.status_code} shows {key}")
    assert not leaks, "\n".join(leaks)


def test_no_one_changes_anything_beyond_their_role(world):
    """Everyone except the case's tribunal tries every change the server accepts. Only their
    own self-service, and a party's own filings and answers, may succeed."""
    sv, ids, tokens = world["sv"], world["ids"], world["tokens"]
    app = create_app(sv)
    spec = app.openapi()
    client = TestClient(app, base_url="http://localhost", raise_server_exceptions=False)
    accepted, malformed = [], []
    for uid in (C_SOL, R_BAR, R_SELF, AUDITOR, GOV, TECH, OUTSIDE):
        for method, path in _routes(app):
            if method == "GET" or (method, path) in SELF_SERVICE:
                continue
            if (method, path) in PARTY_ROUTES and uid in (C_SOL, R_BAR, R_SELF):
                continue
            got = _call(client, spec, uid, tokens, method, path, ids)
            if got.status_code < 300:
                accepted.append(f"{uid} {method} {path} -> {got.status_code}")
            elif (
                got.status_code == 422
                and "detail" in got.json()
                and isinstance(got.json()["detail"], list)
            ):
                malformed.append(f"{uid} {method} {path}: {got.json()['detail'][0]}")
    expected = _role_allows(sv)
    unexpected = [a for a in accepted if a.split(" -> ")[0] not in expected]
    assert not unexpected, "\n".join(unexpected)
    assert not malformed, "the sweep sent an invalid request, so it proved nothing:\n" + "\n".join(
        malformed
    )


def _role_allows(sv) -> set[str]:
    """What these people's own roles do allow them to change, stated as policy. Anything
    accepted that is not here fails the sweep."""
    tech = {  # technical administrator: accounts, settings, the routine checks; no case
        "POST /v1/users",
        "POST /v1/users/{user_id}/passphrase",
        "POST /v1/users/{user_id}/deactivate",
        "POST /v1/users/{user_id}/unlock",
        "DELETE /v1/users/{user_id}/second-factor",
        "POST /v1/config/model",
        "POST /v1/checks/run",
        "POST /v1/network/offline",
        "PUT /v1/network/at-start",
        "POST /v1/audit/checkpoint",
    }
    governance = {  # sources, laws, settings, compliance work, checks; preserving more is safe
        "POST /v1/config/model",
        "POST /v1/checks/run",
        "POST /v1/network/offline",
        "PUT /v1/network/at-start",
        "POST /v1/audit/checkpoint",
        "POST /v1/compliance/evaluation",
        "POST /v1/compliance/documents/{kind}",
        "POST /v1/matters/{matter_id}/preservation-holds",
        "POST /v1/frameworks/upload",
        "POST /v1/sources",
        "POST /v1/sources/{source_id}/approve",
        "POST /v1/sources/{source_id}/revoke",
    }
    auditor = {  # on the case as its auditor: verify the trail, export the evidence pack
        "POST /v1/audit/checkpoint",
        "POST /v1/matters/{matter_id}/runs/{run_id}/evidence-pack",
    }
    judge = {  # a judge not on this case: opens cases of their own; checks the audit trail
        "POST /v1/matters",
        "POST /v1/audit/checkpoint",
    }
    return (
        {f"{TECH} {r}" for r in tech}
        | {f"{GOV} {r}" for r in governance}
        | {f"{AUDITOR} {r}" for r in auditor}
        | {f"{OUTSIDE} {r}" for r in judge}
    )


def test_an_evidence_pack_carries_only_what_its_exporter_may_read(world):
    """The auditor's pack has every record and hash, and no content; a party cannot export."""
    import io
    import zipfile

    sv, ids, tokens = world["sv"], world["ids"], world["tokens"]
    client = TestClient(create_app(sv), base_url="http://localhost", raise_server_exceptions=False)
    path = f"/v1/matters/{ids['matter_id']}/runs/{ids['run_id']}/evidence-pack"
    for uid, allowed in ((AUDITOR, MAY_SEE[AUDITOR]), (LEGAL, MAY_SEE[LEGAL])):
        got = client.post(path, headers={"Authorization": f"Bearer {tokens[uid]}"})
        assert got.status_code == 200, (uid, got.status_code, got.text[:200])
        with zipfile.ZipFile(io.BytesIO(got.content)) as pack:
            text = "".join(pack.read(n).decode("utf-8", "replace") for n in pack.namelist())
        shown = {k for k, marker in MARK.items() if marker in text}
        assert shown <= allowed, (uid, shown - allowed)
        if uid == LEGAL:
            assert {"served", "respondent", "privileged"} <= shown, "a cleared exporter's is whole"
    # Parties, people not on the case, and the tribunal itself (separation of duties: the
    # tribunal does not certify its own evidence) cannot export it.
    for uid in (C_SOL, R_BAR, TECH, OUTSIDE, GOV, ARB):
        got = client.post(path, headers={"Authorization": f"Bearer {tokens[uid]}"})
        assert got.status_code in (403, 404), (uid, got.status_code)


def test_the_sweep_changes_nothing_outside_its_own_folder(world):
    """The settings the technical administrator saved went to the sweep's own file."""
    from pathlib import Path

    assert (world["root"] / ".env").exists()
    assert Path(".env").resolve() != (world["root"] / ".env").resolve()
