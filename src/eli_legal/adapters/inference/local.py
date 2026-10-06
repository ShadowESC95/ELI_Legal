"""Inference adapters for standalone use.

``NullInference`` is the no-model mode: every step that can run without a model still runs, and
steps that need one are skipped and reported. ``OpenAICompatInference`` talks to a model server on
this machine (llama.cpp server, Ollama, LM Studio, vLLM all expose the same chat endpoint).

Matter content is confidential and often privileged. The endpoint must be loopback unless its host
has been explicitly approved, in which case the network guard opens a window for that host only.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from eli_legal.domain.errors import InferenceUnavailable, NetworkDenied
from eli_legal.ports.network import NetworkPort


class NullInference:
    model_id = "none"
    available = False

    def generate(
        self, *, system: str, prompt: str, max_tokens: int = 2048, json_mode: bool = False
    ) -> str:
        raise InferenceUnavailable("no inference backend is configured")


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class OpenAICompatInference:
    available = True

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 300.0,
        network: NetworkPort | None = None,
        seed: int = 7,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"invalid inference URL: {base_url}")
        self.base_url = base_url.rstrip("/")
        self.host = parsed.hostname
        self.loopback = _is_loopback_host(self.host)
        # A model server on another machine would receive matter content. It is accepted only
        # if its host has been approved, and is then reached through the guard's window.
        approved: frozenset[str] = getattr(network, "approved_hosts", frozenset)()
        if not self.loopback and (network is None or self.host.lower() not in approved):
            raise NetworkDenied(
                f"inference host {self.host} is not on this machine and is not an approved host"
            )
        self.model = model
        self.model_id = f"{model}@{self.host}"
        self.api_key = api_key
        self.timeout = timeout
        self.network = network
        self.seed = seed

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result: dict[str, Any] = json.loads(response.read().decode("utf-8"))
                return result
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise InferenceUnavailable(f"inference call failed: {type(exc).__name__}") from exc

    def generate(
        self, *, system: str, prompt: str, max_tokens: int = 2048, json_mode: bool = False
    ) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
            "seed": self.seed,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.loopback or self.network is None:
            payload = self._post(body)
        else:
            with self.network.allow(host=self.host, reason="approved inference endpoint"):
                payload = self._post(body)
        try:
            return str(payload["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise InferenceUnavailable("inference endpoint returned an unexpected shape") from exc


def list_local_models(base_url: str, *, timeout: float = 4.0) -> list[str]:
    """Models offered by an OpenAI-compatible server on this machine. Loopback only."""
    parsed = urlparse(base_url)
    if not parsed.hostname or not _is_loopback_host(parsed.hostname):
        raise NetworkDenied("models can only be listed from a server on this machine")
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/models", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise InferenceUnavailable(f"no model server answered at {base_url}") from exc
    return sorted(str(m.get("id")) for m in payload.get("data", []) if m.get("id"))
