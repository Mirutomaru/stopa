"""Ukázkový plugin F6.4 — web server access log extractor (Nginx/Apache combined).

Kontrakt dle ``docs/PLUGINS_API.md``:
* ``is_access_log_file(path) -> bool`` — detekce podle vzoru řádků (magic-lite)
* ``extract_artifacts(path) -> list[Artifact]`` — pipeline entrypoint, nikdy
  nevyhazuje výjimku doven (defenzivní parsing)

Artefakty se agregují per (ip, method, path) — deterministické pořadí,
kapce MAX_GROUPS artefaktů. Typ ``event_log_entry`` (KNOWN_ARTIFACT_TYPES).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from stopa.models import Artifact

PARSER_VERSION = "1.0.0"

#: Kapce agregovaných skupin na jeden soubor (determinismus + paměť)
MAX_GROUPS = 500

LOG_RE = re.compile(
    r'^(?P<ip>\S+)\s+\S+\s+(?P<user>\S+)\s+'
    r"\[(?P<ts>[^\]]+)\]\s+"
    r'"(?P<method>[A-Z]+)\s+(?P<path>\S+)(?:\s+HTTP/[\d.]+)?"\s+'
    r"(?P<status>\d{3})\s+(?P<size>\d+|-)"
)

#: %b je locale-dependent → ruční mapa měsíců (forenzní determinismus)
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

TS_RE = re.compile(r"^(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}:\d{2}:\d{2})(?:\s+([+-]\d{4}))?$")


def _parse_ts(raw: str) -> datetime | None:
    """'10/Oct/2026:13:55:36 +0200' → aware datetime UTC; None = nepodařilo."""
    m = TS_RE.match(raw.strip())
    if not m:
        return None
    day, mon, year, hms, tz = m.groups()
    month = _MONTHS.get(mon)
    if month is None:
        return None
    hh, mm, ss = (int(x) for x in hms.split(":"))
    dt = datetime(int(year), month, int(day), hh, mm, ss, tzinfo=timezone.utc)
    if tz:
        sign = 1 if tz[0] == "+" else -1
        off_h, off_m = int(tz[1:3]), int(tz[3:5])
        from datetime import timedelta

        dt -= sign * timedelta(hours=off_h, minutes=off_m)
    return dt


def is_access_log_file(path: Path) -> bool:
    """Detekce: ≥ 50 % vzorkovaných neprázdných řádků odpovídá combined formatu."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()][:20]
    except OSError:
        return False
    if len(lines) < 3:
        return False
    hits = sum(1 for ln in lines if LOG_RE.match(ln))
    return hits * 2 >= len(lines)


def _aggregate(text: str) -> list[dict]:
    """ČISTÁ funkce: text logu → agregované skupiny (deterministické)."""
    groups: dict[tuple[str, str, str], dict] = defaultdict(
        lambda: {"count": 0, "first": None, "last": None, "statuses": set()}
    )
    for line in text.splitlines():
        m = LOG_RE.match(line)
        if not m:
            continue
        ts = _parse_ts(m["ts"])
        key = (m["ip"], m["method"], m["path"])
        g = groups[key]
        g["count"] += 1
        g["statuses"].add(int(m["status"]))
        if ts is not None:
            if g["first"] is None or ts < g["first"]:
                g["first"] = ts
            if g["last"] is None or ts > g["last"]:
                g["last"] = ts
    out = []
    for (ip, method, path) in sorted(groups):
        g = groups[(ip, method, path)]
        out.append({
            "ip": ip,
            "method": method,
            "path": path,
            "count": g["count"],
            "first_ts": g["first"].isoformat() if g["first"] else None,
            "last_ts": g["last"].isoformat() if g["last"] else None,
            "statuses": sorted(g["statuses"]),
        })
    return out[:MAX_GROUPS]


def extract_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — access log → event_log_entry artefakty.

    Chyby (IO, dekodování) → prázdný výsledek, nikdy ne výjimka doven.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if not text.strip():
        return []

    arts: list[Artifact] = []
    for grp in _aggregate(text):
        arts.append(
            Artifact(
                artifact_type="event_log_entry",
                timestamp=None,  # agregát — časy v details (first/last)
                title=f"Access log: {grp['count']}× {grp['method']} {grp['path']}",
                details={
                    "engine": "accesslog_plugin",
                    **grp,
                },
                confidence=0.8,
                parser_version=PARSER_VERSION,
            )
        )
    return arts
