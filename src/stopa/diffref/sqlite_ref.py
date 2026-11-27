"""STP-073 — SQLite rodina: nezávislá referenční cesta + STOPA adaptér (pilot vlna 1).

Dvě záměrně oddělené kódové cesty nad stejným souborem (design §2/§6):

* **STOPA strana** (:func:`run_stopa_sqlite`) — běžný extraktor
  ``stopa.artifacts.sqlite_extract``; artifact → surové entry tvaru
  ``{type, ts?, fields}`` pro normalizační vrstvu (§3).
* **Referenční strana** (:func:`read_reference_entries`) — ručně psané SQL
  dotazy z manifestu + vlastní celočíselná konverze epoch (vlastní konstanta
  :data:`CHROME_UNIX_OFFSET_S`, ne ``stopa.domain.times``); stdlib ``sqlite3``
  v read-only režimu (``file::…?mode=ro`` — nedotýká se důkazů).

Pilotní scope (STP-073): schéma Chrome/Edge History (``urls``+``visits``);
vlna 3 (STP-076): Firefox places.sqlite (``moz_places``, unix ms) — stejná
kanonická smlouva ``browser_history`` + pole ``url`` / ``page_title``,
samostatný referenční dataset ``sqlite/firefox_places/``; vlna 4 (STP-077):
Android mmssms.db (tabulka ``sms``, unix ms) — kanonický typ ``sms_message``
+ pole ``body`` / ``address``, samostatný referenční dataset
``sqlite/android_sms/``. Provenienční metadata (např. ``engine``) se do
komparované plochy nedostávají — srovnává se obsah, ne STOPA anotace.

Graceful degradation: pilot běží čistě na stdlib; extras ``[diffref]`` jsou
zatím prázdné a slouží jako kotva pro verzování referenčních nástrojů v
dalších vlnách (design §10).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: Vlastní konstanta reference — 1970−1601 v sekundách (nezávislá na STOPA).
CHROME_UNIX_OFFSET_S = 11_644_473_600

#: Pilot scope: kanonické typy pro SQLite rodinu.
_BROWSER_HISTORY = "browser_history"
_SMS_MESSAGE = "sms_message"  # STP-077 — Android mmssms.db (vlna 4, §7)


def chrome_micros_to_unix_s(value: int) -> int:
    """Chrome ``visit_time`` (µs od Windows epochy 1601) → unix sekundy UTC.

    Přesná celočíselná aritmetika (``// 1_000_000 − offset``): float64 by u
    hodnot ~1.3e16 ztratil přesnost nad 2^53 a mohl se posunout o celou sekundu.
    Pozor: µs, **ne** FILETIME 100ns ticks (ty by vyžadovaly ``// 10_000_000``).

    Raises:
        TypeError: vstup není ``int`` (bool = typová chyba, ne hodnota).
        ValueError: ``value <= 0`` (Chrome používá 0 jako „žádný čas“).
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"očekáváno int (chrome µs), dostalo {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"chrome visit_time musí být kladné µs, dostalo {value}")
    return value // 1_000_000 - CHROME_UNIX_OFFSET_S


def unix_ms_to_unix_s(value: int) -> int:
    """Firefox ``moz_places.last_visit_date`` (ms od Unix epochy 1970) → unix s.

    Přesná celočíselná aritmetika (``// 1_000``). STOPA extraktor používá float
    cestu ``ms / 1000.0`` a normalizace flooruje na celé sekundy — pro hodnoty
    pod 2^53 ms se obě cesty shodují; reference zůstává celočíselná (nezávislá
    cesta, design §2). Pozor: ms, **ne** µs (``// 1_000_000``) ani FILETIME.

    Raises:
        TypeError: vstup není ``int`` (bool = typová chyba, ne hodnota).
        ValueError: ``value < 0`` (STOPA filtruje ``last_visit_date > 0``;
            0 = platná epocha 1970-01-01, konzistentně s ``from_unix``).
    """
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"očekáváno int (unix ms), dostalo {type(value).__name__}")
    if value < 0:
        raise ValueError(f"unix ms musí být ≥ 0, dostalo {value}")
    return value // 1_000


#: Registrované konvertéry epoch (jmena deklarované v manifestu).
CONVERTERS: Mapping[str, Any] = {
    "chrome_micros_to_unix_s": chrome_micros_to_unix_s,
    "unix_ms_to_unix_s": unix_ms_to_unix_s,  # STP-076 — Firefox places.sqlite (vlna 3)
}

_REQUIRED_MANIFEST_KEYS = ("parser_id", "schema_variant", "fixture_file", "reference_tool", "join_keys", "queries")


def load_manifest(path: Path) -> dict[str, Any]:
    """Načte a validuje referenční manifest (design §6.1).

    Returns:
        Slovník s klíči ``parser_id``, ``schema_variant``, ``fixture_file``,
        ``fixture_sha256`` (volitelný pin), ``reference_tool``, ``join_keys``,
        ``queries[].{type, sql, ts_column?, converter?, fields}``.

    Raises:
        ValueError: soubor/JSON nečitelný, chybějící povinný klíč, špatný tvar.
        TypeError: manifest není objekt, queries není list, pole není mapping.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"{path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: neplatný JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise TypeError(f"manifest: očekáván JSON objekt, dostal(a) {type(data).__name__}")
    for key in _REQUIRED_MANIFEST_KEYS:
        if key not in data:
            raise ValueError(f"manifest {path}: chybí povinný klíč {key!r}")
    version = data.get("version")
    if version != 1:
        raise ValueError(f"manifest {path}: neznámá verze manifestu {version!r} (očekáváno 1)")
    queries = data["queries"]
    if not isinstance(queries, list) or not queries:
        raise TypeError("manifest: 'queries' musí být neprázdný list")
    join_keys = data["join_keys"]
    if not isinstance(join_keys, dict):
        raise TypeError("manifest: 'join_keys' musí být objekt TYPE → [pole]")
    for type_name, fields in join_keys.items():
        if not isinstance(fields, list) or not all(isinstance(f, str) and f for f in fields):
            raise ValueError(
                f"manifest: join_keys[{type_name!r}] musí být neprázdný list názvů pole"
            )
    for i, query in enumerate(queries):
        if not isinstance(query, dict):
            raise TypeError(f"manifest: queries[{i}] není objekt")
        for qkey in ("type", "sql"):
            if qkey not in query:
                raise ValueError(f"manifest: queries[{i}] chybí klíč {qkey!r}")
        fields = query.get("fields")
        if fields is not None and (not isinstance(fields, dict) or not all(isinstance(k, str) for k in fields)):
            raise TypeError(f"manifest: queries[{i}].fields musí být objekt CANON→sloupec")
    return data


def read_reference_entries(db_path: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Referenční čtení: SQL dotazy z manifestu → surové entry pro §3.

    Každý řádek se mapuje na ``{type, ts?, fields}``, kde klíče ``fields`` jsou
    **kanonické názvy** (z ``query["fields"]``, CANON→sloupec) a hodnota
    timestampu projde konvertérem epoch z manifestu.

    Raises:
        ValueError: neznámý konvertér, chybějící sloupec v řádku, chyba SQL.
    """
    entries: list[dict[str, Any]] = []
    # file:: URI vyžaduje absolutní cestu (relativní + query parametr se nespolehlivě parsuje)
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)  # read-only — soubor důkazu se nedotkne
    try:
        for query in manifest["queries"]:  # type: ignore[index]
            converter_name = query.get("converter")
            if converter_name is not None and converter_name not in CONVERTERS:
                raise ValueError(f"manifest: neznámý konvertér {converter_name!r}")
            field_map: Mapping[str, str] = query.get("fields") or {}
            cursor = conn.execute(query["sql"])  # type: ignore[index]
            columns = [d[0] for d in cursor.description or []]
            for row in cursor.fetchall():
                values = dict(zip(columns, row))
                fields: dict[str, Any] = {}
                for canon, column in field_map.items():
                    if column not in values:
                        raise ValueError(
                            f"manifest: dotaz pro {query['type']!r} nevrátil sloupec {column!r}"
                        )
                    fields[canon] = values[column]
                entry: dict[str, Any] = {"type": query["type"], "fields": fields}  # type: ignore[index]
                ts_column = query.get("ts_column")
                if ts_column is not None:
                    raw_ts = values.get(ts_column)
                    if converter_name is not None and raw_ts is not None:
                        entry["ts"] = CONVERTERS[converter_name](raw_ts)  # type: ignore[misc]
                entries.append(entry)
    finally:
        conn.close()
    return entries


def run_stopa_sqlite(path: Path) -> list[dict[str, Any]]:
    """STOPA strana: běžný extraktor → surové entry pro normalizaci (§3).

    Scope vlny 4 (STP-077): artifacty ``browser_history`` (Chrome/Edge/Firefox;
    kanonická pole = obsah — ``url``, ``page_title``) a ``sms_message``
    (Android ``mmssms.db``; body z titleu, address z details); provenienční
    metadata (např. ``engine``) se nesrovnávají. Ostatní sqlite typy zatím
    mimo diferenciální scope (§7).
    """
    from stopa.artifacts.sqlite_extract import extract_sqlite_artifacts  # I/O vrstva

    entries: list[dict[str, Any]] = []
    for artifact in extract_sqlite_artifacts(path):
        if artifact.artifact_type == _BROWSER_HISTORY:
            fields: dict[str, Any] = {
                "url": artifact.title,  # extraktor: title = url[:500]
                "page_title": (artifact.details or {}).get("page_title"),
            }
        elif artifact.artifact_type == _SMS_MESSAGE:
            # STP-077 — body z titleu (STOPA strip + [:300]; fixture drží pod limitem)
            fields = {
                "body": artifact.title,
                "address": (artifact.details or {}).get("address"),
            }
        else:
            continue  # ostatní sqlite typy zatím mimo diferenciální scope (§7)
        entry: dict[str, Any] = {"type": artifact.artifact_type, "fields": fields}
        if artifact.timestamp is not None:
            entry["ts"] = artifact.timestamp.timestamp()
        entries.append(entry)
    return entries
