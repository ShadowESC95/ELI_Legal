"""Signing in and out, your own credentials, and (for administrators) other people's accounts."""

# No "from __future__ import annotations": FastAPI resolves route annotations when a route is
# defined, and they refer to names local to register().
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response

from eli_legal import __version__
from eli_legal.application.services import Services
from eli_legal.security.rbac import DEFAULT_ROLE_ACTIONS

from . import schemas
from .auth import WEB_METHOD, Access, csrf_for
from .config import ServerConfig


def register(app: FastAPI, sv: Services, cfg: ServerConfig, access: Access) -> None:
    Actor = Annotated[str, Depends(access.user)]

    def me(user_id: str) -> dict[str, Any]:
        u = sv.ctx.user(user_id)
        can = sv.ctx.authorizer().bindings.can
        return {
            "user_id": u.user_id,
            "display_name": u.display_name,
            "roles": sorted(u.roles),
            "second_factor": sv.users.has_second_factor(user_id),
            "may": {
                a: can(user_id, a)
                for a in (
                    "user.manage",
                    "source.manage",
                    "config.manage",
                    "audit.read",
                    "audit.verify",
                )
            },
        }

    @app.get("/health", response_model=schemas.HealthResponse)
    def health() -> schemas.HealthResponse:
        """Whether the server is up. Says nothing else to someone who has not signed in."""
        return schemas.HealthResponse(status="ok", version=__version__)

    @app.get("/v1/boundaries")
    def boundaries() -> dict[str, Any]:
        """What this system will never do, whoever asks."""
        return {
            "decision_support_only": True,
            "renders_verdict_or_award": False,
            "human_release_required": True,
            "contacts_parties": False,
            "personal_assistant_capabilities": False,
            "general_shell": False,
            "network_default": "deny",
            "prohibited_actions": sorted(sv.ctx.policy.prohibited_actions),
        }

    @app.post("/v1/auth/login")
    def login(body: schemas.LoginIn, response: Response) -> dict[str, Any]:
        """Sign in with a passphrase, and a code if a second factor is set up. Sets the session cookie and returns the CSRF value."""
        token = sv.users.login(
            body.user_id,
            body.passphrase,
            method=WEB_METHOD,
            hours=cfg.session_hours,
            code=body.code,
        )
        access.set_cookie(response, token)
        return {
            "user": me(body.user_id),
            "csrf": csrf_for(token),
            "second_factor_required": cfg.require_second_factor,
            "idle_minutes": cfg.idle_minutes,
        }

    @app.post("/v1/auth/logout", status_code=204)
    def logout(request: Request, response: Response) -> None:
        """End the session and clear the cookie."""
        token = request.cookies.get(cfg.cookie_name, "")
        if token:
            sv.users.logout(token)
        access.clear_cookie(response)

    @app.get("/v1/auth/session")
    def session(actor: Actor, request: Request) -> dict[str, Any]:
        """Who is signed in, their roles, and the CSRF value for this session."""
        token = request.state.session
        return {
            "user": me(actor),
            "csrf": csrf_for(token) if token else None,
            "second_factor_required": cfg.require_second_factor,
            "idle_minutes": cfg.idle_minutes,
        }

    @app.post("/v1/auth/passphrase", status_code=204)
    def change_passphrase(body: schemas.PassphraseChange, actor: Actor, response: Response) -> None:
        """Change your own passphrase. Every session of yours ends, including this one."""
        sv.users.set_passphrase(actor_id=actor, user_id=actor, new=body.new, current=body.current)
        access.clear_cookie(response)

    @app.post("/v1/auth/second-factor/begin")
    def second_factor_begin(actor: Actor) -> dict[str, str]:
        """Start setting up an authenticator. Returns the key to add to the app. A decision: needs the passphrase."""
        secret, uri = sv.users.second_factor_begin(actor_id=actor)
        return {"secret": secret, "uri": uri}

    @app.post("/v1/auth/second-factor/confirm", status_code=204)
    def second_factor_confirm(body: schemas.CodeIn, actor: Actor) -> None:
        """Confirm the authenticator with a code it shows. From then on a code is needed at every sign-in."""
        sv.users.second_factor_confirm(actor_id=actor, code=body.code)

    @app.delete("/v1/auth/second-factor", status_code=204)
    def second_factor_remove(actor: Actor, response: Response) -> None:
        """Remove your own second factor. A decision: needs the passphrase. Ends your sessions."""
        sv.users.second_factor_remove(actor_id=actor, user_id=actor)
        access.clear_cookie(response)

    @app.post("/v1/auth/tokens", status_code=201)
    def own_token(body: schemas.LabelIn, actor: Actor) -> dict[str, str]:
        """A token for a program acting as you. Shown once."""
        return {"token": sv.users.issue_token(actor_id=actor, user_id=actor, label=body.label)}

    # ── users (administrators) ───────────────────────────────────────────────
    @app.get("/v1/users")
    def users(actor: Actor) -> list[dict[str, Any]]:
        """Everyone who has an account, with their roles. Administrators also see lock and second-factor state."""
        manager = sv.ctx.authorizer().bindings.can(actor, "user.manage")
        out = []
        for u in sv.users.directory(actor):
            row: dict[str, Any] = {
                "user_id": u.user_id,
                "display_name": u.display_name,
                "roles": sorted(u.roles),
                "active": u.active,
            }
            if manager:  # who is locked out, or has no second factor, is not for everyone
                row.update(
                    sv.users.account_status(u.user_id), has_passphrase=bool(u.passphrase_hash)
                )
            out.append(row)
        return out

    @app.get("/v1/roles")
    def roles(actor: Actor) -> dict[str, list[str]]:
        """Every role and the actions it permits."""
        return {role: sorted(actions) for role, actions in sorted(DEFAULT_ROLE_ACTIONS.items())}

    @app.post("/v1/users", status_code=201)
    def add_user(body: schemas.UserCreate, actor: Actor) -> dict[str, Any]:
        """Create a user with roles, and optionally a first passphrase. A decision; administrators only."""
        sv.users.add_user(
            actor_id=actor, user_id=body.user_id, display_name=body.display_name, roles=body.roles
        )
        if body.passphrase:
            sv.users.set_passphrase(actor_id=actor, user_id=body.user_id, new=body.passphrase)
        return {"user_id": body.user_id}

    @app.post("/v1/users/{user_id}/passphrase", status_code=204)
    def set_passphrase(user_id: str, body: schemas.NewPassphrase, actor: Actor) -> None:
        """Set another user's passphrase and end their sessions. A decision; administrators only."""
        sv.users.set_passphrase(actor_id=actor, user_id=user_id, new=body.new)

    @app.post("/v1/users/{user_id}/deactivate", status_code=204)
    def deactivate(user_id: str, actor: Actor) -> None:
        """Deactivate a user: their sessions and tokens stop working. A decision; administrators only."""
        sv.users.deactivate(actor_id=actor, user_id=user_id)

    @app.post("/v1/users/{user_id}/unlock", status_code=204)
    def unlock(user_id: str, actor: Actor) -> None:
        """Lift a lock caused by failed sign-ins. A decision; administrators only."""
        sv.users.unlock(actor_id=actor, user_id=user_id)

    @app.delete("/v1/users/{user_id}/second-factor", status_code=204)
    def reset_second_factor(user_id: str, actor: Actor) -> None:
        """Remove a user's second factor (lost device). A decision; administrators only. Ends their sessions."""
        sv.users.second_factor_remove(actor_id=actor, user_id=user_id)

    @app.post("/v1/users/{user_id}/tokens", status_code=201)
    def user_token(user_id: str, body: schemas.LabelIn, actor: Actor) -> dict[str, str]:
        """Issue an API token for another user. Shown once. A decision; administrators only."""
        return {"token": sv.users.issue_token(actor_id=actor, user_id=user_id, label=body.label)}
