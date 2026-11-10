"""F1.4 — Anti-Forensics detekce (ROADMAP V2 Fáze 1).

Pokrývá:
  * domain ``anti_forensics`` — timestomping (future mtime, nemožný pořad,
    bulk touch), log clearing (EVTX 1102 + mezery v record numbers),
    USN truncation (hustota + delete podíl), hidden partitions (MBR),
    LSB steganografie (PIL lazy), tool signatures, image integrity.
  * CLI E2E — seedované artefakty v case DB → ``antiforensics-scan`` →
    artefakty ``antiforensics/<check>`` + timeline alerty; idempotentní
    re-run (STOPA_DB_DIR, offline).

Offline: žádné reálné obrazy/logy — vše syntetické in-mem.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from stopa.domain import anti_forensics as af

# ════════════════════════ helpers: syntetické záznamy ═════════════════════

REF = "2026-11-10T12:00:00+00:00"  # referenční čas pro timestomping


def _file(path, mtime=None, ctime=None, atime=None):
    return {"path": path, "name": Path(path).name,
            "mtime": mtime, "ctime": ctime, "atime": atime}


# ════════════════════════ 1. Timestomping ═════════════════════════════════


class TestTimestomping:
    def test_future_mtime_flagged(self):
        fs = [_file("/a.txt", mtime="2030-01-01T00:00:00+00:00")]
        hits = af.detect_timestomping(fs, reference_time=REF)
        assert len(hits) == 1 and hits[0].check == "timestomping"

    def test_mtime_before_ctime_flagged(self):
        fs = [_file("/b.txt", mtime="2026-01-01T00:00:00+00:00",
                    ctime="2026-02-01T00:00:00+00:00")]
        hits = af.detect_timestomping(fs, reference_time=REF)
        assert any("nemožný pořad" in h.description for h in hits)

    def test_bulk_touch_same_mace(self):
        fs = [_file(f"/bulk/f{i}.txt", mtime="2026-11-01T08:00:00+00:00",
                    ctime="2026-11-01T08:00:00+00:00",
                    atime="2026-11-01T08:00:00+00:00") for i in range(5)]
        hits = af.detect_timestomping(fs, reference_time=REF)
        bulk = [h for h in hits if h.evidence.get("file_count") == 5]
        assert len(bulk) == 1

    def test_clean_files_no_findings(self):
        # každý soubor má UNIKÁTNÍ MACE — jinak by spustil bulk-touch detekce
        fs = []
        for i in range(6):
            base = datetime(2026, 10, 1, 8, 0) + timedelta(hours=i * 3)
            m = (base + timedelta(minutes=5)).isoformat()
            c = base.isoformat()
            a = (base + timedelta(days=1)).isoformat()
            fs.append(_file(f"/ok/f{i}.txt", mtime=m, ctime=c, atime=a))
        assert af.detect_timestomping(fs, reference_time=REF) == []


# ════════════════════════ 2. Log clearing (EVTX) ══════════════════════════


class TestLogClearing:
    def test_event_1102_flagged(self):
        evs = [{"event_id": 1102, "record_id": 500,
                "timestamp": "2026-11-09T23:00:00+00:00"}]
        hits = af.detect_log_clearing(evs)
        assert len(hits) == 1 and hits[0].check == "log_clearing"

    def test_record_number_gap_flagged(self):
        evs = [{"event_id": 4624, "record_id": n} for n in range(1, 50)]
        # mezera: 50..60 chybí → 50+ záznamů → high
        evs.append({"event_id": 4672, "record_id": 101})
        hits = af.detect_log_clearing(evs)
        gap = [h for h in hits if h.evidence.get("gap_count")]
        assert len(gap) == 1 and gap[0].evidence["missing_total"] >= 50

    def test_continuous_records_no_findings(self):
        evs = [{"event_id": 4624, "record_id": n} for n in range(1, 30)]
        assert af.detect_log_clearing(evs) == []


# ════════════════════════ 3. USN truncation ═══════════════════════════════


class TestUsnTruncation:
    def test_low_density_span_flagged(self):
        # 20 záznamů rozprostřených po obrovském spanu → nízká hustota
        recs = [{"usn": i * 100, "reason": "create_file"} for i in range(20)]
        hits = af.detect_usn_truncation(recs)
        assert any(h.check == "usn_truncation" and "hustota" in h.description
                   for h in hits)

    def test_high_delete_ratio_flagged(self):
        recs = ([{"usn": i, "reason": "delete_file"} for i in range(30)]
                + [{"usn": 100 + i, "reason": "create_file"} for i in range(5)])
        hits = af.detect_usn_truncation(recs)
        dr = [h for h in hits if "delete" in h.description]
        assert len(dr) == 1 and dr[0].evidence["delete_ratio"] > 0.8

    def test_small_journal_not_flagged(self):
        recs = [{"usn": i, "reason": "create_file"} for i in range(15)]
        assert af.detect_usn_truncation(recs) == []


# ═══════════════════ 4. Hidden partitions / MBR table ======================


def _mbr(signature: int = 0x55AA, entry: bytes | None = None) -> bytes:
    buf = bytearray(512)
    if entry is not None:
        buf[446:446 + len(entry)] = entry[:16]
    sig_bytes = signature.to_bytes(2, "little")
    buf[510:512] = sig_bytes
    return bytes(buf)


class TestPartitionTable:
    def test_missing_signature_flagged(self):
        hits = af.validate_partition_table(_mbr(signature=0x0000))
        assert len(hits) == 1 and hits[0].check == "hidden_partition"

    def test_valid_mbr_empty_entries_flagged(self):
        hits = af.validate_partition_table(_mbr())
        assert len(hits) == 1 and "prázdná tabulka" in hits[0].description

    def test_valid_mbr_with_entry_ok(self):
        entry = b"\x02\x00\x00\x00" + b"\xAA" * 13  # aktivní, typ NTFS
        assert af.validate_partition_table(_mbr(entry=entry)) == []

    def test_virtual_format_no_mbr_expected(self):
        # .vhd/.vhdx nemají MBR — chybějící signatura není nález
        hits = af.validate_partition_table(b"\x00" * 512, image_ext="vhdx")
        assert hits == []

    def test_short_header_ignored(self):
        assert af.validate_partition_table(b"\x00" * 16) == []


# ════════════════════ 5. LSB steganografie (PIL) ===========================


@pytest.fixture()
def flat_odd_png(tmp_path: Path):
    """PNG se všemi pixely lichou hodnotou → LSB plně vychýlené."""
    from PIL import Image

    img = Image.new("L", (64, 64), color=3)  # 3 je liché → LSB=1
    p = tmp_path / "flat.png"
    img.save(p)
    return p


@pytest.fixture()
def noisy_png(tmp_path: Path):
    """PNG s reálným šumem (seeded) — vyvážená LSB, žádný nález."""
    import random

    from PIL import Image

    rng = random.Random(42)
    img = Image.new("L", (64, 64))
    img.putdata([rng.randrange(256) for _ in range(64 * 64)])
    p = tmp_path / "noise.png"
    img.save(p)
    return p


class TestLsbStego:
    def test_flat_odd_png_flagged(self, flat_odd_png):
        hits = af.detect_lsb_steganography(str(flat_odd_png))
        assert len(hits) == 1 and hits[0].check == "steganography"
        assert hits[0].evidence["lsb_skew"] >= 0.9

    def test_noisy_png_not_flagged(self, noisy_png):
        assert af.detect_lsb_steganography(str(noisy_png)) == []

    def test_missing_path_returns_empty(self):
        assert af.detect_lsb_steganography(None) == []
        assert af.detect_lsb_steganography("/neexistuje/x.png") == []


# ═══════════════════ 6. Tool signatures + image integrity ==================


class TestToolSignatures:
    def test_exact_signature_high(self):
        hits = af.detect_tool_signatures([_file("/tools/fslint.exe")])
        assert len(hits) == 1 and hits[0].severity == "high"

    def test_substring_medium(self):
        hits = af.detect_tool_signatures([_file("/tmp/my_ccleaner_log.txt")])
        assert len(hits) == 1 and hits[0].severity == "medium"

    def test_clean_names_no_findings(self):
        fs = [_file(f"/docs/report{i}.pdf") for i in range(3)]
        assert af.detect_tool_signatures(fs) == []


class TestImageIntegrity:
    def test_truncated_image_flagged(self, tmp_path: Path):
        p = tmp_path / "disk.img"
        p.write_bytes(b"\x00" * 100)
        hits = af.validate_image_header(str(p), p.stat().st_size)
        assert len(hits) == 1 and hits[0].check == "image_integrity"

    def test_vmdk_bad_magic_flagged(self, tmp_path: Path):
        p = tmp_path / "vm.vmdk"
        p.write_bytes(b"\x00" * 2048)  # žádné KDMV magic
        hits = af.validate_image_header(str(p), p.stat().st_size)
        assert len(hits) == 1 and hits[0].evidence["expected_format"] == "vmdk"

    def test_vmdk_valid_magic_ok(self, tmp_path: Path):
        p = tmp_path / "vm.vmdk"
        p.write_bytes(b"KDMV" + b"\x00" * 2044)
        assert af.validate_image_header(str(p), p.stat().st_size) == []


# ════════════════════ 7. Risk score + orchestrátor =========================


class TestOrchestrator:
    def test_empty_inputs_clean_report(self):
        rep = af.detect_anti_forensics(reference_time=REF)
        assert rep["findings_count"] == 0
        assert rep["risk_score"] == 0.0
        assert set(rep) >= {"findings_count", "risk_score", "checks_run",
                            "by_check"}

    def test_all_checks_aggregated(self, flat_odd_png):
        fs = [_file("/t/fslint.exe", mtime="2030-01-01T00:00:00+00:00")]
        evs = [{"event_id": 1102, "record_id": 500}]
        recs = ([{"usn": i, "reason": "delete_file"} for i in range(30)]
                + [{"usn": 100 + i, "reason": "create_file"} for i in range(5)])
        rep = af.detect_anti_forensics(files=fs, events=evs, usn_records=recs,
                                       stego_paths=[str(flat_odd_png)],
                                       reference_time=REF)
        assert set(rep["by_check"]) >= {"timestomping", "log_clearing",
                                        "usn_truncation", "steganography",
                                        "tool_signature"}
        # 4×high + stego medium → risk ≈ 0.34 (formula 1−0.9^acc)
        assert rep["risk_score"] > 0.3

    def test_risk_score_bounds(self):
        assert af.risk_score([]) == 0.0
        crits = [af.Finding(check="x", severity="critical", description="d")
                 for _ in range(20)]
        assert af.risk_score(crits) <= 1.0


# ════════════════════ 8. CLI E2E (seedované artefakty → case DB) ===========


@pytest.fixture()
def af_case(tmp_path: Path, monkeypatch):
    """Syntetický případ se stopy maskování — vše offline."""
    from stopa.data.db import CaseDB
    from stopa.models import Artifact, Case, EvidenceSource, FileRecord

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    case = Case(name="F1.4 E2E", examiner="Tester")
    db = CaseDB(str(tmp_path / f"{case.id}.db"))
    try:
        db.add_case(case)
        src = EvidenceSource(case_id=case.id, kind="folder", path="/evidence/case1")
        db.add_source(src)

        # timestomping — mtime v budoucnosti (vůči now())
        fut = datetime.now(UTC) + timedelta(days=30)
        rec_t = FileRecord(source_id=src.id, rel_path="stomp.txt", name="stomp.txt",
                           size_bytes=10, mtime=fut, ctime=fut - timedelta(hours=1),
                           atime=fut)
        f_t = db.upsert_file(rec_t)

        # tool signature — název známé utility
        rec_tool = FileRecord(source_id=src.id, rel_path="tools/fslint.exe",
                              name="fslint.exe", size_bytes=1024)
        f_tool = db.upsert_file(rec_tool)

        # log clearing + USN truncation — batch zápis přes reálný pipeline
        # pattern (replace_artifacts_for_file); per-record upsert by deduplikoval
        # na (source_id, artifact_type, rel_path) a sbalil vše na 1 záznam.

        def _mk(atype: str, title: str, details: dict) -> Artifact:
            return Artifact(source_id=src.id, file_id=f_t, rel_path="stomp.txt",
                            artifact_type=atype, title=title, details=details,
                            timestamp=datetime.now(UTC), parser_version="test")

        # EVTX — Event ID 1102 + mezera v record numbers (9..60 chybí → 52)
        evtx_arts = [_mk("event_log_entry", "Security ID 1102",
                         {"record_number": 5, "event_id": 1102})]
        for n in (6, 7, 8):
            evtx_arts.append(_mk("event_log_entry", f"Log rec {n}",
                                 {"record_number": n, "event_id": 4624}))
        for n in (61, 62):
            evtx_arts.append(_mk("event_log_entry", f"Log rec {n}",
                                 {"record_number": n, "event_id": 4672}))

        # USN — vysoký podíl delete (30/35 = ~86 % → high)
        usn_arts: list[Artifact] = []
        for i in range(30):
            a = _mk("usn_record", f"USN {i}: delete_file", {"reason": "delete_file"})
            a.file_id, a.rel_path = f_tool, "tools/fslint.exe"
            usn_arts.append(a)
        for i in range(5):
            a = _mk("usn_record", f"USN {100 + i}: create_file",
                    {"reason": "create_file"})
            a.file_id, a.rel_path = f_tool, "tools/fslint.exe"
            usn_arts.append(a)

        db.replace_artifacts_for_file(f_t, evtx_arts)
        db.replace_artifacts_for_file(f_tool, usn_arts)
    finally:
        db.close()
    return case.id


def _main_af(case_id: str) -> int:
    from stopa.cli import main

    return main(["antiforensics-scan", "--json", case_id])


class TestCliE2e:
    def test_full_run_exit_0(self, af_case, capsys):
        rc = _main_af(af_case)
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out[out.index("{"):])
        assert data["findings_count"] >= 3
        assert "risk_score" in data and data["artifacts_saved"] > 0

    def test_artifact_types_in_db(self, af_case):
        from os import environ
        from pathlib import Path as _P

        from stopa.data.db import CaseDB

        rc = _main_af(af_case)
        assert rc == 0
        db_dir = _P(environ["STOPA_DB_DIR"])
        db = CaseDB(str(db_dir / f"{af_case}.db"))
        try:
            arts = [a for a in db.list_artifacts(limit=500)
                    if a.artifact_type.startswith("antiforensics/")]
        finally:
            db.close()
        types = {a.artifact_type for a in arts}
        assert "antiforensics/timestomping" in types
        assert "antiforensics/log_clearing" in types
        assert "antiforensics/usn_truncation" in types
        assert "antiforensics/tool_signature" in types

    def test_timeline_alerts_written(self, af_case):
        from os import environ
        from pathlib import Path as _P

        from stopa.data.db import CaseDB

        rc = _main_af(af_case)
        assert rc == 0
        db_dir = _P(environ["STOPA_DB_DIR"])
        db = CaseDB(str(db_dir / f"{af_case}.db"))
        try:
            rows = db.conn.execute(
                "SELECT COUNT(*) FROM timeline_events"
                " WHERE event_type LIKE 'antiforensics_%'"
            ).fetchone()[0]
        finally:
            db.close()
        assert rows >= 3

    def test_idempotent_rerun(self, af_case):
        """Re-scan — artefakty a timeline se neduplikují."""
        from os import environ
        from pathlib import Path as _P

        from stopa.data.db import CaseDB

        assert _main_af(af_case) == 0
        assert _main_af(af_case) == 0
        db_dir = _P(environ["STOPA_DB_DIR"])
        db = CaseDB(str(db_dir / f"{af_case}.db"))
        try:
            arts = [a for a in db.list_artifacts(limit=500)
                    if a.artifact_type.startswith("antiforensics/")]
            tl = db.conn.execute(
                "SELECT COUNT(*) FROM timeline_events"
                " WHERE event_type LIKE 'antiforensics_%'"
            ).fetchone()[0]
        finally:
            db.close()
        # re-run nahradí staré artefakty (stejné detekce → stejný počet)
        assert len(arts) == tl  # 1 timeline alert na artifact

    def test_missing_image_exit_2(self, af_case, tmp_path: Path, capsys):
        from stopa.cli import main

        rc = main(["antiforensics-scan", af_case, "--image",
                   str(tmp_path / "neexistuje.img")])
        assert rc == 2


# ════════════════════ 9. CLI --image (MBR) E2E =============================


class TestCliImage:
    def test_wiped_mbr_image_flagged(self, af_case, tmp_path: Path):
        from os import environ
        from pathlib import Path as _P

        from stopa.data.db import CaseDB

        img = tmp_path / "wiped.img"
        img.write_bytes(b"\x00" * 4096)  # raw obraz bez MBR signatury
        rc = _main_af_with_image(af_case, str(img))
        assert rc == 0
        db_dir = _P(environ["STOPA_DB_DIR"])
        db = CaseDB(str(db_dir / f"{af_case}.db"))
        try:
            arts = [a for a in db.list_artifacts(limit=500)
                    if a.artifact_type == "antiforensics/hidden_partition"]
        finally:
            db.close()
        assert len(arts) >= 1

    def test_valid_mbr_image_no_flag(self, af_case, tmp_path: Path):
        from os import environ
        from pathlib import Path as _P

        from stopa.data.db import CaseDB

        buf = bytearray(4096)
        entry = b"\x02\x00\x00\x00" + b"\xAA" * 13
        buf[446:458] = entry
        buf[510:512] = (0x55AA).to_bytes(2, "little")
        img = tmp_path / "ok.img"
        img.write_bytes(bytes(buf))

        rc = _main_af_with_image(af_case, str(img))
        assert rc == 0
        db_dir = _P(environ["STOPA_DB_DIR"])
        db = CaseDB(str(db_dir / f"{af_case}.db"))
        try:
            arts = [a for a in db.list_artifacts(limit=500)
                    if a.artifact_type == "antiforensics/hidden_partition"]
        finally:
            db.close()
        assert arts == []


def _main_af_with_image(case_id: str, image_path: str) -> int:
    from stopa.cli import main

    return main(["antiforensics-scan", "--json", case_id, "--image", image_path])
