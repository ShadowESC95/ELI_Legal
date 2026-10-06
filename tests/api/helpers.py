"""A browser, as far as the server can tell: it keeps the cookie, sends the CSRF value with
anything that changes something, and answers the server's request for the passphrase."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


class Browser:
    def __init__(
        self,
        app: Any,
        user: str,
        phrase: str,
        *,
        base: str = "http://localhost",
        code: str | None = None,
    ) -> None:
        self.client = TestClient(app, base_url=base)
        self.user, self.phrase = user, phrase
        signed = self.client.post(
            "/v1/auth/login", json={"user_id": user, "passphrase": phrase, "code": code}
        )
        assert signed.status_code == 200, signed.text
        self.login = signed
        self.csrf = signed.json()["csrf"]

    def get(self, path: str) -> Any:
        return self.client.get(path)

    def send(
        self, method: str, path: str, json: Any = None, *, confirm: bool = False, **kw: Any
    ) -> Any:
        headers = {"X-ELI-CSRF": self.csrf, **kw.pop("headers", {})}
        if confirm:
            headers["X-ELI-Passphrase"] = self.phrase
        return self.client.request(method, path, json=json, headers=headers, **kw)

    def decide(self, method: str, path: str, json: Any = None) -> Any:
        """What the page does: try, and when the server says this needs the passphrase, send it."""
        answer = self.send(method, path, json)
        if answer.status_code == 401 and answer.json()["error"] == "StepUpRequired":
            answer = self.send(method, path, json, confirm=True)
        return answer
