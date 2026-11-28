"""STP-081 / vlna 37 — Apache/Nginx combined access log text parser (§7, design §7).

Podporovaný formát: **combined log format** (Apache ``LogFormat``
``%h %l %u %t "%r" %>s %b "%{Referer}i" "%{User-Agent}i"`` / Nginx default) —
soubory jako ``/var/log/apache2/access.log``, ``logs/access.log`` se řádky::

    192.168.10.5 - alice [10/Oct/2000:13:55:36 +0000] "GET /index.html HTTP/1.0" \\
        200 1461 "http://www.example.com/start.html" "Mozilla/4.08 [en]"

Detekce: **name-based** (``access.log*``, ``*access_log*``) + **content check**
(aspoň jeden combined řádek v hlavičce) — text nemá magic bytes, AXIOM Hunter
pattern. Google 2025 WR soubory ``AccessLogDevices*.json`` chytá dříve cloud
pre-pass (google marker, ``is_google_2025_file``), kolize tedy nevzniká;
souvislé ``accesslog`` bez oddělovače zůstává vyhrazeno Google WR detekci.

Artifact type: ``access_log_entry`` — jedna request = jeden artifact.

Kontrakt normalizace (smlouva reference datasetu, obě cesty stejný tvar):

- ``user``, ``referer``, ``user_agent``: hodnota ``"-"`` → explicitní ``None``
  (§3.3: chybějící ≠ prázdný),
- ``status`` = přesně 3 číslice → int (jinak řádek neplatný); ``size`` = int,
  ``"-"`` → explicitní ``None`` (``0`` zůstává ``0``),
- request řádek: method = první token (``[A-Za-z]+``); protocol = poslední
  token **pouze** pokud má formu ``HTTP/x[.y]``, jinak ``None``; target =
  střední tokeny spojené jednou mezerou (target verbatim, bez unescape),
- timestamp je verbatim v poli ``timestamp`` a navíc obě cesty **nezávisle**
  spočítají Unix epoch sekundy (int) → ``artifact.timestamp``; offset
  se validuje jen po formě (rozsahy ne — dokumentovaná limitace, §C3),
- řádky nesplňující combined formát (pokračování / poškozené) se **přeskočí**;
- pole ``ident`` (``%l``) se parsuje ale do detailů neukládá (v forensice zřídka
  obsazeno — dokumentovaná limitace smlouvy).
"""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_EVENTS_PER_FILE = 10_000

#: Měsíce Apache %t — ručně psaný mapování (úmyslně ne sdílené s reference).
_TS_MONTHS: dict[str, int] = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

#: Jeden combined access log řádek::
#:   ip ident user [dd/Mon/yyyy:HH:MM:SS ±ZZZZ] "request" status size "ref" "ua"
#: ``ident`` = libovolný token (typicky ``-``); request mezi uvozovkami bez
#: unescape; status přesně 3 číslice; size = ``-`` nebo číslice.
_ACCESS_LOG_LINE_RE = re.compile(
    r'^(?P<ip>\S+) (?P<ident>\S+) (?P<user>\S+) \[(?P<ts>[^\]]+)\] '
    r'"(?P<request>[^"]*)" (?P<status>[0-9]{3}) (?P<size>-|[0-9]+) '
    r'"(?P<referer>[^"]*)" "(?P<ua>[^"]*)"\s*$'
)

#: Content check hlavičky — combined řádek (detekce, ne parsing).
_HEAD_LINE_RE = re.compile(
    r'^\S+ \S+ \S+ \[[0-9]{2}/[A-Za-z]{3}/[0-9]{4}:[0-9]{2}:[0-9]{2}:[0-9]{2} '
    r'[+-][0-9]{4}\] "[A-Za-z]+ ',
    re.MULTILINE,
)

#: Apache timestamp ``dd/Mon/yyyy:HH:MM:SS ±ZZZZ`` (přesná forma).
_APACHE_TS_RE = re.compile(
    r"^([0-9]{2})/([A-Za-z]{3})/([0-9]{4}):([0-9]{2}):([0-9]{2}):([0-9]{2}) "
    r"([+-])([0-9]{4})$"
)

#: HTTP verze v request řádku — ``HTTP/x`` nebo ``HTTP/x.y``.
_HTTP_VERSION_RE = re.compile(r"^HTTP/[0-9]+(\.[0-9]+)?$")

#: Názvy souborů, které jsou kandidáty na access log (AXIOM Hunter pattern).
_EXACT_PREFIX = "access.log"  # access.log, access.log.1, access.log.2.gz, …
_NAME_KEYWORD = "access_log"


@dataclass
class AccessLogEvent:
    """Jeden combined access log záznam (request)."""

    ip: str = ""
    user: str | None = None
    timestamp_raw: str = ""
    ts_epoch: int | None = None
    method: str = ""
    target: str = ""
    protocol: str | None = None
    status: int = 0
    size: int | None = None
    referer: str | None = None
    user_agent: str | None = None


def _parse_request(request: str) -> tuple[str, str, str | None] | None:
    """Request řádek → ``(method, target, protocol|None)`` (neplatný → None).

    Pravidla smlouvy (obě cesty stejná): method = první token ``[A-Za-z]+``;
    poslední token se počítá jako protocol **pouze** pokud má formu
    ``HTTP/x[.y]`` a request má ≥ 3 tokeny; target = zbylé tokeny spojené
    jedinou mezerou (verbatim, bez unescape).
    """
    tokens = request.split()
    if len(tokens) < 2:
        return None
    method = tokens[0]
    if not re.fullmatch(r"[A-Za-z]+", method):
        return None
    rest = tokens[1:]
    protocol: str | None = None
    if len(rest) >= 2 and _HTTP_VERSION_RE.match(rest[-1]):
        protocol = rest[-1]
        target_tokens = rest[:-1]
    else:
        target_tokens = rest
    return method, " ".join(target_tokens), protocol


def _parse_apache_ts(ts_raw: str) -> int | None:
    """Apache timestamp → Unix epoch sekundy (int); neplatná forma → None.

    Rok + TZ nese → epoch je spočítatelný (na rozdíl od BSD syslogu). Offset
    se validuje jen po formě ``±ZZZZ``, rozsahy hodnot ne (limitace §C3 —
    stejná sémantika jako u syslogu pro časové komponenty).
    """
    m = _APACHE_TS_RE.match(ts_raw)
    if not m:
        return None
    day, mon, year, hh, mi, ss, sign, off = m.groups()
    month = _TS_MONTHS.get(mon)
    if month is None or not 1 <= int(day) <= 31:
        return None
    offset_s = int(off[:2]) * 3600 + int(off[2:]) * 60
    if sign == "-":
        offset_s = -offset_s
    return calendar.timegm((int(year), month, int(day), int(hh), int(mi), int(ss))) - offset_s


def _parse_line(line: str) -> AccessLogEvent | None:
    """Jeden řádek → událost (neplatný → None)."""
    m = _ACCESS_LOG_LINE_RE.match(line)
    if not m:
        return None
    ts_epoch = _parse_apache_ts(m.group("ts"))
    if ts_epoch is None:
        return None
    parsed_request = _parse_request(m.group("request"))
    if parsed_request is None:
        return None
    method, target, protocol = parsed_request

    def _dash(value: str) -> str | None:
        return None if value == "-" else value

    user = m.group("user")
    referer = m.group("referer")
    ua = m.group("ua")
    size_raw = m.group("size")
    return AccessLogEvent(
        ip=m.group("ip"),
        user=_dash(user),
        timestamp_raw=m.group("ts"),
        ts_epoch=ts_epoch,
        method=method,
        target=target,
        protocol=protocol,
        status=int(m.group("status")),
        size=None if size_raw == "-" else int(size_raw),
        referer=_dash(referer),
        user_agent=_dash(ua),
    )


def parse_access_log_text(data: bytes) -> list[AccessLogEvent]:
    """ČISTÝ parser — textový combined access log → události.

    Raises:
        ValueError: v hlavičce (prvních 4096 B) není žádný combined řádek.
    """
    head_text = data[:4096].decode("utf-8", errors="replace")
    if not _HEAD_LINE_RE.search(head_text):
        raise ValueError("Access log combined řádek nenalezen")

    events: list[AccessLogEvent] = []
    text = data.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if len(events) >= MAX_EVENTS_PER_FILE:
            logger.warning("Access log: dosáhnut limit %d událostí", MAX_EVENTS_PER_FILE)
            break
        event = _parse_line(line)
        if event is not None:
            events.append(event)

    return events


def is_access_log_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce access log souboru (AXIOM Hunter pattern).

    Kandidát = basename začíná na ``access.log`` (včetně rotací ``.1``,
    ``.2.gz``) nebo obsahuje ``access_log``; souvislé ``accesslog`` bez
    oddělovače zůstává vyhrazeno Google 2025 WR pre-pass detekci. Při
    předaném ``head`` se navíc vyžaduje content check (aspoň jeden combined
    řádek v prvních 4096 B).
    """
    lower = name.lower()
    base = lower.rsplit("/", 1)[-1]
    if not (base.startswith(_EXACT_PREFIX) or _NAME_KEYWORD in base):
        return False
    if head:
        text = head[:4096].decode("utf-8", errors="replace")
        if not _HEAD_LINE_RE.search(text):
            return False
    return True


def build_access_log_artifacts(events: list[AccessLogEvent]) -> list[Artifact]:
    """ČISTÁ funkce: z událostí vytvoří artifacty (access_log_entry)."""
    artifacts: list[Artifact] = []
    for e in events:
        try:
            ts_dt = from_unix(e.ts_epoch) if e.ts_epoch is not None else None
        except ValueError:  # epoch < 0 (pred-1970 datum + offset — okraj)
            ts_dt = None
        details: dict[str, Any] = {
            "engine": "access_log",
            "ip": e.ip,
            # explicitní None pro "-" hodnoty (§3.3: chybějící ≠ prázdný)
            "user": e.user,
            "timestamp": e.timestamp_raw,
            "method": e.method,
            "path": e.target,
            "protocol": e.protocol,
            "status": e.status,
            "bytes": e.size,
            "referer": e.referer,
            "user_agent": e.user_agent,
        }
        artifacts.append(
            Artifact(
                artifact_type="access_log_entry",
                timestamp=ts_dt,  # Apache %t nese rok + TZ → přesný UTC čas (na rozdíl od syslogu)
                title=f"{e.method} {e.target}",
                details=details,
                confidence=0.8,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_access_log_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — combined access log text → artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("Access log %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        events = parse_access_log_text(data)
    except ValueError as e:
        logger.debug("Access log %s: %s", path, e)
        return []

    return build_access_log_artifacts(events)
