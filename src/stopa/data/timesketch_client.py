"""STP-059 — Timesketch HTTP klient (oblast Q, interop push).

Timesketch naslouchá na ``http://localhost:8000`` a mluví vlastním REST
API s CSRF ochranou. Kontrakt ověřen z oficiálního Python klienta
(``timesketch_api_client``) a zdrojů serveru (``google/timesketch``):

- **login flow**: ``GET /login/?local_auth=1`` → scrape CSRF tokenu z HTML
  (``input#csrf_token`` nebo ``meta[name=csrf-token]``) →
  ``POST /login/?local_auth=1`` s form daty ``username``/``password``/
  ``csrf_token``; session cookie nastaví server,
- **API volání** nesou headers ``x-csrftoken`` + ``referer``,
- **create sketch**: ``POST {api_root}/sketches/`` JSON
  ``{"name", "description"}`` → 201, ID z ``objects[0].id``,
- **upload timeline**: ``POST /api/v1/upload/`` multipart/form-data —
  povinná pole ``sketch_id`` (int), ``file`` (soubor) a ``name``;
  odpověď 201 s timeline objektem + ``meta.task_id``.

Design (vzor E11 ``LmStudioClient``):
- **graceful degradation** — bez spuštěného Timesketchu ``health()`` vrátí
  ``available=False`` (ne výjimku); operace hájí ``TimesketchUnavailable``,
  který web endpoint mapuje na HTTP 503 srozumitelnou zprávou,
- **env override** — ``STOPA_TIMESKETCH_URL`` / ``STOPA_TIMESKETCH_USER`` /
  ``STOPA_TIMESKETCH_PASS`` (přístupové údaje nikdy nekončí v audit logu),
- offline testovatelnost přes ``httpx.MockTransport`` (vzor E11).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
ENV_BASE_URL = "STOPA_TIMESKETCH_URL"
ENV_USERNAME = "STOPA_TIMESKETCH_USER"
ENV_PASSWORD = "STOPA_TIMESKETCH_PASS"

# CSRF token z login stránky — input#csrf_token (Timesketch default) nebo
# meta[name=csrf-token] (fallback, stejný zdroj jako oficiální klient).
_CSRF_INPUT_RE = re.compile(r'id="csrf_token"[^>]*value="([^"]+)"')
_CSRF_META_RE = re.compile(
    r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)',
)


class TimesketchError(Exception):
    """Základní chyba komunikace s Timesketch."""


class TimesketchUnavailable(TimesketchError):
    """Server nedostupný / neúspěšné přihlášení — GUI ukáže „Timesketch nedostupná“."""


@dataclass(frozen=True)
class TsSettings:
    """Konfigurace Timesketch push (env override + defaulty)."""

    base_url: str = DEFAULT_BASE_URL
    username: str | None = None
    password: str | None = None
    api_timeout_s: float = 30.0
    health_timeout_s: float = 3.0
    _cache: dict[str, object] = field(default_factory=dict, compare=False)

    @property
    def host(self) -> str:
        return self.base_url.rstrip("/")

    @property
    def api_root(self) -> str:
        return f"{self.host}/api/v1"


def settings_from_env() -> TsSettings:
    """TsSettings z prostředí + defaulty (přístupové údaje volitelné)."""
    base = os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/")
    user = os.environ.get(ENV_USERNAME) or None
    pwd = os.environ.get(ENV_PASSWORD) or None
    return TsSettings(base_url=base, username=user, password=pwd)


def _scrape_csrf(html: str) -> str | None:
    """CSRF token z HTML login stránky (bez bs4 — deterministický regex)."""
    m = _CSRF_INPUT_RE.search(html) or _CSRF_META_RE.search(html)
    return m.group(1) if m else None


class TimesketchClient:
    """Tenký wrapper nad Timesketch REST API (login + sketches + upload).

    Každá veřejná operace otevře vlastní ``httpx.Client`` (session cookie
    přežívá uvnitř jedné operace — login → API volání), takže klient je
    bezpečný pro sekvenční použití i offline testy s MockTransportem.
    """

    def __init__(self, settings: TsSettings | None = None) -> None:
        self.settings = settings or settings_from_env()

    # ── health ────────────────────────────────────────────────────────────
    def health(self) -> dict[str, object]:
        """``{"available": bool}`` — bez výjimek.

        Volá ``GET {host}/``; jakákoli HTTP odpověď = server běží (Timesketch
        root redirectuje na /login nebo /sketches). Connection error → False.
        Přístupové údaje neověřuje (health zůstává levné a bez side effectů).
        """
        s = self.settings
        try:
            with httpx.Client(timeout=s.health_timeout_s, follow_redirects=False) as client:
                r = client.get(s.host + "/")
            return {"available": True, "status_code": r.status_code}
        except (httpx.HTTPError, ValueError):
            return {"available": False, "status_code": None}

    # ── login flow ────────────────────────────────────────────────────────
    def _login(self, client: httpx.Client) -> str:
        """Přihlášení (local auth) → CSRF token pro API volání.

        Hází ``TimesketchUnavailable`` při nedostupném serveru a
        ``TimesketchError`` při neúspěšném přihlášení / chybějícím tokenu.
        """
        s = self.settings
        if not s.username or not s.password:
            raise TimesketchError(
                "chybějí přístupové údaje — nastavte STOPA_TIMESKETCH_USER/PASS"
            )
        login_url = f"{s.host}/login/?local_auth=1"
        try:
            r = client.get(login_url)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise TimesketchUnavailable(
                f"Timesketch nedostupný ({exc.__class__.__name__})"
            ) from exc

        csrf = _scrape_csrf(r.text)
        if not csrf:
            raise TimesketchError("login stránka neobsahuje CSRF token")

        try:
            r2 = client.post(
                login_url,
                data={"username": s.username, "password": s.password,
                      "csrf_token": csrf},
                headers={"x-csrftoken": csrf, "referer": s.host + "/"},
            )
        except httpx.HTTPError as exc:
            raise TimesketchUnavailable(
                f"Timesketch nedostupný při přihlášení ({exc.__class__.__name__})"
            ) from exc

        if r2.status_code == 401:
            raise TimesketchError("přihlášení zamítnuto (401)")
        # tiché selhání local loginu — server vrátí stránku /login znovu
        final_path = r2.url.path.rstrip("/")
        if final_path.endswith("/login"):
            raise TimesketchError("přihlášení selhalo: neplatné přístupové údaje")
        return csrf

    def _api_headers(self, csrf: str) -> dict[str, str]:
        """Headers API volání (CSRF + referer — kontrakt oficiálního klienta)."""
        return {"x-csrftoken": csrf, "referer": self.settings.host + "/"}

    # ── sketches ──────────────────────────────────────────────────────────
    def create_sketch(self, name: str, description: str = "") -> int:
        """Vytvoří sketch → jeho ID (int).

        ``POST {api_root}/sketches/`` JSON ``{"name", "description"}`` → 201;
        ID z ``objects[0].id``. Hází ``TimesketchError`` /
        ``TimesketchUnavailable`` dle login flow a HTTP stavu.
        """
        s = self.settings
        try:
            # follow_redirects=True — úspěšné přihlášení končí 302 → /sketches/;
            # detekce selhání (zůstává na /login/) to potřebuje.
            with httpx.Client(timeout=s.api_timeout_s, follow_redirects=True) as client:
                csrf = self._login(client)
                r = client.post(
                    f"{s.api_root}/sketches/",
                    json={"name": name, "description": description},
                    headers=self._api_headers(csrf),
                )
        except httpx.HTTPError as exc:
            raise TimesketchUnavailable(
                f"Timesketch nedostupný ({exc.__class__.__name__})"
            ) from exc

        if r.status_code != 201:
            raise TimesketchError(f"create sketch HTTP {r.status_code}: {r.text[:200]}")
        try:
            payload = r.json()
            return int(payload["objects"][0]["id"])
        except (ValueError, KeyError, IndexError) as exc:
            raise TimesketchError(
                f"nečekaná odpověď create sketch: {r.text[:200]}"
            ) from exc

    # ── upload timeline ───────────────────────────────────────────────────
    def upload_timeline(
        self,
        sketch_id: int,
        name: str,
        file_bytes: bytes,
        filename: str = "timeline.l2t.csv",
    ) -> dict[str, object]:
        """Nahraje timeline soubor do sketchu → souhrn odpovědi.

        ``POST /api/v1/upload/`` multipart/form-data — povinná pole
        ``sketch_id``, ``name`` a file pole ``file`` (kontrakt serveru).
        Odpověď 201 nese timeline objekt + ``meta.task_id``; vrací
        ``{"timeline_id", "task_id"}`` (None pokud server nevrátil).

        Hází ``TimesketchError`` / ``TimesketchUnavailable``.
        """
        s = self.settings
        try:
            # follow_redirects=True — úspěšné přihlášení končí 302 → /sketches/;
            # detekce selhání (zůstává na /login/) to potřebuje.
            with httpx.Client(timeout=s.api_timeout_s, follow_redirects=True) as client:
                csrf = self._login(client)
                r = client.post(
                    f"{s.host}/api/v1/upload/",
                    data={"sketch_id": str(sketch_id), "name": name},
                    files={"file": (filename, file_bytes, "text/csv")},
                    headers=self._api_headers(csrf),
                )
        except httpx.HTTPError as exc:
            raise TimesketchUnavailable(
                f"Timesketch nedostupný ({exc.__class__.__name__})"
            ) from exc

        if r.status_code != 201:
            raise TimesketchError(f"upload HTTP {r.status_code}: {r.text[:200]}")
        try:
            payload = r.json()
        except ValueError as exc:
            raise TimesketchError(
                f"nečekaná odpověď upload (ne-JSON): {r.text[:200]}"
            ) from exc

        timeline_id: int | None = None
        obj = payload.get("objects") or [{}]
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            tid = obj[0].get("id")
            if isinstance(tid, int):
                timeline_id = tid
        meta = payload.get("meta") or {}
        task_id: str | None = (
            str(meta["task_id"]) if isinstance(meta, dict) and meta.get("task_id") else None
        )
        return {"timeline_id": timeline_id, "task_id": task_id}

    # ── STP-061 — status timeline (live polling po uploadu) ───────────────
    def timeline_status(self, sketch_id: int, timeline_id: int) -> dict[str, object]:
        """Dotáže stav indexace timeline → ``{"status", "updated_at"}``.

        ``GET {api_root}/sketches/{sketch_id}/timelines/{timeline_id}/`` —
        odpověď 200 nese timeline objekt; stav je **nested** pod
        ``objects[0].status.status`` (kontrakt ověřen ze zdrojů serveru:
        ``fields.Nested(status_fields)``). Hodnoty: ``new`` / ``processing`` /
        ``ready`` / ``fail``. Chybějící pole → ``None`` (ne výjimka), aby UI
        mohlo pollovat i při částečně vyplněné odpovědi.

        Hází ``TimesketchError`` (HTTP != 200, ne-JSON) a
        ``TimesketchUnavailable`` (server nedostupný / login selhal).
        """
        s = self.settings
        try:
            with httpx.Client(timeout=s.api_timeout_s, follow_redirects=True) as client:
                csrf = self._login(client)
                r = client.get(
                    f"{s.api_root}/sketches/{int(sketch_id)}"
                    f"/timelines/{int(timeline_id)}/",
                    headers=self._api_headers(csrf),
                )
        except httpx.HTTPError as exc:
            raise TimesketchUnavailable(
                f"Timesketch nedostupný ({exc.__class__.__name__})"
            ) from exc

        if r.status_code != 200:
            raise TimesketchError(f"timeline status HTTP {r.status_code}: {r.text[:200]}")
        try:
            payload = r.json()
        except ValueError as exc:
            raise TimesketchError(
                f"nečekaná odpověď timeline status (ne-JSON): {r.text[:200]}"
            ) from exc

        obj = payload.get("objects") or [{}]
        first = obj[0] if isinstance(obj, list) and obj else {}
        status_obj = first.get("status") if isinstance(first, dict) else None
        status: str | None = (
            str(status_obj["status"])
            if isinstance(status_obj, dict) and status_obj.get("status")
            else None
        )
        updated_at: str | None = (
            str(status_obj["updated_at"])
            if isinstance(status_obj, dict) and status_obj.get("updated_at")
            else None
        )
        return {"status": status, "updated_at": updated_at}
