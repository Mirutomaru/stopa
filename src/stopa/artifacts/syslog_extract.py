"""STP-080 / vlna 36 — Unix BSD syslog text parser (§7 pilot, design §7).

Podporovaný formát: **textový výstup BSD syslog (RFC 3164)** — soubory jako
``/var/log/syslog``, ``/var/log/messages``, ``system.log`` se řádky::

    MMM DD HH:MM:SS host process[pid]: zpráva

Detekce: **name-based** (názvy souborů) + **content check** (aspoň jeden
timestampovaný řádek v hlavičce) — text nemá magic bytes, AXIOM Hunter pattern.

Artifact type: ``syslog_event`` — jedna událost = jeden artifact.

Kontrakt normalizace (smlouva reference datasetu, obě cesty stejný tvar):

- den je **nulově doplněn** (``Nov  7`` i ``Nov 07`` → pole ``date="Nov 07"``),
- čas ``time`` = verbatim ``HH:MM:SS``,
- timestamp syslogu **nemá rok** (ani TZ) → ``artifact.timestamp=None``;
  srovnatelné jsou pole ``date``/``time`` (limitace parseru — registry §C3),
- ``pid`` je int nebo chybí z detailů (explicitní ``None`` v reference, §3.3),
- řádky bez timestampové hlavičky (pokračování záznamů) se **přeskočí**.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_EVENTS_PER_FILE = 10_000

#: Jména měsíců — BSD syslog používá anglické zkratky (RFC 3164).
_MONTHS = frozenset(
    {
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    }
)

#: Jeden syslog řádek: ``MMM DD HH:MM:SS host proc[pid]: zpráva``.
#: Den 1–2 číslice (systémové doplnění mezerou se sníma ``\s+``); proces bez
#: mezer/dvojteček/hranatých závorek; volitelné ``[pid]``; oddělovač zprávy
#: je přesně ``": "`` (zpráva pak libovolná, i s dvojtečkami).
_SYSLOG_LINE_RE = re.compile(
    r"^(?P<month>[A-Z][a-z]{2})\s+(?P<day>\d{1,2}) (?P<hhmmss>\d{2}:\d{2}:\d{2}) "
    r"(?P<host>\S+) (?P<proc>[^\s:\[\]]+)(?:\[(?P<pid>\d+)\])?: (?P<msg>.*)$"
)

#: Content check hlavičky — timestampovaný řádek (detekce, ne parsing).
_HEAD_LINE_RE = re.compile(
    r"^[A-Z][a-z]{2}\s+\d{1,2} \d{2}:\d{2}:\d{2} \S+ ", re.MULTILINE
)

#: Názvy souborů, které jsou kandidáty na syslog (AXIOM Hunter pattern).
_NAME_KEYWORD = "syslog"
_EXACT_NAMES = frozenset({"messages", "system.log"})


@dataclass
class SyslogEvent:
    """Jeden syslog událostní záznam."""

    month: str = ""
    day: int = 0
    time_str: str = ""
    host: str = ""
    process: str = ""
    pid: int | None = None
    message: str = ""


def _parse_line(line: str) -> SyslogEvent | None:
    """Jeden řádek → událost (neplatný → None).

    Den se validuje rozsahem 1–31; čas jen formou ``HH:MM:SS`` (rozsahy
    se nevalidují — dokumentovaná limitace, obě cesty stejný kontrakt).
    """
    m = _SYSLOG_LINE_RE.match(line)
    if not m:
        return None
    month = m.group("month")
    if month not in _MONTHS:
        return None
    day = int(m.group("day"))
    if not 1 <= day <= 31:
        return None
    pid_raw = m.group("pid")
    return SyslogEvent(
        month=month,
        day=day,
        time_str=m.group("hhmmss"),
        host=m.group("host"),
        process=m.group("proc"),
        pid=int(pid_raw) if pid_raw is not None else None,
        message=m.group("msg"),
    )


def parse_syslog_text(data: bytes) -> list[SyslogEvent]:
    """ČISTÝ parser — textový BSD syslog → události.

    Raises:
        ValueError: v hlavičce (prvních 4096 B) není žádný timestampovaný řádek.
    """
    head = data[:4096]
    try:
        head_text = head.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — decode s replace nikdy nevyhodí, ale defenzivně
        raise ValueError("Syslog timestamp řádek nenalezen") from None
    if not _HEAD_LINE_RE.search(head_text):
        raise ValueError("Syslog timestamp řádek nenalezen")

    events: list[SyslogEvent] = []
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — defenzivně (viz výše)
        return events

    for line in text.splitlines():
        if len(events) >= MAX_EVENTS_PER_FILE:
            logger.warning("Syslog: dosáhnut limit %d událostí", MAX_EVENTS_PER_FILE)
            break
        event = _parse_line(line)
        if event is not None:
            events.append(event)

    return events


def is_syslog_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce syslog souboru (AXIOM Hunter pattern).

    Kandidát = název obsahuje ``syslog`` nebo je přesně ``messages`` /
    ``system.log``; při předaném ``head`` se navíc vyžaduje content check
    (aspoň jeden timestampovaný řádek v prvních 4096 B).
    """
    lower = name.lower()
    base = lower.rsplit("/", 1)[-1]
    if _NAME_KEYWORD not in lower and base not in _EXACT_NAMES:
        return False
    if head:
        try:
            text = head[:4096].decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — defenzivně (viz výše)
            return False
        if not _HEAD_LINE_RE.search(text):
            return False
    return True


def build_syslog_artifacts(events: list[SyslogEvent]) -> list[Artifact]:
    """ČISTÁ funkce: z událostí vytvoří artifacty (syslog_event)."""
    artifacts: list[Artifact] = []
    for e in events:
        details: dict[str, Any] = {
            "engine": "syslog",
            "host": e.host,
            # normalizace smlouvy: den nulově doplněn (raw ``Nov  7`` → ``Nov 07``)
            "date": f"{e.month} {e.day:02d}",
            "time": e.time_str,
            "process": e.process,
            "message": e.message,
        }
        if e.pid is not None:
            details["pid"] = e.pid

        artifacts.append(
            Artifact(
                artifact_type="syslog_event",
                timestamp=None,  # syslog timestamp nemá rok/TZ (limitace parseru)
                title=f"Syslog — {e.process}",
                details=details,
                confidence=0.8,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_syslog_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — syslog text → syslog_event artifacty.

    Chyby (poškozený soubor, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("Syslog %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        events = parse_syslog_text(data)
    except ValueError as e:
        logger.debug("Syslog %s: %s", path, e)
        return []

    return build_syslog_artifacts(events)
