"""STOPA P0 Intelligence I3 — Entity Resolution 2.0 (testy).

Pokrytí:
- čtyři úrovně confidence vztahů + mapování starých hodnot (verified/inferred),
- normalizace platformních účtů (WhatsApp JID → wa:+E164, skype:/telegram: handle),
- klasifikace classify_value() → nový druh entity ``user_account``,
- heuristická detekce duplicitních entit (merge candidates) + determinismus,
- časové rozmezí vztahů first_seen/last_seen (same_contact + temporal_overlap),
- migrace case DB schéma v10 → v11 (CHECK entities/correlations, bez ztráty dat),
- web endpoint ``GET /api/cases/{id}/entities/merge-candidates``.

Vše plně offline — žádné IO kromě SQLite v tmp_path a FastAPI TestClientu.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from stopa.data.db import SCHEMA_VERSION, CaseDB
from stopa.domain.correlation import correlate
from stopa.domain.entities import EntityOccurrence, classify_value, normalize_phone
from stopa.domain.entity_resolution import (
    CONFIDENCE_LEVELS,
    find_merge_candidates,
    is_platform_account,
    is_whatsapp_jid,
    map_legacy_confidence,
    normalize_user_account,
)

T0 = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)


# ── 1) čtyři úrovně confidence + legacy mapping ───────────────────


class TestConfidenceLevels:
    def test_four_levels_defined(self):
        assert CONFIDENCE_LEVELS == ("confirmed", "strong_candidate", "possible", "unverified")

    def test_legacy_verified_maps_to_confirmed(self):
        assert map_legacy_confidence("verified") == "confirmed"

    def test_legacy_inferred_maps_to_possible(self):
        assert map_legacy_confidence("inferred") == "possible"

    def test_new_levels_idempotent(self):
        for lvl in CONFIDENCE_LEVELS:
            assert map_legacy_confidence(lvl) == lvl

    def test_unknown_falls_back_to_unverified(self):
        assert map_legacy_confidence("bogus") == "unverified"
        assert map_legacy_confidence(None) == "unverified"


# ── 2) normalizace platformních účtů (kind=user_account) ───────────


class TestUserAccountNormalization:
    def test_whatsapp_jid_to_e164(self):
        """+420 777 123 456@c.us → wa:+E164 (telefon se normalizuje, @c.us odřízne)."""
        expected = "wa:" + normalize_phone("+420 777 123 456")
        assert normalize_user_account("+420 777 123 456@c.us") == expected

    def test_whatsapp_jid_variants_same_canonical(self):
        """Různé tvary JID (mezery, 00 prefix, velká @c.US) → jedna entita."""
        base = normalize_user_account("+420 777 123 456@c.us")
        assert normalize_user_account("00420777123456@c.US") == base
        assert normalize_user_account("(+420) 777-123.456@c.us") == base

    def test_is_whatsapp_jid(self):
        assert is_whatsapp_jid("+420 777 123 456@c.us") is True
        assert is_whatsapp_jid("jan.novak@gmail.com") is False
        assert is_whatsapp_jid(None) is False

    def test_scheme_handle_lowercased(self):
        assert normalize_user_account("Skype:Jan.Novak") == "skype:jan.novak"
        assert normalize_user_account("Telegram:User_123") == "telegram:user_123"

    def test_is_platform_account(self):
        assert is_platform_account("+420 777 123 456@c.us") is True
        assert is_platform_account("skype:jan.novak") is True
        # čistý telefon / e-mail → NE platformní účet (řeší je normalize_phone/email)
        assert is_platform_account("+420 777 123 456") is False
        assert is_platform_account("jan.novak@gmail.com") is False

    def test_short_noise_rejected(self):
        assert normalize_user_account("a") is None  # < 2 znaky
        assert normalize_user_account("") is None


# ── 3) classify_value → user_account ───────────────────────────────


class TestClassifyValue:
    def test_jid_classified_as_user_account(self):
        e = classify_value("+420 777 123 456@c.us")
        assert e is not None and e.kind == "user_account"
        assert e.value == normalize_user_account("+420 777 123 456@c.us")

    def test_plain_phone_still_phone(self):
        e = classify_value("+420 777 123 456")
        assert e is not None and e.kind == "phone"

    def test_email_priority_over_phone(self):
        e = classify_value("jan.novak@gmail.com")
        assert e is not None and e.kind == "email"


# ── 4) detekce duplicitních entit (merge candidates) ───────────────


class TestMergeCandidates:
    def test_phone_same_national_suffix(self):
        """Dva telefony se stejným posledních-7 číslic → kandidát na merge."""
        rows = [
            {"kind": "phone", "value": "+420777123456"},
            {"kind": "phone", "value": "+490777123456"},  # stejné posledních 7 číslic
        ]
        out = find_merge_candidates(rows)
        assert len(out) == 1
        m = out[0]
        assert m.kind == "phone"
        assert {m.value_a, m.value_b} == {"+420777123456", "+490777123456"}
        assert "národní číslo" in m.reason

    def test_email_same_local_part(self):
        """Stejný local-part na různých doménách → kandidát na merge."""
        rows = [
            {"kind": "email", "value": "jan.novak@gmail.com"},
            {"kind": "email", "value": "jan.novak@outlook.com"},
        ]
        out = find_merge_candidates(rows)
        assert len(out) == 1
        m = out[0]
        assert m.kind == "email"
        assert {m.value_a, m.value_b} == {"jan.novak@gmail.com", "jan.novak@outlook.com"}
        assert "local-part" in m.reason

    def test_no_false_positive_different_numbers(self):
        rows = [
            {"kind": "phone", "value": "+420777123456"},
            {"kind": "phone", "value": "+420777999888"},  # jiné posledních 7
        ]
        assert find_merge_candidates(rows) == []

    def test_deterministic_order_independent_of_input(self):
        a = [
            {"kind": "email", "value": "jan.novak@outlook.com"},
            {"kind": "phone", "value": "+490777123456"},
            {"kind": "email", "value": "jan.novak@gmail.com"},
            {"kind": "phone", "value": "+420777123456"},
        ]
        b = list(reversed(a))
        ra, rb = find_merge_candidates(a), find_merge_candidates(b)
        assert [(m.kind, m.value_a, m.value_b) for m in ra] == [
            (m.kind, m.value_a, m.value_b) for m in rb
        ]

    def test_empty_and_noise_rows_ignored(self):
        rows = [{"kind": "phone", "value": ""}, {"kind": "hash", "value": "abc"}, {}]
        assert find_merge_candidates(rows) == []


# ── 5) časové rozmezí vztahů (first_seen / last_seen) ───────────────


class TestTimeRanges:
    def _occ(self, value, source, artifact, ts):
        return EntityOccurrence(
            kind="phone", value=value, source_id=source, artifact_id=artifact, ts_utc=ts
        )

    def test_same_contact_time_range(self):
        """same_contact nese first/last seen z timestampů výskytů."""
        o1 = self._occ("+420777123456", "s1", "a1", T0)
        o2 = self._occ("+420777123456", "s2", "a2", T0 + timedelta(hours=2))
        res = [r for r in correlate([o1, o2], []) if r.relation == "same_contact"]
        assert len(res) == 1
        assert res[0].first_seen == T0.isoformat()
        assert res[0].last_seen == (T0 + timedelta(hours=2)).isoformat()

    def test_same_contact_no_timestamps_none(self):
        o1 = self._occ("+420777123456", "s1", "a1", None)
        o2 = self._occ("+420777123456", "s2", "a2", None)
        res = [r for r in correlate([o1, o2], []) if r.relation == "same_contact"]
        assert len(res) == 1 and res[0].first_seen is None and res[0].last_seen is None

    def test_temporal_overlap_union_range(self):
        """temporal_overlap nese sjednocení časových oken obou entit."""
        # entita X na zdroji s1: okno [T0, T0+2h] (dva výskyty)
        xa = self._occ("+420777123456", "s1", "a1", T0)
        xb = self._occ("+420777123456", "s1", "a9", T0 + timedelta(hours=2))
        # entita Y na zdroji s2: okno [T0+1h, T0+3h] (překrývá se)
        ya = EntityOccurrence(kind="email", value="x@y.cz", source_id="s2", artifact_id="b1", ts_utc=T0 + timedelta(hours=1))
        yb = EntityOccurrence(kind="email", value="x@y.cz", source_id="s2", artifact_id="b9", ts_utc=T0 + timedelta(hours=3))
        res = [r for r in correlate([xa, xb, ya, yb], []) if r.relation == "temporal_overlap"]
        assert len(res) == 1
        # sjednocení oken: min(T0, T0+1h)=T0 … max(T0+2h, T0+3h)=T0+3h
        assert res[0].first_seen == T0.isoformat()
        assert res[0].last_seen == (T0 + timedelta(hours=3)).isoformat()


# ── 6) migrace case DB schéma v10 → v11 ─────────────────────────────

OLD_ENTITIES_V10 = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('phone', 'email', 'url_host', 'hash')),
    value_normalized TEXT NOT NULL,
    raw_value TEXT,
    first_seen TEXT,
    last_seen TEXT,
    UNIQUE (case_id, kind, value_normalized)
);"""

OLD_CORRELATIONS_V10 = """
CREATE TABLE IF NOT EXISTS correlations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    entity_a TEXT NOT NULL,
    entity_b TEXT NOT NULL,
    relation TEXT NOT NULL CHECK (relation IN ('same_contact', 'temporal_overlap', 'hash_match')),
    confidence TEXT NOT NULL DEFAULT 'inferred' CHECK (confidence IN ('verified', 'inferred')),
    evidence_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);"""


def _make_v10_db(path: Path) -> None:
    """Vytvoří starou case DB (schéma v10) se starými CHECKy + daty."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema_version', '10');
        CREATE TABLE cases (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
            examiner TEXT, notes TEXT, timezone_name TEXT DEFAULT 'Europe/Prague'
        );
        INSERT INTO cases (id, name, created_at) VALUES ('c1', 'old case', '2026-01-01T00:00:00+00:00');
        """
    )
    conn.executescript(OLD_ENTITIES_V10)
    conn.executescript(OLD_CORRELATIONS_V10)
    # stará data — musí přežít migraci beze změny (kromě confidence remapování)
    conn.execute(
        "INSERT INTO entities (id, case_id, kind, value_normalized, raw_value)"
        " VALUES ('e1', 'c1', 'phone', '+420777123456', '+420 777 123 456')"
    )
    conn.execute(
        "INSERT INTO correlations (case_id, entity_a, entity_b, relation, confidence,"
        " evidence_json, created_at) VALUES"
        " ('c1', 'tel:+420777123456', 'tel:+420777123456', 'same_contact', 'verified', '[]',"
        "  '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO correlations (case_id, entity_a, entity_b, relation, confidence,"
        " evidence_json, created_at) VALUES"
        " ('c1', 'tel:+420777123456', 'email:x@y.cz', 'temporal_overlap', 'inferred', '[]',"
        "  '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()


class TestMigrationV10ToV11:
    def test_old_db_migrates_up(self, tmp_path: Path):
        """Stará DB (v10) → open → v11, confidence remapováno, data zachována."""
        p = tmp_path / "old.db"
        _make_v10_db(p)

        d = CaseDB(p)
        try:
            assert d.schema_version() == SCHEMA_VERSION == 11
            # confidence remap: verified→confirmed, inferred→possible
            cors = {c["relation"]: c["confidence"] for c in d.list_correlations("c1")}
            assert cors["same_contact"] == "confirmed"
            assert cors["temporal_overlap"] == "possible"
            # nové sloupce existují (None — staré řádky je neměly)
            row = d.conn.execute(
                "SELECT first_seen, last_seen FROM correlations WHERE relation='same_contact'"
            ).fetchone()
            assert row["first_seen"] is None and row["last_seen"] is None
            # entity data zachována + nový CHECK přijme user_account
            ents = d.list_entities("c1")
            assert any(e["kind"] == "phone" for e in ents)
            n = d.upsert_entities(
                "c1", [("user_account", "wa:+420777123456", "+420 777 123 456@c.us", None, None)]
            )
            assert n >= 1
            kinds = {e["kind"] for e in d.list_entities("c1")}
            assert "user_account" in kinds
        finally:
            d.close()

    def test_migration_idempotent(self, tmp_path: Path):
        """Druhé otevření už v11 DB → migrace no-op, data stabilní."""
        p = tmp_path / "old.db"
        _make_v10_db(p)
        d = CaseDB(p)
        d.close()
        d2 = CaseDB(p)
        try:
            assert d2.schema_version() == 11
            cors = {c["relation"]: c["confidence"] for c in d2.list_correlations("c1")}
            assert cors["same_contact"] == "confirmed"
            assert cors["temporal_overlap"] == "possible"
        finally:
            d2.close()


# ── 7) web endpoint merge-candidates ───────────────────────────────


class TestWebMergeCandidates:
    def test_endpoint_returns_pairs(self, tmp_path: Path):
        from stopa.web.app import create_app

        app = create_app(db_dir=tmp_path)
        with TestClient(app) as c:
            r = c.post("/api/cases", json={"name": "I3 web", "examiner": "Z"})
            assert r.status_code == 201, r.text
            case_id = r.json()["id"]

            db = CaseDB(tmp_path / f"{case_id}.db")
            # dva e-maily se stejným local-partem na různých doménách → merge kandidát
            db.upsert_entities(
                case_id,
                [
                    ("email", "jan.novak@gmail.com", "Jan.Novak@Gmail.COM", None, None),
                    ("email", "jan.novak@outlook.com", "jan.novak@outlook.com", None, None),
                ],
            )
            db.close()

            r = c.get(f"/api/cases/{case_id}/entities/merge-candidates")
            assert r.status_code == 200, r.text
            body = r.json()
            assert len(body) == 1
            m = body[0]
            assert m["kind"] == "email"
            assert {m["value_a"], m["value_b"]} == {"jan.novak@gmail.com", "jan.novak@outlook.com"}
            assert "local-part" in m["reason"]

    def test_endpoint_empty_when_no_duplicates(self, tmp_path: Path):
        from stopa.web.app import create_app

        app = create_app(db_dir=tmp_path)
        with TestClient(app) as c:
            r = c.post("/api/cases", json={"name": "I3 web empty", "examiner": "Z"})
            case_id = r.json()["id"]
            db = CaseDB(tmp_path / f"{case_id}.db")
            db.upsert_entities(case_id, [("email", "solo@example.com", None, None, None)])
            db.close()
            r = c.get(f"/api/cases/{case_id}/entities/merge-candidates")
            assert r.status_code == 200 and r.json() == []
