"""F3.3 — Natural Language Query → validní SQL dotaz nad case DB.

Design (bez nových externích závislostí, bez LLM v runtime cestě):

* ``llm_call(nl_text, schema_context) -> dict|str`` je injektovatelná
  funkce (offline testy = deterministická FakeLLM). Vrací JSON s klíči:

  - ``sql``    — SELECT/WITH dotaz s placeholderem ``?`` (povinný),
  - ``params`` — seznam parametrů pro ``?`` (volitelný, výchozí prázdný).

* **Validace proti schématu** — dotaz musí být jedním vyjádřením
  ``SELECT``/``WITH``, bez mutujících klíčových slov a s odkazy pouze na
  tabulky existující v case DB (whitelist z ``sqlite_master``, FTS shadow
  tabulky ``*_data/*_idx/*_docsize/*_config`` vynechané).

* **Sandbox read-only** — provedení na samostatném spojení
  ``file:<case>.db?mode=ro`` (write do sandboxu = SQLite error), takže
  dotaz nesmí ani náhodou měnit case DB.

* **Timeout** — ``sqlite3.set_progress_callback`` s monotonic deadline
  (výchozí 5 s dle AK); překrok = :class:`QueryTimeoutError`.

* **Omezení výstupu** — max. ``MAX_ROWS_HARD_CAP`` řádků, více =
  ``truncated=True`` v výsledku.

AK: 50 testovacích NL queries → ≥90 % úspěšnost; žádný SQL injection
(parameterized); timeout 5 s — viz ``tests/test_f33_nl_query.py``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 5.0
MAX_ROWS_DEFAULT = 100
MAX_ROWS_HARD_CAP = 500

#: Tabulky, pro které se generuje schema context (řazení dle důležitosti).
_CONTEXT_TABLES = ("files", "artifacts", "entities", "timeline_events", "sources")

_FTS_SHADOW_RE = re.compile(r"_(data|idx|docsize|config)$")
_FORBIDDEN_KW_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|PRAGMA|ATTACH|DETACH|"
    r"BEGIN|COMMIT|ROLLBACK|VACUUM|REINDEX|ANALYZE|SAVEPOINT)\b",
    re.IGNORECASE,
)
_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w]*)", re.IGNORECASE)


class NLQueryError(Exception):
    """Běžná chyba NL query vrstvy."""


class InvalidQueryError(NLQueryError):
    """Dotaz neprošel validací (syntax, whitelist tabulek, placeholder)."""

    def __init__(self, message: str, sql: str | None = None) -> None:
        super().__init__(message)
        self.sql = sql


class QueryTimeoutError(NLQueryError):
    """Dotaz překročil časový rozpočet sandboxu."""


@dataclass(frozen=True)
class NLQueryResult:
    """Ověřený výsledek NL query — řádky jako list dict, sloupce ze schématu."""

    sql: str
    params: tuple
    columns: tuple[str, ...]
    rows: list[dict]
    truncated: bool = False
    elapsed_ms: float = 0.0


def known_tables(db) -> frozenset[str]:
    """Whitelist tabulek case DB (bez ``sqlite_%`` a FTS shadow tabulek)."""
    names = [
        r[0]
        for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    return frozenset(n for n in names if not _FTS_SHADOW_RE.search(n))


def build_schema_context(db, case_id: str) -> str:
    """Kompaktní popis schématu + slovníku pro LLM prompt.

    Obsahuje tabulky se sloupci a *reálné hodnoty* přítomné v případě
    (artifact typy, entity kinds), aby LLM generovala platné dotazy.
    """
    lines: list[str] = []
    for table in _CONTEXT_TABLES:
        cols = [r[1] for r in db.conn.execute(f"PRAGMA table_info({table})")]
        if cols:
            lines.append(f"{table}({', '.join(cols)})")
    # Slovník reálných hodnot v případě — LLM musí učit se na datech, ne hádat.
    types = [
        r[0]
        for r in db.conn.execute(
            "SELECT DISTINCT artifact_type FROM artifacts WHERE source_id IN "
            "(SELECT id FROM sources WHERE case_id = ?) ORDER BY 1 LIMIT 40",
            (case_id,),
        )
    ]
    if types:
        lines.append("artifact_type hodnoty v případě: " + ", ".join(types))
    kinds = [
        r[0]
        for r in db.conn.execute(
            "SELECT DISTINCT kind FROM entities WHERE case_id = ? ORDER BY 1 LIMIT 40",
            (case_id,),
        )
    ]
    if kinds:
        lines.append("entity kind hodnoty v případě: " + ", ".join(kinds))
    return "\n".join(lines)


def _validate_sql(sql: str, tables: frozenset[str]) -> None:
    """Statická validace dotazu; při selhání :class:`InvalidQueryError`."""
    s = sql.strip()
    if not s:
        raise InvalidQueryError("prázdný SQL", sql)
    # Jedno vyjádření: semikolona jen jako závěrečná tečka.
    body = s[:-1].strip() if s.endswith(";") else s
    if ";" in body:
        raise InvalidQueryError("více vyjádření (semikolon uprostřed)", sql)
    first = re.split(r"\s+", body, maxsplit=1)[0].upper()
    if first not in ("SELECT", "WITH"):
        raise InvalidQueryError(f"očekáván SELECT/WITH, dostal: {first}", sql)
    m = _FORBIDDEN_KW_RE.search(body)
    if m:
        raise InvalidQueryError(f"zakázané klíčové slovo v dotazu: {m.group(1)}", sql)
    refs = [t for t in _TABLE_REF_RE.findall(body)]
    unknown = sorted({t for t in refs if t not in tables})
    if unknown:
        raise InvalidQueryError(f"neznámé tabulky v dotazu: {', '.join(unknown)}", sql)


def execute_sandboxed(
    db, sql: str, params: tuple, timeout_s: float = DEFAULT_TIMEOUT_S
) -> NLQueryResult:
    """Provedení ověřeného dotazu na read-only spojení s timeoutem."""
    path: Path = Path(db.path)
    ro = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    ro.row_factory = sqlite3.Row
    deadline = time.monotonic() + timeout_s

    def _progress() -> int:
        return 1 if time.monotonic() > deadline else 0

    ro.set_progress_handler(_progress, 250_000)  # kontrola každých ~250k VM instrukcí
    t0 = time.monotonic()
    try:
        cur = ro.execute(sql, params)
        columns = tuple(d[0] for d in (cur.description or ()))
        fetched = cur.fetchmany(MAX_ROWS_HARD_CAP + 1)
        truncated = len(fetched) > MAX_ROWS_HARD_CAP
        rows = [dict(r) for r in fetched[:MAX_ROWS_HARD_CAP]]
    except sqlite3.OperationalError as exc:
        msg = str(exc)
        # CPython mapuje návrat progress handleru na interrupt; starší/ostatní
        # buildy vrací "callback requested a stop" — obojí = náš timeout.
        if "callback requested a stop" in msg or msg == "interrupted":
            raise QueryTimeoutError(
                f"dotaz překročil rozpočet {timeout_s:g} s"
            ) from exc
        raise InvalidQueryError(msg, sql) from exc
    finally:
        ro.close()
    return NLQueryResult(
        sql=sql,
        params=params,
        columns=columns,
        rows=rows,
        truncated=truncated,
        elapsed_ms=(time.monotonic() - t0) * 1000.0,
    )


def _parse_llm_payload(payload: dict | str) -> tuple[str, list]:
    """LLM výstup → ``(sql, params)``; tolerantně k JSON string i dict."""
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InvalidQueryError(f"LLM vrátila ne-JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise InvalidQueryError("LLM výstup musí být objekt s klíčem 'sql'")
    sql = payload.get("sql")
    params = payload.get("params", [])
    if not isinstance(sql, str) or not sql.strip():
        raise InvalidQueryError("chybějící nebo prázdné pole 'sql'")
    if not isinstance(params, list):
        raise InvalidQueryError("pole 'params' musí být seznam")
    return sql, params


def run_nl_query(
    db,
    case_id: str,
    nl_text: str,
    llm_call=None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> NLQueryResult:
    """NL text → validní dotaz → ověřený výsledek (fail-closed).

    :param db: CaseDB (case DB s tabulkami files/artifacts/entities/…).
    :param case_id: ID případu — data se filtrují v LLM generovaném SQL.
    :param nl_text: přirozenojazykový dotaz.
    :param llm_call: injektovatelná ``(nl_text, schema_context) -> dict|str``;
        ``None`` = provider nenastaven → :class:`NLQueryError`.
    """
    if llm_call is None:
        raise NLQueryError("llm_call není nastaven (injektovatelný pro testy)")
    tables = known_tables(db)
    schema = build_schema_context(db, case_id)
    sql, params = _parse_llm_payload(llm_call(nl_text, schema))
    if len(params) != sql.count("?"):
        raise InvalidQueryError(
            f"počet parametrů ({len(params)}) ≠ počet placeholderů "
            f"({sql.count('?')})",
            sql,
        )
    _validate_sql(sql, tables)
    result = execute_sandboxed(db, sql, tuple(params), timeout_s=timeout_s)
    db.log_operation(
        "nl_query",
        actor="nl_query",
        details={
            "case_id": case_id,
            "nl_text": nl_text[:200],
            "sql": result.sql[:400],
            "rows": len(result.rows),
            "truncated": result.truncated,
            "elapsed_ms": round(result.elapsed_ms, 1),
        },
    )
    return result
