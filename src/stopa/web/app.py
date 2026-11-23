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

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import socket  # P4-7 — node_id default (hostname) pro registry lease
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stopa import __version__
from stopa.data.case_registry_repository import (
    heartbeat as _registry_heartbeat,  # P4-7 — lease beat
)
from stopa.data.cross_case_repository import open_instance  # P4-7 — instance DB (event bus)
from stopa.data.db import CaseDB

# P4-7 — DB event bus I/O (cross-process distribuce LiveEvent)
from stopa.data.event_repository import max_event_id as _bus_max_id
from stopa.data.event_repository import poll_events as _bus_poll
from stopa.data.event_repository import prune_old_events as _bus_prune
from stopa.data.event_repository import publish_event as _bus_publish
from stopa.data.lmstudio_client import LmStudioClient
from stopa.data.schema import MULTITENANT_DDL  # F4.4 — instance DB DDL
from stopa.data.user_repository import UserRepository  # F4.4
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
    RBACDenied,
    require_permission,
)

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
    resume_mode: str | None = None  # P0.1 — "fast" (výchozí) / "strict"; viz process_source
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


class AiRunIn(BaseModel):
    """Tělo POST .../ai/run — P1-2 AI role agenta nad důkazy případu."""

    role: str  # evidence|timeline|network|memory|intelligence|hypothesis|report|qa
    question: str = ""
    artifact_ids: list[str] | None = None  # None = implicitně poslední 5 artefaktů


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


# P4-7 — výchozí interval polling workeru cross-process event busu (produkce);
# unit testy používají default ``None`` = vypnuto.
EVENT_POLL_INTERVAL_S: float = 0.25
# P4-7 — retence událostí v tabulce events a frekvence pruningu (cykly workeru).
EVENT_BUS_RETENTION_H: float = 2.0  # starší řádky se mažou
PRUNE_EVERY_CYCLES: int = 240  # při 0,25 s ≈ jednou za 60 s


def create_app(
    db_dir: Path | None = None,
    ws_heartbeat_s: float = 15.0,
    sso_fetcher: Callable[[str], dict] | None = None,  # F4.4 — test hook for JWKS
    mail_backend: Callable[[dict], None] | None = None,  # F4.5 — email transport (injektovatelný)
    event_poll_interval_s: float | None = None,  # P4-7 — DB→bus polling worker (None = vypnuto)
) -> FastAPI:
    """App factory — `db_dir` pro testy (tmp), default z env STOPA_DB_DIR.

    ``ws_heartbeat_s`` (F4.2): interval heartbeatu WebSocket spojení;
    v testech se zkracuje, aby se suite netestovala na 15 s čekání.
    ``sso_fetcher`` (F4.4): injektovatelný JWKS fetch pro OIDC SSO testy (bez sítě).
    ``mail_backend`` (F4.5): volitelný email transport pro notifikace; payload =
    ``{"to": username, "subject": str, "body": str}``. Bez backendu zůstávají
    notifikace in-app (graceful degradation — mail nesmí rozbít API cestu).
    ``event_poll_interval_s`` (P4-7): interval polling workeru, který distribuuje
    LiveEvent události napříč procesy přes instance DB (tabulka ``events``);
    ``None`` = vypnuto (výchozí pro unit testy; produkční serve zapíná 0.25 s).
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

    # P4-7 — cross-process distribuce LiveEvent přes instance DB (tabulka events).
    # Publisher: insert do DB + lokální bus publish (dedupace podle _pid).
    # Subscriber: polling worker čte nové řádky a forwarduje cizí události.
    _inst_conn: sqlite3.Connection | None = None
    _inst_lock = threading.Lock()

    def _instance_db() -> sqlite3.Connection | None:
        """Lazy instance DB (event bus); chyba → ``None`` (defenzivní)."""
        nonlocal _inst_conn
        with _inst_lock:
            if _inst_conn is None:
                try:
                    _inst_conn = open_instance(base, check_same_thread=False)
                except sqlite3.Error:  # bus nesmí rozbít API cestu (jen debug log)
                    log.debug("instance DB se nepodařilo otevřít", exc_info=True)
                    return None
            return _inst_conn

    def _publish_case(case_id: str, etype: str, **payload) -> None:
        """Publikuje událost na téma case; chyby jen loguje (defenzivní).

        Parametr ``etype`` (ne ``event_type``): payload timeline eventu má
        vlastní klíč ``event_type`` (typ záznamu), který by do kolize s
        pozičním parametrem a hook ho potichu polkl. P4-7: zároveň perzistentuje
        událost do instance DB pro cross-process distribuci (polling worker).
        """
        ev = {"type": etype, "case_id": case_id, "ts": _now_iso(), **payload}
        topic = case_topic(case_id)
        try:
            conn = _instance_db()
            if conn is not None:
                with _inst_lock:
                    _bus_publish(conn, topic, ev)
        except (sqlite3.Error, ValueError, TypeError):  # DB cesta je volitelná
            log.debug("DB bus publish selhal pro %s", etype, exc_info=True)
        try:
            # _pid = dedupace polling workeru (vlastní události se ne-forwardují)
            ev["_pid"] = os.getpid()
            _bus.publish(topic, ev)
        except Exception:  # live kanál nesmí rozbít API cestu (jen debug log)
            log.debug("live publish selhal pro %s", etype, exc_info=True)

    def _attach_live_events(db: CaseDB, case_id: str) -> None:
        """F4.2 — naváže ``db.on_event`` na bus (timeline + AI akce)."""
        db.on_event = lambda etype, payload: _publish_case(case_id, etype, **payload)

    if event_poll_interval_s is not None and event_poll_interval_s > 0:
        _stop_event_poller = threading.Event()

        def _event_poller_worker() -> None:
            """P4-7 — polling worker instance DB → lokální bus (cross-process).

            Startuje s kurzorem na aktuálním max id (bez replaye historie);
            cizí události (jiný ``_pid``) forwarduje do LiveEventBus. Chyby jen
            loguje a cyklus pokračuje (worker nesmí umřít na jedné výjimce).
            """
            own_pid = os.getpid()
            own_node = os.environ.get("STOPA_NODE_ID") or socket.gethostname()
            conn: sqlite3.Connection | None = None
            cycle = 0
            try:
                conn = open_instance(base, check_same_thread=False)
                cursor = _bus_max_id(conn)
                while True:
                    # P4-7 — lease heartbeat: běh workeru = liveness uzlu registru.
                    # Monotónní seq (bez wall-clock); expirace po LEASE_WINDOW beatů.
                    try:
                        _registry_heartbeat(conn, node_id=own_node)
                    except sqlite3.Error:  # busy/locked — příští cyklus
                        log.debug("registry heartbeat selhal", exc_info=True)
                    cycle += 1
                    if cycle % PRUNE_EVERY_CYCLES == 0:
                        cutoff = (
                            datetime.now(timezone.utc) - timedelta(hours=EVENT_BUS_RETENTION_H)
                        ).isoformat(timespec="seconds")
                        try:
                            _bus_prune(conn, older_than_iso=cutoff)
                        except sqlite3.Error:  # pruning nesmí zastavit bus
                            log.debug("event bus pruning selhal", exc_info=True)
                    try:
                        batch = _bus_poll(conn, after_id=cursor, limit=500)
                    except sqlite3.Error:  # např. busy/locked — příští cyklus
                        log.debug("event poll selhal", exc_info=True)
                        batch = []
                    for item in batch:
                        cursor = max(cursor, int(item["id"]))
                        if int(item["event"].get("_pid", -1)) == own_pid:
                            continue  # lokálně už doručeno přímo přes bus
                        _bus.publish(item["topic"], item["event"])
                    if _stop_event_poller.wait(event_poll_interval_s):
                        break
            except Exception:  # worker se sám nespustil (např. DB nedostupná)
                log.debug("event poller worker skončil", exc_info=True)
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except sqlite3.Error:  # defenzivní close při shutdownu
                        pass

        _event_poller_thread = threading.Thread(
            target=_event_poller_worker, name="stopa-event-poller", daemon=True
        )
        _event_poller_thread.start()
    else:
        _stop_event_poller = None  # type: ignore[assignment]

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

        P1 security — path traversal: validace zde (ne jen u volajících endpointů)
        je obrana v hloubce; strict regex _CASE_ID_RE nepustí tečku ani lomítko,
        takže žádný legitimní ID neunikne z ``exports/``.
        """
        validate_case_id(case_id)  # P1 security — defense in depth (400 při traversalu)
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

    # ── cases ─────────────────────────────────────────────────



    # ── sources / ingest ──────────────────────────────────────

    # ── STP-021 — Processing Monitor (živý progress ingestu) ───────────────

    # ── F4.2 — WebSocket real-time updates (live progress/timeline/AI) ─────

    # ── files / search / timeline ─────────────────────────────

    # F4.3 — Peer-Review Workflow (stavový automat v domain/review.py) ──────────










    # ── F2.2 DuckDB OLAP analytics ────────────────────────────────────

    # ── STP-018 Timeline Intelligence 2.0 ─────────────────────────────

    # ── E4 Entity + Correlation Engine ────────────────────────────────




    # ── partition map (GUI File System & Carving — vizuální mapa) ────────────

    # ── file inspector (GUI pravý panel) ───────────────────────










    # ── STP-058 — interop exporty (l2tcsv / UCO / CSV / JSON / ...) ───────

    # ── STP-068 — ZIP bundle všech datasetů (oblast Q ★★) ───────────────

    # ── STP-064 — L2T CSV preview (oblast Q ★★) ───────────────

    # ── STP-066 — Export center: náhled CSV/JSON (UCO) před downloadem ──

    # ── STP-067 — re-download posledního exportu z historie (oblast Q ★★) ──

    # ── STP-069 — download posledního automatického ZIP bundle (opt-in) ──

    # ── STP-059 — Timesketch push (oblast Q, interop) ───────────────

    # ── STP-061 — Timesketch timeline status (live polling, oblast Q ★★) ───

    # ── STP-063 — Plaso import (l2tcsv upload, oblast Q ★★) ────────────────

    # ── Pluginy (F6.4) ────────────────────────────────────────

    # ── MITRE ATT&CK map (F6.3) ──────────────────────────────

    # ── report (FÁZE 7) ───────────────────────────────────────

    # ── F5.2 — SWGDE/ISO 27037 Compliance Report ────────────────

    # ── F5.5 — Daubert challenge preparedness pack (1-click JSON pro soud) ────

    # ── F5.4 — Write-blocker integration API (status + attach/remove) ──────────



    # ── STP-050 — Validation Center (C3 registry + C6 report) ──


    # ── P0-4 — validation lab (per-parser status + test coverage) ────────────

    # ── STP-052 — Audit Center (oblast O) ─────────────────────

    # ── E11 — AI Forensic Assistant (LM Studio) ───────────────


    # ── P0 Intelligence I1 — AI orchestrace (multi-agent) ───────────────

    # ── E12 — System Diagnostics ──────────────────────────────
    # ── F3.5: Hypothesis Graph (AI graf hypotéz + ruční potvrzení/vyvrácení) ──





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




    # ── F4.4 — Multi-tenant RBAC endpoints (orgs/teams/users/members/sso) ───────













    # ── F4.5 — Case sharing & collaboration (comments na artefaktech + notifikace)









    # ── E12 — Cases CRUD (update/delete nad existujícím GET/POST) ───────────────


    # ── statická SPA ──────────────────────────────────────────
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # F4.1 — nová React SPA (build z frontend/ do static/spa); /spa → index.html.
    spa_dir = STATIC_DIR / "spa"
    if spa_dir.is_dir():
        app.mount("/spa", StaticFiles(directory=spa_dir, html=True), name="spa")

    # P1-4 vlna C — routery domén (povrch byte-přesný: tests/golden/p14_web_surface.json)
    from .routers import (
        ai,
        analysis,
        cases,
        classification,
        collab,
        exchange,
        files,
        i18n,
        intel,
        investigation,
        registry,
        reports,
        system,
        xcorr,
    )

    ctx = {
        "base": base,
        "_jobs": _jobs,
        "_jobs_lock": _jobs_lock,
        "_bus": _bus,
        "_stop_event_poller": _stop_event_poller,  # P4-7 — clean stop polling workeru (testy)
        "_ws_heartbeat_s": _ws_heartbeat_s,
        "_last_ingest_pub": _last_ingest_pub,
        "_now_iso": _now_iso,
        "_publish_case": _publish_case,
        "_attach_live_events": _attach_live_events,
        "_job_update": _job_update,
        "_instance_conn": _instance_conn,
        "_user_repo": _user_repo,
        "_session_secret": _session_secret,
        "_current_user": _current_user,
        "_multi_user_mode": _multi_user_mode,
        "_sso_config": _sso_config,
        "_sso_verify_id_token": _sso_verify_id_token,
        "open_db": open_db,
        "_last_export_path": _last_export_path,
        "_save_last_export": _save_last_export,
        "_save_last_export_bytes": _save_last_export_bytes,
        "_load_last_export": _load_last_export,
        "_settings_path": _settings_path,
        "_load_settings": _load_settings,
        "_save_settings": _save_settings,
        "_current_role": _current_role,
        "_require": _require,
    }
    # P4-7 — test hook: interní stav (bus, poller stop) dostupný přes app.state.ctx
    app.state.ctx = ctx

    cases.register(app, ctx)
    files.register(app, ctx)
    analysis.register(app, ctx)
    ai.register(app, ctx)
    reports.register(app, ctx)
    collab.register(app, ctx)
    investigation.register(app, ctx)  # P2-4 — investigation workspace
    intel.register(app, ctx)  # P2-5 — threat intelligence workspace (IoC feed + match)
    classification.register(app, ctx)  # P3-3 — automated classification souborů (+ override)
    registry.register(app, ctx)  # P2-2 — centrální registr případů (instance DB)
    xcorr.register(app, ctx)  # P2-6 — cross-case correlation (instance DB)
    exchange.register(app, ctx)  # P2-7 — case exchange bundle v1 (pack/verify marketplace)
    system.register(app, ctx)
    i18n.register(app, ctx)  # P4-8 — /api/i18n/{lang} katalogy (legacy UI)

    @app.get("/")
    def index(request: Request) -> FileResponse:
        """P4-4 W3 — root URL = kanonická SPA; ?ui=legacy → legacy GUI (non-kanonické).

        Graceful degradation: pokud chybí SPA build v static/spa/ (minimální instalace),
        fallback na legacy index."""
        if request.query_params.get("ui") == "legacy":
            return FileResponse(STATIC_DIR / "index.html")
        spa_index = STATIC_DIR / "spa" / "index.html"
        if spa_index.is_file():
            return FileResponse(spa_index)
        return FileResponse(STATIC_DIR / "index.html")  # fallback — chybí SPA build

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


app = create_app(event_poll_interval_s=EVENT_POLL_INTERVAL_S)  # P4-7 — cross-process bus ON
