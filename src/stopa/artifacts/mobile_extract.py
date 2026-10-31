"""Mobilní logická extrakce (FÁZE 6a) — kontakty, WhatsApp, iOS Safari.

AXIOM-style: každý soubor se SQLite signaturou projde schema detektorem.
Tento modul pokrývá mobilní DB, která nezachytí `sqlite_extract.py`:

- Android contacts2.db: `data`(data1, mimetype) + `raw_contacts` → kontakty
  (mimetypes vinylist: phone_number / email / name / organization_name ...)
- iOS AddressBook.sqlite: `ABPerson`(FIRST, LAST) + `ABMultiValue`(VALUE, RECORD_ID)
  → kontakty (Apple databáze adresáře z logical backupu)
- WhatsApp msgstore.db: `ZWAMESSAGE`(ZMESSAGE, ZDATE=CFAbsoluteTime od 2001)
  → whatsapp_message artifacty
- iOS Safari History.db: `HistoryItems`(URL, VISIT_TIME=CFAbsoluteTime)
  → browser_history (engine ios_safari)

Konvence sdílené s `sqlite_extract.py`:
- IO je jen v `extract_mobile_artifacts()`; detektory jsou čisté funkce.
- Vrací `None`, pokud DB nezná žádný mobilní schéma — volající pak spadne
  do generic triage (tabulky + počty řádků).
"""

from __future__ import annotations

import logging
import sqlite3

from stopa.domain.times import from_apple_absolute
from stopa.models import Artifact

log = logging.getLogger("stopa.artifacts.mobile")

# E1: verze parseru — eviduje se v audit logu (reprodukovatelnost analýzy)
PARSER_VERSION = "1.0"


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {r["name"] for r in rows}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


# ── Android contacts2.db ────────────────────────────────────────

def _is_android_contacts(conn: sqlite3.Connection) -> bool:
    """Android contacts2.db: `data`(data1, mimetype) + `raw_contacts`."""
    tables = _tables(conn)
    if not {"data", "raw_contacts"} <= tables:
        return False
    cols = _table_columns(conn, "data")
    return {"data1", "mimetype"} <= cols


def _extract_android_contacts(conn: sqlite3.Connection) -> list[Artifact]:
    """Každá data1 hodnota (telefon/mail/jméno) → contact artifact."""
    rows = conn.execute(
        "SELECT data1, mimetype FROM data WHERE data1 IS NOT NULL AND data1 != ''"
    ).fetchall()
    out: list[Artifact] = []
    for r in rows:
        value = (r["data1"] or "").strip()
        if not value:
            continue
        out.append(
            Artifact(
                artifact_type="contact",
                timestamp=None,
                title=value[:200],
                details={"mimetype": r["mimetype"], "engine": "android_contacts"},
            )
        )
    return out


# ── iOS AddressBook.sqlite ──────────────────────────────────────

def _is_ios_addressbook(conn: sqlite3.Connection) -> bool:
    """iOS AddressBook: `ABPerson`(FIRST, LAST) + `ABMultiValue`(VALUE, RECORD_ID)."""
    tables = _tables(conn)
    if not {"ABPerson", "ABMultiValue"} <= tables:
        return False
    person_cols = _table_columns(conn, "ABPerson")
    mv_cols = _table_columns(conn, "ABMultiValue")
    return {"FIRST", "LAST"} <= person_cols and {"VALUE", "RECORD_ID"} <= mv_cols


def _extract_ios_addressbook(conn: sqlite3.Connection) -> list[Artifact]:
    """Každá multi-value hodnota osoby → contact artifact s jménem v detailu."""
    rows = conn.execute(
        "SELECT p.FIRST, p.LAST, mv.VALUE"
        " FROM ABPerson p JOIN ABMultiValue mv ON mv.RECORD_ID = p._ID"
        " WHERE mv.VALUE IS NOT NULL AND mv.VALUE != ''"
    ).fetchall()
    out: list[Artifact] = []
    for r in rows:
        value = (r["VALUE"] or "").strip()
        if not value:
            continue
        name = f"{(r['FIRST'] or '').strip()} {(r['LAST'] or '').strip()}".strip()
        out.append(
            Artifact(
                artifact_type="contact",
                timestamp=None,
                title=value[:200],
                details={"person_name": name or None, "engine": "ios_addressbook"},
            )
        )
    return out


# ── WhatsApp msgstore.db ────────────────────────────────────────

def _is_whatsapp(conn: sqlite3.Connection) -> bool:
    """WhatsApp msgstore.db: `ZWAMESSAGE`(ZMESSAGE, ZDATE=CFAbsoluteTime)."""
    tables = _tables(conn)
    if "ZWAMESSAGE" not in tables:
        return False
    cols = _table_columns(conn, "ZWAMESSAGE")
    return {"ZMESSAGE", "ZDATE"} <= cols


def _extract_whatsapp(conn: sqlite3.Connection) -> list[Artifact]:
    """Každá WhatsApp zpráva → artifact s textem a časem (CFAbsoluteTime)."""
    rows = conn.execute(
        "SELECT ZMESSAGE, ZDATE FROM ZWAMESSAGE WHERE ZMESSAGE IS NOT NULL AND ZDATE > 0"
    ).fetchall()
    out: list[Artifact] = []
    for r in rows:
        try:
            ts = from_apple_absolute(r["ZDATE"])
        except ValueError as e:
            log.debug("whatsapp %s: %s", r["ZDATE"], e)
            continue
        text = (r["ZMESSAGE"] or "").strip()
        out.append(
            Artifact(
                artifact_type="whatsapp_message",
                timestamp=ts,
                title=text[:300] or "(prázdná zpráva)",
                details={"engine": "whatsapp"},
            )
        )
    return out


# ── iOS Safari History.db ───────────────────────────────────────

def _is_ios_safari(conn: sqlite3.Connection) -> bool:
    """iOS Safari History.db: `HistoryItems`(URL, VISIT_TIME=CFAbsoluteTime)."""
    tables = _tables(conn)
    if "HistoryItems" not in tables:
        return False
    cols = _table_columns(conn, "HistoryItems")
    return {"URL", "VISIT_TIME"} <= cols


def _extract_ios_safari(conn: sqlite3.Connection) -> list[Artifact]:
    """Každý navštívený URL → browser_history artifact (CFAbsoluteTime)."""
    rows = conn.execute(
        "SELECT URL, VISIT_TIME FROM HistoryItems"
        " WHERE VISIT_TIME > 0 AND URL IS NOT NULL"
    ).fetchall()
    out: list[Artifact] = []
    for r in rows:
        try:
            ts = from_apple_absolute(r["VISIT_TIME"])
        except ValueError as e:
            log.debug("safari %s: %s", r["VISIT_TIME"], e)
            continue
        out.append(
            Artifact(
                artifact_type="browser_history",
                timestamp=ts,
                title=r["URL"][:500],
                details={"engine": "ios_safari"},
            )
        )
    return out


# ── veřejné API ────────────────────────────────────────────────

def extract_mobile_artifacts(conn: sqlite3.Connection) -> list[Artifact] | None:
    """Detekuje mobilní schéma a extrahuje artifacty.

    Vrací `None`, pokud DB nezná žádný mobilní formát (volající spadne do
    generic triage). Chyby → log + práznej výsledek, nikdy ne výjimka nahoru.
    """
    try:
        if _is_android_contacts(conn):
            return _extract_android_contacts(conn)
        if _is_ios_addressbook(conn):
            return _extract_ios_addressbook(conn)
        if _is_whatsapp(conn):
            return _extract_whatsapp(conn)
        if _is_ios_safari(conn):
            return _extract_ios_safari(conn)
    except sqlite3.Error as e:
        log.warning("mobile extract: %s", e)
        return []
    return None
