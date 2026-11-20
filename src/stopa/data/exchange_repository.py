"""STOPA — P2-7 Case Exchange: datová vrstva (read-only I/O nad case DB).

Formát bundle v1 žije v ``domain/exchange``, anonymizace v ``domain/anonymize``;
tady se staví deterministický snapshot case DB a volá do domény. Počty sledují
konvenci P2-2 registru (celotabulkové počty — case DB obsahuje přesně jeden
případ); entity jsou filtrované podle ``case_id`` (DDL UNIQUE zaručuje bez
duplicit). Provenance souhrn je agregace nad ``artifacts`` (P0-1):

- ``artifacts_total`` / ``with_provenance`` (nenulový ``provenance_json``) /
  ``derived`` (``parent_artifact_id IS NOT NULL``) / ``root``.

Pack je read-only operace — do case DB se nic nezapisuje.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from stopa.domain.anonymize import AnonKey, AnonResult, anonymize
from stopa.domain.exchange import build_bundle


def exchange_snapshot(conn: sqlite3.Connection, case_id: str) -> dict[str, Any]:
    """Deterministický snapshot case DB pro bundle v1.

    :param conn: Spojení na case DB (read-only dotazy).
    :raises ValueError: Neznámý případ (chybí v tabulce ``cases``).
    """
    row = conn.execute("SELECT name FROM cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise ValueError(f"Případ {case_id!r} není v tabulce cases")

    file_count = int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
    artifact_rows = conn.execute(
        "SELECT provenance_json, parent_artifact_id FROM artifacts"
    ).fetchall()
    with_prov = sum(1 for r in artifact_rows if (r["provenance_json"] or "[]") not in ("[]", ""))
    derived = sum(1 for r in artifact_rows if r["parent_artifact_id"] is not None)

    entity_rows = conn.execute(
        "SELECT kind, value_normalized FROM entities"
        " WHERE case_id = ? ORDER BY kind ASC, value_normalized ASC",
        (case_id,),
    ).fetchall()
    # P3-6 — IoC z threat-intel feedu s per-entity TLP (zdroj pro verify kontrolu)
    ioc_rows = conn.execute(
        "SELECT kind, value, tlp FROM ioc_feed_items"
        " WHERE case_id = ? ORDER BY kind ASC, value ASC",
        (case_id,),
    ).fetchall()

    return {
        "title": row["name"],  # může být NULL → build_bundle akceptuje None
        "counts": {
            "files": file_count,
            "artifacts": len(artifact_rows),
            "entities": len(entity_rows),
        },
        "entities": [(r["kind"], r["value_normalized"]) for r in entity_rows],
        # 3-ice (kind, value, tlp) — build_bundle je akceptuje (P3-6 per-entity TLP);
        # v anon režimu se IoC neanonymizují (kanonická hodnota = cross-ref do feedu).
        "ioc_entities": [(r["kind"], r["value"], r["tlp"]) for r in ioc_rows],
        "provenance": {
            "artifacts_total": len(artifact_rows),
            "with_provenance": with_prov,
            "derived": derived,
            "root": len(artifact_rows) - derived,
        },
    }


def pack_case_bundle(
    conn: sqlite3.Connection,
    case_id: str,
    *,
    packed_at: str,
    anon_key: AnonKey | None = None,
    tlp: str | None = None,
) -> tuple[dict[str, Any], AnonResult | None]:
    """Snapshot + volitelná anonymizace → bundle v1 (doména ``build_bundle``).

    :param anon_key: Klíč anonymizace; ``None`` = kanonické entity.
    :param tlp: P3-6 — deklarovaná distribuční úroveň (CLEAR/GREEN/AMBER/RED/WHITE);
        ``None`` = klíč se do bundle nedostane (digest starých bundlů beze změny).
    :return: ``(bundle, AnonResult|None)`` — mapping je v ``AnonResult.mapping``
        a **nesmí** se dostat do bundle (re-anonymizovatelné jen s klíčem).

    Entity payload = kanonické entity (nebo jejich pseudonymy) + IoC z feedu
    s per-entity TLP; ``counts.entities`` sleduje finální délku payloadu.
    """
    snap = exchange_snapshot(conn, case_id)
    entities: list[tuple[str, str] | tuple[str, str, str]] = [
        (k, v) for k, v in snap["entities"]
    ]
    anon: AnonResult | None = None
    if anon_key is not None:
        anon = anonymize(anon_key, [(k, v) for k, v in snap["entities"]])  # fail-closed výše
        entities = [(r.kind, r.pseudonym) for r in anon.records]

    bundle = build_bundle(
        case_id=case_id,
        title=snap["title"],
        packed_at=packed_at,
        counts={
            "files": snap["counts"]["files"],
            "artifacts": snap["counts"]["artifacts"],
            # finální payload: kanonické/pseudonymizované entity + IoC s TLP (P3-6)
            "entities": len(entities) + len(snap["ioc_entities"]),
        },
        entities=[*entities, *snap["ioc_entities"]],
        provenance=snap["provenance"],
        tlp=tlp,
    )
    return bundle, anon
