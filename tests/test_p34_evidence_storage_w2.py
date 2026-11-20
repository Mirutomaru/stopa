"""P3-4 Evidence Storage Manager — Wave 2 testy (data layer + CLI).

Offline a deterministické: reálné soubory v ``tmp_path`` jako kvarenténa,
CaseDB na disku. Pokrývají read-only rehash inventáře (verified/corrupt/
missing/no_reference), kapacitní report, fail-closed export/import podepsaného
manifestu (Ed25519 — volitelná ``cryptography``) a CLI exit kódy 0/2.

Semantika: kvarenténa případu = unie zdrojových cest (sources.path +
files.rel_path); no_reference není fatální pro export/verify exit code.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from importlib import util as il_util
from pathlib import Path

import pytest

from stopa.data.audit_repository import AuditRepository
from stopa.data.db import CaseDB
from stopa.data.evidence_storage_repository import EvidenceStorageRepository
from stopa.domain.evidence_storage import (
    build_report,
    verify_manifest,
)
from stopa.domain.evidence_storage import (
    export_manifest as domain_export_manifest,
)

CASE_ID = "p34-case"
CLEAN_CASE_ID = "p34-clean"
NOW_ISO = "2026-11-20T12:00:00+00:00"

REQUIRES_CRYPTO = pytest.mark.skipif(
    il_util.find_spec("cryptography") is None, reason="volitelná cryptography chybí"
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


NOTES = b"hello notes\n"
DATA_BIN = bytes(range(256)) * 4
LEGACY_DAT = b"legacy content"
LOG_EVT = b"log-line\n"
GONE_BIN = b"gone"

# (rel_path, source_id, obsah) — referenční velikosti pro report testy
SEED_FILES: list[tuple[str, str, bytes]] = [
    ("notes.txt", "s1", NOTES),
    ("data.bin", "s1", DATA_BIN),
    ("legacy.dat", "s1", LEGACY_DAT),  # v DB bez sha256 (no_reference)
    ("log.evt", "s2", LOG_EVT),        # po seedu poškozen na disku
    ("gone.bin", "s2", GONE_BIN),      # po seedu smazán z disku
]


def _seed(db: CaseDB, root_a: Path, root_b: Path) -> None:
    c = db.conn
    c.execute("INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
              (CASE_ID, "P3-4", NOW_ISO))
    c.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES ('s1', ?, 'file', ?, ?)",
        (CASE_ID, str(root_a), NOW_ISO),
    )
    c.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES ('s2', ?, 'file', ?, ?)",
        (CASE_ID, str(root_b), NOW_ISO),
    )
    for rel_path, sid, content in SEED_FILES:
        sha = None if rel_path == "legacy.dat" else _sha(content)
        c.execute(
            "INSERT INTO files (id, source_id, rel_path, name, size_bytes, sha256)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (rel_path, sid, rel_path, Path(rel_path).name, len(content), sha),
        )
    c.commit()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch) -> dict[str, object]:
    """Případ s rozdíly: 2 verified + 1 corrupt + 1 missing + 1 no_reference."""
    dbdir = tmp_path / "cases"
    dbdir.mkdir()
    root_a = tmp_path / "src-a"
    root_b = tmp_path / "src-b"
    root_a.mkdir()
    root_b.mkdir()

    files_by_path: dict[Path, bytes] = {}
    for rel_path, sid, content in SEED_FILES:
        target = (root_a if sid == "s1" else root_b) / rel_path
        target.write_bytes(content)
        files_by_path[target] = content

    # poškození + ztráta PO seedu → inventář musí rozdíly zachytit
    dbdir_case = CaseDB(dbdir / f"{CASE_ID}.db")
    _seed(dbdir_case, root_a, root_b)
    (root_b / "log.evt").write_bytes(b"CORRUPTED-CONTENT\n")
    (root_b / "gone.bin").unlink()
    dbdir_case.close()

    monkeypatch.setenv("STOPA_DB_DIR", str(dbdir))
    return {
        "db_path": dbdir / f"{CASE_ID}.db",
        "root_a": root_a,
        "root_b": root_b,
        "files_by_path": files_by_path,
    }


@pytest.fixture()
def clean_env(tmp_path: Path, monkeypatch) -> dict[str, object]:
    """Čistý případ (bez missing/corrupt) pro export/import testy."""
    dbdir = tmp_path / "cases"
    dbdir.mkdir()
    root_a = tmp_path / "src-clean"
    root_a.mkdir()
    files: dict[Path, bytes] = {root_a / "a.bin": b"alpha", root_a / "b.bin": b"beta beta"}

    for path, content in files.items():
        path.write_bytes(content)

    case_db = CaseDB(dbdir / f"{CLEAN_CASE_ID}.db")
    c = case_db.conn
    c.execute("INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
              (CLEAN_CASE_ID, "P3-4 clean", NOW_ISO))
    c.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES ('s1', ?, 'file', ?, ?)",
        (CLEAN_CASE_ID, str(root_a), NOW_ISO),
    )
    for rel_path in ("a.bin", "b.bin"):
        content = files[root_a / rel_path]
        c.execute(
            "INSERT INTO files (id, source_id, rel_path, name, size_bytes, sha256)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (rel_path, "s1", rel_path, rel_path, len(content), _sha(content)),
        )
    c.commit()
    case_db.close()

    monkeypatch.setenv("STOPA_DB_DIR", str(dbdir))
    return {"db_path": dbdir / f"{CLEAN_CASE_ID}.db", "root_a": root_a}


@pytest.fixture()
def repo(env: dict[str, object]) -> Iterator[EvidenceStorageRepository]:
    db = CaseDB(Path(str(env["db_path"])))  # type: ignore[arg-type]
    yield EvidenceStorageRepository(db.conn)
    db.close()


@pytest.fixture()
def clean_repo(clean_env: dict[str, object]) -> Iterator[EvidenceStorageRepository]:
    db = CaseDB(Path(str(clean_env["db_path"])))  # type: ignore[arg-type]
    yield EvidenceStorageRepository(db.conn)
    db.close()


# ── inventář / read-only rehash ──────────────────────────────────────────────


class TestVerifyInventory:
    def test_status_counts_and_deterministic_order(self, repo: EvidenceStorageRepository):
        entries = repo.verify(CASE_ID)
        report = build_report(entries)
        assert (report.verified, report.corrupt, report.missing, report.no_reference) == (2, 1, 1, 1)
        keys = [(e.source_id, e.rel_path) for e in entries]
        assert keys == sorted(keys)

    def test_per_entry_statuses(self, repo: EvidenceStorageRepository):
        by_key = {(e.source_id, e.rel_path): e for e in repo.verify(CASE_ID)}
        assert by_key[("s1", "notes.txt")].status == "verified"
        assert by_key[("s1", "data.bin")].status == "verified"
        assert by_key[("s1", "legacy.dat")].status == "no_reference"
        assert by_key[("s2", "log.evt")].status == "corrupt"
        assert by_key[("s2", "gone.bin")].status == "missing"

    def test_read_only_originals_untouched(self, repo: EvidenceStorageRepository, env: dict[str, object]):
        root_a = Path(str(env["root_a"]))  # type: ignore[arg-type]
        root_b = Path(str(env["root_b"]))  # type: ignore[arg-type]
        targets = [root_a / "notes.txt", root_b / "log.evt"]
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in targets}
        repo.verify(CASE_ID)  # read-only — nesmí měnit obsah ani mtime originálů
        for p in targets:
            assert p.read_bytes() == before[p][0]
            assert p.stat().st_mtime_ns == before[p][1]

    def test_unknown_case_value_error(self, repo: EvidenceStorageRepository):
        with pytest.raises(ValueError, match="neexistuje"):
            repo.verify("nope")

    def test_missing_source_root_files_missing(self, repo: EvidenceStorageRepository):
        repo.conn.execute(
            "INSERT INTO sources (id, case_id, kind, path, added_at)"
            " VALUES ('s3', ?, 'file', '/nonexistent-root-xyz', ?)",
            (CASE_ID, NOW_ISO),
        )
        content = b"orphan file"
        repo.conn.execute(
            "INSERT INTO files (id, source_id, rel_path, name, size_bytes, sha256)"
            " VALUES ('s3/x.bin', 's3', 'x.bin', 'x.bin', ?, ?)",
            (len(content), _sha(content)),
        )
        repo.conn.commit()
        by_key = {(e.source_id, e.rel_path): e for e in repo.verify(CASE_ID)}
        assert by_key[("s3", "x.bin")].status == "missing"


# ── kapacitní report (DB metadata, bez disk I/O) ─────────────────────────────


class TestReportMeta:
    def test_totals_from_db_metadata_only(self, repo: EvidenceStorageRepository):
        expected_bytes = sum(len(c) for _, _, c in SEED_FILES)
        data = repo.report_meta(CASE_ID)
        assert data["total_files"] == 5
        assert data["total_bytes"] == expected_bytes
        assert data["capacity"]["budget_bytes"] is None

    def test_budget_exact_fit_and_over(self, repo: EvidenceStorageRepository):
        total = sum(len(c) for _, _, c in SEED_FILES)
        exact = repo.report_meta(CASE_ID, budget_bytes=total)
        assert exact["capacity"]["utilization"] == 1.0 and not exact["capacity"]["over_budget"]
        over = repo.report_meta(CASE_ID, budget_bytes=total - 1)
        assert over["capacity"]["over_budget"] is True

    def test_bad_budget_value_error(self, repo: EvidenceStorageRepository):
        for bad in (0, -3):
            with pytest.raises(ValueError, match="budget"):
                repo.report_meta(CASE_ID, budget_bytes=bad)

    def test_type_and_case_errors(self, repo: EvidenceStorageRepository):
        with pytest.raises(TypeError):
            repo.report_meta(CASE_ID, budget_bytes="10")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="neexistuje"):
            repo.report_meta("nope")


# ── export / import manifestu (fail-closed Ed25519) ──────────────────────────


@REQUIRES_CRYPTO
class TestExportImport:
    def test_export_fail_closed_on_gaps(self, repo: EvidenceStorageRepository):
        with pytest.raises(ValueError, match="pre-export verifikace selhala"):
            repo.export_manifest(CASE_ID)

    def test_export_clean_structure_sorted_and_signed(
        self, clean_repo: EvidenceStorageRepository
    ):
        manifest = clean_repo.export_manifest(CLEAN_CASE_ID)
        assert set(manifest) == {
            "format_version", "case_id", "public_key_b64", "entries", "signature_b64"
        }
        names = [e["rel_path"] for e in manifest["entries"]]
        assert names == sorted(names)
        assert verify_manifest(manifest).ok is True

    def test_export_no_reference_not_fatal(self, clean_repo: EvidenceStorageRepository):
        # no_reference položka (bez referenčního hashu) export nenechá padnout —
        # její aktuální stav se stává součástí nového reference snapshotu
        root_a = Path(str(clean_repo.conn.execute("SELECT path FROM sources WHERE id='s1'").fetchone()["path"]))
        legacy = root_a / "legacy.bin"
        legacy.write_bytes(b"no ref here")
        clean_repo.conn.execute(
            "INSERT INTO files (id, source_id, rel_path, name, size_bytes)"
            " VALUES ('legacy.bin', 's1', 'legacy.bin', 'legacy.bin', ?)",
            (len(b"no ref here"),),
        )
        clean_repo.conn.commit()
        manifest = clean_repo.export_manifest(CLEAN_CASE_ID)
        assert any(e["rel_path"] == "legacy.bin" for e in manifest["entries"])

    def test_import_persists_to_meta(self, repo: EvidenceStorageRepository):
        priv, pub = AuditRepository(
            repo.conn
        ).ensure_integrity_key()
        manifest = domain_export_manifest(CASE_ID, pub, priv, [("s1", "notes.txt", _sha(NOTES), len(NOTES))])
        imported = repo.import_manifest(CASE_ID, manifest)
        assert imported == manifest
        stored = repo.stored_manifest(CASE_ID)
        assert stored is not None and stored["case_id"] == CASE_ID

    def test_import_tampered_entry_fail_closed(self, clean_repo: EvidenceStorageRepository):
        manifest = clean_repo.export_manifest(CLEAN_CASE_ID)
        tampered = json.loads(json.dumps(manifest))
        tampered["entries"][0]["sha256"] = _sha(b"other content")
        with pytest.raises(ValueError, match="podpis"):
            clean_repo.import_manifest(CLEAN_CASE_ID, tampered)

    def test_import_unknown_source_reference_missing(
        self, repo: EvidenceStorageRepository
    ):
        priv, pub = AuditRepository(
            repo.conn
        ).ensure_integrity_key()
        manifest = domain_export_manifest(CASE_ID, pub, priv, [("s9", "ghost.bin", _sha(GONE_BIN), len(GONE_BIN))])
        assert verify_manifest(manifest).ok is True  # podpis validní — struktura v pořádku
        repo.import_manifest(CASE_ID, manifest)
        ref = {(e["source_id"], e["rel_path"]): (e["sha256"], int(e["size"])) for e in manifest["entries"]}
        entries = repo.verify(CASE_ID, reference=ref)
        assert len(entries) == 1 and entries[0].status == "missing"

    def test_verify_against_reference_detects_drift(
        self, clean_repo: EvidenceStorageRepository, clean_env: dict[str, object]
    ):
        manifest = clean_repo.export_manifest(CLEAN_CASE_ID)
        ref = {(e["source_id"], e["rel_path"]): (e["sha256"], int(e["size"])) for e in manifest["entries"]}
        assert build_report(clean_repo.verify(CLEAN_CASE_ID, reference=ref)).verified == 2
        root_a = Path(str(clean_env["root_a"]))  # type: ignore[arg-type]
        (root_a / "a.bin").write_bytes(b"DRIFTED")
        report = build_report(clean_repo.verify(CLEAN_CASE_ID, reference=ref))
        assert report.corrupt == 1 and report.verified == 1


# ── CLI (exit kódy + JSON/txt výstup) ────────────────────────────────────────


class TestCli:
    def _run(self, argv: list[str], capsys):
        from stopa.cli import build_parser

        args = build_parser().parse_args(argv)
        rc = args.func(args)  # type: ignore[union-attr]
        return rc, capsys.readouterr()

    def test_verify_gaps_exit2_text(self, env: dict[str, object], capsys):
        rc, out = self._run(["evidence-storage", "verify", CASE_ID], capsys)
        assert rc == 2
        text = out.out
        assert f"EVIDENCE STORAGE — {CASE_ID} (verify)" in text
        assert "[!] s2/gone.bin" in text and "CHYBÍ NA DISKU" in text
        assert "[!] s2/log.evt" in text and "POŠKOZENÝ" in text
        assert "[!] s1/legacy.dat" in text and "BEZ REFERENČNÍHO HASHU" in text

    def test_verify_gaps_json_shape(self, env: dict[str, object], capsys):
        rc, out = self._run(["evidence-storage", "verify", CASE_ID, "--json"], capsys)
        assert rc == 2
        data = json.loads(out.out)
        assert data["ok"] is False and data["action"] == "verify"
        assert data["report"]["missing"] == 1 and data["report"]["corrupt"] == 1
        assert len(data["entries"]) == 5

    def test_verify_clean_exit0(self, clean_env: dict[str, object], capsys):
        rc, out = self._run(["evidence-storage", "verify", CLEAN_CASE_ID], capsys)
        assert rc == 0
        assert "✓ všechny soubory odpovídají referenci" in out.out

    def test_report_budget_over_text(self, env: dict[str, object], capsys):
        # rozpočet 0.001 MB = 1048 B < 1064 B celkem → PŘE RODPOČETU
        rc, out = self._run(["evidence-storage", "report", CASE_ID, "--budget", "0.001"], capsys)
        assert rc == 0
        assert "PŘE RODPOČETU!" in out.out

    def test_report_json_budget_bytes_conversion(self, env: dict[str, object], capsys):
        rc, out = self._run(
            ["evidence-storage", "report", CASE_ID, "--budget", "1.5", "--json"], capsys
        )
        assert rc == 0
        data = json.loads(out.out)
        assert data["capacity"]["budget_bytes"] == int(1.5 * 1024 * 1024)

    def test_export_flag_rejected_on_report(self, env: dict[str, object], capsys):
        # --export/--import patří k verify; na reportu nejsou → argparse exit 2
        with pytest.raises(SystemExit):
            self._run(["evidence-storage", "report", CASE_ID, "--export", "x.json"], capsys)

    def test_export_cli_writes_signed_manifest(
        self, clean_env: dict[str, object], tmp_path: Path, capsys
    ):
        out_file = tmp_path / "manifest.json"
        rc, out = self._run(
            ["evidence-storage", "verify", CLEAN_CASE_ID, "--export", str(out_file), "--json"], capsys
        )
        assert rc == 0
        data = json.loads(out.out)
        assert data["ok"] is True and data.get("manifest_file") == str(out_file)
        manifest = json.loads(out_file.read_text(encoding="utf-8"))
        assert verify_manifest(manifest).ok is True

    def test_import_cli_roundtrip_and_drift_exit2(
        self, env: dict[str, object], tmp_path: Path, capsys
    ):
        """Import reference manifestu = kontrola PŘESNĚ importovaného množiny.

        Manifest s 3 zdravými soubory → exit 0; po poškození jednoho na disku → exit 2.
        """
        db = CaseDB(Path(str(env["db_path"])))  # type: ignore[arg-type]
        priv, pub = AuditRepository(
            db.conn
        ).ensure_integrity_key()
        healthy = [
            ("s1", "notes.txt", _sha(NOTES), len(NOTES)),
            ("s1", "data.bin", _sha(DATA_BIN), len(DATA_BIN)),
            ("s1", "legacy.dat", _sha(LEGACY_DAT), len(LEGACY_DAT)),
        ]
        manifest = domain_export_manifest(CASE_ID, pub, priv, healthy)
        db.close()
        mfile = tmp_path / "ref.json"
        mfile.write_text(json.dumps(manifest), encoding="utf-8")

        rc, out = self._run(["evidence-storage", "verify", CASE_ID, "--import", str(mfile)], capsys)
        assert rc == 0
        assert "(3 položek)" in out.out

        (Path(str(env["root_a"])) / "notes.txt").write_bytes(b"tampered")  # type: ignore[arg-type]
        rc2, _ = self._run(["evidence-storage", "verify", CASE_ID, "--import", str(mfile), "--json"], capsys)
        assert rc2 == 2

    def test_unknown_case_systemexit(self, env: dict[str, object], capsys):
        with pytest.raises(SystemExit):
            self._run(["evidence-storage", "verify", "nope-case"], capsys)
