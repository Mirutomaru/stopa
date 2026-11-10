"""F1.2 — Memory Forensics: Volatility 3 výstup → STOPA artefakty (ROADMAP V2 Fáze 1).

Čistá domain logika bez IO — Volatility 3 běží jako externí proces
(``data/volatility.py``) a vrácený JSON (list dictů, sloupce = klíče) se tady
mapuje na kanonické ``Artifact`` záznamy + anomaly flags.

Design (dle ROADMAP_V2 F1.2):
  * Volitelná runtime závislost — bez nainstalovaného ``vol`` CLI vrace
    data vrstva srozumitelnou chybu, domain funkce běží i na syntetických
    řádcích (offline testovatelné).
  * **PII/credential zásada Crypto K-linka**: hashdump-style surové hase se
    do case DB NEUKLÁDAJÍ — jen typ + fingerprint (SHA-256 prefix).
  * Anomaly rules: injected code (malfind protection flags / velká alokace),
    skryté procesy, podezřelé porty.

Plugin registry (Volatility 3 2.x CLI plugin → artifact_type):
  ==========================  =======================
  windows.pslist              memory_v3_process
  windows.psscan              memory_v3_process
  windows.netscan             memory_v3_connection
  windows.netstat             memory_v3_connection
  windows.ldrmodules          memory_v3_module
  windows.malfind             memory_v3_injected
  windows.getsids             memory_v3_sid (fingerprint jen)
  ==========================  =======================
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from stopa.models import Artifact

# ── Plugin registry ────────────────────────────────────────────────────────

#: Výchozí sada pluginů pro ``stopa memory-analyze`` (bez hashdump — PII).
DEFAULT_PLUGINS: tuple[str, ...] = (
    "windows.pslist",
    "windows.netscan",
    "windows.ldrmodules",
    "windows.malfind",
)

#: Volitelné pluginy dostupné přes ``--plugin`` (explicitní opt-in).
OPTIONAL_PLUGINS: tuple[str, ...] = (
    "windows.psscan",
    "windows.netstat",
    "windows.getsids",
)

#: Plugin → kanonický artifact_type.
PLUGIN_ARTIFACT_TYPES: dict[str, str] = {
    "windows.pslist": "memory_v3_process",
    "windows.psscan": "memory_v3_process",
    "windows.netscan": "memory_v3_connection",
    "windows.netstat": "memory_v3_connection",
    "windows.ldrmodules": "memory_v3_module",
    "windows.malfind": "memory_v3_injected",
    "windows.getsids": "memory_v3_sid",
}

#: Veškeré podporované pluginy (registry + optionální).
SUPPORTED_PLUGINS: frozenset[str] = frozenset(PLUGIN_ARTIFACT_TYPES)


class MemForensicsError(ValueError):
    """Neplatný vstup memory forensics analýzy."""


def validate_plugins(plugins: list[str]) -> list[str]:
    """Validace seznamu pluginů — vrací deduplikovaný pořad, zvedne na neznámé.

    Neznámý plugin → ``MemForensicsError`` s evidencí všech podporovaných.
    """
    if not plugins:
        raise MemForensicsError("Prázdný seznam pluginů")
    unknown = [p for p in plugins if p not in SUPPORTED_PLUGINS]
    if unknown:
        supported = ", ".join(sorted(SUPPORTED_PLUGINS))
        raise MemForensicsError(
            f"Neznané pluginy Volatility 3: {', '.join(unknown)} "
            f"(podporované: {supported})"
        )
    seen: set[str] = set()
    ordered: list[str] = []
    for p in plugins:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


# ── Timestamp normalizace ──────────────────────────────────────────────────

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"
)


def parse_vol_timestamp(value: Any) -> datetime | None:
    """Vol JSON timestamp → aware UTC ``datetime`` (None = nepodařilo se).

    Podporované tvary: ISO 8601 (Z / offset / naive→UTC), epoch sekundy,
    FILETIME (ns od 1601, int ≥ 10**17) a stringy s číslem.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        try:
            if num >= 1e17:  # FILETIME — 100 ns od 1601-01-01
                epoch_s = (num - 11_644_473_600_000_000_000) / 1e7
            elif num >= 1e9:  # epoch sekundy
                epoch_s = num
            else:
                return None
            return datetime.fromtimestamp(epoch_s, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if s.isdigit():
                return parse_vol_timestamp(int(s))
            if _ISO_RE.match(s):
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


# ── Credential guard (PII zásada Crypto K-linka) ───────────────────────────

#: Sloupce, které obsahují surové credential material — nikdy do details.
SENSITIVE_COLUMNS: frozenset[str] = frozenset(
    {"D", "LM", "Hash", "Hashes", "Password", "Secret"}
)


def fingerprint_value(value: str | int) -> dict[str, Any]:
    """Surová hodnota → {fingerprint, length} (SHA-256 prefix 16 hex).

    Surová hodnota se do case DB neukládá — jen typ + fingerprint.
    """
    raw = str(value).encode("utf-8", errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    return {"fingerprint": f"sha256:{digest[:16]}", "length": len(str(value))}


def _filter_sensitive(row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Rozliší bezpečné sloupce od sensitive (vrať detaily + seznam skrytých)."""
    safe: dict[str, Any] = {}
    hidden: list[str] = []
    for key, val in row.items():
        if isinstance(key, str) and key.upper() in SENSITIVE_COLUMNS:
            hidden.append(key)
        else:
            safe[key] = val
    return safe, hidden


# ── Per-plugin parsery (JSON rows → Artifacty) ─────────────────────────────

def _make_artifact(
    *,
    plugin: str,
    row: dict[str, Any],
    title: str | None,
    details: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
    anomaly_flags: list[str] | None = None,
) -> Artifact:
    return Artifact(
        artifact_type=PLUGIN_ARTIFACT_TYPES[plugin],
        title=title,
        details=details or {},
        timestamp=timestamp,
        parser_version="mem_forensics/1.0",
        anomaly_flags=list(anomaly_flags or []),
    )


def parse_pslist(rows: list[Any]) -> list[Artifact]:
    """windows.pslist / psscan → memory_v3_process."""
    arts: list[Artifact] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pid = _int_or_none(row.get("PID"))
        image = str(row.get("ImageFileName") or row.get("ProcessName") or "").strip()
        if not pid and not image:
            continue
        details: dict[str, Any] = {}
        if pid is not None:
            details["PID"] = pid
        for col in ("PPID", "Threads", "Handles", "SessionId"):
            if col in row:
                details[col] = _plain(row.get(col))
        ts = parse_vol_timestamp(row.get("CreateTime"))
        flag = pid if pid is not None else (image or "?")
        title = f"PID {flag} — {image}" if image else f"PID {flag}"
        arts.append(
            _make_artifact(
                plugin="windows.pslist", row=row, title=title,
                details=details, timestamp=ts,
            )
        )
    return arts


def parse_netscan(rows: list[Any]) -> list[Artifact]:
    """windows.netscan / netstat → memory_v3_connection."""
    arts: list[Artifact] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        proto = str(row.get("Proto") or "").strip()
        local_addr = _addr(row.get("Local Address"))
        foreign_addr = _addr(row.get("Foreign Address"))
        state = str(row.get("State") or "").strip()
        pid = _int_or_none(row.get("PID"))
        if not proto and not local_addr:
            continue
        details: dict[str, Any] = {
            "proto": proto,
            "local_address": local_addr,
            "foreign_address": foreign_addr,
            "state": state,
        }
        if pid is not None:
            details["pid"] = pid
        owner = str(row.get("Owner") or row.get("ProcessName") or "").strip()
        if owner:
            details["owner"] = owner
        title = f"{proto} {local_addr}:{_port(local_addr)} → {_host(foreign_addr)}"
        arts.append(_make_artifact(plugin="windows.netscan", row=row, title=title, details=details))
    return arts


def parse_ldrmodules(rows: list[Any]) -> list[Artifact]:
    """windows.ldrmodules → memory_v3_module."""
    arts: list[Artifact] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        path = str(row.get("MappedPath") or "").strip()
        if not path:
            continue
        pid = _int_or_none(row.get("Pid"))
        base = str(row.get("Base") or "").strip()
        details: dict[str, Any] = {"mapped_path": path}
        for col in ("InLoad", "InInit", "InMem"):
            if col in row and isinstance(row.get(col), bool):
                details[col.lower()] = row.get(col)
        if pid is not None:
            details["pid"] = pid
        if base:
            details["base_address"] = base
        title = f"{path} (PID {pid})" if pid is not None else path
        arts.append(_make_artifact(plugin="windows.ldrmodules", row=row, title=title, details=details))
    return arts


def parse_malfind(rows: list[Any]) -> list[Artifact]:
    """windows.malfind → memory_v3_injected (+ anomaly flags).

    Anomaly rules (ROADMAP V2 F1.2):
      * protection contains EXECUTE + WRITE (PAGE_EXECUTE_READWRITE) → ``mem_rw_x``
      * alokace ≥ 64 KiB s execute → ``mem_large_executable``
      * hexdump present → evidence fingerprint (hash), ne surové bajty
    """
    arts: list[Artifact] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start = str(row.get("Start VPN") or "").strip()
        end = str(row.get("End VPN") or "").strip()
        if not start and not end:
            continue
        protection = str(row.get("Protection") or "").strip().upper()
        tag = str(row.get("Tag") or "").strip()
        pid = _int_or_none(row.get("PID"))
        process = str(row.get("Process") or "").strip()

        size = _vpn_range_size(start, end)
        flags: list[str] = []
        if "EXECUTE" in protection and ("WRITE" in protection or "READWRITE" in protection):
            flags.append("mem_rw_x")
        if size is not None and size >= 64 * 1024 and "EXECUTE" in protection:
            flags.append("mem_large_executable")

        details: dict[str, Any] = {
            "start_vpn": start or None,
            "end_vpn": end or None,
            "protection": protection or None,
            "tag": tag or None,
        }
        if size is not None:
            details["size_bytes"] = size
        if pid is not None:
            details["pid"] = pid
        if process:
            details["process"] = process
        hexdump = row.get("Hexdump")
        if isinstance(hexdump, str) and hexdump.strip():
            # jen fingerprint — surové bajty do DB nejdou (paměť + PII)
            fp = hashlib.sha256(hexdump.encode("utf-8", errors="replace")).hexdigest()[:16]
            details["hexdump_fingerprint"] = f"sha256:{fp}"

        title = f"injected {start}–{end} ({protection or 'unknown'})"
        if process:
            title += f" — {process}"
        arts.append(
            _make_artifact(
                plugin="windows.malfind", row=row, title=title,
                details=details, anomaly_flags=flags,
            )
        )
    return arts


def parse_getsids(rows: list[Any]) -> list[Artifact]:
    """windows.getsids → memory_v3_sid.

    Credential guard: surové SID + username zůstávají (identita uživatele je
    forenzně legitimní), ale jakýkoli hash sloupec se nahradí fingerprintem.
    """
    arts: list[Artifact] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("SID") or "").strip()
        user = str(row.get("User Name") or "").strip()
        if not sid and not user:
            continue
        safe, _hidden = _filter_sensitive(row)
        details: dict[str, Any] = {k: v for k, v in safe.items() if isinstance(v, (str, int, float, bool))}
        fingerprints: list[dict[str, Any]] = []
        for key, val in row.items():
            if isinstance(key, str) and key.upper() in SENSITIVE_COLUMNS and not _is_empty(val):
                fingerprints.append({"column": key, **fingerprint_value(val)})
        if fingerprints:
            details["credential_fingerprints"] = fingerprints  # typ + fingerprint, ne hodnota
        title = f"SID {sid}" if sid else user
        arts.append(_make_artifact(plugin="windows.getsids", row=row, title=title, details=details))
    return arts


#: Plugin → parser.
PARSERS: dict[str, Any] = {
    "windows.pslist": parse_pslist,
    "windows.psscan": parse_pslist,
    "windows.netscan": parse_netscan,
    "windows.netstat": parse_netscan,
    "windows.ldrmodules": parse_ldrmodules,
    "windows.malfind": parse_malfind,
    "windows.getsids": parse_getsids,
}


# ── Vstupní validace (JSON z vol CLI) ─────────────────────────────────────

def validate_vol_output(rows: Any) -> list[dict[str, Any]]:
    """Vol JSON výstup → list dictů; nevalidní tvar → MemForensicsError."""
    if rows is None:
        return []
    if isinstance(rows, dict):  # vol může vrátit {data: [...]} nebo jediný záznam
        inner = rows.get("data") or rows.get("rows")
        return validate_vol_output(inner) if inner is not None else [rows]
    if not isinstance(rows, list):
        raise MemForensicsError(
            f"Očekávám JSON list/objekt od vol CLI, dostal: {type(rows).__name__}"
        )
    for i, item in enumerate(rows):
        if not isinstance(item, dict):
            raise MemForensicsError(f"Řádek #{i} není objekt: {item!r}")
    return rows


def parse_plugin_output(plugin: str, rows: Any) -> list[Artifact]:
    """Vol JSON výstup jednoho pluginu → Artifacty (validace + parser)."""
    if plugin not in PLUGIN_ARTIFACT_TYPES:
        raise MemForensicsError(f"Neznaný plugin: {plugin}")
    clean = validate_vol_output(rows)
    return PARSERS[plugin](clean)


# ── Anomaly rules (cross-plugin) ───────────────────────────────────────────

#: Porty, které v serverové kontextu bývají C2/poslední sloupy.
SUSPICIOUS_PORTS: frozenset[int] = frozenset({443, 8080, 6667, 6697})


def apply_cross_plugin_rules(arts: list[Artifact]) -> int:
    """Cross-plugin anomaly rules — doplňuje flags na place (vrať počet doplněných).

    Pravidla:
      * proces s PID, který vlastní podezřelé výchozí spojení → ``mem_c2_candidate``
        na obou artefaktech (proces + connection)
      * injected kód do procesu bez odpovídajícího záznamu v pslist →
        ``mem_injected_unknown_process``

    Mutuje ``anomaly_flags`` in-place; idempotentní (žádné duplikáty).
    """
    added = 0

    def _flag(art: Artifact, flag: str) -> None:
        nonlocal added
        if flag not in art.anomaly_flags:
            art.anomaly_flags.append(flag)
            added += 1

    def _process_pids() -> set[int]:
        pids: set[int] = set()
        for a in arts:
            if a.artifact_type != "memory_v3_process":
                continue
            pid = a.details.get("PID")
            if isinstance(pid, int):
                pids.add(pid)
            title = a.title or ""
            if title.startswith("PID ") and len(title.split()) > 1:
                parsed = _int_or_none(title.split()[1])
                if parsed is not None:
                    pids.add(parsed)
        return pids

    known_pids = _process_pids()

    injected_pids = {
        a.details["pid"]
        for a in arts
        if a.artifact_type == "memory_v3_injected" and isinstance(a.details.get("pid"), int)
    }
    unknown_inj = injected_pids - known_pids
    for a in arts:
        if a.artifact_type == "memory_v3_injected":
            pid = a.details.get("pid")
            if isinstance(pid, int) and pid in unknown_inj:
                _flag(a, "mem_injected_unknown_process")

    c2_pids: set[int] = set()
    for a in arts:
        if a.artifact_type != "memory_v3_connection":
            continue
        foreign = str(a.details.get("foreign_address") or "")
        port = _port(foreign)
        proto = str(a.details.get("proto") or "").upper()
        if port in SUSPICIOUS_PORTS and proto.startswith(("TCP",)):
            pid = a.details.get("pid")
            if isinstance(pid, int):
                c2_pids.add(pid)
                _flag(a, "mem_c2_candidate")

    for a in arts:
        if a.artifact_type != "memory_v3_process":
            continue
        pid = a.details.get("PID")
        if isinstance(pid, int) and pid in c2_pids:
            _flag(a, "mem_c2_candidate")

    return added


def summarize(arts: list[Artifact]) -> dict[str, Any]:
    """Shrnutí analýzy pro CLI výstup (typy + anomaly counts)."""
    by_type: dict[str, int] = {}
    flags: dict[str, int] = {}
    for a in arts:
        by_type[a.artifact_type] = by_type.get(a.artifact_type, 0) + 1
        for f in a.anomaly_flags:
            flags[f] = flags.get(f, 0) + 1
    return {
        "total": len(arts),
        "by_type": dict(sorted(by_type.items())),
        "anomaly_flags": dict(sorted(flags.items())),
    }


# ── helpers ────────────────────────────────────────────────────────────────

def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return int(s)
    return None


def _plain(value: Any) -> Any:
    """Vol JSON hodnoty → JSON-safe scalar (dict/list se znehodnotí na repr)."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _addr(raw: Any) -> str:
    """Vol addr sloupec '127.0.0.1:80' → string (None/'' → '')."""
    if raw is None:
        return ""
    s = str(raw).strip()
    # vol někdy vrací tuple-like [ip, port]
    if isinstance(raw, list) and len(raw) == 2:
        ip, port = raw[0], raw[1]
        return f"{ip}:{port}" if port is not None else str(ip)
    return s


def _host(addr: str) -> str:
    a = addr.strip()
    if ":" in a and not a.startswith("["):
        return a.rsplit(":", 1)[0] or a
    return a or "?"


def _port(addr: str) -> int | None:
    a = addr.strip().rsplit("]", 1)[-1]
    if ":" in a:
        tail = a.rsplit(":", 1)[-1]
        if tail.isdigit():
            return int(tail)
    return None


def _vpn_range_size(start: str, end: str) -> int | None:
    """VPN range (hex stringy '0xfffff803c12a4000') → velikost v bytech."""

    def _to_int(s: str) -> int | None:
        t = s.strip().lower()
        if not t:
            return None
        t = t.removeprefix("0x")
        try:
            return int(t, 16)
        except ValueError:
            try:
                return int(t, 10)
            except ValueError:
                return None

    a, b = _to_int(start), _to_int(end)
    if a is None or b is None or b < a:
        return None
    return b - a + 1


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())
