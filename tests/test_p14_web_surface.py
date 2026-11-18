"""P1-4 — Web povrch: zlatý snapshot rout tabulky (characterization).

Než se god-file ``web/app.py`` rozloží do balíku ``stopa.web.routers``,
zafixujeme celkový HTTP/WS povrch aplikace: každý registr route
(FastAPI route, WebSocket route i Mount) s metodou a cestou. Po
rozkladu musí být povrch **byte-přesně stejný** (backward-kompatibilita
bez spuštění serveru — deterministicky offline přes ``create_app()``).

Snapshot: ``tests/golden/p14_web_surface.json`` (seřazené [kind, method, path]).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.routing import APIWebSocketRoute, Mount

GOLDEN = Path(__file__).parent / "golden" / "p14_web_surface.json"


def _route_table() -> list[list]:
    """Vytvoří seřazenou tabulku [kind, method|None, path] pro celou app."""
    from stopa.web.app import create_app

    app = create_app()
    rows: list[list] = []
    for r in app.routes:
        if isinstance(r, Mount):
            kind, method = "mount", None
        elif isinstance(r, APIWebSocketRoute):
            kind, method = "ws", None
        else:
            methods = sorted(m for m in (getattr(r, "methods", None) or ()) if m != "HEAD")
            kind, method = "http", methods[0] if len(methods) == 1 else "+".join(methods)
        rows.append([kind, method, r.path])
    return sorted(rows)


def test_web_surface_matches_golden():
    """Povrch (routy + metody) musí být byte-přesně jako snapshot."""
    table = _route_table()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert len(table) >= 90, f"podezřele málo rout: {len(table)}"
    assert [tuple(row) for row in table] == [tuple(row) for row in golden], (
        "Web povrch se změnil vs snapshot — aktualizuj tests/golden/p14_web_surface.json "
        "jen při uvědomělém rozšíření API"
    )


def test_golden_snapshot_well_formed():
    """Snapshot je seřazený, bez duplicit a s platnými kind hodnotami."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rows = [tuple(row) for row in golden]
    assert rows == sorted(rows), "snapshot není seřazen"
    assert len(rows) == len(set(rows)), "snapshot obsahuje duplicity"
    for kind, method, path in rows:
        assert kind in ("http", "ws", "mount"), f"neplatný kind {kind!r}"
        if kind == "http":
            assert method and set(method.split("+")) <= {
                "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS",
            }, f"neplatná metoda {method!r} pro {path}"
        else:
            assert method is None, f"{kind} route nesmí mít metodu ({path})"
