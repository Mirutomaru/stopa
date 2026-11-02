"""E11 — LM Studio HTTP klient (OpenAI-kompatibilní API).

LM Studio naslouchá na ``http://localhost:1234/v1`` a mluví OpenAI chat
completions protokolem. Cíl lze přepsat env ``STOPA_LMSTUDIO_URL``
(např. pro vzdálený instance nebo jiný port).

Design:
- **graceful degradation** — bez spuštěného LM Studio ``health()`` vrátí
  ``available=False`` (ne výjimku); ``chat()`` háje ``LmStudioUnavailable``,
  který web endpoint mapuje na HTTP 503 srozumitelnou zprávou
- model: explicitní ``model=`` nebo automaticky první načtený z ``/models``
  (LM Studio má obvykle jeden aktivní model)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE_URL = "http://localhost:1234/v1"
ENV_BASE_URL = "STOPA_LMSTUDIO_URL"


class LmStudioError(Exception):
    """Základní chyba komunikace s LM Studio."""


class LmStudioUnavailable(LmStudioError):
    """Server nedostupný / žádný načtený model — GUI ukáže „AI nedostupná“."""


@dataclass(frozen=True)
class AiSettings:
    """Konfigurace AI asistenta (env override + defaulty)."""

    base_url: str = DEFAULT_BASE_URL
    model: str | None = None  # None → automaticky první z /models
    chat_timeout_s: float = 120.0  # lokální inference může být pomalá
    health_timeout_s: float = 3.0
    max_tokens: int = 600
    _cache: dict[str, str] = field(default_factory=dict, compare=False)

    def resolved_model(self) -> str | None:
        return self._cache.get("model")


def settings_from_env() -> AiSettings:
    """AiSettings z prostředí (``STOPA_LMSTUDIO_URL``) + defaulty."""
    base = os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/")
    return AiSettings(base_url=base)


class LmStudioClient:
    """Tenký wrapper nad OpenAI-kompatibilním chat completions endpointem."""

    def __init__(self, settings: AiSettings | None = None) -> None:
        self.settings = settings or settings_from_env()

    # ── health / model discovery ────────────────────────────────────────
    def health(self) -> dict[str, object]:
        """``{"available": bool, "model": str|None}`` — bez výjimek.

        Volá ``GET {base}/models``; při connection error / prázdném seznamu
        modelů → ``available=False`` (LM Studio běží, ale není načtený model).
        """
        s = self.settings
        try:
            with httpx.Client(timeout=s.health_timeout_s) as client:
                r = client.get(f"{s.base_url}/models")
                r.raise_for_status()
                data = r.json().get("data", [])
        except (httpx.HTTPError, ValueError):
            return {"available": False, "model": None}
        model_id: str | None = None
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict) and first.get("id"):
                model_id = str(first["id"])
        if model_id:
            s._cache["model"] = model_id  # type: ignore[misc]  (frozen cache)
        return {"available": bool(model_id), "model": model_id}

    def _resolve_model(self, client: httpx.Client) -> str:
        """Explicitní model z settings, jinak první načtený (s cachem)."""
        if self.settings.model:
            return self.settings.model
        cached = self.settings.resolved_model()
        if cached:
            return cached
        r = client.get(f"{self.settings.base_url}/models")
        r.raise_for_status()
        data = r.json().get("data", [])
        if isinstance(data, list) and data and isinstance(data[0], dict):
            model_id = str(data[0].get("id", ""))
            if model_id:
                self.settings._cache["model"] = model_id  # type: ignore[misc]
                return model_id
        raise LmStudioUnavailable("LM Studio nemá načtený žádný model")

    # ── chat completion ─────────────────────────────────────────────────
    def chat(self, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        """Jedna chat completion → text odpovědi.

        Hází ``LmStudioUnavailable`` (server/model nedostupný) a
        ``LmStudioError`` (jiná HTTP/JSON chyba).
        """
        s = self.settings
        try:
            with httpx.Client(timeout=s.chat_timeout_s) as client:
                model = self._resolve_model(client)
                r = client.post(
                    f"{s.base_url}/chat/completions",
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": max_tokens or s.max_tokens,
                        "temperature": 0.2,  # forenzní kontext → deterministické
                    },
                )
        except httpx.HTTPError as exc:
            raise LmStudioUnavailable(f"LM Studio nedostupný ({exc.__class__.__name__})") from exc

        if r.status_code != 200:
            raise LmStudioError(f"LM Studio HTTP {r.status_code}: {r.text[:200]}")
        try:
            payload = r.json()
            text = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LmStudioError(f"nečekaná odpověď LM Studio: {r.text[:200]}") from exc
        if not isinstance(text, str) or not text.strip():
            raise LmStudioUnavailable("LM Studio vrátil prázdnou odpověď")
        return text
