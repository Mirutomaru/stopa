"""H3 — explicitní verze výstupních schémat STOPA (CLI --json + HTML report).

Jediný zdroj pravdy pro strojově čitelné povrchy. Verze se zvyšuje jen při
změně smlouvy výstupu (odebrání/přejmenování klíče, změna tvaru); aditivní
doplnění polí bez změny existujících verzi nemění.

Leží v domain (čisté konstanty bez I/O), aby oba povrchy — ``cli/_util``
(_print_json) i ``domain/report`` (build_html) — sdílely identický zdroj a
nemohl dojít k driftu mezi CLI výstupy a reportem.
"""

from __future__ import annotations

#: H3 — verze výstupního schématu (CLI --json stdout + HTML report).
OUTPUT_SCHEMA_VERSION = 1

#: Klíč, pod nímž je verze injectována do strojově čitelných výstupů.
#: Namespaced „stopa_“ — bez kolize s klíči jednotlivých payloadů.
SCHEMA_KEY = "stopa_output_schema"


def schema_meta() -> dict[str, int]:
    """Fragment metadata pro výstupy: ``{klíč: verze}``.

    Pomocná funkce pro konzumenty a testy, kteří potřebují metafragment
    bez importu obou konstant zvlášť.
    """
    return {SCHEMA_KEY: OUTPUT_SCHEMA_VERSION}
