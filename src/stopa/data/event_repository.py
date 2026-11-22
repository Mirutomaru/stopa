"""P4-7 — DB event bus: repository (disk I/O).

Tabulka ``events`` v instance DB (:func:`stopa.data.cross_case_repository.open_instance`).
Konekce zajišťuje volající (open_instance); commituje se po jednotlivých operacích.
Čistá logika (tvar událostí, kanonické JSON) žije v :mod:`stopa.domain.event_bus`.
"""

from __future__ import annotations

import sqlite3

from ..domain.event_bus import canonical_json, parse_event, validate_topic


def publish_event(conn: sqlite3.Connection, topic: str, event: dict) -> int:
    """Vloží událost do busu; vrací monotónní ``id`` řádku.

    :param conn: Konekce na instance DB (open_instance).
    :param topic: Téma v tvaru ``case:{case_id}``.
    :param event: Kanonická událost (dict z :func:`stopa.domain.event_bus.make_event`).
    :raises ValueError: Neplatné téma / payload.
    """
    validate_topic(topic)
    ts = str(event.get("ts", ""))
    cur = conn.execute(
        "INSERT INTO events (topic, payload_json, ts_utc) VALUES (?, ?, ?)",
        (topic, canonical_json(event), ts or "1970-01-01T00:00:00Z"),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def poll_events(conn: sqlite3.Connection, after_id: int = 0, limit: int = 500) -> list[dict]:
    """Nové události od ``after_id`` (včetně mezery), seřazené podle id.

    :return: Seznam ``{"id": int, "topic": str, "event": dict}`` (max ``limit``).
    :raises ValueError: Zkorumpovaný payload v DB (defenzivní — viz parse_event).
    """
    rows = conn.execute(
        "SELECT id, topic, payload_json FROM events WHERE id > ? ORDER BY id LIMIT ?",
        (int(after_id), int(limit)),
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        event = parse_event(row["payload_json"])
        out.append({"id": int(row["id"]), "topic": str(row["topic"]), "event": event})
    return out


def max_event_id(conn: sqlite3.Connection) -> int:
    """Aktuální maximum id (0 = prázdný bus)."""
    row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM events").fetchone()
    return int(row["m"])


def prune_old_events(conn: sqlite3.Connection, older_than_iso: str, batch_limit: int = 1000) -> int:
    """Smaže nejstarší řádky starší ``older_than_iso`` (omezeno na ``batch_limit``).

    Pruning běží periodicky (polling worker) — bus nikdy neroste bez omezení,
    ale jedno volání nezadrží zápisce. :return: počet smazaných řádků.
    """
    cur = conn.execute(
        "DELETE FROM events WHERE id IN ("
        "SELECT id FROM events WHERE ts_utc < ? ORDER BY id LIMIT ?)",
        (str(older_than_iso), int(batch_limit)),
    )
    conn.commit()
    return cur.rowcount
