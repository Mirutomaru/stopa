"""STOPA web GUI — FastAPI nad `analyze()` pipeline + statická SPA.

Design:
- **jeden endpoint = jedna DB operace** (per-request CaseDB open/close —
  SQLite je thread-safe při sekvenčním přístupu, uvicorn single worker)
- **vanilla JS SPA** bez build kroku (index.html + app.js + style.css) —
  forenzní nástroj by neměl potřebovat Node toolchain
- pipeline sdílí s CLI stejnou `process_source()` — web není paralelní implementace

Spuštění: ``stopa serve [--port 8473]`` nebo ``uvicorn stopa.web.app:app``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import queue
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stopa import __version__
from stopa.data.db import CaseDB
from stopa.data.lmstudio_client import LmStudioClient, LmStudioUnavailable
from stopa.data.schema import MULTITENANT_DDL  # F4.4 — instance DB DDL
from stopa.data.timesketch_client import (
    TimesketchClient,
    TimesketchError,
    TimesketchUnavailable,
)
from stopa.data.user_repository import UserRepository  # F4.4
from stopa.data.write_blocker_repository import WriteBlockerRepository  # F5.4
from stopa.domain.ai_assistant import (
    build_explain_prompt,
    build_nl_search_prompt,
    build_summary_prompt,
    extract_citations,
    parse_confidence,
    parse_nl_search,
)
from stopa.domain.events import LiveEventBus, case_topic  # F4.2 — live events
from stopa.domain.multitenant import (  # F4.4 — OIDC SSO + per-case RBAC
    JwtError,
    access_for_case,
    verify_jwt,
)
from stopa.domain.rbac import (
    DEFAULT_ROLE,
    PERMISSIONS,
    ROLE_LABELS,
    ROLES,
    RBACDenied,
    normalize_role,
    permissions_for,
    require_permission,
)
from stopa.domain.times import to_local_iso
from stopa.domain.write_blocker import (  # F5.4 — write-blocker API
    VENDORS,
    detect_write_blocker,
    ingest_gate,
    known_vendor_ids,
)
from stopa.models import Case, EvidenceSource
from stopa.pipeline import process_source

log = logging.getLogger("stopa.web")

STATIC_DIR = Path(__file__).parent / "static"


def _db_dir() -> Path:
    d = Path(os.environ.get("STOPA_DB_DIR", "cases"))
    d.mkdir(parents=True, exist_ok=True)
    return d


# audit P1 — case_id z URL jde přímo do cesty; bez sanitace uniká `../secret.db`
# mimo STOPA_DB_DIR (path traversal). Legitní ID = `case-<hex>` → strict regex.
_CASE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def validate_case_id(case_id: str) -> None:
    """Odmítne case_id, které by mohly uniknout DB adresáře (path traversal)."""
    if not _CASE_ID_RE.match(case_id):
        raise HTTPException(400, f"neplatné ID případu: {case_id!r}")


# ── F4.4 — session tokens (HMAC-SHA256 signed, no new dependencies) ────────────────
_SESSION_TTL_S = 12 * 3600  # 12h sessions


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def sign_session_token(payload: dict, secret: str, ttl_s: int = _SESSION_TTL_S) -> str:
    """Signed session token ``body.sig`` (HMAC-SHA256 over body)."""
    body_payload = {**payload, "exp": time.time() + ttl_s}
    body = _b64url(json.dumps(body_payload, sort_keys=True).encode())
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64url(sig)}"


def verify_session_token(token: str, secret: str) -> dict | None:
    """Fail-closed verification of the session token; invalid/expired → ``None``."""
    try:
        body, sig = token.rsplit(".", 1)
        expect = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expect), sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if time.time() >= float(payload.get("exp", 0)):
            return None
        username = str(payload.get("u") or "")
        return {"username": username} if username else None
    except (ValueError, TypeError):
        return None


def _default_jwks_fetch(jwks_uri: str) -> dict:
    """Fetches JWKS from the IdP (Keycloak/Okta — HTTPS)."""
    import urllib.request

    with urllib.request.urlopen(jwks_uri, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


#: F4.4 — session token for the current request (set by HTTP middleware).
_current_token_var: ContextVar[str | None] = ContextVar("stopa_session_token", default=None)


class CaseIn(BaseModel):
    name: str
    examiner: str | None = None
    notes: str | None = None


class SourceIn(BaseModel):
    path: str
    profile: str = "forensic"
    resume: bool = False  # E3 checkpointing — přeskočit soubory už v DB
    background: bool = False  # STP-021 — async ingest (default sync = backward compat)


class WBAttachIn(BaseModel):
    """F5.4 — write-blocker připojení (vendor auto-detekce z device stringu)."""

    device: str | None = None
    vendor: str | None = None  # explicitní override, když detekce nestačí
    product: str | None = None
    notes: str | None = None


class WBRemoveIn(BaseModel):
    """F5.4 — write-blocker odebrání."""

    reason: str | None = None


class AiQueryIn(BaseModel):
    """E11 — dotaz na AI asistenta (režim + parametry)."""

    mode: str  # nl_search | summary | explain
    question: str = ""  # nl_search: přirozená řeč; explain: volitelný kontext
    artifact_id: str | None = None  # explain: který artifact vysvětlit


class AiAnalyzeIn(BaseModel):
    """P0 Intelligence I1 — analytický úkol pro AI orchestraci.

    ``agent`` je volitelné (None = auto-routing podle dotazu).
    """

    question: str
    agent: str | None = None  # case_analyst|timeline_analyst|artifact_analyst|media_analyst|report_analyst


class AiHypoGenerateIn(BaseModel):
    """F3.5 — generování grafu hypotéz (use_ai = LM Studio, jinak fallback)."""

    use_ai: bool = False


class AiHypoStatusIn(BaseModel):
    """F3.5 — ruční potvrzení/vyvrácení hypotézy."""

    status: str


class ReviewStateIn(BaseModel):
    """Tělo POST .../artifacts/{artifact_id}/review (F4.3 Peer-Review Workflow)."""

    state: str = Field(min_length=1, max_length=32)  # draft|reviewed|approved|court_ready
    reviewer: str = Field(min_length=1, max_length=200)  # distinct examinátor (kvorum!)
    note: str | None = Field(default=None, max_length=500)


class TimesketchPushIn(BaseModel):
    """STP-059 — push datasetu případu do Timesketch sketchu."""

    what: str = "timeline"  # artifacts | timeline | correlations
    limit: int | None = Field(  # STP-065 — jen první N záznamů (None = vše)
        default=None, ge=1
    )


class LoginIn(BaseModel):
    """F4.4 — login body: SSO id_token or local username (exactly one)."""

    id_token: str | None = None
    username: str | None = None


class OrgIn(BaseModel):
    """F4.4 — organization creation."""

    name: str = Field(min_length=1, max_length=100)


class TeamIn(BaseModel):
    """F4.4 — team creation (within an org)."""

    org_id: str
    name: str = Field(min_length=1, max_length=100)


class UserIn(BaseModel):
    """F4.4 — new user (admin UI)."""

    username: str = Field(min_length=1, max_length=200)
    display_name: str | None = None
    team_id: str | None = None
    role: str = "examiner"  # analyst|examiner|admin


class UserUpdateIn(BaseModel):
    """F4.4 — user update (only specified fields)."""

    display_name: str | None = None
    team_id: str | None = None
    role: str | None = None
    active: bool | None = None


class MemberGrantIn(BaseModel):
    """F4.4 — case membership grant."""

    user_id: str
    role: str = "examiner"  # analyst|examiner|admin


class CommentIn(BaseModel):
    """F4.5 — nový komentář na artefakt (body 1–4000 znaků)."""

    body: str = Field(min_length=1, max_length=4000)


class CommentEditIn(CommentIn):
    """F4.5 — editace komentáře; expected_revision = optimistické zamykání."""

    expected_revision: int | None = None


class SettingsIn(BaseModel):
    """E12 — uživatelská nastavení (jen zadaná pole se uloží)."""

    timezone_name: str | None = None
    ai_url: str | None = None
    role: str | None = None  # examiner | analyst | admin
    bind_address: str | None = None
    ai_redact_pii: bool | None = None  # STP-019 — maskovat PII v LLM promptech
    require_write_blocker: bool | None = None  # F5.4 — ingest gate bez WB (default OFF)


class CaseUpdateIn(BaseModel):
    """E12 — aktualizace metadat případu (jen zadaná pole)."""

    name: str | None = None
    examiner: str | None = None
    notes: str | None = None
    timezone_name: str | None = None
    auto_export_enabled: bool | None = None  # STP-069 — opt-in automatický export
    # STP-070 — interval periodického auto-bundle v minutách (5–43200).
    # str|None: UI posílá i prázdný string („vymazat“); None = pole nezadáno.
    auto_export_interval_minutes: int | str | None = None


# ── STP-070 — periodický plánovač auto-bundle (scheduler) ───────────────
_AUTO_EXPORT_TICK_SECONDS = 60  # tick každou minutu; minimální interval je 5 min


def run_auto_export_tick(db_dir: Path, now_utc: datetime | None = None) -> list[dict]:
    """STP-070 — jeden průchod plánovače: auto-bundle pro všechny „due“ případy.

    Procházejí se všechny case DB v ``db_dir``; u každého případu se
    ``auto_export_enabled=1`` a nastaveným intervalem se ověří doménová
    podmínka :func:`stopa.domain.export_schedule.is_due` (explicitní
    ``now_utc`` → deterministicky testovatelné). Due případy dostanou
    deterministický ZIP bundle (STP-069 ``build_auto_bundle``), atomicky
    uložený do trvalé cache, a persistovaný čas spuštění.

    Chyba u jednoho případu nepadá celý tick — zaloguje se a pokračuje.

    Returns:
        Seznam ``{"case_id", "path"}`` pro každé vygenerované bundle.
    """
    from stopa.domain.export import build_auto_bundle
    from stopa.domain.export_schedule import is_due

    now = now_utc or datetime.now(timezone.utc)
    results: list[dict] = []
    for path in sorted(db_dir.glob("case-*.db")):
        case_id = path.stem
        if not _CASE_ID_RE.match(case_id):
            continue
        db = CaseDB(path)
        try:
            due_cases = [
                c
                for c in db.list_scheduled_cases()
                if is_due(c.last_auto_export_at, now, c.auto_export_interval_minutes or 0)
            ]
            for case in due_cases:
                try:
                    data, out_path = build_auto_bundle(db, case_id)
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    tmp = out_path.with_name(out_path.name + ".tmp")
                    tmp.write_bytes(data)
                    tmp.replace(out_path)  # atomický (same volume)
                    db.set_last_auto_export(case_id, str(out_path))
                    db.mark_auto_export_ran(case_id, now.isoformat())
                    results.append({"case_id": case_id, "path": str(out_path)})
                except Exception:  # jeden případ nepadá tick
                    log.warning(
                        "STP-070 auto-bundle selhal pro %s", case_id, exc_info=True
                    )
        finally:
            db.close()
    return results


def _auto_export_scheduler_loop(db_dir: Path) -> None:
    """STP-070 — smyčka daemon threadu (sleep-first → testy nevidí tick)."""
    while True:
        time.sleep(_AUTO_EXPORT_TICK_SECONDS)
        try:
            run_auto_export_tick(db_dir)
        except Exception:  # scheduler nikdy nesmí zemřít
            log.warning("STP-070 scheduler tick selhal", exc_info=True)


def create_app(
    db_dir: Path | None = None,
    ws_heartbeat_s: float = 15.0,
    sso_fetcher: Callable[[str], dict] | None = None,  # F4.4 — test hook for JWKS
    mail_backend: Callable[[dict], None] | None = None,  # F4.5 — email transport (injektovatelný)
) -> FastAPI:
    """App factory — `db_dir` pro testy (tmp), default z env STOPA_DB_DIR.

    ``ws_heartbeat_s`` (F4.2): interval heartbeatu WebSocket spojení;
    v testech se zkracuje, aby se suite netestovala na 15 s čekání.
    ``sso_fetcher`` (F4.4): injektovatelný JWKS fetch pro OIDC SSO testy (bez sítě).
    ``mail_backend`` (F4.5): volitelný email transport pro notifikace; payload =
    ``{"to": username, "subject": str, "body": str}``. Bez backendu zůstávají
    notifikace in-app (graceful degradation — mail nesmí rozbít API cestu).
    """
    app = FastAPI(title="STOPA", version=__version__)
    base = db_dir or _db_dir()
    app.state.db_dir = base  # pro testy (TestClient)
    app.state.sso_fetcher = sso_fetcher  # F4.4 — OIDC JWKS test hook
    app.state.mail_backend = mail_backend  # F4.5 — email transport (None = in-app only)

    # STP-021 — Processing Monitor: registry běhů ingestu (in-memory, per-app).
    # Job = {id, case_id, source_id, status, done, total, error, result}.
    # Sync POST /sources (default) se do registru taky zapisuje → GUI vidí i
    # právě probíhající synchronní ingest přes poll endpoint.
    _jobs: dict[str, dict] = {}
    _jobs_lock = threading.Lock()

    # F4.2 — LiveEventBus pro WebSocket push (in-memory; single-process model).
    _bus = LiveEventBus(maxsize=256)
    _ws_heartbeat_s = ws_heartbeat_s
    _last_ingest_pub: dict[str, float] = {}  # job_id → monotonic ts throttlu

    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds")

    def _publish_case(case_id: str, etype: str, **payload) -> None:
        """Publikuje událost na téma case; chyby jen loguje (defenzivní).

        Parametr ``etype`` (ne ``event_type``): payload timeline eventu má
        vlastní klíč ``event_type`` (typ záznamu), který by do kolize s
        pozičním parametrem a hook ho potichu polkal.
        """
        ev = {"type": etype, "case_id": case_id, "ts": _now_iso(), **payload}
        try:
            _bus.publish(case_topic(case_id), ev)
        except Exception:  # live kanál nesmí rozbít API cestu (jen debug log)
            log.debug("live publish selhal pro %s", etype, exc_info=True)

    def _attach_live_events(db: CaseDB, case_id: str) -> None:
        """F4.2 — naváže ``db.on_event`` na bus (timeline + AI akce)."""
        db.on_event = lambda etype, payload: _publish_case(case_id, etype, **payload)

    def _job_update(job_id: str, **fields) -> None:
        with _jobs_lock:
            if job_id not in _jobs:
                return
            _jobs[job_id].update(fields)
            snapshot = dict(_jobs[job_id])
        # F4.2 — live progress ingestu přes WS (throttle 0,15 s/job;
        # terminální stavy done/error se posílají vždy bez throttlu).
        if "done" in fields or "total" in fields or "status" in fields:
            terminal = snapshot.get("status") in ("done", "error")
            now = time.monotonic()
            if terminal or now - _last_ingest_pub.get(job_id, 0.0) >= 0.15:
                _last_ingest_pub[job_id] = now
                _publish_case(
                    str(snapshot["case_id"]), "ingest.progress",
                    job_id=job_id, source_id=snapshot.get("source_id"),
                    status=snapshot.get("status"), done=snapshot.get("done"),
                    total=snapshot.get("total"), error=snapshot.get("error"),
                )

    # ── F4.4 — Multi-tenant RBAC: instance DB + session auth ────────────────
    def _instance_conn() -> sqlite3.Connection:
        """Centrální instance DB sdílená napříč case DB (orgs/teams/users/case_members)."""
        conn = sqlite3.connect(base / "stopa_instance.db")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(MULTITENANT_DDL)  # idempotentní (IF NOT EXISTS)
        return conn

    def _user_repo() -> UserRepository:
        """Repozitář na instance DB (single-process; volající zavírá ``.conn``)."""
        return UserRepository(_instance_conn())

    def _session_secret() -> str:
        s = _load_settings().get("session_secret")
        if not s:
            s = uuid.uuid4().hex
            data = dict(_load_settings())
            data["session_secret"] = s
            _save_settings(data)
        return str(s)

    def _current_user() -> tuple[str, dict | None]:
        """F4.4 — vyhodnotí session: ``(status, user)``, status ∈ no-token|bad|ok."""
        token = _current_token_var.get()
        if not token:
            return ("no-token", None)
        payload = verify_session_token(token, _session_secret())
        if payload is None:
            return ("bad", None)
        repo = _user_repo()
        try:
            row = repo.get_user(username=payload["username"])
        finally:
            repo.conn.close()
        if row is None or not row["active"]:
            return ("bad", None)
        return ("ok", dict(row))

    def _multi_user_mode() -> bool:
        """Multi-user režim = existuje alespoň jeden uživatel (bootstrap detekce)."""
        repo = _user_repo()
        try:
            return repo.multi_user_mode()
        finally:
            repo.conn.close()

    @app.middleware("http")
    async def _session_middleware(request, call_next):
        """F4.4 — předá session token (header ``X-Stopa-Token`` nebo cookie) handlerům."""
        tok = request.headers.get("x-stopa-token") or request.cookies.get("stopa_token")
        _current_token_var.set(tok)
        return await call_next(request)

    def _sso_config() -> dict:
        issuer = os.environ.get("STOPA_OIDC_ISSUER") or ""
        client_id = os.environ.get("STOPA_OIDC_CLIENT_ID") or ""
        return {"enabled": bool(issuer), "issuer": issuer, "client_id": client_id}

    def _sso_verify_id_token(id_token: str) -> dict:
        """Ověří OIDC ID token (Keycloak/Okta): RS256 přes JWKS nebo HS256 secret.

        Discovery ``{issuer}/.well-known/openid-configuration``; s injektovaným
        ``sso_fetcher`` se síť vůbec nevolá (testovací hook).
        """
        cfg = _sso_config()
        if not cfg["enabled"]:
            raise HTTPException(400, "SSO není nakonfigurováno (STOPA_OIDC_ISSUER)")
        secret = os.environ.get("STOPA_OIDC_HS256_SECRET") or ""
        jwks: dict | None = None
        if not secret:
            fetcher: Callable[[str], dict] | None = getattr(app.state, "sso_fetcher", None)
            try:
                if fetcher is not None:
                    # testovací hook — bez sítě; fetcher vrací JWKS přímo
                    jwks = fetcher(cfg["issuer"])
                else:
                    import urllib.request

                    url = cfg["issuer"].rstrip("/") + "/.well-known/openid-configuration"
                    with urllib.request.urlopen(url, timeout=10) as resp:
                        disc = json.loads(resp.read().decode("utf-8"))
                    jwks_uri = str(disc.get("jwks_uri") or "")
                    if not jwks_uri:
                        raise ValueError("OIDC discovery bez jwks_uri")
                    jwks = _default_jwks_fetch(jwks_uri)
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(502, f"OIDC JWKS fetch selhal: {exc}") from exc
        audience = os.environ.get("STOPA_OIDC_AUDIENCE") or cfg["client_id"] or None
        try:
            return verify_jwt(
                id_token,
                jwks=jwks,
                secret=secret or None,
                issuer=cfg["issuer"],
                audience=audience,
            )
        except JwtError as exc:
            raise HTTPException(401, f"neplatný ID token: {exc}") from exc

    def open_db(case_id: str) -> CaseDB:
        validate_case_id(case_id)
        path = base / f"{case_id}.db"
        if not path.exists():
            raise HTTPException(404, f"případ {case_id} nenalezen")
        db = CaseDB(path)
        _attach_live_events(db, case_id)  # F4.2 — live timeline/AI události
        return db

    # ── STP-067 — cache posledního exportu (re-download z historie) ──
    def _last_export_path(case_id: str, what: str, format: str) -> Path:
        """Cesta cache souboru pro dataset+formát případu.

        Layout: ``{db_dir}/exports/{case_id}/{what}.{format}`` — vedle case DB,
        aby re-download fungoval i po restartu serveru (trvalá cache).
        """
        return base / "exports" / case_id / f"{what}.{format}"

    def _save_last_export(case_id: str, what: str, format: str, text: str) -> None:
        """Atomicky uloží poslední export do cache (tmp → rename).

        Chyba zápisu nepadá export — cache je pohodlí, ne zdroj pravdy.
        """
        try:
            target = _last_export_path(case_id, what, format)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(target)  # atomický na POSIX i Windows (same volume)
        except OSError:
            logging.getLogger("stopa.web").warning(
                "cache posledního exportu se nepodařilo uložit (%s/%s %s)",
                case_id, what, format, exc_info=True,
            )

    def _save_last_export_bytes(
        case_id: str, what: str, format: str, data: bytes
    ) -> None:
        """Atomicky uloží binární export (ZIP bundle) do cache (STP-068).

        Stejná sémantika jako :func:`_save_last_export`, ale pro bajty —
        ZIP bundle nelze bezpečně přes text/utf-8. Chyba zápisu nepadá export.
        """
        try:
            target = _last_export_path(case_id, what, format)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)  # atomický na POSIX i Windows (same volume)
        except OSError:
            logging.getLogger("stopa.web").warning(
                "cache posledního exportu se nepodařilo uložit (%s/%s %s)",
                case_id, what, format, exc_info=True,
            )

    def _load_last_export(case_id: str, what: str, format: str) -> Path | None:
        """Vrátí existující cache soubor nebo None (ještě neexportováno)."""
        path = _last_export_path(case_id, what, format)
        return path if path.is_file() else None

    # ── health ────────────────────────────────────────────────
    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "db_dir": str(base)}

    # ── cases ─────────────────────────────────────────────────
    @app.get("/api/cases")
    def list_cases() -> list[dict]:
        _require("case.read")  # legacy: settings role; multi-user bez tokenu → 401 fail-closed
        # F4.4 — multi-user: uživatel vidí jen případy, ve kterých je člen (admin = vše).
        visible: set[str] | None = None
        status, user = _current_user()
        if status == "ok" and normalize_role(user["role"]) != "admin":
            repo = _user_repo()
            try:
                visible = set(repo.member_case_ids(user["id"]))  # fail-closed filtr
            finally:
                repo.conn.close()
        out = []
        for path in sorted(base.glob("case-*.db")):
            if visible is not None and path.stem not in visible:
                continue
            db = CaseDB(path)
            try:
                case = db.get_case(path.stem)
                if case is None:
                    continue
                stats = db.stats()
                art = db.artifact_stats()
                out.append(
                    {
                        "id": case.id,
                        "name": case.name,
                        "examiner": case.examiner,
                        "created_at": case.created_at.isoformat(),
                        "files": stats["files"],
                        "bytes": stats["bytes"],
                        "bad_ext": stats["bad_ext"],
                        "dups": stats["dups"],
                        "artifacts": art.get("total", 0),
                        # STP-069 — stav auto-exportu pro UI checkbox
                        "auto_export_enabled": bool(case.auto_export_enabled),
                        # STP-070 — interval plánovače pro UI input (None = nenastaveno)
                        "auto_export_interval_minutes": case.auto_export_interval_minutes,
                    }
                )
            finally:
                db.close()
        return out

    @app.post("/api/cases", status_code=201)
    def create_case(body: CaseIn) -> dict:
        _require("case.create", "create_case")
        # nová DB na nový soubor — case ID je v názvu souboru
        case = Case(name=body.name, examiner=body.examiner, notes=body.notes)
        db = CaseDB(base / f"{case.id}.db")
        try:
            db.add_case(case)
            # P0 Core C4: Ed25519 klíčový pár případu (graceful degradation bez cryptography).
            try:
                db.ensure_integrity_key()
            except RuntimeError:  # chybí balík cryptography — checkpointy degradují
                pass
        finally:
            db.close()
        return {"id": case.id, "name": case.name}

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str) -> dict:
        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, "případ neexistuje")
            return {
                "id": case.id,
                "name": case.name,
                "examiner": case.examiner,
                "notes": case.notes,
                "created_at": case.created_at.isoformat(),
                # STP-069 — opt-in automatický export + cesta k poslednímu bundle.
                "auto_export_enabled": bool(case.auto_export_enabled),
                "last_auto_export_path": case.last_auto_export_path,
                # STP-070 — periodický plánovač auto-bundle (interval + čas spuštění).
                "auto_export_interval_minutes": case.auto_export_interval_minutes,
                "last_auto_export_at": (
                    case.last_auto_export_at.isoformat() if case.last_auto_export_at else None
                ),
                "sources": [
                    {"id": s.id, "kind": s.kind, "path": s.path,
                     "added_at": s.added_at.isoformat()}
                    for s in db.list_sources(case_id)
                ],
                "stats": db.stats(),
                "artifact_stats": db.artifact_stats(),
            }
        finally:
            db.close()

    # ── sources / ingest ──────────────────────────────────────
    @app.post("/api/cases/{case_id}/sources", status_code=201)
    def add_source(case_id: str, body: SourceIn) -> dict:
        _require("source.add", "add_source", case_id=case_id)
        root = Path(body.path).expanduser()
        if not root.exists():
            raise HTTPException(400, f"zdroj neexistuje: {root}")
        db = open_db(case_id)

        # F5.4 — write-blocker gate (settings require_write_blocker, default OFF;
        # 409 = brána blokuje ingest bez připojeného WB)
        _wb_gate = ingest_gate(
            WriteBlockerRepository(db.conn, db.audit_repo).latest_state(),
            bool(_load_settings().get("require_write_blocker", False)),
        )
        if not _wb_gate.allowed:
            raise HTTPException(409, _wb_gate.warning or "write-blocker gate")

        # STP-021 — Processing Monitor: registrovat běh (sync i async).
        job_id = uuid.uuid4().hex[:12]
        with _jobs_lock:
            _jobs[job_id] = {
                "id": job_id,
                "case_id": case_id,
                "source_id": None,
                "status": "running",
                "done": 0,
                "total": 0,
                "error": None,
                "result": None,
            }

        def _progress(done: int, total: int) -> None:
            _job_update(job_id, done=done, total=total)

        if body.background:
            # STP-021 — async ingest: background thread se VLASTNÍ DB spojením
            # (per-thread sqlite3.connect; hlavní request vrací 201 okamžitě).
            db.close()

            def _run() -> None:
                tdb = CaseDB(base / f"{case_id}.db")
                _attach_live_events(tdb, case_id)  # F4.2 — live události i z bg ingestu
                try:
                    source = EvidenceSource(
                        case_id=case_id,
                        kind="folder" if root.is_dir() else "file",
                        path=str(root),
                    )
                    tdb.add_source(source)
                    _job_update(job_id, source_id=source.id)
                    result = process_source(
                        tdb, source.id, root, body.profile,
                        progress=_progress, resume=body.resume,
                        pool="threads",  # F2.4 — web běží s pozadím vlákny (uvicorn);
                        # per-request spawn procesů by byl zbytečný + fork riziko
                    )
                    _job_update(job_id, status="done", result=result.model_dump())
                except Exception as exc:  # defenzivně — thread nesmí umlčet chybu
                    log.exception("background ingest %s selhal", job_id)
                    _job_update(job_id, status="error", error=str(exc))
                finally:
                    tdb.close()

            threading.Thread(target=_run, name=f"stopa-ingest-{job_id}", daemon=True).start()
            return {"source_id": None, "job_id": job_id, "status": "running"}

        # sync ingest (default — backward compat): request čeká na dokončení
        try:
            source = EvidenceSource(
                case_id=case_id,
                kind="folder" if root.is_dir() else "file",
                path=str(root),
            )
            db.add_source(source)
            _job_update(job_id, source_id=source.id)
            # F2.4 — web běží s pozadím vlákny (uvicorn); per-request spawn procesů
            # by byl zbytečný + fork riziko → explicitně threads (původní E3 režim)
            result = process_source(db, source.id, root, body.profile, progress=_progress, resume=body.resume, pool="threads")
            _job_update(job_id, status="done", result=result.model_dump())
            return {
                "source_id": source.id,
                "job_id": job_id,
                **result.model_dump(),
            }
        except Exception:
            _job_update(job_id, status="error")
            raise
        finally:
            db.close()

    # ── STP-021 — Processing Monitor (živý progress ingestu) ───────────────
    @app.get("/api/cases/{case_id}/processing")
    def processing_status(case_id: str) -> dict:
        """STP-021 — stav běhů ingestu pro případ (live progress).

        `active` = právě probíhající job (GUI polluje tento endpoint během
        async ingestu); `recent` = poslední 10 běhů (nejnovější první).
        """
        with _jobs_lock:
            mine = [dict(j) for j in _jobs.values() if j["case_id"] == case_id]
        active = next((j for j in reversed(mine) if j["status"] == "running"), None)
        return {"active": active, "recent": list(reversed(mine[-10:]))}

    # ── F4.2 — WebSocket real-time updates (live progress/timeline/AI) ─────
    @app.websocket("/api/cases/{case_id}/ws")
    async def case_events_ws(websocket: WebSocket, case_id: str) -> None:
        """F4.2 — live události případu přes WebSocket.

        Kontrakt:
        - při připojení okamžitě ``{"type": "hello", ...}`` (marker pro
          klienty = úspěšné (re)spojení);
        - pak stream událostí ``ingest.progress`` / ``timeline.event`` /
          ``ai.action`` (typ v poli ``type``, čas v ``ts`` ISO-8601 UTC);
        - **heartbeat** ``{"type": "heartbeat"}`` každé ``ws_heartbeat_s``
          při neaktivitě (AK F4.2; default 15 s, parametr factory pro testy);
        - **reconnection** je na klientu (exponenciální backoff + fallback
          na REST polling — graceful degradation: bez WS vše funguje dál);
        - neznámý případ → close code 4004.

        Latence AK < 200 ms: publish je nablokující put_nowait do fronty,
        handler čte přes ``asyncio.to_thread`` (worker vlákna nepočeká).
        """
        if not re.fullmatch(r"[A-Za-z0-9._-]+", case_id or ""):
            await websocket.close(code=4000)
            return
        if not (base / f"{case_id}.db").exists():
            await websocket.accept()
            await websocket.close(code=4004, reason="případ nenalezen")
            return

        topic = case_topic(case_id)
        q: queue.Queue = _bus.subscribe(topic)
        try:
            await websocket.accept()
            await websocket.send_json({"type": "hello", "case_id": case_id, "ts": _now_iso()})
            while True:
                # get s timeoutem v worker vláknu — nepadá event loop;
                # při datu se vrátí okamžitě (latence = put_nowait + scheduling).
                try:
                    event = await asyncio.to_thread(q.get, True, _ws_heartbeat_s)
                except queue.Empty:
                    await websocket.send_json({"type": "heartbeat", "ts": _now_iso()})
                else:
                    await websocket.send_json(event)
        except WebSocketDisconnect:
            pass  # normální konec (reconnection na klientu)
        finally:
            _bus.unsubscribe(topic, q)

    # ── files / search / timeline ─────────────────────────────
    @app.get("/api/cases/{case_id}/files")
    def list_files(
        case_id: str,
        bad_ext: bool = False,
        dups: bool = False,
        family: str | None = None,
        source: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        db = open_db(case_id)
        try:
            recs = db.list_files(
                source_id=source,
                bad_extensions_only=bad_ext,
                duplicates_only=dups,
                signature_family=family,
                limit=limit,
                offset=offset,
            )
            return [r.model_dump(mode="json") for r in recs]
        finally:
            db.close()

    # F4.3 — Peer-Review Workflow (stavový automat v domain/review.py) ──────────
    @app.get("/api/cases/{case_id}/artifacts")
    def list_artifacts(case_id: str, file_id: str | None = None, limit: int = 500) -> list[dict]:
        """Artefakty případu (volitelně filtr na soubor) včetně review_state."""
        db = open_db(case_id)
        try:
            arts = db.list_artifacts(limit=limit) if file_id is None else [
                a for a in db.list_artifacts(limit=10_000) if a.file_id == file_id
            ]
            return [a.model_dump(mode="json") for a in arts]
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/artifacts/{artifact_id}/review", status_code=201)
    def artifact_review(case_id: str, artifact_id: str, body: ReviewStateIn) -> dict:
        """Přechod review stavu (draft→reviewed→approved→court_ready).

        409 = neplatný přechod/přeskočení/kvorum; 404 = artefakt neexistuje.
        Každá akce = audit log + neměnný řádek v artifact_reviews (F4.3 AK).
        """
        from stopa.domain.review import ReviewError

        _require("case.review", case_id, case_id=case_id)
        db = open_db(case_id)
        try:
            try:
                info = db.artifact_repo.set_review_state(
                    artifact_id, body.state, body.reviewer, note=body.note
                )
            except ReviewError as e:
                raise HTTPException(409, str(e)) from e
            except ValueError as e:  # artefakt neexistuje (ReviewError je subclass)
                raise HTTPException(404, str(e)) from e
        finally:
            db.close()
        _publish_case(case_id, "review.state", **info)
        return info

    @app.get("/api/cases/{case_id}/artifacts/{artifact_id}/reviews")
    def artifact_reviews(case_id: str, artifact_id: str) -> dict:
        """Aktuální stav + kritičnost + neměnná historie review akcí."""
        db = open_db(case_id)
        try:
            art = db.get_artifact(artifact_id)
            if art is None:
                raise HTTPException(404, f"artefakt {artifact_id} nenalezen")
            return {
                "artifact_id": artifact_id,
                "review_state": art.review_state,
                "critical": db.artifact_repo.is_critical_artifact(artifact_id),
                "reviews": db.artifact_repo.list_artifact_reviews(artifact_id),
            }
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/families")
    def families(case_id: str) -> list[str]:
        """DISTINCT detekované signatury — pro filtr v File System gridu."""
        db = open_db(case_id)
        try:
            rows = db.conn.execute(
                "SELECT DISTINCT signature_type FROM files"
                " WHERE signature_type IS NOT NULL AND signature_type != ''"
                " ORDER BY 1"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/search")
    def search(
        case_id: str,
        q: str = "",
        hash: str | None = Query(None),  # E9 — exact hash lookup (SHA-256/MD5)
        limit: int = 100,
    ) -> list[dict]:
        """E9 Search rozšíření: FTS + metadata filtry v `q` nebo exact `?hash=`.

        - `q` — kombinace FTS termínů a filtrů (``size:>1MB``, ``mtime:A..B``,
          ``ext:jpg``, ``in-artifact:X``)
        - `hash` — hex SHA-256/MD5 → exact lookup přes index (priorita před `q`)
        """
        db = open_db(case_id)
        try:
            if hash and hash.strip():
                recs = db.search_by_hash(hash, limit=limit)
            elif q.strip():
                from stopa.domain.search_filters import SearchFilterError

                try:
                    recs = db.search(q, limit=limit)
                except SearchFilterError as exc:
                    raise HTTPException(400, f"neplatný filtr: {exc}") from exc
            else:
                return []
            return [r.model_dump(mode="json") for r in recs]
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/timeline")
    def timeline(
        case_id: str,
        type: str | None = Query(None),
        source: str | None = Query(None),
        from_ts: datetime | None = Query(None),
        to_ts: datetime | None = Query(None),
        anomalies_only: bool = Query(False),
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict]:
        """Timeline (E2) — chronologické události s UTC i lokálním časem.

        Primárně čte materializovanou ``timeline_events``; prázdná (starý case
        bez re-ingestu) → fallback na ``artifacts``. Lokální čas počítáme přes
        case ``timezone_name`` (default Europe/Prague). Backward-kompatibilní:
        staré GUI konzumuje ``timestamp`` / ``artifact_type`` / ``title``.
        """
        db = open_db(case_id)
        try:
            tz_name = "Europe/Prague"
            case = db.get_case(case_id)
            if case is not None and case.timezone_name:
                tz_name = case.timezone_name

            events = db.list_timeline_events(
                source_id=source,
                event_type=type,
                from_ts=from_ts,
                to_ts=to_ts,
                anomalies_only=anomalies_only,
                limit=limit,
                offset=offset,
            )
            if events:
                out = []
                for e in events:
                    # lokální čas pro zobrazení (UTC zůstává kanonický)
                    local_iso = to_local_iso(
                        datetime.fromisoformat(e["ts_utc"])
                        if e["ts_utc"] else None,
                        tz_name,
                    )
                    row = {**e, "ts_local": local_iso}
                    # backward-kompatibilní aliasy pro staré GUI (artifact_type/timestamp)
                    row["artifact_type"] = e.get("event_type")
                    row["timestamp"] = e.get("ts_utc")
                    out.append(row)
                return out

            # fallback: starý case bez materializované timeline → artifacts
            arts = db.list_artifacts(
                source_id=source,
                artifact_type=type,
                from_ts=from_ts,
                to_ts=to_ts,
                anomalies_only=anomalies_only,
                limit=limit,
                offset=offset,
            )
            out = []
            for a in arts:
                d = a.model_dump(mode="json")
                local_iso = to_local_iso(a.timestamp, tz_name) if a.timestamp else None
                # backward-kompatibilní pole pro staré GUI (timestamp/artifact_type/title)
                d["ts_utc"] = d.get("timestamp")
                d["ts_local"] = local_iso
                d["anomaly_flags"] = list(a.anomaly_flags or ())
                out.append(d)
            return out
        finally:
            db.close()

    # ── F2.2 DuckDB OLAP analytics ────────────────────────────────────
    @app.get("/api/cases/{case_id}/analytics")
    def analytics(
        case_id: str,
        from_ts: datetime | None = Query(None),
        to_ts: datetime | None = Query(None),
        type: str | None = Query(None),
        limit: int = 200,
    ) -> dict:
        """F2.2 — DuckDB OLAP agregace nad timeline (histogram, top typy, okno).

        Bez nainstalovaného duckdb ([analytics] extra) → HTTP 503 s hláškou;
        standardní timeline/search zůstává v SQLite (backward-kompatibilní).
        """
        from stopa.data.analytics import AnalyticsError, AnalyticsStore, duckdb_available

        if not duckdb_available():
            raise HTTPException(
                status_code=503,
                detail="DuckDB není nainstalováno — pip install 'stopa[analytics]'",
            )
        db = open_db(case_id)
        try:
            db_path = str(db.path)
        finally:
            db.close()
        try:
            store = AnalyticsStore(db_path)
            payload: dict[str, object] = {
                "case_id": case_id,
                "status": store.status(),
                "top_event_types": store.top_event_types(limit=20),
                "entity_summary": store.entity_summary(),
            }
            if from_ts is not None and to_ts is not None:
                events = store.timeline_range(
                    from_ts.isoformat(),
                    to_ts.isoformat(),
                    event_type=type,
                    limit=limit,
                )
                payload["timeline_window"] = {
                    "from": from_ts.isoformat(),
                    "to": to_ts.isoformat(),
                    "events": events,
                    "count": len(events),
                }
            return payload  # type: ignore[return-value]
        except AnalyticsError as exc:
            raise HTTPException(status_code=502, detail=f"Analytics chyba: {exc}") from exc

    # ── STP-018 Timeline Intelligence 2.0 ─────────────────────────────
    @app.post("/api/cases/{case_id}/timeline/intel")
    def timeline_intel(case_id: str, window_seconds: float = Query(60.0)) -> dict:
        """STP-018 — explicitní spuštění Timeline Intelligence 2.0 post-passu.

        Rozpory (souběžná aktivita subjektu) + duplikáty napříč zdroji nad
        materializovanou timeline. Idempotentní, deterministický výsledek.
        """
        _require("analysis.run", "timeline_intel", case_id=case_id)
        from stopa.pipeline import run_timeline_intel

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            summary = run_timeline_intel(db, window_seconds=window_seconds)
            db.log_operation(
                "timeline_intel_run",
                actor=case.examiner if case else None,
                details={**summary, "window_seconds": window_seconds},
            )
            return summary
        finally:
            db.close()

    # ── E4 Entity + Correlation Engine ────────────────────────────────
    @app.post("/api/cases/{case_id}/correlate")
    def correlate(case_id: str) -> dict:
        """Explicitní krok korelace (ROADMAP E4 bod 4) — re-run = clear + insert."""
        _require("analysis.run", "correlate", case_id=case_id)
        from stopa.domain.correlation import run_correlation

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            summary = run_correlation(db, case_id)
            db.log_operation(
                "correlation_run",
                actor=case.examiner if case else None,
                details={
                    "entities": summary["entities"],
                    "correlations_total": summary["correlations_total"],
                    "by_relation": summary["by_relation"],
                    "merge_candidates": len(summary.get("merge_candidates", [])),
                },
            )
            return summary
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/correlations")
    def list_correlations(case_id: str) -> list[dict]:
        """Propojení entit s evidence listy (dohledatelnost každého nálezu)."""
        db = open_db(case_id)
        try:
            return db.list_correlations(case_id)
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/entities")
    def list_entities(case_id: str) -> list[dict]:
        """Kanonické entity extrahované z artifactů (E4)."""
        db = open_db(case_id)
        try:
            return db.list_entities(case_id)
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/entities/merge-candidates")
    def merge_candidates(case_id: str) -> list[dict]:
        """P0 I3 — detekce duplicitních entit s důvody (heuristické páry)."""
        from stopa.domain.entity_resolution import find_merge_candidates

        db = open_db(case_id)
        try:
            return [
                {"kind": m.kind, "value_a": m.value_a, "value_b": m.value_b, "reason": m.reason}
                for m in find_merge_candidates(db.list_entities(case_id))
            ]
        finally:
            db.close()

    # ── partition map (GUI File System & Carving — vizuální mapa) ────────────
    @app.get("/api/cases/{case_id}/partition-map")
    def partition_map(case_id: str) -> list[dict]:
        """Partition mapy všech diskových obrazů v případu."""
        db = open_db(case_id)
        try:
            arts = db.list_artifacts(artifact_type="disk_image")
            out: list[dict] = []
            for a in arts:
                d = a.details or {}
                pm = d.get("partition_map") or []
                if not pm and d.get("partitions"):
                    # starší artifact bez strukturované mapy — jen textový popis
                    pm = [{"desc": d["partitions"], "fstype": None,
                           "offset_sectors": 0, "size_sectors": 0}]
                out.append({
                    "source_id": a.source_id,
                    "image_name": a.rel_path,
                    "description": d.get("description"),
                    "files_total": d.get("files_total", 0),
                    "partitions": pm,
                })
            return out
        finally:
            db.close()

    # ── file inspector (GUI pravý panel) ───────────────────────
    @app.get("/api/cases/{case_id}/files/{file_id}")
    def get_file(case_id: str, file_id: str) -> dict:
        """Detail jednoho souboru + flagy (File Inspector)."""
        db = open_db(case_id)
        try:
            rec = db.get_file(file_id)
            if rec is None or rec.source_id not in {s.id for s in db.list_sources(case_id)}:
                raise HTTPException(404, f"soubor {file_id} nenalezen")
            source = db.get_source(rec.source_id)
            return {
                **rec.model_dump(mode="json"),
                "flags": list(db.get_file_flags(file_id)),
                "source_path": source.path if source else None,
                "in_image": bool(rec.meta_addr),  # soubor v diskovém obrazu (TSK)
            }
        finally:
            db.close()

    # ── E8 — souborová metadata (PDF/OOXML/ID3/MP4/EXIF) ───────────────
    META_MAX_BYTES = 32 * 1024 * 1024  # metadata bývají na začátku; strop pro velké soubory

    @app.get("/api/cases/{case_id}/files/{file_id}/metadata")
    def file_metadata(case_id: str, file_id: str) -> dict:
        """Metadata z obsahu souboru (čistý Python + volitelné EXIF)."""
        from stopa.domain.file_meta import extract_metadata

        db = open_db(case_id)
        try:
            rec = db.get_file(file_id)
            if rec is None or rec.source_id not in {s.id for s in db.list_sources(case_id)}:
                raise HTTPException(404, f"soubor {file_id} nenalezen")
            data = _read_file_bytes(db, rec, offset=0, length=META_MAX_BYTES)
            meta = extract_metadata(data, rec.name or "")
            return {"file_id": file_id, "name": rec.name, "metadata": meta}
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/files/compare-metadata")
    def compare_metadata(case_id: str, a: str, b: str) -> dict:
        """Porovnání metadat dvou souborů (řádky field/a/b/match)."""
        from stopa.domain.file_meta import diff_metadata, extract_metadata

        db = open_db(case_id)
        try:
            ra = db.get_file(a)
            rb = db.get_file(b)
            srcs = {s.id for s in db.list_sources(case_id)}
            if ra is None or rb is None or ra.source_id not in srcs or rb.source_id not in srcs:
                raise HTTPException(404, "soubor nenalezen")
            ma = extract_metadata(_read_file_bytes(db, ra, 0, META_MAX_BYTES), ra.name or "")
            mb = extract_metadata(_read_file_bytes(db, rb, 0, META_MAX_BYTES), rb.name or "")
            return {
                "a": {"file_id": a, "name": ra.name},
                "b": {"file_id": b, "name": rb.name},
                "diff": diff_metadata(ma, mb),
            }
        finally:
            db.close()

    @app.post("/api/files/{file_id}/flag")
    def set_flag(file_id: str, flag: str = "evidence", on: bool = True) -> dict:
        """Přepne flag souboru — „Mark as Evidence“ / „Add to Report“."""
        _require("file.flag", "set_flag")
        if flag not in ("evidence", "report"):
            raise HTTPException(400, f"neznámý flag: {flag}")
        # flag je globální (file_id je unikátní napříč case DB) — najdi správnou DB
        for path in sorted(base.glob("case-*.db")):
            db = CaseDB(path)
            try:
                if db.get_file(file_id) is None:
                    continue
                db.set_file_flag(file_id, flag, on)
                return {"file_id": file_id, "flag": flag, "on": on,
                        "flags": list(db.get_file_flags(file_id))}
            finally:
                db.close()
        raise HTTPException(404, f"soubor {file_id} nenalezen")

    @app.get("/api/cases/{case_id}/marked")
    def marked(case_id: str, flag: str | None = None) -> list[dict]:
        """Označené soubory (Evidence / Report modul)."""
        db = open_db(case_id)
        try:
            out = []
            for rec, flags in db.list_marked():
                if flag and flag not in flags:
                    continue
                out.append({**rec.model_dump(mode="json"), "flags": list(flags)})
            return out
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/files/{file_id}/hex")
    def file_hex(case_id: str, file_id: str, offset: int = 0, length: int = 256) -> dict:
        """Hex dump úryvku souboru (File Inspector — hex grid)."""
        db = open_db(case_id)
        try:
            rec = db.get_file(file_id)
            if rec is None:
                raise HTTPException(404, f"soubor {file_id} nenalezen")
            data = _read_file_bytes(db, rec, offset=offset, length=length)
            return {"file_id": file_id, "offset": offset, "length": len(data),
                    "hex": _hex_dump(data)}
        finally:
            db.close()

    # ── STP-051 — File Preview (oblast G) ───────────────────────────────
    PREVIEW_HEAD_BYTES = 64 * 1024      # hlavička pro klasifikaci
    PREVIEW_MAX_MEDIA_BYTES = 20 * 1024 * 1024   # strop inline media (RAM peak)
    PREVIEW_TEXT_SAMPLE_BYTES = 256 * 1024       # vzorka pro textový preview

    @app.get("/api/cases/{case_id}/files/{file_id}/preview")
    def file_preview(case_id: str, file_id: str):
        """Preview souboru v UI — inline media (image/audio/video) nebo JSON text.

        Klasifikace přes `domain.file_preview` (čistá logika). Neznámý/nelze
        zobrazit → 415; příliš velký media → 413.
        """
        from fastapi import Response

        from stopa.domain.file_preview import (
            classify_preview,
            extract_text_preview,
            preview_media_type,
        )

        db = open_db(case_id)
        try:
            rec = db.get_file(file_id)
            if rec is None:
                raise HTTPException(404, f"soubor {file_id} nenalezen")
            head = _read_file_bytes(db, rec, offset=0, length=PREVIEW_HEAD_BYTES)
            kind = classify_preview(head, rec.name or "")
            if kind is None:
                raise HTTPException(415, "preview není pro tento formát k dispozici")

            if kind == "text":
                sample = _read_file_bytes(db, rec, offset=0, length=PREVIEW_TEXT_SAMPLE_BYTES)
                text, truncated = extract_text_preview(sample)
                return {"kind": "text", "name": rec.name, "truncated": truncated, "text": text}

            # image / audio / video — inline bytes s MIME
            if (rec.size_bytes or 0) > PREVIEW_MAX_MEDIA_BYTES:
                raise HTTPException(413, "soubor je příliš velký pro preview")
            mime = preview_media_type(rec.signature_type, rec.name or "") or "application/octet-stream"
            data = _read_file_bytes(db, rec, offset=0, length=None)
            return Response(content=data, media_type=mime)
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/files/{file_id}/export")
    def export_file(case_id: str, file_id: str):
        """Stáhnout obsah souboru (Export File)."""
        from fastapi import Response

        db = open_db(case_id)
        try:
            rec = db.get_file(file_id)
            if rec is None:
                raise HTTPException(404, f"soubor {file_id} nenalezen")
            data = _read_file_bytes(db, rec, offset=0, length=None)
            # audit P1 — RFC 5987 quoting: nequoted `"` v názvu = header injection;
            # filename* nese UTF-8 (české názvy), fallback filename je ASCII-safe.
            # isprintable() vyfiltruje i control chars (\r\n) → CRLF injection pryč.
            name = rec.name or "soubor"
            ascii_name = "".join(c if c.isascii() and c.isprintable() and c not in '"\\' else "_" for c in name)
            return Response(
                content=data,
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{ascii_name}"; '
                        f"filename*=UTF-8''{quote(name)}"
                    )
                },
            )
        finally:
            db.close()

    # ── STP-058 — interop exporty (l2tcsv / UCO / CSV / JSON / ...) ───────
    @app.get("/api/cases/{case_id}/interop-export")
    def interop_export(
        case_id: str, what: str = "artifacts", format: str = "csv"
    ):
        """Export dat případu do interop formátů (GUI — oblast Q ★★).

        Zrcadlí ``stopa export`` CLI (stejná domain funkce), ale vrací
        soubor jako HTTP Response s Content-Disposition. Formáty:
        csv / json / jsonl / xml / stix / l2tcsv / uco. Datasety:
        artifacts / timeline / correlations. Audit + integrity checkpoint.
        """
        from fastapi import Response

        from stopa.domain.export import (
            ARTIFACT_COLUMNS,
            CORRELATION_COLUMNS,
            TIMELINE_COLUMNS,
            artifact_records,
            correlation_records,
            timeline_records,
            to_csv,
            to_json,
            to_jsonl,
            to_l2tcsv,
            to_stix_bundle,
            to_xml,
        )

        _require("analysis.run", "interop_export", case_id=case_id)
        if what not in ("artifacts", "timeline", "correlations"):
            raise HTTPException(400, f"neplatný dataset: {what}")
        valid_formats = ("csv", "json", "jsonl", "xml", "stix", "l2tcsv", "uco")
        if format not in valid_formats:
            raise HTTPException(400, f"neplatný formát: {format}")

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if what == "artifacts":
                records = artifact_records(db.list_artifacts())
                columns = ARTIFACT_COLUMNS
            elif what == "timeline":
                records = timeline_records(db.list_timeline_events())
                columns = TIMELINE_COLUMNS
            else:  # correlations
                records = correlation_records(db.list_correlations(case_id))
                columns = CORRELATION_COLUMNS

            if format == "csv":
                text = to_csv(records, columns)
            elif format == "jsonl":
                text = to_jsonl(records)
            elif format == "xml":
                text = to_xml(records, dataset=what)
            elif format == "stix":
                text = to_stix_bundle(records, dataset=what)
            elif format == "l2tcsv":
                text = to_l2tcsv(records, dataset=what)
            elif format == "uco":
                from stopa.domain.uco import to_uco_json

                text = to_uco_json(records, dataset=what)
            else:  # json (default)
                text = to_json(records)

            media_type = {
                "csv": "text/csv",
                "json": "application/json",
                "uco": "application/json",
                "stix": "application/json",
                "jsonl": "application/x-ndjson",
                "xml": "application/xml",
                "l2tcsv": "text/plain",
            }[format]

            # STP-067 — cache posledního exportu pro re-download z historie UI.
            _save_last_export(case_id, what, format, text)

            # audit P1 — RFC 5987 quoting (stejný vzor jako export_file)
            ascii_name = f"{case_id}_{what}.{format}"
            db.log_operation(
                "interop_exported",
                actor=case.examiner if case else None,
                details={"what": what, "format": format, "records": len(records)},
            )
            # P0 Core C4: kontrolní bod po exportu.
            db.add_integrity_checkpoint("export")
            return Response(
                content=text.encode("utf-8"),
                media_type=media_type,
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{ascii_name}"; '
                        f"filename*=UTF-8''{quote(ascii_name)}"
                    )
                },
            )
        finally:
            db.close()

    # ── STP-068 — ZIP bundle všech datasetů (oblast Q ★★) ───────────────
    @app.get("/api/cases/{case_id}/interop-export-bundle")
    def interop_export_bundle(case_id: str, limit: int | None = Query(default=None)):
        """Export všech 3 datasetů případu do jednoho deterministického ZIP (GUI — oblast Q ★★).

        Zrcadlí ``stopa export --bundle`` CLI (stejná domain funkce
        ``to_zip_bundle``): artifacts + timeline + correlations jako CSV
        soubory + manifest.json se SHA-256 kontrolními součty. Deterministický
        výstup pro C4: fixní pořadí souborů, fixní timestamps v ZIP, stabilní
        manifest. Volitelné ``limit`` — exportuje jen první N záznamů každého
        datasetu (None = vše; <1 → 422). Audit + integrity checkpoint.
        """
        from fastapi import Response

        from stopa.domain.export import (
            artifact_records,
            correlation_records,
            timeline_records,
            to_zip_bundle,
        )

        _require("analysis.run", "interop_export_bundle", case_id=case_id)
        if limit is not None and limit < 1:
            raise HTTPException(422, f"limit musí být ≥ 1 (dostalo se {limit})")

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, f"Případ '{case_id}' nenalezen")
            datasets = {
                "artifacts": artifact_records(db.list_artifacts()),
                "timeline": timeline_records(db.list_timeline_events()),
                "correlations": correlation_records(db.list_correlations(case_id)),
            }
            if limit is not None:
                datasets = {k: v[:limit] for k, v in datasets.items()}

            # STP-068 — deterministický timestamp z case.created_at (C4).
            data = to_zip_bundle(datasets, case_id, case.created_at.isoformat())

            # STP-068 — cache binárního bundle pro re-download z historie UI.
            _save_last_export_bytes(case_id, "bundle", "zip", data)

            ascii_name = f"{case_id}_interop-bundle.zip"
            db.log_operation(
                "interop_bundle_exported",
                actor=case.examiner if case else None,
                details={
                    "datasets": {k: len(v) for k, v in datasets.items()},
                    "limit": limit,
                    "bytes": len(data),
                },
            )
            # P0 Core C4: kontrolní bod po exportu.
            db.add_integrity_checkpoint("export")
            return Response(
                content=data,
                media_type="application/zip",
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{ascii_name}"; '
                        f"filename*=UTF-8''{quote(ascii_name)}"
                    )
                },
            )
        finally:
            db.close()

    # ── STP-064 — L2T CSV preview (oblast Q ★★) ───────────────
    @app.get("/api/cases/{case_id}/l2tcsv-preview")
    def l2tcsv_preview(case_id: str, what: str = "artifacts", limit: int = 50) -> dict:
        """Náhled l2tcsv exportu (GUI — oblast Q ★★).

        Zrcadlí ``stopa export --format l2tcsv`` / interop-export endpoint
        (stejná domain funkce ``to_l2tcsv``): vrátí první N řádků toho, co se
        reálně vyexportuje — uživatel si ověří data před downloadem/pushem.
        Read-only: bez audit záznamu i integrity checkpointu (není export).

        Datasety: artifacts / timeline / correlations. Limit clamp 1..500.
        """
        import csv as _csv
        import io as _io

        from stopa.domain.export import (
            L2TCSV_COLUMNS,
            artifact_records,
            correlation_records,
            timeline_records,
            to_l2tcsv,
        )

        _require("analysis.run", "l2tcsv_preview", case_id=case_id)
        if what not in ("artifacts", "timeline", "correlations"):
            raise HTTPException(400, f"neplatný dataset: {what}")
        limit = max(1, min(int(limit), 500))

        db = open_db(case_id)
        try:
            if what == "artifacts":
                records = artifact_records(db.list_artifacts())
            elif what == "timeline":
                records = timeline_records(db.list_timeline_events())
            else:  # correlations
                records = correlation_records(db.list_correlations(case_id))

            text = to_l2tcsv(records, dataset=what)
            rows = list(_csv.reader(_io.StringIO(text)))
            header = rows[0] if rows else []
            body = rows[1 : limit + 1]
            return {
                "case_id": case_id,
                "dataset": what,
                "columns": list(L2TCSV_COLUMNS),
                "total_records": len(records),
                "limit": limit,
                "rows": [dict(zip(header, r)) for r in body],
            }
        finally:
            db.close()

    # ── STP-066 — Export center: náhled CSV/JSON (UCO) před downloadem ──
    @app.get("/api/cases/{case_id}/export-preview")
    def export_preview(case_id: str, what: str = "artifacts", format: str = "csv", limit: int = 50) -> dict:
        """Náhled exportu v zvoleném formátu (GUI — oblast Q ★★).

        Generalizace l2tcsv-preview (STP-064) na všechny exportní formáty:
        ``l2tcsv`` / ``csv`` / ``uco`` (JSON-LD). Zrcadlí reálný export
        (stejné domain serializátory) — uživatel si ověří data před
        downloadem. Read-only: bez audit záznamu i integrity checkpointu.

        - ``l2tcsv`` — 17 sloupců log2timeline.pl (stejně jako l2tcsv-preview),
        - ``csv``    — nativní STOPA sloupce datasetu,
        - ``uco``    — první N objektů UCO JSON-LD dokumentu.

        Datasety: artifacts / timeline / correlations. Limit clamp 1..500.
        """
        import csv as _csv
        import io as _io
        import json as _json

        from stopa.domain.export import (
            ARTIFACT_COLUMNS,
            CORRELATION_COLUMNS,
            L2TCSV_COLUMNS,
            TIMELINE_COLUMNS,
            artifact_records,
            correlation_records,
            timeline_records,
            to_l2tcsv,
        )
        from stopa.domain.uco import to_uco_json

        _require("analysis.run", "export_preview", case_id=case_id)
        if what not in ("artifacts", "timeline", "correlations"):
            raise HTTPException(400, f"neplatný dataset: {what}")
        if format not in ("l2tcsv", "csv", "uco"):
            raise HTTPException(400, f"neplatný formát: {format}")
        limit = max(1, min(int(limit), 500))

        db = open_db(case_id)
        try:
            if what == "artifacts":
                records = artifact_records(db.list_artifacts())
            elif what == "timeline":
                records = timeline_records(db.list_timeline_events())
            else:  # correlations
                records = correlation_records(db.list_correlations(case_id))

            total = len(records)
            if format == "l2tcsv":
                text = to_l2tcsv(records, dataset=what)
                rows = list(_csv.reader(_io.StringIO(text)))
                header = rows[0] if rows else []
                body = rows[1 : limit + 1]
                return {
                    "case_id": case_id,
                    "dataset": what,
                    "format": format,
                    "columns": list(L2TCSV_COLUMNS),
                    "total_records": total,
                    "limit": limit,
                    "rows": [dict(zip(header, r)) for r in body],
                }

            if format == "csv":
                columns = {
                    "artifacts": ARTIFACT_COLUMNS,
                    "timeline": TIMELINE_COLUMNS,
                    "correlations": CORRELATION_COLUMNS,
                }[what]
                return {
                    "case_id": case_id,
                    "dataset": what,
                    "format": format,
                    "columns": list(columns),
                    "total_records": total,
                    "limit": limit,
                    "rows": [dict(r) for r in records[:limit]],
                }

            # uco — JSON-LD dokument; preview = první N objektů
            doc = _json.loads(to_uco_json(records, dataset=what))
            objects = doc.get("objects", [])[:limit]
            cols: list[str] = []
            for obj in objects:
                for key in obj:
                    if key not in cols:
                        cols.append(key)
            return {
                "case_id": case_id,
                "dataset": what,
                "format": format,
                "columns": cols,
                "total_records": total,
                "limit": limit,
                "rows": objects,
            }
        finally:
            db.close()

    # ── STP-067 — re-download posledního exportu z historie (oblast Q ★★) ──
    @app.get("/api/cases/{case_id}/last-export")
    def last_export(case_id: str, what: str = "artifacts", format: str = "csv"):
        """Re-download posledního exportu datasetu+formátu (GUI — oblast Q ★★).

        Vrací cache soubor uložený při posledním ``interop-export`` pro daný
        dataset a formát — uživatel si z historie v UI stáhne stejná data,
        která už jednou vyexportoval, bez nového exportu. Read-only: bez audit
        záznamu i integrity checkpointu (není nový export).

        STP-068: ``what=bundle&format=zip`` re-downloaduje poslední ZIP bundle
        všech datasetů (cache uložená při ``interop-export-bundle``).

        404 = pro daný dataset+formát ještě nebylo nic exportováno.
        """
        _require("analysis.run", "last_export", case_id=case_id)
        if what not in ("artifacts", "timeline", "correlations", "bundle"):
            raise HTTPException(400, f"neplatný dataset: {what}")
        # STP-068 — bundle se re-downloaduje jen jako zip; ostatní datasety
        # zip neznají (cache layout {what}.{format} je sdílený).
        if what == "bundle":
            valid_formats = ("zip",)
        else:
            valid_formats = ("csv", "json", "jsonl", "xml", "stix", "l2tcsv", "uco")
        if format not in valid_formats:
            raise HTTPException(400, f"neplatný formát: {format}")

        # case musí existovat (open_db → 404), cache nemusí
        db = open_db(case_id)
        db.close()

        path = _load_last_export(case_id, what, format)
        if path is None:
            raise HTTPException(
                404, f"pro {what}/{format} ještě nebylo nic exportováno"
            )

        media_type = {
            "csv": "text/csv",
            "json": "application/json",
            "uco": "application/json",
            "stix": "application/json",
            "jsonl": "application/x-ndjson",
            "xml": "application/xml",
            "l2tcsv": "text/plain",
            "zip": "application/zip",  # STP-068 — ZIP bundle
        }[format]
        # FileResponse s filename= sám nastaví Content-Disposition: attachment.
        return FileResponse(path, media_type=media_type, filename=f"{case_id}_{what}.{format}")

    # ── STP-069 — download posledního automatického ZIP bundle (opt-in) ──
    @app.get("/api/cases/{case_id}/auto-export")
    def auto_export_download(case_id: str):
        """Re-download posledního automatického ZIP bundle (STP-069).

        Auto-bundle generuje pipeline hook po dokončení processingu, pokud je u
        případu zapnutý ``auto_export_enabled``. Cesta je persistovaná v case DB
        (``last_auto_export_path``); fallback = trvalá cache layout
        ``{db_dir}/exports/{case_id}/auto-bundle.zip``. Read-only: bez auditu.

        404 = auto-export ještě nikdy nebyl vygenerován.
        """
        _require("analysis.run", "auto_export_download", case_id=case_id)
        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, f"Případ '{case_id}' nenalezen")
        finally:
            db.close()

        path: Path | None = None
        persisted = getattr(case, "last_auto_export_path", None)
        if persisted and Path(persisted).is_file():
            path = Path(persisted)
        else:
            path = _load_last_export(case_id, "auto-bundle", "zip")
        if path is None:
            raise HTTPException(404, "automatický export ještě nebyl vygenerován")

        return FileResponse(
            path, media_type="application/zip", filename=f"{case_id}_auto-bundle.zip"
        )

    # ── STP-059 — Timesketch push (oblast Q, interop) ───────────────
    @app.post("/api/cases/{case_id}/timesketch-push")
    def timesketch_push(case_id: str, body: TimesketchPushIn) -> dict:
        """Push datasetu případu do nového Timesketch sketchu (GUI — oblast Q ★★).

        Zrcadlí ``stopa timesketch-push`` CLI (stejná domain funkce):
        vytvoří sketch a nahraje l2tcsv timeline. Datasety: artifacts /
        timeline / correlations. STP-065: volitelné ``limit`` — pushne jen
        první N záznamů datasetu (None = vše; <1 → 422). Audit + integrity
        checkpoint. Timesketch nedostupná → 503; push selhal → 502 srozumitelnou
        zprávou.
        """
        from stopa.domain.export import (
            artifact_records,
            correlation_records,
            timeline_records,
        )
        from stopa.domain.timesketch_push import push_to_timesketch

        _require("analysis.run", "timesketch_push", case_id=case_id)
        if body.what not in ("artifacts", "timeline", "correlations"):
            raise HTTPException(400, f"neplatný dataset: {body.what}")

        client = TimesketchClient()
        health = client.health()
        if not health["available"]:
            raise HTTPException(
                503, "Timesketch nedostupná — spusťte ji (STOPA_TIMESKETCH_URL)"
            )

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if body.what == "artifacts":
                records = artifact_records(db.list_artifacts())
            elif body.what == "timeline":
                records = timeline_records(db.list_timeline_events())
            else:  # correlations
                records = correlation_records(db.list_correlations(case_id))

            try:
                summary = push_to_timesketch(
                    client, case.name if case else case_id, body.what, records,
                    limit=body.limit,
                )
            except TimesketchUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except (TimesketchError, ValueError) as exc:
                raise HTTPException(502, f"Timesketch push selhal: {exc}") from exc

            db.log_operation(
                "timesketch_pushed",
                actor=case.examiner if case else None,
                details={**summary, "what": body.what},
            )
            # P0 Core C4: kontrolní bod po pushi.
            db.add_integrity_checkpoint("timesketch-push")
            return summary
        finally:
            db.close()

    # ── STP-061 — Timesketch timeline status (live polling, oblast Q ★★) ───
    @app.get("/api/cases/{case_id}/timesketch-status")
    def timesketch_status(case_id: str):
        """Live stav indexace naposledy pushnuté timeline (oblast Q ★★).

        Read-only endpoint pro UI polling: najde poslední audit záznam
        ``timesketch_pushed`` (sketch_id + timeline_id) a dotáže Timesketch
        ``GET /api/v1/sketches/{sid}/timelines/{tid}/`` → stav indexace
        (``new``/``processing``/``ready``/``fail``).

        Chybové cesty: 404 — case neexistuje nebo ještě žádný push;
        503 — Timesketch nedostupná; 502 — dotaz selhal (HTTP != 200 /
        ne-JSON). Read-only → RBAC ``case.read`` (všechny role), bez auditu.
        """
        _require("case.read", "timesketch_status", case_id=case_id)

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, f"case neexistuje: {case_id}")

            # poslední push — audit log je nejnovější první
            last_push: dict | None = None
            for entry in db.list_audit_log(limit=200):
                if entry.get("action") == "timesketch_pushed":
                    last_push = entry
                    break
            details = (last_push or {}).get("details") or {}
            sketch_id = details.get("sketch_id")
            timeline_id = details.get("timeline_id")
            if not isinstance(sketch_id, int) or not isinstance(timeline_id, int):
                raise HTTPException(
                    404, "zatím žádný Timesketch push v audit logu"
                )

            client = TimesketchClient()
            health = client.health()
            if not health["available"]:
                raise HTTPException(
                    503, "Timesketch nedostupná — spusťte ji (STOPA_TIMESKETCH_URL)"
                )
            try:
                st = client.timeline_status(sketch_id, timeline_id)
            except TimesketchUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except TimesketchError as exc:
                raise HTTPException(502, f"Timesketch status selhal: {exc}") from exc

            return {
                "sketch_id": sketch_id,
                "timeline_id": timeline_id,
                "status": st["status"],
                "updated_at": st["updated_at"],
            }
        finally:
            db.close()

    # ── STP-063 — Plaso import (l2tcsv upload, oblast Q ★★) ────────────────
    @app.post("/api/cases/{case_id}/plaso-import")
    async def plaso_import(case_id: str, file: UploadFile = File(...)) -> dict:
        """Import l2tcsv souboru do případu (GUI — oblast Q ★★).

        Zrcadlí ``stopa plaso-import`` CLI (stejná domain funkce): evidence
        source + artifacts (idempotentní upsert) + timeline events. Audit +
        integrity checkpoint. Chybové cesty: 404 case neexistuje; 415 špatný
        typ souboru; 422 prázdný soubor / nevalidní UTF-8.
        """
        from stopa.domain.plaso_import import import_l2tcsv

        _require("analysis.run", "plaso_import", case_id=case_id)

        filename = file.filename or ""
        if not filename.endswith((".csv", ".l2t.csv")):
            raise HTTPException(415, "očekáván l2tcsv soubor (.csv)")

        raw = await file.read()
        if not raw.strip():
            raise HTTPException(422, "soubor je prázdný")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(422, f"soubor není validní UTF-8: {exc}") from exc

        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            summary = import_l2tcsv(db, case_id, text, source_path=filename)
            db.log_operation(
                "plaso_import",
                actor=case.examiner if case else None,
                details={**summary, "file": filename},
            )
            # P0 Core C4: kontrolní bod po importu.
            db.add_integrity_checkpoint("plaso-import")
            return summary
        finally:
            db.close()

    # ── report (FÁZE 7) ───────────────────────────────────────
    @app.get("/api/cases/{case_id}/report")
    def report(case_id: str, format: str = "html"):
        from fastapi import Response

        from stopa.presentation.case_report import build_html

        db = open_db(case_id)
        try:
            data = build_report_data_safe(db, case_id)
        finally:
            db.close()
        html_doc = build_html(data)
        filename = f"{case_id}_report.{format}"
        if format == "pdf":
            import io

            from weasyprint import HTML  # type: ignore[import-untyped]

            buf = io.BytesIO()
            try:
                HTML(string=html_doc).write_pdf(buf)
            except Exception as e:
                raise HTTPException(500, f"PDF report selhal: {e}") from e
            return Response(
                content=buf.getvalue(),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        return Response(
            content=html_doc.encode("utf-8"),
            media_type="text/html",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── F5.2 — SWGDE/ISO 27037 Compliance Report ────────────────
    @app.get("/api/cases/{case_id}/compliance-report")
    def compliance_report(case_id: str, format: str = "pdf"):
        """Podepsaný compliance report (PDF nebo JSON) pro externího auditora."""
        from fastapi import Response

        from stopa.presentation.compliance_report import generate_compliance_report

        db = open_db(case_id)
        try:
            out = generate_compliance_report(db, case_id)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        finally:
            db.close()
        filename = f"{case_id}_compliance.{format}"
        if format == "json":
            content = out["json_path"].read_text(encoding="utf-8").encode("utf-8")
            return Response(
                content=content,
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        if out.get("pdf_path") is None:
            raise HTTPException(500, "PDF compliance report selhal (weasyprint chybí)")
        return Response(
            content=out["pdf_path"].read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── F5.5 — Daubert challenge preparedness pack (1-click JSON pro soud) ────
    @app.get("/api/cases/{case_id}/daubert-pack")
    def daubert_pack(case_id: str):
        """Daubert balík: peer-reviewed reference, validační testy, error rates."""
        from fastapi import Response

        from stopa.presentation.daubert import generate_daubert_pack

        db = open_db(case_id)
        try:
            out = generate_daubert_pack(db, case_id)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        finally:
            db.close()
        content = out["json_path"].read_text(encoding="utf-8").encode("utf-8")
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{case_id}_daubert.json"'
            },
        )

    # ── F5.4 — Write-blocker integration API (status + attach/remove) ──────────
    @app.get("/api/cases/{case_id}/write-blocker")
    def wb_status(case_id: str) -> dict:
        """Aktuální WB stav + rozhodnutí ingest brány pro UI."""
        db = open_db(case_id)
        try:
            repo = WriteBlockerRepository(db.conn, db.audit_repo)
            state = repo.latest_state()
            require_wb = bool(_load_settings().get("require_write_blocker", False))
            gate = ingest_gate(state, require_wb)
            return {
                "state": state,
                "require_wb": require_wb,
                "allowed": gate.allowed,
                "warning": gate.warning,
                # podporovaní vendori pro UI select (AK: 3 vendori)
                "vendors": [{"id": v.vendor_id, "label": v.label} for v in VENDORS],
                "history": repo.history(),
            }
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/write-blocker/attach", status_code=201)
    def wb_attach(case_id: str, body: WBAttachIn) -> dict:
        """Zaznamenat připojení WB (auto-detekce vendoru z device stringu)."""
        _require("source.add", "wb_attach", case_id=case_id)
        db = open_db(case_id)
        try:
            repo = WriteBlockerRepository(db.conn, db.audit_repo)
            device = (body.device or "").strip()
            match = detect_write_blocker(device) if device else None
            vendor_id = body.vendor or (match.vendor_id if match else None)
            if not vendor_id:
                raise HTTPException(
                    400,
                    f"vendor nedetekován ({device!r}) — zadejte vendor z "
                    f"{', '.join(known_vendor_ids())}",
                )
            row_id = repo.attach(
                vendor=vendor_id,
                product=body.product,
                device=device or None,
                notes=body.notes,
            )
            return {
                "vendor": vendor_id,
                "detected_from_device": match is not None and bool(device),
                "audit_id": row_id,
            }
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/write-blocker/remove")
    def wb_remove(case_id: str, body: WBRemoveIn) -> dict:
        """Zaznamenat odebrání WB."""
        _require("source.add", "wb_remove", case_id=case_id)
        db = open_db(case_id)
        try:
            row_id = WriteBlockerRepository(db.conn, db.audit_repo).remove(
                reason=body.reason
            )
            return {"audit_id": row_id}
        finally:
            db.close()

    # ── STP-050 — Validation Center (C3 registry + C6 report) ──
    @app.get("/api/cases/{case_id}/validation")
    def validation_report(case_id: str) -> dict:
        """Validační report případu — coverage parserů, statusy, per-artifact řádky.

        Čistá agregace nad DB (C6 ``build_validation_report``); selhání registry
        degraduje na 500 s logem (defenzivní obal).
        """
        from stopa.data.validation_report import build_validation_report

        db = open_db(case_id)
        try:
            return build_validation_report(db, case_id)
        except Exception as e:  # doplňková vrstva — log + degradace
            log.warning("validation report selhal pro %s: %s", case_id, e)
            raise HTTPException(500, f"validační report selhal: {e}") from e
        finally:
            db.close()

    @app.get("/api/validation/registry")
    def validation_registry() -> dict:
        """Parser Validation Registry (C3) — řádky s identitou a validací parserů.

        Synchronizace registry × pipeline; nesoulad → 500 s logem (defenzivní obal).
        """
        from stopa.domain.validation_registry import build_registry, registry_report

        try:
            rows = registry_report(build_registry())
        except Exception as e:  # doplňková vrstva — log + degradace
            log.warning("parser validation registry selhal: %s", e)
            raise HTTPException(500, f"parser registry selhal: {e}") from e
        return {"count": len(rows), "parsers": rows}

    # ── STP-052 — Audit Center (oblast O) ─────────────────────
    @app.get("/api/cases/{case_id}/audit")
    def audit_center(
        case_id: str, limit: int = 100, actor: str | None = Query(None)
    ) -> dict:
        """Audit Center — neměnná stopa + integrity v jednom reportu.

        F4.4: ``actor`` volitelně filtruje audit log per user (username).

        Agreguje (čistá čtení nad DB):
        - ``chain`` — výsledek ověření hash řetězce audit logu (C4),
        - ``entries`` — nejnovější záznamy audit trailu (limit, default 100),
        - ``checkpoints`` — Ed25519 kontrolní body + nezávislé ověření podpisů,
        - ``seals`` / ``seal_checks`` — F5.1 Merkle pečetě případu + jejich
          ověření (root shoda + Ed25519 podpis) pro soudní report.

        Selhání degraduje na 500 s logem (defenzivní obal).
        """
        db = open_db(case_id)
        try:
            report = db.verify_audit_chain()
            entries = db.list_audit_log(limit=max(1, min(int(limit), 1000)), actor=actor)
            checkpoints = db.list_integrity_checkpoints()
            checkpoint_checks = db.verify_integrity_checkpoints()
            seals = db.seal_repo.list_seals()
            seal_checks = db.seal_repo.verify_all()
            return {
                "chain": {
                    "ok": report.ok,
                    "rows_checked": report.rows_checked,
                    "broken_at_id": report.broken_at_id,
                    "reason": report.reason,
                },
                "total_entries": len(entries),
                "entries": entries,
                "public_key": db.integrity_public_key(),
                "checkpoints": checkpoints,
                "checkpoint_checks": checkpoint_checks,
                "seals": seals,
                "seal_checks": seal_checks,
            }
        except Exception as e:  # doplňková vrstva — log + degradace
            log.warning("audit center selhal pro %s: %s", case_id, e)
            raise HTTPException(500, f"audit report selhal: {e}") from e
        finally:
            db.close()

    # ── E11 — AI Forensic Assistant (LM Studio) ───────────────
    @app.get("/api/ai/status")
    def ai_status() -> dict:
        """Dostupnost LM Studio — GUI ukáže „AI nedostupná“ bez chyb."""
        return LmStudioClient().health()

    @app.post("/api/cases/{case_id}/ai/query")
    def ai_query(case_id: str, body: AiQueryIn) -> dict:
        """Jeden dotaz na AI asistenta (3 režimy).

        - ``nl_search`` → vrácen i použitý STOPA FTS query + citace souborů
        - ``summary``   → shrnutí případu s citacemi artifactů
        - ``explain``   → vysvětlení jednoho artifactu (artifact_id)

        Citace = validované ID (soubory/artifacty existují v DB); GUI je
        vykreslí jako klikací odkazy na File Inspector.
        """
        if body.mode not in ("nl_search", "summary", "explain"):
            raise HTTPException(400, f"neznámý režim: {body.mode}")
        _require("analysis.run", "ai_query", case_id=case_id)
        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, "případ neexistuje")

            client = LmStudioClient()
            health = client.health()
            if not health["available"]:
                raise HTTPException(503, "AI nedostupná — spusťte LM Studio (localhost:1234)")

            # STP-019 — PII redaktor (settings toggle, default ON) + auditní model name
            redact_pii = bool(_load_settings().get("ai_redact_pii", True))
            model_name = str(health.get("model") or None)
            try:
                if body.mode == "nl_search":
                    return _ai_nl_search(
                        db, case_id, case.name, body.question, client,
                        redact_pii=redact_pii, model=model_name,
                    )
                if body.mode == "summary":
                    return _ai_summary(
                        db, case_id, case.name, client,
                        redact_pii=redact_pii, model=model_name,
                    )
                return _ai_explain(
                    db, case_id, body.artifact_id, client,
                    redact_pii=redact_pii, model=model_name,
                )
            except LmStudioUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
        finally:
            db.close()

    # ── P0 Intelligence I1 — AI orchestrace (multi-agent) ───────────────
    @app.post("/api/cases/{case_id}/ai/analyze")
    def ai_analyze(case_id: str, body: AiAnalyzeIn) -> dict:
        """Analytický úkol přes AI orchestraci (5 agentů).

        Explicitní ``agent`` má přednost; jinak auto-routing podle dotazu.
        Výstup = validovaný JSON modelu vybraného agenta + auditní metadata
        (citace, délka promptu, doba inference). Fail-closed: nevalidní
        odpověď LLM → 502 s úryvkem (auditovatelné).
        """
        from stopa.intelligence import (
            OrchestrationError,
            audit_ai_query,
            build_case_context,
            orchestrate,
            prompt_hash,
            retrieve,
        )

        if not body.question.strip():
            raise HTTPException(400, "chybí otázka")
        _require("analysis.run", "ai_analyze", case_id=case_id)
        db = open_db(case_id)
        try:
            case = db.get_case(case_id)
            if case is None:
                raise HTTPException(404, "případ neexistuje")

            client = LmStudioClient()
            health = client.health()
            if not health["available"]:
                raise HTTPException(503, "AI nedostupná — spusťte LM Studio (localhost:1234)")

            context = build_case_context(db, case_id)
            # P0 Intelligence I2 — Forensic RAG: retrieval napříč vrstvami
            rag = retrieve(body.question, db=db, case_id=case_id)
            # STP-019 — PII redaktor (settings toggle, default ON)
            redact_pii = bool(_load_settings().get("ai_redact_pii", True))
            try:
                result = orchestrate(
                    client.chat,
                    context,
                    body.question,
                    agent_id=body.agent,
                    rag=rag,
                    redact_pii=redact_pii,
                )
            except LmStudioUnavailable as exc:
                raise HTTPException(503, str(exc)) from exc
            except OrchestrationError as exc:
                raise HTTPException(502, f"AI orchestrace selhala: {exc}") from exc

            # audit AI dotazu (evidence modelu + promptu) — analysis_operations
            from stopa.intelligence.ai_orchestrator import build_prompt, route_agent

            profile = route_agent(body.question, body.agent)
            ph = prompt_hash(
                build_prompt(profile, context, body.question, rag=rag, redact_pii=redact_pii)
            )
            audit_ai_query(
                db,
                case_id=case_id,
                question=body.question,
                model=str(health.get("model") or None),
                prompt_sha256=ph,
                citations=result.citations,
                agent=result.agent_id,
            )

            db.log_operation(
                "ai_analyzed",
                actor="web",
                details={
                    "agent": result.agent_id,
                    "question": body.question[:200],
                    "citations": result.citations,
                    "duration_ms": round(result.duration_ms, 1),
                },
            )
            return {
                "agent": result.agent_id,
                "output": result.output.model_dump(mode="json"),
                "citations": result.citations,
                "rag": {
                    "case": len(rag.case_chunks),
                    "technical": len(rag.technical_chunks),
                    "knowledge": len(rag.knowledge_chunks),
                },
                "prompt_chars": result.prompt_chars,
                "duration_ms": round(result.duration_ms, 1),
            }
        finally:
            db.close()

    # ── E12 — System Diagnostics ──────────────────────────────
    # ── F3.5: Hypothesis Graph (AI graf hypotéz + ruční potvrzení/vyvrácení) ──
    @app.get("/api/cases/{case_id}/hypotheses")
    def hypotheses_list(case_id: str) -> dict:
        """Graf hypotéz případu: uzly + hrany + lineage k artefaktům."""
        from stopa.intelligence.hypothesis_graph import graph_payload

        _require("analysis.run", "hypotheses_list", case_id=case_id)
        db = open_db(case_id)
        try:
            if db.get_case(case_id) is None:
                raise HTTPException(404, "případ neexistuje")
            return graph_payload(db, case_id)
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/hypotheses/generate", status_code=201)
    def hypotheses_generate(case_id: str, body: AiHypoGenerateIn) -> dict:
        """Sestaví a uloží graf hypotéz (AI nebo deterministický fallback)."""
        from stopa.intelligence.hypothesis_graph import (
            HypothesisGraphError,
            build_hypothesis_graph,
            graph_payload,
            store_graph,
        )

        _require("analysis.run", "hypotheses_generate", case_id=case_id)
        db = open_db(case_id)
        try:
            if db.get_case(case_id) is None:
                raise HTTPException(404, "případ neexistuje")
            llm_call: Callable[[str], str] | None = None
            source = "fallback"
            if body.use_ai:
                client = LmStudioClient()
                health = client.health()
                if not health["available"]:
                    raise HTTPException(503, "AI nedostupná — spusťte LM Studio (localhost:1234)")

                def _llm(prompt: str) -> str:
                    return client.chat([{"role": "user", "content": prompt}])

                llm_call = _llm
                source = "llm"
            try:
                nodes = build_hypothesis_graph(db, case_id, llm_call=llm_call)
            except HypothesisGraphError as exc:
                raise HTTPException(422, f"neplatný výstup LLM: {exc}") from exc
            ids = store_graph(db, case_id, nodes, source=source)
            return {"nodes": len(ids), "ids": ids, "graph": graph_payload(db, case_id)}
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/hypotheses/{hyp_id}/status")
    def hypotheses_status(case_id: str, hyp_id: str, body: AiHypoStatusIn) -> dict:
        """Ruční potvrzení/vyvrácení hypotézy (AK F3.5)."""
        from stopa.data.hypothesis_repository import HYPOTHESIS_STATUSES

        _require("analysis.run", "hypotheses_status", case_id=case_id)
        if body.status not in HYPOTHESIS_STATUSES:
            raise HTTPException(400, f"neplatný stav (očekáváno pending|confirmed|refuted): {body.status}")
        db = open_db(case_id)
        try:
            node = db.get_hypothesis(hyp_id)
            if node is None or node["case_id"] != case_id:
                raise HTTPException(404, "hypotéza neexistuje")
            db.set_hypothesis_status(hyp_id, body.status)
            db.log_operation(
                "hypothesis_status_changed", actor="web", details={"id": hyp_id, "status": body.status}
            )
            return db.get_hypothesis(hyp_id) or {}
        finally:
            db.close()

    @app.get("/api/cases/{case_id}/hypotheses/export")
    def hypotheses_export(case_id: str, format: str = Query("json")) -> Response:
        """Export grafu hypotéz — PDF/JSON (AK F3.5)."""
        from stopa.intelligence.hypothesis_graph import export_graph_json, export_graph_pdf

        _require("analysis.run", "hypotheses_export", case_id=case_id)
        if format not in ("json", "pdf"):
            raise HTTPException(400, f"neznámý formát: {format}")
        db = open_db(case_id)
        try:
            if db.get_case(case_id) is None:
                raise HTTPException(404, "případ neexistuje")
            if format == "json":
                text = export_graph_json(db, case_id)
                _save_last_export(case_id, "hypotheses", "json", text)
                return Response(content=text, media_type="application/json")
            out = _last_export_path(case_id, "hypotheses", "pdf")
            try:
                export_graph_pdf(db, case_id, out)
            except RuntimeError as exc:
                raise HTTPException(501, str(exc)) from exc
            data = out.read_bytes()
            _save_last_export_bytes(case_id, "hypotheses", "pdf", data)
            return Response(content=data, media_type="application/pdf")
        finally:
            db.close()

    @app.get("/api/diagnostics")
    def diagnostics() -> dict:
        """Verze knihoven + dostupnost volitelných komponent (TSK/EWF/FDE).

        Poslední operace z audit_log všech případů (nejnovější 10) — GUI je
        zobrazí jako „poslední aktivity“; chyby = processing_completed s errors>0.
        """
        from stopa.data.diagnostics import collect_diagnostics
        from stopa.data.query_cache import PROCESS_CACHE

        out = collect_diagnostics()
        # F2.5 — stav query cache (hit ratio pro opakované operace)
        out["query_cache"] = PROCESS_CACHE.stats()
        recent: list[dict] = []
        for path in sorted(base.glob("case-*.db")):
            db = CaseDB(path)
            try:
                for row in db.list_audit_log(limit=10):
                    row["case_id"] = path.stem
                    recent.append(row)
            finally:
                db.close()
        recent.sort(key=lambda r: r.get("ts") or "", reverse=True)
        out["recent_operations"] = recent[:25]
        return out

    # ── E12 — Settings (persistence do settings.json v db_dir) ──
    def _settings_path() -> Path:
        return base / "settings.json"

    def _load_settings() -> dict:
        p = _settings_path()
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            log.warning("settings.json je poškozený — použiju defaulty")
            return {}

    def _save_settings(data: dict) -> None:
        _settings_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── STP-053 — RBAC enforcement (permission matrix z domain/rbac.py) ──
    def _current_role() -> str:
        """Aktuální role; bez uložené hodnoty → default (examiner)."""
        return _load_settings().get("role") or DEFAULT_ROLE

    def _require(permission: str, context: str = "", *, case_id: str | None = None) -> None:
        """Validuje oprávnění — F4.4 multi-user + STP-053 legacy role.

        - **Session uživatel** (multi-user): efektivní role z per-case členství
          (:func:`access_for_case`); ``case_id`` aktivuje case kontext;
          bez přístupu → 403 fail-closed.
        - **Bez tokenu**: multi-user režim → 401 (fail-closed); legacy single-operator
          → settings role jako dosud (zpětná kompatibilita).
        - **Neplatný/expirovaný token** → 401 (fail-closed).
        """
        status, user = _current_user()
        if status == "ok":
            if case_id is not None:
                # case kontext: členství vyhrává (access_for_case), fail-closed 403
                repo = _user_repo()
                try:
                    grants = repo.case_grants(user["id"], case_id)
                finally:
                    repo.conn.close()
                has_access, role = access_for_case(user["role"], grants)
                if not (has_access and role is not None):
                    raise HTTPException(403, f"uživatel {user['username']} nemá přístup k případu")
            else:
                # globální operace mimo case kontext → globální role uživatele
                role = user["role"]
            try:
                require_permission(role, permission, context=context or (case_id or ""))
            except RBACDenied as exc:
                raise HTTPException(403, str(exc)) from exc
        elif status == "no-token":
            if _multi_user_mode():
                raise HTTPException(401, "chybějící session (F4.4 multi-user režim)")
            try:
                require_permission(_current_role(), permission, context=context)
            except RBACDenied as exc:
                raise HTTPException(403, str(exc)) from exc
        else:  # bad token — fail-closed
            raise HTTPException(401, "neplatná nebo expirovaná session")

    @app.get("/api/settings")
    def get_settings() -> dict:
        """Uživatelská nastavení (defaulty + uložené přepsání)."""
        s = _load_settings()
        # F4.4 — multi-user: role session uživatele mačí přepínač v settings
        status, user = _current_user()
        role = user["role"] if status == "ok" else (s.get("role") or DEFAULT_ROLE)
        return {
            "timezone_name": s.get("timezone_name", "Europe/Prague"),
            "ai_url": s.get("ai_url") or os.environ.get(
                "STOPA_LMSTUDIO_URL", "http://localhost:1234/v1"
            ),
            "role": role,
            # STP-053 — oprávnění aktuální role (permission matrix)
            "permissions": permissions_for(role),
            "bind_address": s.get("bind_address", "127.0.0.1"),
            # STP-019 — PII redaktor je default ON (fail-safe: maskovat)
            "ai_redact_pii": bool(s.get("ai_redact_pii", True)),
            # F5.4 — write-blocker ingest gate (default OFF = backward compat)
            "require_write_blocker": bool(s.get("require_write_blocker", False)),
            # F4.4 — multi-user režim + identita session (SPA topbar / login gate)
            "multi_user_mode": _multi_user_mode(),
            "user": (
                {"username": user["username"], "role": user["role"]}
                if status == "ok"
                else None
            ),
        }

    @app.get("/api/roles")
    def get_roles() -> dict:
        """STP-056 — matice rolí pro UI přepínač role (Settings + topbar).

        Vrací role v pořadí od nejnižší po nejvyšší privilegie, labely a
        oprávnění každé role (z permission matrix — jediný zdroj pravdy).
        Čistě čtení; žádné oprávnění nevyžaduje.
        """
        return {
            "default": DEFAULT_ROLE,
            "roles": [
                {"id": r, "label": ROLE_LABELS[r], "permissions": permissions_for(r)}
                for r in ROLES
            ],
            # všechna oprávnění v matici (pro UI legendu) — deterministicky seřazené
            "all_permissions": sorted(PERMISSIONS),
        }

    @app.put("/api/settings")
    def put_settings(body: SettingsIn) -> dict:
        """Uloží nastavení (jen zadaná pole). Bind address platí po restartu."""
        _require("settings.write", "put_settings")
        if body.role is not None and normalize_role(body.role) is None:
            raise HTTPException(400, f"neznámá role: {body.role!r} (povoleno: analyst/examiner/admin)")
        s = _load_settings()
        if body.timezone_name is not None:
            s["timezone_name"] = body.timezone_name
        if body.ai_url is not None:
            s["ai_url"] = body.ai_url
        if body.role is not None:
            s["role"] = body.role
        if body.bind_address is not None:
            s["bind_address"] = body.bind_address
        if body.ai_redact_pii is not None:
            s["ai_redact_pii"] = bool(body.ai_redact_pii)
        if body.require_write_blocker is not None:  # F5.4 — WB ingest gate
            s["require_write_blocker"] = bool(body.require_write_blocker)
        _save_settings(s)
        return get_settings()

    # ── F4.4 — Multi-tenant RBAC endpoints (orgs/teams/users/members/sso) ───────
    @app.get("/auth/me")
    def auth_me() -> dict:
        """Identita aktuální session + case členství; anonymní → 401 fail-closed."""
        status, user = _current_user()
        if status != "ok":
            raise HTTPException(401, "neaktivní nebo neplatná session")
        repo = _user_repo()
        try:
            memberships = repo.user_memberships(user["id"])
        finally:
            repo.conn.close()
        return {**dict(user), "memberships": memberships}

    @app.post("/auth/login")
    def auth_login(body: LoginIn) -> dict:
        """Login přes SSO ``id_token`` nebo lokální ``username`` (bootstrap režim)."""
        if bool(body.id_token) == bool(body.username):
            raise HTTPException(400, "zadejte právě id_token nebo username")
        if body.id_token is not None:
            claims = _sso_verify_id_token(body.id_token)  # RS256/HS256 fail-closed
            repo = _user_repo()
            try:
                row = repo.get_user(username=str(claims["sub"]))
            finally:
                repo.conn.close()
            if row is None or not row["active"]:
                raise HTTPException(401, "uživatel není v STOPA (nebo je neaktivní)")
        else:  # bootstrap: multi-user režim ještě nenastal (žádní uživatelé)
            repo = _user_repo()
            try:
                if repo.multi_user_mode():
                    raise HTTPException(401, "multi-user režim — použijte SSO login")
                row = repo.get_user(username=body.username or "")
            finally:
                repo.conn.close()
            if row is None or not row["active"]:
                raise HTTPException(401, f"neznámý uživatel: {body.username!r}")
        token = sign_session_token({"u": dict(row)["username"]}, _session_secret())
        return {"token": token, "user": dict(row)}

    @app.post("/auth/logout")
    def auth_logout() -> dict:
        """Logout (client odstraní token; secret zůstává — stateless HMAC)."""
        return {"ok": True}

    @app.get("/api/orgs")
    def list_orgs() -> list[dict]:
        _require("settings.read", "list_orgs")
        repo = _user_repo()
        try:
            return repo.list_orgs()
        finally:
            repo.conn.close()

    @app.post("/api/orgs", status_code=201)
    def create_org(body: OrgIn) -> dict:
        _require("settings.write", "create_org")
        org_id = hashlib.sha256(f"org:{body.name}".encode()).hexdigest()[:16]
        repo = _user_repo()
        try:
            return repo.upsert_org(org_id=org_id, name=body.name)
        finally:
            repo.conn.close()

    @app.get("/api/teams")
    def list_teams(org_id: str | None = Query(None)) -> list[dict]:
        _require("settings.read", "list_teams")
        repo = _user_repo()
        try:
            return repo.list_teams(org_id=org_id)
        finally:
            repo.conn.close()

    @app.post("/api/teams", status_code=201)
    def create_team(body: TeamIn) -> dict:
        _require("settings.write", "create_team")
        team_id = hashlib.sha256(f"team:{body.org_id}:{body.name}".encode()).hexdigest()[:16]
        repo = _user_repo()
        try:
            return repo.upsert_team(team_id=team_id, org_id=body.org_id, name=body.name)
        finally:
            repo.conn.close()

    @app.get("/api/users")
    def list_users() -> list[dict]:
        _require("settings.read", "list_users")
        repo = _user_repo()
        try:
            return repo.list_users()
        finally:
            repo.conn.close()

    @app.post("/api/users", status_code=201)
    def create_user(body: UserIn) -> dict:
        if normalize_role(body.role) is None:
            raise HTTPException(400, f"neplatná role: {body.role!r}")
        _require("settings.write", "create_user")
        repo = _user_repo()
        try:
            user_id = hashlib.sha256(f"user:{body.username}".encode()).hexdigest()[:16]
            try:
                return repo.create_user(
                    user_id=user_id,
                    username=body.username,
                    display_name=body.display_name,
                    team_id=body.team_id,
                    role=body.role,
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, f"username už existuje: {body.username!r}") from exc
        finally:
            repo.conn.close()

    @app.patch("/api/users/{user_id}")
    def update_user(user_id: str, body: UserUpdateIn) -> dict:
        if body.role is not None and normalize_role(body.role) is None:
            raise HTTPException(400, f"neplatná role: {body.role!r}")
        _require("settings.write", "update_user")
        repo = _user_repo()
        try:
            user = repo.get_user(user_id=user_id)
            if user is None:
                raise HTTPException(404, f"uživatel neexistuje: {user_id!r}")
            if body.active is not None:
                repo.set_user_active(user_id, bool(body.active))
            return repo.upsert_user(
                user_id=user_id,
                username=dict(user)["username"],
                display_name=body.display_name,  # None = bez změny (upsert sémantika)
                team_id=body.team_id,
                role=body.role,
            )
        finally:
            repo.conn.close()

    @app.post("/api/cases/{case_id}/members", status_code=201)
    def grant_member(case_id: str, body: MemberGrantIn) -> dict:
        """Per-case oprávnění — přide členství (role v případě); F4.5 → sdílecí notifikace."""
        if normalize_role(body.role) is None:
            raise HTTPException(400, f"neplatná role: {body.role!r}")
        _require("case.update", "members_grant", case_id=case_id)
        db = open_db(case_id)  # existence check fail-closed (404 jinak)
        repo = _user_repo()
        try:
            if repo.get_user(user_id=body.user_id) is None:
                raise HTTPException(404, f"uživatel neexistuje: {body.user_id!r}")
            info = repo.grant_case(case_id, body.user_id, role=body.role)
            # F4.5 — sdílení případu: in-app + email notifikace pro nového člena.
            uname = next(
                (m["username"] for m in repo.list_case_members(case_id) if m["user_id"] == body.user_id),
                "?",
            )
            msg = f"případ {case_id} byl sdílen s vámi (role: {body.role})"
            _notify_user(db, uname, "shared", msg, case_id=case_id)
            return info
        finally:
            repo.conn.close()
            db.close()

    @app.delete("/api/cases/{case_id}/members/{user_id}", status_code=204)
    def revoke_member(case_id: str, user_id: str) -> None:
        _require("case.update", "members_revoke", case_id=case_id)
        open_db(case_id).close()
        repo = _user_repo()
        try:
            if not repo.revoke_case(case_id, user_id):
                raise HTTPException(404, "členství neexistuje")
        finally:
            repo.conn.close()

    @app.get("/api/cases/{case_id}/members")
    def list_members(case_id: str) -> list[dict]:
        _require("case.read", "members_list", case_id=case_id)
        open_db(case_id).close()
        repo = _user_repo()
        try:
            return repo.list_case_members(case_id)
        finally:
            repo.conn.close()

    # ── F4.5 — Case sharing & collaboration (comments na artefaktech + notifikace)
    def _comment_username() -> str:
        """Identita autora komentáře / vlastníka inboxu — session username; legacy = "user"."""
        status, user = _current_user()
        return user["username"] if status == "ok" else "user"

    def _notify_user(
        db: CaseDB, uname: str, kind: str, body: str, case_id: str | None = None, artifact_id: str | None = None
    ) -> None:
        """F4.5 — in-app notifikace + volitelný e-mail (defenzivní: mail nesmí rozbít API cestu)."""
        db.collab_repo.add_notification(uname, kind, body[:200], case_id=case_id, artifact_id=artifact_id)
        mail = getattr(app.state, "mail_backend", None)
        if mail is None:
            return
        try:
            mail({"to": uname, "subject": f"STOPA ({kind})", "body": body})
        except Exception:  # noqa: BLE001 — defenzivní (jen log)
            log.warning("F4.5 e-mail pro %s selhal (%s)", uname, kind)

    @app.get("/api/cases/{case_id}/sharing")
    def sharing_summary(case_id: str) -> list[dict]:
        """F4.5 — přehled sdílení případu: členové + read/write úroveň (efektivní role)."""
        _require("case.read", "sharing_summary", case_id=case_id)
        open_db(case_id).close()
        repo = _user_repo()
        try:
            out = []
            for m in repo.list_case_members(case_id):
                level = "write" if m["role"] in ("examiner", "admin") else "read"
                out.append({**m, "access_level": level})
            return out
        finally:
            repo.conn.close()

    @app.post("/api/cases/{case_id}/artifacts/{artifact_id}/comments", status_code=201)
    def add_comment(case_id: str, artifact_id: str, body_in: CommentIn) -> dict:
        """F4.5 — komentář na artefakt (write úroveň); @mentions → notifikace."""
        from stopa.domain.collab import parse_mentions, validate_comment_body

        _require("comment.post", "add_comment", case_id=case_id)
        try:
            text = validate_comment_body(body_in.body)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        mentions = parse_mentions(text)
        author = _comment_username()
        db = open_db(case_id)
        repo = _user_repo()
        try:
            if db.get_artifact(artifact_id) is None:
                raise HTTPException(404, f"artefakt {artifact_id} nenalezen")
            info = db.collab_repo.add_comment(case_id, artifact_id, author, text, mentions)
            known = {u["username"] for u in repo.list_users()}
            for name in mentions:
                if name != author and name in known:
                    _notify_user(
                        db, name, "mention", f"{author}: {text}", case_id=case_id, artifact_id=artifact_id
                    )
        finally:
            repo.conn.close()
            db.close()
        payload = {"id": info["id"], "artifact_id": artifact_id, "author": author, "body": text}
        _publish_case(case_id, "comment.new", **payload)
        return info

    @app.get("/api/cases/{case_id}/artifacts/{artifact_id}/comments")
    def list_comments(case_id: str, artifact_id: str) -> list[dict]:
        """F4.5 — komentářové vlákno artefaktu (read úroveň)."""
        _require("case.read", "list_comments", case_id=case_id)
        db = open_db(case_id)
        try:
            return db.collab_repo.list_comments(case_id, artifact_id)
        finally:
            db.close()

    @app.put("/api/cases/{case_id}/artifacts/{artifact_id}/comments/{comment_id}")
    def edit_comment(
        case_id: str, artifact_id: str, comment_id: str, body_in: CommentEditIn
    ) -> dict:
        """F4.5 — editace vlastního komentáře; expected_revision = optimistické zamykání (409)."""
        from stopa.domain.collab import parse_mentions, validate_comment_body

        _require("comment.post", "edit_comment", case_id=case_id)
        try:
            text = validate_comment_body(body_in.body)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        me = _comment_username()
        db = open_db(case_id)
        try:
            cur = db.collab_repo.get_comment(comment_id)
            if cur is None or cur["artifact_id"] != artifact_id:
                raise HTTPException(404, f"komentář {comment_id} nenalezen")
            if cur["author"] != me:
                raise HTTPException(403, "komentář upravuje jen jeho autor")
            try:
                info = db.collab_repo.update_comment(
                    comment_id, text, parse_mentions(text), body_in.expected_revision
                )
            except ValueError as e:  # verze se změnila (souběžná editace) → konflikt
                raise HTTPException(409, str(e)) from e
        finally:
            db.close()
        payload = {"id": info["id"], "artifact_id": artifact_id, "revision": int(info["revision"])}
        _publish_case(case_id, "comment.updated", **payload)
        return info

    @app.delete("/api/cases/{case_id}/artifacts/{artifact_id}/comments/{comment_id}", status_code=204)
    def delete_comment(case_id: str, artifact_id: str, comment_id: str) -> None:
        """F4.5 — smazání komentáře (jen jeho autor)."""
        _require("comment.post", "delete_comment", case_id=case_id)
        me = _comment_username()
        db = open_db(case_id)
        try:
            cur = db.collab_repo.get_comment(comment_id)
            if cur is None or cur["artifact_id"] != artifact_id:
                raise HTTPException(404, f"komentář {comment_id} nenalezen")
            if cur["author"] != me:
                raise HTTPException(403, "komentář smaže jen jeho autor")
            db.collab_repo.delete_comment(comment_id)
        finally:
            db.close()
        _publish_case(case_id, "comment.deleted", comment_id=comment_id, artifact_id=artifact_id)

    @app.get("/api/cases/{case_id}/notifications")
    def my_notifications(case_id: str, unread_only: bool = False) -> list[dict]:
        """F4.5 — in-app inbox session uživatele (per případ)."""
        _require("case.read", "my_notifications", case_id=case_id)
        db = open_db(case_id)
        try:
            return db.collab_repo.list_notifications(_comment_username(), unread_only=unread_only)
        finally:
            db.close()

    @app.post("/api/cases/{case_id}/notifications/read-all", status_code=204)
    def mark_all_read(case_id: str) -> None:
        """F4.5 — označit všechny notifikace v inboxu jako přečtené."""
        _require("case.read", "read_all_notifications", case_id=case_id)
        db = open_db(case_id)
        try:
            db.collab_repo.mark_all_read(_comment_username())
        finally:
            db.close()

    # ── E12 — Cases CRUD (update/delete nad existujícím GET/POST) ───────────────
    @app.patch("/api/cases/{case_id}")
    def update_case(case_id: str, body: CaseUpdateIn) -> dict:
        """Aktualizace metadat případu (name/examiner/notes/timezone/auto-export)."""
        _require("case.update", "update_case", case_id=case_id)
        db = open_db(case_id)
        try:
            ok = db.update_case(
                case_id,
                name=body.name,
                examiner=body.examiner,
                notes=body.notes,
                timezone_name=body.timezone_name,
                auto_export_enabled=body.auto_export_enabled,  # STP-069
            )
            if not ok:
                raise HTTPException(404, "případ neexistuje")
            # STP-070 — interval periodického auto-bundle. Pole chybí v requestu =
            # bez změny; explicitní null / prázdný string = vymazat; číslo = nastavit.
            if "auto_export_interval_minutes" in body.model_fields_set:
                from stopa.domain.export_schedule import parse_interval_minutes

                try:
                    minutes = parse_interval_minutes(body.auto_export_interval_minutes)
                except ValueError as exc:
                    raise HTTPException(422, str(exc)) from exc
                ok_int = db.set_auto_export_interval(case_id, minutes)
                if not ok_int:
                    raise HTTPException(404, "případ neexistuje")
            db.log_operation("case_updated", details={"case_id": case_id})
            return get_case(case_id)
        finally:
            db.close()

    @app.delete("/api/cases/{case_id}")
    def delete_case(case_id: str) -> dict:
        """Smaže případ i zdroje (kaskáda na files/artifacts/timeline)."""
        _require("case.delete", "delete_case", case_id=case_id)
        validate_case_id(case_id)
        path = base / f"{case_id}.db"
        db = CaseDB(path) if path.exists() else None
        try:
            if db is None or db.get_case(case_id) is None:
                raise HTTPException(404, "případ neexistuje")
            db.log_operation("case_deleted", details={"case_id": case_id})
            db.delete_case(case_id)
        finally:
            if db is not None:
                db.close()
        # F2.2 — materiálový DuckDB stav je odvozený artefakt; po smazání zmizí.
        try:
            from stopa.data.analytics import drop_case_analytics

            drop_case_analytics(path)
        except Exception as exc:  # noqa: BLE001 — cleanup nesmí rozbít delete
            log.warning("DuckDB cleanup selhal pro case %s: %s", case_id, exc)
        # F4.4 — instance DB: smazat řádek case → FK CASCADE odstraní i členství
        repo = _user_repo()
        try:
            repo.conn.execute("DELETE FROM cases WHERE id=?", (case_id,))
            repo.conn.commit()
        finally:
            repo.conn.close()
        return {"deleted": case_id}

    # ── statická SPA ──────────────────────────────────────────
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # F4.1 — nová React SPA (build z frontend/ do static/spa); /spa → index.html.
    spa_dir = STATIC_DIR / "spa"
    if spa_dir.is_dir():
        app.mount("/spa", StaticFiles(directory=spa_dir, html=True), name="spa")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    # ── STP-070 — periodický plánovač auto-bundle (daemon thread) ──
    # Spouští se vždy s app factory; tick každou minutu, sleep-first.
    # Daemon → umírá s procesem, explicitní stop není potřeba.
    threading.Thread(
        target=_auto_export_scheduler_loop, args=(base,), name="stopa-auto-export", daemon=True
    ).start()

    return app


def _ground_answer_safe(
    text: str, cited_ids: list[str], artifacts_by_id: dict[str, dict]
) -> dict | None:
    """STP-049 — grounding odpovědi LLM proti citovaným záznamům (defenzivní obal).

    Vrací report ``to_dict()`` nebo ``None`` (žádné citace / interní chyba).
    Grounding je doplňková vrstva — nesmí rozbít hlavní odpověď, proto se
    jakákoli výjimka loguje a degraduje na ``None``.
    """
    if not cited_ids:
        return None
    try:
        from stopa.domain.ai_grounding import ground_answer

        report = ground_answer(text, list(cited_ids), artifacts_by_id)
    except Exception:  # doplňková vrstva, log + degradace
        log.exception("AI grounding selhalo (odpověď se vrací bez reportu)")
        return None
    return report.to_dict()


def _ai_nl_search(
    db: CaseDB, case_id: str, case_name: str, question: str, client: LmStudioClient, *, redact_pii: bool = True, model: str | None = None
) -> dict:
    """Režim ``nl_search`` — přirozená řeč → STOPA FTS query + výsledky.

    Citace = soubory, které dotaz vrátil (GUI je propojí na File Inspector).
    STP-019: PII v promptu se maskuje podle ``redact_pii``; audit do analysis_operations.
    """
    from stopa.domain.search_filters import SearchFilterError
    from stopa.intelligence.rag import audit_ai_query, prompt_hash

    if not question.strip():
        raise HTTPException(400, "chybí otázka")
    messages = build_nl_search_prompt(question, case_name, redact_pii=redact_pii)
    text = client.chat(messages)
    query, explanation, confidence = parse_nl_search(text)
    if not query:
        raise HTTPException(502, f"AI nevrátila validní query (odpověď: {text[:160]!r})")

    try:
        records = db.search(query, limit=50)
    except SearchFilterError as exc:
        raise HTTPException(400, f"AI vygenerovala neplatný dotaz „{query}“: {exc}") from exc

    citations = [
        {"file_id": r.id, "rel_path": r.rel_path, "name": r.name} for r in records[:20]
    ]
    # STP-049 — grounding: tvrzení v odpovědi vs mtime citovaných souborů
    file_by_id = {
        r.id: {"id": r.id, "timestamp": r.mtime.isoformat() if r.mtime else None}
        for r in records
    }
    grounding = _ground_answer_safe(text, [c["file_id"] for c in citations], file_by_id)
    # STP-019 — audit AI volání (model + hash skutečně odeslaného promptu)
    audit_ai_query(
        db,
        case_id=case_id,
        question=question,
        model=model or "unknown",
        prompt_sha256=prompt_hash(messages),
        citations=[c["file_id"] for c in citations],
        agent="e11:nl_search",
    )
    return {
        "mode": "nl_search",
        "answer": explanation or f"Vyhledáno: {query}",
        "query": query,
        "confidence": confidence,
        "citations": citations,
        "files": [r.model_dump(mode="json") for r in records],
        "grounding": grounding,
    }


def _ai_summary(
    db: CaseDB, case_id: str, case_name: str, client: LmStudioClient, *, redact_pii: bool = True, model: str | None = None
) -> dict:
    """Režim ``summary`` — shrnutí případu s citacemi artifactů ze vzorku.

    STP-019: PII v promptu se maskuje podle ``redact_pii``; audit do analysis_operations.
    """
    from stopa.intelligence.rag import audit_ai_query, prompt_hash

    stats = db.stats()
    art_stats = db.artifact_stats()
    sample = [a.model_dump(mode="json") for a in db.list_artifacts(limit=15)]

    messages = build_summary_prompt(case_name, stats, art_stats, sample, redact_pii=redact_pii)
    text = client.chat(messages)
    valid_ids = {a["id"] for a in sample}
    answer, cited = extract_citations(text, valid_ids)
    by_id = {a["id"]: a for a in sample}
    citations = [
        {"artifact_id": aid, "title": by_id[aid].get("title"), "rel_path": by_id[aid].get("rel_path")}
        for aid in cited
    ]
    # STP-049 — grounding: tvrzení v odpovědi vs data citovaných artifactů
    grounding = _ground_answer_safe(text, list(cited), by_id)
    # STP-019 — audit AI volání (model + hash skutečně odeslaného promptu)
    audit_ai_query(
        db,
        case_id=case_id,
        question=f"summary: {case_name}",
        model=model or "unknown",
        prompt_sha256=prompt_hash(messages),
        citations=list(cited),
        agent="e11:summary",
    )
    return {
        "mode": "summary",
        "answer": answer or text.strip(),
        "confidence": parse_confidence(text),
        "citations": citations,
        "grounding": grounding,
    }


def _ai_explain(
    db: CaseDB, case_id: str, artifact_id: str | None, client: LmStudioClient, *, redact_pii: bool = True, model: str | None = None
) -> dict:
    """Režim ``explain`` — vysvětlení jednoho artifactu + citace na něj.

    STP-019: PII v promptu se maskuje podle ``redact_pii``; audit do analysis_operations.
    """
    from stopa.intelligence.rag import audit_ai_query, prompt_hash

    if not artifact_id:
        raise HTTPException(400, "chybí artifact_id")
    art = db.get_artifact(artifact_id)
    if art is None:
        raise HTTPException(404, f"artifact {artifact_id} nenalezen")

    payload = art.model_dump(mode="json")
    messages = build_explain_prompt(payload, redact_pii=redact_pii)
    text = client.chat(messages)
    answer, cited = extract_citations(text, {art.id})
    # STP-049 — grounding: tvrzení v odpovědi vs data citovaného artifactu
    grounding = _ground_answer_safe(text, list(cited), {art.id: payload})
    # STP-019 — audit AI volání (model + hash skutečně odeslaného promptu)
    audit_ai_query(
        db,
        case_id=case_id,
        question=f"explain: {artifact_id}",
        model=model or "unknown",
        prompt_sha256=prompt_hash(messages),
        citations=list(cited),
        agent="e11:explain",
    )
    return {
        "mode": "explain",
        "answer": answer or text.strip(),
        "confidence": parse_confidence(text),
        "citations": (
            [{"artifact_id": art.id, "title": art.title, "rel_path": art.rel_path}]
            if cited
            else []
        ),
        "grounding": grounding,
    }


def build_report_data_safe(db: CaseDB, case_id: str):
    """build_report_data s HTTPException místo ValueError (404)."""
    from stopa.presentation.case_report import build_report_data

    try:
        return build_report_data(db, case_id)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


def _read_file_bytes(db: CaseDB, rec, offset: int = 0, length: int | None = None) -> bytes:
    """Obsah souboru — z disku (folder/file zdroj) nebo TSK icat (diskový obraz).

    ``length=None`` → celý obsah; jinak úryvek [offset : offset+length].
    """
    from pathlib import Path as _P

    source = db.get_source(rec.source_id)
    if source is None:
        raise HTTPException(404, "zdroj souboru neexistuje")
    root = _P(source.path).expanduser()

    if rec.meta_addr:
        # soubor v diskovém obrazu → TSK icat (partice z partition mapy)
        from stopa.data.tsk import Partition, TskError, extract_file

        parts: list[Partition] = []
        for a in db.list_artifacts(source_id=rec.source_id, artifact_type="disk_image"):
            pm = (a.details or {}).get("partition_map") or []
            for p in pm:
                if p.get("fstype"):
                    parts.append(
                        Partition(
                            index=p["index"],
                            offset_sectors=p["offset_sectors"],
                            size_sectors=p["size_sectors"],
                            desc=p["desc"],
                            fstype=p["fstype"],
                        )
                    )
        data: bytes | None = None
        for part in ([None] if not parts else parts):
            try:
                data = extract_file(root, rec.meta_addr, partition=part)
                break
            except TskError:
                continue  # jiná partice / obraz bez TSK — zkus další
        if data is None:
            raise HTTPException(502, "TSK icat se nedaří přečíst soubor z obrazu")
        end = len(data) if length is None else min(len(data), offset + length)
        return data[offset:end]

    # diskový zdroj — audit P1: rel_path s `..` (symlink ve zdroji) unikne kořene
    p = root / rec.rel_path if not root.is_file() else root
    try:
        resolved = p.resolve(strict=True)
    except OSError:
        raise HTTPException(404, f"soubor na disku neexistuje: {p}") from None
    root_resolved = root.resolve()
    if resolved != root_resolved and not str(resolved).startswith(str(root_resolved) + os.sep):
        # soubor je mimo kořen zdroje (.. nebo symlink ven) → 404, ne 500
        raise HTTPException(404, f"soubor uniká kořene zdroje: {rec.rel_path}")

    # audit P1 — RAM peak: ranged read (seek + read) místo read_bytes() celého souboru
    with open(p, "rb") as fh:
        if offset:
            fh.seek(offset)
        data = fh.read(length) if length is not None else fh.read()
    return data


def _hex_dump(data: bytes) -> list[str]:
    """Hex dump řádky (16 B/řádek): ``0000  48 53 ... |HS...|``."""
    lines: list[str] = []
    for i in range(0, len(data), 16):
        chunk = data[i : i + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:04x}  {hexpart:<47}  |{asc}|")
    return lines


app = create_app()
