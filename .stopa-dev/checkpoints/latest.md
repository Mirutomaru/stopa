# STOPA — Checkpoint (2026-11-08)

## Hotovo
**STP-061 — Oblast Q ★★: Timesketch timeline status (live polling) = read-only endpoint pro live stav indexace naposledy pushnuté timeline hotový**
- `data/timesketch_client.py` (+35 ř.) — nová metoda `timeline_status(sketch_id, timeline_id)`: GET `/api/v1/sketches/{sid}/timelines/{tid}/`, **nested** parsing `objects[0].status.status` (kontrakt ověřen ze zdrojů Timesketch serveru: `fields.Nested(status_fields)`), hodnoty `new/processing/ready/fail`; chybějící pole → `None` (ne výjimka) aby UI mohlo pollovat i při částečně vyplněné odpovědi; hází `TimesketchError` (HTTP != 200 / ne-JSON) a `TimesketchUnavailable` (server nedostupný).
- `web/app.py` (+45 ř.) — nový read-only endpoint `GET /api/cases/{id}/timesketch-status`: RBAC `case.read` (všechny role), bez auditu; najde poslední audit záznam `timesketch_pushed` (sketch_id + timeline_id) a dotáže Timesketch. Chybové cesty: 404 — case neexistuje / žádný push, 503 — Timesketch nedostupná, 502 — dotaz selhal.
- `tests/test_stp061.py` (nový, 10 testů): klient přes `httpx.MockTransport` (ready/processing/missing→None/HTTP error/connection error) + web E2E přes TestClient s monkeypatchovaným klientem (404 bez pushu, 404 neznámý case, 503 nedostupná, 200 ready, 502 selhání).
- Ověřeno: cílené **10/10 passed**, full suite **2058p/1s** bez regresí (2048 → +10), ruff clean.

## Stav
- HEAD: `8c02098` feat(interop): STP-061 Timesketch timeline status — klient + web endpoint + testy
- Full suite: **2058 passed, 1 skipped**, ruff clean; JS DOM: graph 5/5 + interop 5/5
