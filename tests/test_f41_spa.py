"""F4.1 — SPA Frontend: web mount ``/spa`` (React build z ``frontend/``).

AK F4.1 (milestone 1):
- statický React+TS+Vite build servírovaný FastAPI na ``/spa``;
- Service Worker registrovatelný (offline-first read-only);
- legacy GUI na ``/`` zůstává dostupné;
- typovaný API klient + i18n CS/EN (testy ve ``frontend/src``, vitest).

Build: ``cd frontend && npm install && npx vite build`` → ``src/stopa/web/static/spa``.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from stopa.web.app import STATIC_DIR, create_app

SPA = STATIC_DIR / "spa"


@pytest.fixture()
def client(tmp_path: Path):
    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        yield c


class TestSpaMount:
    def test_spa_index_html(self, client: TestClient) -> None:
        r = client.get("/spa/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert 'id="root"' in r.text

    def test_sw_js_served(self, client: TestClient) -> None:
        """Offline-first (AK): Service Worker musí být dostupný pro registraci."""
        r = client.get("/spa/sw.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]
        # audit 2026-11: cache bump v2 (starší v1 se při activate() vyčistí)
        assert "stopa-spa-v2" in r.text

    def test_sw_cache_semantics(self, client: TestClient) -> None:
        """Audit 2026-11 — SW cache sémantika (live E2E potvrzené problémy):

        - navigace /spa/ = network-first → bez zastaralého index.html po deployu;
        - API GET se cache jen při res.ok → jednorázové 4xx/5xx netrvají v cache.
        """
        r = client.get("/spa/sw.js")
        assert 'req.mode === "navigate"' in r.text
        assert "res.ok" in r.text

    def test_build_assets_served(self, client: TestClient) -> None:
        """Všechny artefakty buildu v /spa/assets/* se servírují (200)."""
        js_files = glob.glob(str(SPA / "assets" / "*.js"))
        assert js_files, f"SPA build chybí — spusťte `npx vite build` v {Path('frontend').resolve()}"
        for f in js_files:
            name = Path(f).name
            r = client.get(f"/spa/assets/{name}")
            assert r.status_code == 200, f"asset {name} se neservíruje"

    def test_legacy_index_still_available(self, client: TestClient) -> None:
        """Legacy vanilla JS GUI na ``/`` zůstává (přechodová doba)."""
        r = client.get("/")
        assert r.status_code == 200
        assert "STOPA" in r.text

    def test_spa_link_in_legacy_topbar(self, client: TestClient) -> None:
        """Legacy GUI obsahuje odkaz na nové SPA (AK: viditelná cesta)."""
        r = client.get("/")
        assert '/spa/' in r.text
