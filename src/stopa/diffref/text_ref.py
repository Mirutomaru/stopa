"""STP-074 / STP-080 / STP-081 — textová reference pro parsery ``net_connections``,
``syslog`` a ``access_log`` (pilot vlna 1 část B + §7 pilot, design §6/§7).

Druhá nezávislá cesta diferenciálního testování (§6): STOPA extraktor
(``extract_netstat_artifacts`` / ``extract_syslog_artifacts`` /
``extract_access_log_artifacts``) vs. **ručně psané referenční čtecí**
textových formátů (stdlib only, žádný import z ``stopa.artifacts``).

Podporované varianty (deklarované v manifestu per fixture):

- ``windows_netstat_ano`` — Windows ``netstat -ano`` (Proto Local Foreign State PID),
- ``unix_ss`` — Unix ``ss`` (Netid State Recv-Q Send-Q Local Peer Process),
- ``unix_syslog`` — STP-080: Unix BSD syslog / RFC 3164 řádky,
- ``apache_combined`` — STP-081: Apache/Nginx combined access log řádky.

Pole záznamu ``network_connection`` (smlouva manifestu, obě cesty stejný tvar):

- ``proto``  — uppercase (``TCP``/``UDP``),
- ``local``  — ``addr:port``; port chybí → jen adresa (IPv6 drží hranaté závorky),
- ``remote`` — jako local, ale ``*`` bez portu zůstává ``"*"`` a prázdná adresa
               → ``"(broadcast)"`` (sémantika detailů STOPA artifactu),
- ``state``  — uppercase nebo explicitní ``None`` (chybějící stav ≠ prázdný, §3.3),
- ``pid``    — int nebo explicitní ``None``,
- čas        — vždy ``ts=None`` (netstat/ss = snapshot bez časového razítka).

Pole záznamu ``syslog_event`` (STP-080 smlouva manifestu, obě cesty stejný tvar):

- ``host``     — hostname (varianta bez hostu je limitace parseru),
- ``process``  — název procesu; ``pid`` = int nebo explicitní ``None``,
- ``date``     — ``"MMM DD"``, den **nulově doplněn** (raw ``Nov  7`` → ``Nov 07``),
- ``time``     — verbatim ``HH:MM:SS``,
- ``message``  — zpráva verbatim za oddělovačem ``": "``;
- čas          — vždy ``ts=None`` (syslog timestamp nemá rok ani TZ).

Pole záznamu ``access_log_entry`` (STP-081 smlouva manifestu, obě cesty stejný tvar):

- ``ip``/``user``    — user = explicitní ``None`` pro ``"-"`` (§3.3),
- ``timestamp``      — verbatim Apache timestamp; **ts** = Unix epoch sekundy (int) —
                       rok + TZ nese, obě cesty spočítají nezávisle,
- ``method``/``path``/``protocol`` — z request řádku; protocol explicitní ``None``,
                                     pokud poslední token nemá formu ``HTTP/x[.y]``,
- ``status``         — int (přesně 3 číslice); ``bytes`` = int, ``"-"`` → ``None``,
- ``referer``/``user_agent`` — verbatim; ``"-"`` → explicitní ``None``.

Join key (manifest): ``network_connection = proto+local+remote``;
``syslog_event = host+process+date+time``;
``access_log_entry = ip+timestamp+method+path`` — identita události; obsahová pole
se komparují. Duplicitní join klíč se páruje po sobě deterministicky (§3.2).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ARTIFACT_TYPE = "network_connection"

#: Pole záznamu — pevná množina klíčů (explicitní None pro chybějící hodnoty).
FIELD_KEYS: tuple[str, ...] = ("proto", "local", "remote", "state", "pid")

#: Známé stavy Windows netstat -ano (úplné názvy, uppercase).
_WINDOWS_STATES = frozenset(
    {
        "LISTENING", "ESTABLISHED", "TIME_WAIT", "CLOSE_WAIT",
        "FIN_WAIT1", "FIN_WAIT2", "SYN_SENT", "SYN_RECEIVED",
        "LAST_ACK", "CLOSING",
    }
)

#: Známé stavy Unix ss (zkratky, uppercase).
_SS_STATES = frozenset(
    {
        "LISTEN", "ESTAB", "UNCONN", "NONE", "TIME-WAIT", "CLOSE-WAIT",
        "FIN-WAIT-1", "FIN-WAIT-2", "SYN-SENT", "SYN-RECV", "LAST-ACK", "CLOSED",
    }
)

#: varianta manifestu → referenční parser (nezávislá implementace).
_VARIANTS = {
    "windows_netstat_ano": "_ref_windows_netstat",
    "unix_ss": "_ref_unix_ss",
    # STP-080 / vlna 36 — Unix BSD syslog (RFC 3164)
    "unix_syslog": "_ref_unix_syslog",
    # STP-081 / vlna 37 — Apache/Nginx combined access log
    "apache_combined": "_ref_apache_combined",
}


def _entry(proto: str, local: str, remote: str, state: str | None, pid: int | None) -> dict:
    """Surový entry v tvaru, který očekává normalizační vrstva (§3)."""
    return {
        "type": ARTIFACT_TYPE,
        "ts": None,  # snapshot bez času (limitace parseru — registry §C3)
        "fields": {"proto": proto, "local": local, "remote": remote, "state": state, "pid": pid},
    }


def _split_endpoint(token: str) -> tuple[str, int | None]:
    """``addr:port`` → ``(addr, port)``; port ``*`` → ``None``.

    Vlastní rozbor (rpartition na posledním dvojtečku) — nezávislý na regexu
    STOPA extraktoru. IPv6 drží hranaté závorky jako součást adresy.
    """
    addr, sep, port = token.rpartition(":")
    if not sep or not addr:
        return (token, None)  # holá adresa bez portu (okraj; fixture takové nemá)
    return (addr, int(port) if port.isdigit() else None)


def _local_field(token: str) -> str:
    """Smlouva pole ``local`` — ``addr:port``, bez portu jen adresa."""
    addr, port = _split_endpoint(token)
    return f"{addr}:{port}" if port is not None else addr


def _remote_field(token: str) -> str:
    """Smlouva pole ``remote`` (sémantika detailů STOPA artifactu).

    ``addr:port`` pokud je port a adresa není ``*``; jinak jen adresa
    (prázdná → ``(broadcast)``). ``"*"`` bez portu zůstává ``"*"``.
    """
    addr, port = _split_endpoint(token)
    if port is not None and addr != "*":
        return f"{addr}:{port}"
    return addr or "(broadcast)"


def _ref_windows_netstat(text: str) -> list[dict]:
    """Referenční čtecí Windows ``netstat -ano`` (token-based, vlastní logika).

    Data řádek = první token je uppercase ``TCP``/``UDP`` a minimálně 3 tokeny.
    Stav = první známý stav mezi adresami a PID; PID = poslední číslicový token.
    """
    out: list[dict] = []
    for line in text.splitlines():
        toks = line.split()
        if len(toks) < 3 or toks[0] not in ("TCP", "UDP"):
            continue
        state = next((t for t in toks[3:-1] if t in _WINDOWS_STATES), None)
        pid = int(toks[-1]) if toks[-1].isdigit() else None
        out.append(_entry(toks[0], _local_field(toks[1]), _remote_field(toks[2]), state, pid))
    return out


def _ref_unix_ss(text: str) -> list[dict]:
    """Referenční čtecí Unix ``ss`` (Netid State Recv-Q Send-Q Local Peer …).

    Data řádek = první token lowercase ``tcp``/``udp`` a minimálně 6 tokenů;
    pozice sloupců jsou fixní dle formátu ss. PID ze sloupce Process
    (``users:(("jméno",pid=N,fd=M))``) — vlastní extrakce, ne regex STOPA.
    """
    out: list[dict] = []
    for line in text.splitlines():
        toks = line.split()
        if len(toks) < 6 or toks[0].lower() not in ("tcp", "udp"):
            continue
        proto = toks[0].upper()
        state = toks[1].upper() if toks[1].upper() in _SS_STATES else None
        pid: int | None = None
        for tok in toks[6:]:  # sloupec Process a dál — ostatní pozice neobsahují "pid="
            idx = tok.find("pid=")
            if idx != -1:
                digits = tok[idx + 4 :].split(",")[0]
                pid = int(digits) if digits.isdigit() else None
                break
        out.append(_entry(proto, _local_field(toks[4]), _remote_field(toks[5]), state, pid))
    return out


# ---------------------------------------------------------------------------
# STP-080 / vlna 36 — Unix BSD syslog (RFC 3164) reference, nezávislá cesta
# ---------------------------------------------------------------------------

#: Měsíce RFC 3164 — ručně psaný seznam, úmyslně ne sdílený s STOPA parserem.
_REF_SYSLOG_MONTHS = frozenset(
    {
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    }
)

#: Pole záznamu syslog_event — smlouva manifestu (obě cesty stejný tvar).
SYSLOG_FIELD_KEYS = ("host", "process", "pid", "date", "time", "message")


def _ref_unix_syslog(text: str) -> list[dict[str, Any]]:
    """Ruční referenční parsing BSD syslog řádků (tokenizace, ne regex).

    Nezávislá implementace STOPA parseru: řádek se rozseká na tokeny
    ``month day time host tail``; v ``tail`` najdeme **první** výskyt
    ``": "`` — to je oddělovač proces/zpráva (proces nemá mezery a PID část
    jen číslice/brackety, takže dřívější ``": "`` být nemůže).

    Normalizace smlouvy: den nulově doplněn; ``pid`` int nebo explicitní
    None; řádky bez platné hlavičky (pokračování záznamu) se přeskočí.
    """
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        month, day_raw, time_str, tail = parts

        if month not in _REF_SYSLOG_MONTHS:
            continue
        # den: 1–2 číslice, rozsah 1..31 (nezávislá validace STOPA regexu)
        if len(day_raw) > 2 or not day_raw.isdigit():
            continue
        day = int(day_raw)
        if not 1 <= day <= 31:
            continue
        # čas: přesně HH:MM:SS — ruční kontrola, ne regex (jen forma, ne rozsah)
        if (
            len(time_str) != 8
            or time_str[2] != ":"
            or time_str[5] != ":"
            or not time_str[:2].isdigit()
            or not time_str[3:5].isdigit()
            or not time_str[6:].isdigit()
        ):
            continue

        # tail = "host proc[pid]: zpráva" — host je první token (bez mezer)
        host, sep, rest = tail.partition(" ")
        if not sep or not rest:
            continue

        idx = rest.find(": ")
        if idx <= 0:
            continue
        proc_part = rest[:idx]
        message = rest[idx + 2:]

        # proces: bez mezer/dvojteček/hranatých závorek; volitelné [pid] na konci
        pid: int | None = None
        if proc_part.endswith("]"):
            bracket = proc_part.rfind("[")
            if bracket <= 0:
                continue
            pid_raw = proc_part[bracket + 1:-1]
            if not pid_raw.isdigit():
                continue
            process = proc_part[:bracket]
            pid = int(pid_raw)
        else:
            process = proc_part

        bad_chars = (" ", ":", "[", "]")
        if not process or any(c in process for c in bad_chars):
            continue

        out.append(
            {
                "type": "syslog_event",
                # syslog timestamp nemá rok/TZ → ts=None (limitace parseru)
                "ts": None,
                "fields": {
                    "host": host,
                    "process": process,
                    "pid": pid,
                    "date": f"{month} {day:02d}",  # smlouva: den nulově doplněn
                    "time": time_str,
                    "message": message,
                },
            }
        )

    return out


# ---------------------------------------------------------------------------
# STP-081 / vlna 37 — Apache/Nginx combined access log reference, nezávislá cesta
# ---------------------------------------------------------------------------

#: Měsíce Apache %t — ručně psaný mapování, úmyslně ne sdílené s STOPA parserem.
_REF_APACHE_MONTHS: dict[str, int] = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

#: Pole záznamu access_log_entry — smlouva manifestu (obě cesty stejný tvar).
ACCESS_LOG_FIELD_KEYS = (
    "ip", "user", "timestamp", "method", "path",
    "protocol", "status", "bytes", "referer", "user_agent",
)


def _ref_is_ascii_digits(value: str) -> bool:
    """ASCII číslice (``str.isdigit()`` by akceptoval i unicode cifry)."""
    return bool(value) and all(c in "0123456789" for c in value)


def _days_from_civil(year: int, month: int, day: int) -> int:
    """Dny od Unix epochy — Hinnantův algoritmus (nezávisle na STOPA calendar.timegm)."""
    y = year - 1 if month <= 2 else year
    era = y // 400 if y >= 0 else -((-y) // 400)
    yoe = y - era * 400  # [0, 399]
    m = month + (-3 if month > 2 else 9)
    doy = (153 * m + 2) // 5 + day - 1  # [0, 365]
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy  # [0, 146096]
    return era * 146097 + doe - 719468


def _ref_parse_apache_ts(ts_raw: str) -> int | None:
    """Apache timestamp ``dd/Mon/yyyy:HH:MM:SS ±ZZZZ`` → Unix epoch sekundy.

    Ruční parsing (bez regex, bez calendar.timegm — nezávislost na STOPA).
    Offset se validuje jen po formě, rozsahy hodnot ne (limitace §C3 — stejná
    sémantika jako u syslogu pro časové komponenty).
    """
    if len(ts_raw) != 26:
        return None
    day_raw = ts_raw[:2]
    month_name = ts_raw[3:6]
    year_raw = ts_raw[7:11]
    hhmmss = ts_raw[12:20]
    sign = ts_raw[21]
    off_raw = ts_raw[22:26]
    if (
        ts_raw[2] != "/" or ts_raw[6] != "/" or ts_raw[11] != ":"
        or ts_raw[14] != ":" or ts_raw[17] != ":" or ts_raw[20] != " "
        or sign not in "+-"
    ):
        return None
    if not (
        _ref_is_ascii_digits(day_raw)
        and _ref_is_ascii_digits(year_raw)
        and _ref_is_ascii_digits(hhmmss[:2])
        and _ref_is_ascii_digits(hhmmss[3:5])
        and _ref_is_ascii_digits(hhmmss[6:8])
        and _ref_is_ascii_digits(off_raw)
    ):
        return None
    month = _REF_APACHE_MONTHS.get(month_name)
    if month is None or not 1 <= int(day_raw) <= 31:
        return None
    hour, minute, second = int(hhmmss[:2]), int(hhmmss[3:5]), int(hhmmss[6:8])
    offset_s = int(off_raw[:2]) * 3600 + int(off_raw[2:]) * 60
    if sign == "-":
        offset_s = -offset_s
    return (
        _days_from_civil(int(year_raw), month, int(day_raw)) * 86400
        + hour * 3600 + minute * 60 + second - offset_s
    )


def _ref_is_http_version(token: str) -> bool:
    """``HTTP/x`` nebo ``HTTP/x.y`` — ruční forma, ne regex (smlouva obou cest)."""
    if not token.startswith("HTTP/"):
        return False
    segments = token[5:].split(".")
    if len(segments) > 2:
        return False
    return all(_ref_is_ascii_digits(seg) for seg in segments)


def _ref_parse_request(request: str) -> tuple[str, str, str | None] | None:
    """Request řádek → ``(method, target, protocol|None)`` (smlouva obou cest).

    method = první token (písmena A–Z/a–z); poslední token se počítá jako
    protocol **pouze** pokud má formu ``HTTP/x[.y]`` a request má ≥ 3 tokeny;
    target = zbylé tokeny spojené jednou mezerou (verbatim, bez unescape).
    """
    tokens = request.split()
    if len(tokens) < 2:
        return None
    method = tokens[0]
    if not all(("a" <= c <= "z") or ("A" <= c <= "Z") for c in method):
        return None
    rest = tokens[1:]
    protocol: str | None = None
    if len(rest) >= 2 and _ref_is_http_version(rest[-1]):
        protocol = rest[-1]
        target_tokens = rest[:-1]
    else:
        target_tokens = rest
    return method, " ".join(target_tokens), protocol


def _ref_apache_combined(text: str) -> list[dict[str, Any]]:
    """Ruční referenční parsing combined access log řádků (tokenizace + sken uvozovek).

    Nezávislá implementace STOPA parseru: bez regex přes celý řádek — tokeny se
    ručně rozsekávají a uvozené sekce najíme polohou. Vnitřní struktura za
    ``[timestamp]`` je striktně po jedné mezeře (ekvivalent STOPA regexu).
    Řádky nesplňující smlouvu (pokračování / poškozené) se přeskočí.
    """
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        ip, _ident, user_raw, rest = parts

        # [timestamp] — hranatá závorka musí být na začátku rest
        if not rest.startswith("["):
            continue
        close = rest.find("]")
        if close < 1:
            continue
        ts_raw = rest[1:close]
        after = rest[close + 1 :]
        if not after.startswith(" "):
            continue
        after = after[1:]

        # "request" — první uvozená sekce `after` (musí začínat ihned)
        q1 = after.find('"')
        if q1 != 0:
            continue
        req_end = after.find('"', 1)
        if req_end < 0:
            continue
        request = after[1:req_end]
        tail = after[req_end + 1 :]

        # status size — striktně jedna mezera + přesně 3 číslice + jedna mezera + size
        if len(tail) < 1 or tail[0] != " ":
            continue
        t = tail[1:]
        sp1 = t.find(" ")
        if sp1 <= 0:
            continue
        status_raw, t2 = t[:sp1], t[sp1 + 1 :]
        if not _ref_is_ascii_digits(status_raw) or len(status_raw) != 3:
            continue

        # size — až na další mezery (``-`` nebo ASCII číslice; leading zeros OK)
        sp2 = t2.find(" ")
        if sp2 <= 0:
            continue
        size_raw, quoted_tail = t2[:sp2], t2[sp2 + 1 :]
        if not (size_raw == "-" or _ref_is_ascii_digits(size_raw)):
            continue

        # "referer" "user-agent" — dvě uvozené sekce oddělené striktně jednou mezerou;
        # za závěrečnou uvozovkou jen whitespace (ekvivalent STOPA \s*$)
        if not quoted_tail.startswith('"'):
            continue
        ref_end = quoted_tail.find('"', 1)
        if ref_end < 0:
            continue
        referer_raw = quoted_tail[1:ref_end]
        ua_part = quoted_tail[ref_end + 1 :]
        if not ua_part.startswith(" "):
            continue
        ua_part = ua_part[1:]
        if not ua_part.startswith('"'):
            continue
        ua_end = ua_part.find('"', 1)
        if ua_end < 0:
            continue
        ua_raw = ua_part[1:ua_end]
        if ua_part[ua_end + 1:].strip():
            continue

        ts_epoch = _ref_parse_apache_ts(ts_raw)
        if ts_epoch is None:
            continue
        parsed_request = _ref_parse_request(request)
        if parsed_request is None:
            continue
        method, target, protocol = parsed_request

        out.append(
            {
                "type": "access_log_entry",
                # Apache %t nese rok + TZ → epoch spočítatelný (int)
                "ts": ts_epoch,
                "fields": {
                    "ip": ip,
                    "user": None if user_raw == "-" else user_raw,
                    "timestamp": ts_raw,
                    "method": method,
                    "path": target,
                    "protocol": protocol,
                    "status": int(status_raw),
                    "bytes": None if size_raw == "-" else int(size_raw),
                    "referer": None if referer_raw == "-" else referer_raw,
                    "user_agent": None if ua_raw == "-" else ua_raw,
                },
            }
        )

    return out


def load_text_manifest(path: Path) -> dict[str, Any]:
    """Načte + validuje manifest textového reference datasetu.

    Povinné klíče: ``version`` (== 1), ``parser_id``, ``reference_tool``,
    ``join_keys`` (mapa typ → list neprázdných str) a ``fixtures`` (neprázdný
    list záznamů ``{file, sha256, variant}`` s deklarovanou variantou).

    Raises:
        ValueError: souborová chyba / neplatný JSON / nesplněná validace.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: neplatný JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise TypeError(f"{path}: očekáván JSON objekt, dostalo {type(data).__name__}")

    if data.get("version") != 1:
        raise ValueError(f"{path}: nepodporovaná verze manifestu (očekáváno 1)")
    for key in ("parser_id", "reference_tool"):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{path}: klíč {key!r} musí být neprázdný string")

    join_keys = data.get("join_keys")
    if not isinstance(join_keys, dict) or not join_keys:
        raise ValueError(f"{path}: 'join_keys' musí být neprázdná mapa typ → pole")
    for type_name, fields in join_keys.items():
        if (
            not isinstance(type_name, str)
            or not isinstance(fields, list)
            or not all(isinstance(f, str) and f.strip() for f in fields)
        ):
            raise ValueError(f"{path}: join_keys[{type_name!r}] musí být list neprázdných pole")

    fixtures = data.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError(f"{path}: 'fixtures' musí být neprázdný list záznamů")
    for fx in fixtures:
        if not isinstance(fx, dict):
            raise TypeError(f"{path}: fixture záznam musí být objekt")
        name = fx.get("file")
        sha = fx.get("sha256")
        variant = fx.get("variant")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path}: fixture klíč 'file' chybí nebo je prázdný")
        if not isinstance(sha, str) or len(sha) != 64:
            raise ValueError(f"{path}: fixture {name!r} — 'sha256' musí být 64-znakový hex")
        if variant not in _VARIANTS:
            known = ", ".join(sorted(_VARIANTS))
            raise ValueError(
                f"{path}: fixture {name!r} — neznámá reference varianta "
                f"{variant!r} (deklarované: {known})"
            )
    return data


def run_stopa_netstat(path: Path) -> list[dict]:
    """STOPA strana: běžný extraktor → surové entry s pevnou množinou pole.

    Detaily artifactu obsahují ``state``/``pid`` jen při přítomnosti — entry
    doplní explicitní ``None`` (§3.3: chybějící ≠ prázdný, obě cesty stejná
    množina klíčů).
    """
    from stopa.artifacts.net_connections import extract_netstat_artifacts  # I/O vrstva

    entries: list[dict] = []
    for artifact in extract_netstat_artifacts(path):
        details = dict(artifact.details or {})
        entries.append(
            {
                "type": ARTIFACT_TYPE,
                "ts": None,
                "fields": {key: details.get(key) for key in FIELD_KEYS},
            }
        )
    return entries


def run_stopa_syslog(path: Path) -> list[dict]:
    """STOPA cesta (STP-080): ``extract_syslog_artifacts`` → záznamy pro komparaci.

    Pole se berou přímo z detailů artifactu — STOPA parser je normalizuje dle
    smlouvy manifestu (den nulově doplněn, chybějící pid = None).
    """
    from stopa.artifacts.syslog_extract import extract_syslog_artifacts  # I/O vrstva

    return [
        {
            "type": "syslog_event",
            "ts": a.timestamp,  # syslog timestamp nemá rok/TZ → None (limitace)
            "fields": {key: (a.details or {}).get(key) for key in SYSLOG_FIELD_KEYS},
        }
        for a in extract_syslog_artifacts(path)
    ]


def run_stopa_access_log(path: Path) -> list[dict]:
    """STOPA cesta (STP-081): ``extract_access_log_artifacts`` → záznamy pro komparaci.

    Pole se berou přímo z detailů artifactu — STOPA parser je normalizuje dle
    smlouvy manifestu (``"-"`` = None, status/bytes int). Timestamp je UTC datetime
    (Apache %t nese rok + TZ) → epoch sekundy pro ``normalize_ts`` (§3.1).
    """
    from stopa.artifacts.access_log_extract import extract_access_log_artifacts  # I/O vrstva

    return [
        {
            "type": "access_log_entry",
            "ts": int(a.timestamp.timestamp()) if a.timestamp is not None else None,
            "fields": {key: (a.details or {}).get(key) for key in ACCESS_LOG_FIELD_KEYS},
        }
        for a in extract_access_log_artifacts(path)
    ]


def _fixture_for(manifest: Mapping[str, object], name: str) -> Mapping[str, object]:
    """Fixture záznam manifestu podle názvu souboru (fail-fast)."""
    fixtures = manifest["fixtures"]  # validováno v load_text_manifest
    for fx in fixtures:  # type: ignore[union-attr]
        if isinstance(fx, Mapping) and fx.get("file") == name:
            return fx
    declared = ", ".join(
        str(fx.get("file")) for fx in fixtures if isinstance(fx, Mapping)  # type: ignore[union-attr]
    ) or "(žádné)"
    raise ValueError(f"manifest: fixture {name!r} není deklarovaná (deklarováno: {declared})")


def read_reference_entries(path: Path, manifest: Mapping[str, object]) -> list[dict]:
    """Referenční strana: vlastní čtecí dle varianty deklarované v manifestu.

    Fail-fast kontrola SHA-256 pinu fixtury (drift důkazu = vstupní chyba) a
    dispatch na nezávislý parser varianty.

    Raises:
        ValueError: fixture nedeklarovaná, hash-pin se neshoduje, chyba čtení.
    """
    fx = _fixture_for(manifest, path.name)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{path}: {exc.strerror or exc}") from exc
    actual = hashlib.sha256(data).hexdigest()
    if actual != fx["sha256"]:
        raise ValueError(
            f"hash fixtury se neshoduje s pinem v manifestu "
            f"(manifest {str(fx['sha256'])[:12]}… vs vstup {actual[:12]}…)"
        )
    parser_name = str(fx["variant"])  # validováno při načtení manifestu
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception as exc:  # decode s errors="replace" prakticky nepadne; defenzivní obal
        raise ValueError(f"{path}: chyba dekodování ({exc})") from exc
    return globals()[_VARIANTS[parser_name]](text)
