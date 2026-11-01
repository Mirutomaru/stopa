"""STOPA E4 — Entity + Correlation Engine (normalizace, extrakce, 3 pravidla).

Pokrytí: kanonické tvary (tel:+E164 / email lowercase / URL host / hash hex),
extrakce z artifactů (typově specifická pole + generický sken), tři korelační
pravidla (same_contact verified, temporal_overlap inferred, hash_match verified),
determinismus nezávislý na pořadí vstupů, DB roundtrip s idempotentním re-runem,
CLI `stopa correlate` a web endpointy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from stopa.domain.correlation import (
    DEFAULT_OVERLAP_TOLERANCE,
    correlate,
    entity_id,
    hash_match_rules,
    run_correlation,
    same_contact_rules,
    temporal_overlap_rules,
)
from stopa.domain.entities import (
    collect_occurrences,
    extract_entities,
    normalize_email,
    normalize_hash,
    normalize_phone,
    normalize_url_host,
)
from stopa.models import Artifact, FileRecord

T0 = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)


def _art(aid: str, source_id: str, typ: str, title: str, details=None, ts=T0) -> Artifact:
    return Artifact(
        id=aid,
        source_id=source_id,
        artifact_type=typ,
        title=title,
        details=details or {},
        timestamp=ts,
    )


# ── normalizace (kanonické tvary) ────────────────────────────────


class TestNormalization:
    def test_phone_variants_same_canonical(self):
        """+420 777 123 456 / 00420… / (+420) 777-123-456 → jedna entita."""
        assert normalize_phone("+420 777 123 456") == "+420777123456"
        assert normalize_phone("00420777123456") == "+420777123456"
        assert normalize_phone("(+420) 777-123.456") == "+420777123456"

    def test_phone_noise_rejected(self):
        assert normalize_phone("") is None
        assert normalize_phone("12345") is None  # < 7 číslic
        assert normalize_phone("john@example.com") is None  # @ → email doména

    def test_email_lowercase_and_validation(self):
        assert normalize_email("John.Doe@Example.COM") == "john.doe@example.com"
        assert normalize_email("not-an-email") is None
        assert normalize_email("a@b") is None  # bez TLD

    def test_url_host_canonical(self):
        assert normalize_url_host("https://Example.COM/path?q=1") == "example.com"
        assert normalize_url_host("www.example.com:8443/x") == "www.example.com"
        assert normalize_url_host("example.com") == "example.com"
        assert normalize_url_host("") is None

    def test_hash_hex_lowercase(self):
        md5 = "a" * 32
        sha1 = "b" * 40
        sha256 = "C" * 64
        assert normalize_hash(md5) == md5
        assert normalize_hash(sha1.upper()) == sha1.lower()
        assert normalize_hash("SHA256:" + sha256) == sha256.lower()
        assert normalize_hash("abc") is None  # špatná délka


# ── extrakce z artifactů ─────────────────────────────────────────


class TestExtraction:
    def test_contact_phone_and_email(self):
        a = _art(
            "a1", "s1", "contact", "+420 777 123 456",
            {"mimetype": "vnd.android.cursor.item/phone_v2"},
        )
        e = extract_entities(a)
        assert ("phone", "+420777123456") in {(x.kind, x.value) for x in e}

        b = _art("a2", "s1", "contact", "John.Doe@Example.COM", {"mimetype": "email"})
        e2 = extract_entities(b)
        assert ("email", "john.doe@example.com") in {(x.kind, x.value) for x in e2}

    def test_message_handles_and_browser_host(self):
        sms = _art("a3", "s1", "sms_message", "Ahoj", {"handle": "+420 777 123 456"})
        assert ("phone", "+420777123456") in {(x.kind, x.value) for x in extract_entities(sms)}

        im = _art("a4", "s2", "imessage", "hi", {"address": "john.doe@example.com"}, ts=T0 + timedelta(hours=1))
        assert ("email", "john.doe@example.com") in {(x.kind, x.value) for x in extract_entities(im)}

        br = _art("a5", "s2", "browser_history", "https://Example.COM/x?q=1")
        assert ("url_host", "example.com") in {(x.kind, x.value) for x in extract_entities(br)}

    def test_free_text_scan(self):
        """E-mail + telefon + hash ve volném textu (title/details)."""
        a = _art(
            "a6", "s1", "note",
            "Kontakt: 00420777123456, mail john.doe@example.com",
            {"body": "hash sha256:" + "d" * 64},
        )
        got = {(x.kind, x.value) for x in extract_entities(a)}
        assert ("phone", "+420777123456") in got
        assert ("email", "john.doe@example.com") in got
        assert ("hash", "d" * 64) in got


# ── pravidlo 1: same_contact (verified) ───────────────────────────


class TestSameContact:
    def test_same_phone_two_artifacts_verified(self):
        arts = [
            _art("a1", "s1", "sms_message", "x", {"handle": "+420 777 123 456"}),
            _art("a2", "s1", "contact", "+420777123456", {"mimetype": "phone"}, ts=T0 + timedelta(minutes=5)),
        ]
        occ = collect_occurrences(arts)
        res = same_contact_rules(occ)
        assert len(res) == 1
        r = res[0]
        assert r.relation == "same_contact" and r.confidence == "verified"
        assert r.entity_a == r.entity_b == entity_id("phone", "+420777123456")
        # evidence list — oba artifacty, dohledatelnost
        ev_ids = {e["artifact_id"] for e in r.evidence}
        assert ev_ids == {"a1", "a2"}

    def test_single_artifact_no_rule(self):
        arts = [_art("a1", "s1", "sms_message", "x", {"handle": "+420 777 123 456"})]
        assert same_contact_rules(collect_occurrences(arts)) == []


# ── pravidlo 2: temporal_overlap (inferred) ───────────────────────


class TestTemporalOverlap:
    def _occ(self, value, source, ts):
        return collect_occurrences([_art("a", source, "sms_message", "", {"handle": value}, ts=ts)])

    def test_overlapping_windows_inferred(self):
        occ = self._occ("+420777123456", "s1", T0) + self._occ("john.doe@example.com", "s2", T0 + timedelta(minutes=10))
        res = temporal_overlap_rules(occ)
        assert len(res) == 1
        r = res[0]
        assert r.relation == "temporal_overlap" and r.confidence == "inferred"
        ids = {r.entity_a, r.entity_b}
        assert ids == {"tel:+420777123456", "email:john.doe@example.com"}

    def test_disjoint_windows_no_rule(self):
        occ = self._occ("+420777123456", "s1", T0) + self._occ("john.doe@example.com", "s2", T0 + timedelta(hours=5))
        assert temporal_overlap_rules(occ) == []

    def test_same_source_no_rule(self):
        occ = self._occ("+420777123456", "s1", T0) + self._occ("john.doe@example.com", "s1", T0 + timedelta(minutes=5))
        assert temporal_overlap_rules(occ) == []

    def test_tolerance_boundary(self):
        """Přesně na hranici tolerance (30 min) → překryv; o minutu dál → ne."""
        occ = self._occ("+420777123456", "s1", T0) + self._occ("john.doe@example.com", "s2", T0 + DEFAULT_OVERLAP_TOLERANCE)
        assert len(temporal_overlap_rules(occ)) == 1
        occ2 = self._occ("+420777123456", "s1", T0) + self._occ("john.doe@example.com", "s2", T0 + DEFAULT_OVERLAP_TOLERANCE + timedelta(minutes=1))
        assert temporal_overlap_rules(occ2) == []


# ── pravidlo 3: hash_match (verified) ─────────────────────────────


class TestHashMatch:
    def test_same_sha256_two_sources_verified(self):
        files = [
            FileRecord(id="f1", source_id="s1", rel_path="a/x.bin", name="x.bin", size_bytes=10, sha256="e" * 64),
            FileRecord(id="f2", source_id="s2", rel_path="b/x.bin", name="x.bin", size_bytes=10, sha256="E" * 64),
        ]
        res = hash_match_rules(files)
        assert len(res) == 1
        r = res[0]
        h = "e" * 64
        assert r.relation == "hash_match" and r.confidence == "verified"
        assert r.entity_a == r.entity_b == f"hash:{h}"
        ev_files = {e["file_id"] for e in r.evidence}
        assert ev_files == {"f1", "f2"}

    def test_same_source_only_no_rule(self):
        files = [
            FileRecord(id="f1", source_id="s1", rel_path="a/x.bin", name="x.bin", size_bytes=10, sha256="e" * 64),
            FileRecord(id="f2", source_id="s1", rel_path="b/x.bin", name="x.bin", size_bytes=10, sha256="e" * 64),
        ]
        assert hash_match_rules(files) == []


# ── determinismus + DB roundtrip ──────────────────────────────────


class TestDeterminismAndDb:
    def _arts(self):
        return [
            _art("a1", "s1", "sms_message", "x", {"handle": "+420 777 123 456"}, ts=T0),
            _art("a2", "s1", "contact", "+420777123456", {"mimetype": "phone"}, ts=T0 + timedelta(minutes=5)),
            _art("a3", "s2", "imessage", "y", {"address": "john.doe@example.com"}, ts=T0 + timedelta(minutes=10)),
        ]

    def test_correlate_deterministic_regardless_of_input_order(self):
        a = self._arts()
        b = list(reversed(a))
        r1 = correlate(collect_occurrences(a), [])
        r2 = correlate(collect_occurrences(b), [])
        assert [ (x.entity_a, x.entity_b, x.relation, x.confidence) for x in r1 ] == \
               [ (x.entity_a, x.entity_b, x.relation, x.confidence) for x in r2 ]
        # i evidence listy deterministické
        assert [list(x.evidence) for x in r1] == [list(x.evidence) for x in r2]

    def test_run_correlation_db_roundtrip_and_rerun(self, tmp_path: Path):
        from stopa.data.db import CaseDB
        from stopa.models import Case, EvidenceSource, new_id

        db = CaseDB(tmp_path / "case-e4.db")
        cid = "case-e4"
        db.add_case(Case(id=cid, name="E4", created_at=T0, examiner="T"))
        s1 = EvidenceSource(id=new_id("src"), case_id=cid, kind="folder", path="/a", size_bytes=0, added_at=T0)
        s2 = EvidenceSource(id=new_id("src"), case_id=cid, kind="folder", path="/b", size_bytes=0, added_at=T0)
        db.add_source(s1)
        db.add_source(s2)
        # same_contact: telefon ve 2 artifactech; email napříč zdroji
        arts = [
            _art("a1", s1.id, "sms_message", "x", {"handle": "+420 777 123 456"}, ts=T0),
            _art("a2", s1.id, "contact", "+420777123456", {"mimetype": "phone"}, ts=T0 + timedelta(minutes=5)),
            _art("a3", s1.id, "sms_message", "y", {"handle": "john.doe@example.com"}, ts=T0),
            _art("a4", s2.id, "imessage", "z", {"address": "John.Doe@Example.COM"}, ts=T0 + timedelta(minutes=10)),
        ]
        for a in arts:
            db.upsert_artifact(a)

        summary = run_correlation(db, cid)
        assert summary["entities"] >= 2
        rels = {c["relation"] for c in db.list_correlations(cid)}
        assert "same_contact" in rels and "hash_match" not in rels

        # re-run = clear + insert → stejný počet (idempotence)
        summary2 = run_correlation(db, cid)
        assert summary2["correlations_total"] == summary["correlations_total"]
        assert len(db.list_correlations(cid)) == summary["correlations_total"]

        # entities: first_seen/last_seen agregace přes MIN/MAX (re-run s jiným časem)
        ent = {e["value"]: e for e in db.list_entities(cid)}
        phone = ent["+420777123456"]
        assert phone["first_seen"] is not None and phone["last_seen"] is not None
        assert phone["first_seen"] <= phone["last_seen"]
        db.close()

    def test_entity_upsert_first_last_seen_aggregation(self, tmp_path: Path):
        from stopa.data.db import CaseDB
        from stopa.models import Case

        db = CaseDB(tmp_path / "case-e4b.db")
        cid = "case-e4b"
        db.add_case(Case(id=cid, name="E4b", created_at=T0, examiner="T"))
        # první běh: 10:00–10:05; druhý běh přidá 09:30 a 10:20 → MIN/MAX
        db.upsert_entities(cid, [("phone", "+420777123456", "+420 777 123 456", T0.isoformat(), (T0 + timedelta(minutes=5)).isoformat())])
        db.upsert_entities(cid, [("phone", "+420777123456", None, (T0 - timedelta(minutes=30)).isoformat(), (T0 + timedelta(minutes=20)).isoformat())])
        rows = db.list_entities(cid)
        assert len(rows) == 1  # UNIQUE (case_id, kind, value_normalized)
        e = rows[0]
        assert e["first_seen"] == (T0 - timedelta(minutes=30)).isoformat()
        assert e["last_seen"] == (T0 + timedelta(minutes=20)).isoformat()
        assert e["raw_value"] == "+420 777 123 456"  # zachováno z prvního běhu
        db.close()


# ── CLI stopa correlate ───────────────────────────────────────────


class TestCliCorrelate:
    def test_cli_correlate_and_audit(self, tmp_path: Path, monkeypatch):
        from stopa import cli
        from stopa.data.db import CaseDB
        from stopa.models import EvidenceSource, new_id

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        assert cli.main(["case", "new", "E4 CLI"]) == 0
        case_id = next(iter(list(tmp_path.glob("*.db")))).stem

        db = CaseDB(tmp_path / f"{case_id}.db")
        s1 = EvidenceSource(id=new_id("src"), case_id=case_id, kind="folder", path="/a", size_bytes=0, added_at=T0)
        db.add_source(s1)
        arts = [
            _art("c1", s1.id, "sms_message", "x", {"handle": "+420 777 123 456"}, ts=T0),
            _art("c2", s1.id, "contact", "+420777123456", {"mimetype": "phone"}, ts=T0 + timedelta(minutes=5)),
        ]
        for a in arts:
            db.upsert_artifact(a)
        db.close()

        assert cli.main(["correlate", case_id]) == 0
        db = CaseDB(tmp_path / f"{case_id}.db")
        cors = db.list_correlations(case_id)
        assert len(cors) == 1 and cors[0]["relation"] == "same_contact"
        # audit log — explicitní krok je zaznamenán (provenience)
        actions = [e["action"] for e in db.list_audit_log()]
        assert "correlation_run" in actions
        run_entry = next(e for e in db.list_audit_log() if e["action"] == "correlation_run")
        assert run_entry["details"]["correlations_total"] == 1
        db.close()


# ── web endpointy ─────────────────────────────────────────────────


class TestWebCorrelate:
    def test_correlate_and_list_endpoints(self, tmp_path: Path):
        from fastapi.testclient import TestClient

        from stopa.data.db import CaseDB
        from stopa.models import EvidenceSource, new_id
        from stopa.web.app import create_app

        app = create_app(db_dir=tmp_path)
        with TestClient(app) as c:
            r = c.post("/api/cases", json={"name": "E4 web", "examiner": "Z"})
            assert r.status_code == 201, r.text
            case_id = r.json()["id"]

            db = CaseDB(tmp_path / f"{case_id}.db")
            s1 = EvidenceSource(id=new_id("src"), case_id=case_id, kind="folder", path="/a", size_bytes=0, added_at=T0)
            db.add_source(s1)
            arts = [
                _art("w1", s1.id, "sms_message", "x", {"handle": "+420 777 123 456"}, ts=T0),
                _art("w2", s1.id, "contact", "+420777123456", {"mimetype": "phone"}, ts=T0 + timedelta(minutes=5)),
            ]
            for a in arts:
                db.upsert_artifact(a)
            db.close()

            r = c.post(f"/api/cases/{case_id}/correlate")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["correlations_total"] >= 1
            assert body["by_relation"].get("same_contact", 0) >= 1

            r = c.get(f"/api/cases/{case_id}/correlations")
            assert r.status_code == 200
            cors = r.json()
            assert any(x["relation"] == "same_contact" for x in cors)
            # evidence listy dohledatelné (artifact id + detail)
            sc = next(x for x in cors if x["relation"] == "same_contact")
            assert {e["artifact_id"] for e in sc["evidence"]} == {"w1", "w2"}

            r = c.get(f"/api/cases/{case_id}/entities")
            assert r.status_code == 200
            ents = r.json()
            assert any(e["kind"] == "phone" and e["value"] == "+420777123456" for e in ents)
