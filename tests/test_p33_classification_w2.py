"""STOPA P3-3 Wave 2 — Automated Classification: v26 migrace + data vrstva + CLI + Web.

Doménová coverage (pravidla, AK1/AK2) je v ``tests/test_p33_classification_domain.py``
(Wave 1); tady je hrana:

- schéma **v26**: tabulka ``classifications`` (aditivní) + migrace legacy v25→v26;
- ``ClassificationRepository.classify_case``: vstupy per soubor z DB stavu,
  re-derivace entit, deterministický re-run (upsert AUTO polí), souhrn;
- lidský override: aditivní sloupec + append-only audit_log (hash chain),
  reverzibilní (auto hodnota zůstává);
- CLI ``stopa classify <case> [--override ID --category X --reason R]`` — exit kódy;
- Web ``GET/POST /api/cases/{id}/classifications…`` (404 neznámý případ, 400 semantika).

Offline a deterministické: dočasná CaseDB ve standardním layoutu; FastAPI
TestClient bez spuštění serveru.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sqlite3
from datetime import datetime, timezone  # noqa: F401 — NOW_ISO fallback v testech
from pathlib import Path

import pytest

from stopa.data.db import CaseDB

CASE_ID = "p33-case"
NOW_ISO = "2026-11-20T12:00:00+00:00"

#: Očekávaná množina sloupců tabulky classifications (v26).
CLASSIFICATION_COLUMNS = frozenset({
    "id", "case_id", "file_id", "rel_path", "category", "confidence",
    "reasons_json", "needs_review", "risk_flags_json", "classified_at",
    "stopa_version", "status", "override_category", "override_actor",
    "override_reason", "overridden_at",
})


def _run(cmd, **kw) -> tuple[int, str]:
    """Spuští CLI příkaz s Namespace; vrací (exit_code, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cmd(argparse.Namespace(**kw)) or 0
    return int(rc), buf.getvalue()


# ── fixture: case DB se soubory pokrývajícími všechna rozhodnutí klasifikátoru ──


def _seed_case(d: CaseDB) -> None:
    """Šest souborů — po jednom na každou cestu klasifikátoru (viz testy)."""
    c = d.conn
    c.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
        (CASE_ID, "P3-3", NOW_ISO),
    )
    c.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES ('s1', ?, 'file', '/x', ?)",
        (CASE_ID, NOW_ISO),
    )

    def add_file(fid: str, rel: str, name: str, ext: str | None = None,
                 sig: str | None = None, bad: int = 0, hashhit: str | None = None) -> None:
        c.execute(
            "INSERT INTO files (id, source_id, rel_path, name, size_bytes, extension,"
            " signature_type, bad_extension, hash_set_hit)"
            " VALUES (?, 's1', ?, ?, ?, ?, ?, ?, ?)",
            (fid, rel, name, len(name), ext, sig, bad, hashhit),
        )

    def add_art(aid: str, fid: str, atype: str, title: str = "") -> None:
        c.execute(
            "INSERT INTO artifacts (id, source_id, file_id, artifact_type, title)"
            " VALUES (?, 's1', ?, ?, ?)",
            (aid, fid, atype, title),
        )

    # f1 — browser: silné parser signály (browser_history + cookie)
    add_file("f1", "C:/Users/u/AppData/Local/Google/Chrome/User Data/Login Data", "Login Data")
    add_art("a1", "f1", "browser_history", "https://example.com/page")
    add_art("a2", "f1", "browser_cookie", "cookie example.com")

    # f2 — chat: parser signál + telefon ve volném textu (entity corroboration)
    add_file("f2", "android/WhatsApp/msg.db", "msg.db", ext="db")
    add_art("a3", "f2", "whatsapp_message", "msg from +420 777 123 456: ahoj")

    # f3 — dokumenty: jen heuristika extenze (bez parser artefaktů)
    add_file("f3", "docs/report.docx", "report.docx", ext="docx")

    # f4 — systémové logy: binární signatura evtx, neparsovaný soubor
    add_file("f4", "C:/Windows/System32/winevt/Log/security.evtx", "security.evtx",
             ext="evtx", sig="evtx")

    # f5 — neznámý obsah + rizikové flagy (slabý signál generic_log)
    add_file("f5", "misc/data.bin", "data.bin", ext="bin", bad=1, hashhit="malware-v3")
    add_art("a4", "f5", "generic_log", "raw line without structure")

    # f6 — neznámý obsah: žádné signály vůbec
    add_file("f6", "misc/weird.xyz", "weird.xyz", ext="xyz")
    c.commit()


@pytest.fixture()
def dbdir(tmp_path: Path, monkeypatch) -> Path:
    d = tmp_path / "cases"
    d.mkdir()
    monkeypatch.setenv("STOPA_DB_DIR", str(d))
    seeded = CaseDB(d / f"{CASE_ID}.db")
    _seed_case(seeded)
    seeded.close()
    return d


@pytest.fixture()
def db(dbdir: Path) -> CaseDB:
    d = CaseDB(dbdir / f"{CASE_ID}.db")
    yield d
    d.close()


# ── schéma v26 + migrace legacy ───────────────────────────────────────────────


class TestSchemaV26:
    def test_new_db_has_classifications_table(self, dbdir):
        """Classifications tabulka (v26) persistuje i v aktuálním schématu (B10 v29)."""
        from stopa.data.schema import SCHEMA_VERSION

        assert SCHEMA_VERSION == 29
        d = CaseDB(dbdir / f"{CASE_ID}.db")
        try:
            assert d.schema_version() == SCHEMA_VERSION
            cols = {r[1] for r in d.conn.execute("PRAGMA table_info(classifications)")}
            assert cols == CLASSIFICATION_COLUMNS
        finally:
            d.close()

    def test_category_check_rejects_unknown_value(self, dbdir):
        d = CaseDB(dbdir / f"{CASE_ID}.db")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                d.conn.execute(
                    "INSERT INTO classifications (case_id, file_id, rel_path,"
                    " category, confidence, classified_at)"
                    " VALUES (?, 'fx', 'x.txt', 'not_a_category', 0.5, ?)",
                    (CASE_ID, NOW_ISO),
                )
        finally:
            d.close()

    def test_legacy_v25_migrates_to_latest(self, dbdir):
        """Staré v25 DB (bez tabulky) se po open dostanou na aktuální verzi (B10 v29)."""
        path = dbdir / f"{CASE_ID}.db"
        d = CaseDB(path)
        d.conn.execute("DROP TABLE classifications")
        d.conn.execute(
            "UPDATE meta SET value = '25' WHERE key = 'schema_version'"
        )
        d.conn.commit()
        d.close()

        d2 = CaseDB(path)  # reopen → apply_legacy_migrations (v26..v29 aditivní)
        try:
            assert d2.schema_version() == 29
            tables = {
                r[0] for r in d2.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert {"classifications", "seal_chain"} <= tables
        finally:
            d2.close()


# ── data vrstva: classify_case ────────────────────────────────────────────────


EXPECTED_BY_FILE = {  # file_id → (category, confidence, needs_review)
    "f1": ("browser", 1.0, False),
    "f2": ("chat_messaging", 1.0, False),
    "f3": ("documents_media", 0.5, True),
    "f4": ("system_logs", 0.5, True),
    "f5": ("unknown", 0.4, True),
    "f6": ("unknown", 0.2, True),
}


class TestClassifyCase:
    def test_summary_counts(self, db):
        from stopa.data.classification_repository import ClassificationRepository

        summary = ClassificationRepository(db.conn).classify_case(CASE_ID)
        assert summary["total_files"] == 6
        assert summary["by_category"] == {
            "browser": 1, "chat_messaging": 1, "documents_media": 1,
            "system_logs": 1, "unknown": 2,
        }
        assert summary["needs_review_count"] == 4

    def test_per_file_results_match_design(self, db):
        from stopa.data.classification_repository import ClassificationRepository

        repo = ClassificationRepository(db.conn)
        repo.classify_case(CASE_ID)
        rows = {r["file_id"]: r for r in repo.list_classifications(CASE_ID)}
        assert set(rows) == set(EXPECTED_BY_FILE)
        for fid, (category, confidence, needs_review) in EXPECTED_BY_FILE.items():
            row = rows[fid]
            assert row["category"] == category, fid
            assert row["confidence"] == pytest.approx(confidence), fid
            assert row["needs_review"] is needs_review, fid
            assert row["reasons"], f"{fid}: reasons musí být neprázdné (AK2)"

    def test_risk_flags_and_reasons_for_f5(self, db):
        from stopa.data.classification_repository import ClassificationRepository

        repo = ClassificationRepository(db.conn)
        repo.classify_case(CASE_ID)
        row = next(r for r in repo.list_classifications(CASE_ID) if r["file_id"] == "f5")
        assert set(row["risk_flags"]) == {"hash_set_hit", "bad_extension"}
        joined = "\n".join(row["reasons"])
        assert "hash nalezen ve známém hash setu" in joined
        assert "nesouhlasí extenze" in joined

    def test_entity_corroboration_rederived_from_db(self, db):
        """f2: telefon re-derivovaný z artefaktu potvrzuje chat (E4)."""
        from stopa.data.classification_repository import ClassificationRepository

        repo = ClassificationRepository(db.conn)
        repo.classify_case(CASE_ID)
        row = next(r for r in repo.list_classifications(CASE_ID) if r["file_id"] == "f2")
        assert any("potvrzeno entitami" in reason and "phone" in reason
                   for reason in row["reasons"])

    def test_rerun_is_deterministic_and_preserves_auto_fields(self, db):
        """Re-run: stejný výsledek (category/confidence/reasons), upsert bez duplicit."""
        from stopa.data.classification_repository import ClassificationRepository

        repo = ClassificationRepository(db.conn)
        s1 = repo.classify_case(CASE_ID)
        first = {r["file_id"]: r for r in repo.list_classifications(CASE_ID)}
        s2 = repo.classify_case(CASE_ID)
        second = {r["file_id"]: r for r in repo.list_classifications(CASE_ID)}
        assert s1 == s2  # souhrn deterministický (bez času)
        assert set(first) == set(second) and len(first) == 6  # žádný duplicitní řádek
        for fid, before in first.items():
            after = second[fid]
            assert after["category"] == before["category"], fid
            assert after["confidence"] == before["confidence"], fid
            assert after["reasons"] == before["reasons"], fid

    def test_stopa_version_recorded(self, db):
        from stopa import __version__
        from stopa.data.classification_repository import ClassificationRepository

        repo = ClassificationRepository(db.conn)
        repo.classify_case(CASE_ID)
        row = next(r for r in repo.list_classifications(CASE_ID) if r["file_id"] == "f1")
        assert row["stopa_version"] == __version__


# ── data vrstva: lidský override (AK3 — auditovalný + reverzibilní) ───────────


class TestOverride:
    def _repo(self, db):
        from stopa.data.classification_repository import ClassificationRepository

        return ClassificationRepository(db.conn)

    def test_override_updates_row_and_audit_chain(self, db):
        repo = self._repo(db)
        repo.classify_case(CASE_ID)
        target = next(r for r in repo.list_classifications(CASE_ID) if r["file_id"] == "f1")

        result = repo.override(
            CASE_ID, target["id"], "email", actor="mirda", reason="reviewer souhlasí"
        )
        assert result is not None
        assert result["status"] == "overridden"
        assert result["category"] == "browser"  # auto hodnota zůstává (reverzibilní)
        assert result["override_category"] == "email"
        assert result["effective_category"] == "email"
        assert result["override_actor"] == "mirda"

        audit = db.conn.execute(
            "SELECT action, details_json FROM audit_log WHERE action = 'classification_override'"
        ).fetchall()
        assert len(audit) == 1
        details = json.loads(audit[0]["details_json"])
        assert details["auto_category"] == "browser"
        assert details["override_category"] == "email"
        # hash chain záznam je kompletní (prev_hash/hash vyplněny — E3/P0)
        row = db.conn.execute(
            "SELECT prev_hash, hash FROM audit_log WHERE action = 'classification_override'"
        ).fetchone()
        assert row["hash"] and row["hash"] != ""

    def test_rerun_preserves_override(self, db):
        repo = self._repo(db)
        repo.classify_case(CASE_ID)
        target = next(r for r in repo.list_classifications(CASE_ID) if r["file_id"] == "f3")
        assert repo.override(
            CASE_ID, target["id"], "system_logs", actor="x", reason="pravděpodobně log"
        ) is not None

        repo.classify_case(CASE_ID)  # re-run klasifikátoru
        row = next(r for r in repo.list_classifications(CASE_ID) if r["file_id"] == "f3")
        assert row["category"] == "documents_media"  # auto výsledek se přepočítal
        assert row["status"] == "overridden"  # ale override zůstal

    def test_override_semantic_errors(self, db):
        repo = self._repo(db)
        repo.classify_case(CASE_ID)
        target = next(r for r in repo.list_classifications(CASE_ID) if r["file_id"] == "f1")
        with pytest.raises(ValueError, match="neplatná kategorie"):
            repo.override(CASE_ID, target["id"], "nope", reason="r")
        with pytest.raises(ValueError, match="prázdný důvod"):
            repo.override(CASE_ID, target["id"], "email", reason="   ")

    def test_override_missing_row_returns_none(self, db):
        repo = self._repo(db)
        repo.classify_case(CASE_ID)
        assert repo.override(CASE_ID, 9999, "email", reason="r") is None


# ── CLI: stopa classify <case> [--override …] ────────────────────────────────


class TestCliClassify:
    def test_classify_json_exit0(self, dbdir):
        from stopa.cli.commands.classification import cmd_classify

        rc, out = _run(cmd_classify, case_id=CASE_ID, json=True)
        assert rc == 0
        body = json.loads(out)
        assert body["ok"] is True
        assert body["summary"]["total_files"] == 6
        assert len(body["classifications"]) == 6

    def test_classify_text_summary(self, dbdir):
        from stopa.cli.commands.classification import cmd_classify

        rc, out = _run(cmd_classify, case_id=CASE_ID, json=False)
        assert rc == 0
        assert "KLASIFIKACE PŘÍPADU p33-case — 6 souborů" in out
        assert "ČEKÁ NA REVIZI — 4 souborů" in out

    def test_override_json(self, dbdir):
        from stopa.cli.commands.classification import cmd_classify

        _, out = _run(cmd_classify, case_id=CASE_ID, json=True)
        target_id = next(
            r["id"] for r in json.loads(out)["classifications"] if r["file_id"] == "f1"
        )
        rc, out2 = _run(
            cmd_classify,
            case_id=CASE_ID,
            json=True,
            override=str(target_id),
            category="email",
            reason="reviewer souhlasí",
            actor=None,
        )
        assert rc == 0
        body = json.loads(out2)
        assert body["ok"] is True and body["effective_category"] == "email"

    def test_override_bad_category_exit2(self, dbdir):
        from stopa.cli.commands.classification import cmd_classify

        _, out = _run(cmd_classify, case_id=CASE_ID, json=True)
        target_id = next(
            r["id"] for r in json.loads(out)["classifications"] if r["file_id"] == "f1"
        )
        rc, out2 = _run(
            cmd_classify,
            case_id=CASE_ID,
            json=True,
            override=str(target_id),
            category="nope",
            reason="r",
            actor=None,
        )
        assert rc == 2 and "neplatná kategorie" in out2

    def test_parser_has_classify_with_flags(self):
        from stopa.cli import build_parser

        args = build_parser().parse_args(
            ["classify", CASE_ID, "--override", "5", "--category", "email",
             "--reason", "r"]
        )
        assert args.case_id == CASE_ID and args.override == "5"
        assert args.category == "email" and args.reason == "r"


# ── Web: /api/cases/{id}/classifications… ─────────────────────────────────────


@pytest.fixture()
def client(dbdir: Path):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    return TestClient(create_app(dbdir))


class TestWebClassify:
    def test_list_empty_before_classify(self, client):
        resp = client.get(f"/api/cases/{CASE_ID}/classifications")
        assert resp.status_code == 200 and resp.json() == {"classifications": []}

    def test_classify_then_list_and_filter(self, client):
        resp = client.post(f"/api/cases/{CASE_ID}/classifications/classify")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True and body["summary"]["total_files"] == 6

        listing = client.get(f"/api/cases/{CASE_ID}/classifications").json()
        assert len(listing["classifications"]) == 6
        review_only = client.get(
            f"/api/cases/{CASE_ID}/classifications", params={"needs_review": "true"}
        ).json()
        assert len(review_only["classifications"]) == 4

    def test_override_ok_and_errors(self, client):
        client.post(f"/api/cases/{CASE_ID}/classifications/classify")
        target_id = next(
            r["id"] for r in client.get(
                f"/api/cases/{CASE_ID}/classifications").json()["classifications"]
            if r["file_id"] == "f1"
        )

        ok = client.post(
            f"/api/cases/{CASE_ID}/classifications/override",
            json={"classification_id": target_id, "category": "email",
                  "reason": "reviewer souhlasí"},
        )
        assert ok.status_code == 200 and ok.json()["classification"]["effective_category"] == "email"

        bad_cat = client.post(
            f"/api/cases/{CASE_ID}/classifications/override",
            json={"classification_id": target_id, "category": "nope", "reason": "r"},
        )
        assert bad_cat.status_code == 400 and "neplatná kategorie" in bad_cat.json()["detail"]

        missing = client.post(
            f"/api/cases/{CASE_ID}/classifications/override",
            json={"classification_id": 9999, "category": "email", "reason": "r"},
        )
        assert missing.status_code == 404

    def test_unknown_case_404(self, client):
        resp = client.get("/api/cases/missing-case/classifications")
        assert resp.status_code == 404
