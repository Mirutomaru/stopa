"""P2 security — sdílená budget logika pro import-mobile (Cell A, §10 audit reportu).

ADB větev ``cmd_import_mobile`` měla vlastní neomezenou rglob smyčku mimo P1 ZIP
limity. Nyní sdílí obě větve jednu čistou implementaci
``domain.archive_budget.ArchiveBudget``:

  - per-member limit → tichý skip (v ADB jen .vcf — DB se streamují po cestě),
  - celkový velikostní limit → přeskočí konkrétní soubory, sběr pokračuje,
  - počtový limit → konec sběru.

Unit testy = čistá doménová logika (bez I/O); E2E přes ``cli.main`` — stejný
pattern jako test_p1_zip_bounded.py (module globály monkeypatchované na malé
hodnoty; čtení z globalu v době volání).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ── Unit: domain.archive_budget (čistá logika, bez I/O) ────────────────


class TestArchiveBudgetUnit:
    def test_constructor_validates_positive_limits(self):
        from stopa.domain.archive_budget import ArchiveBudget

        for kwargs in (
            {"max_member": 0, "max_total": 10, "max_members": 5},
            {"max_member": 10, "max_total": -1, "max_members": 5},
            {"max_member": 10, "max_total": 100, "max_members": 0},
        ):
            try:
                ArchiveBudget(**kwargs)
                raise AssertionError("ValueError očekáván")
            except ValueError:
                pass

    def test_exhausted_boundary(self):
        from stopa.domain.archive_budget import ArchiveBudget

        b = ArchiveBudget(max_member=10, max_total=100, max_members=2)
        assert not b.exhausted
        b.accept(3)
        assert not b.exhausted
        b.accept(4)
        assert b.exhausted  # přesně na limitu → vyčerpaný

    def test_fits_member_boundary_inclusive(self):
        from stopa.domain.archive_budget import ArchiveBudget

        b = ArchiveBudget(max_member=10, max_total=100, max_members=5)
        assert b.fits_member(10)  # hranice povolená (P1 sémantika: striktní >)
        assert not b.fits_member(11)
        assert b.accepted_count == 0 and b.total_bytes == 0  # bez změny stavu

    def test_fits_total_boundary_and_no_state_change(self):
        from stopa.domain.archive_budget import ArchiveBudget

        b = ArchiveBudget(max_member=10, max_total=12, max_members=5)
        b.accept(7)
        assert b.fits_total(5)  # 7+5 == 12 → vejde se (inkluzivní hranice)
        assert not b.fits_total(6)  # 7+6 > 12
        assert b.total_bytes == 7  # check nic neregistruje

    def test_accept_updates_counters(self):
        from stopa.domain.archive_budget import ArchiveBudget

        b = ArchiveBudget(max_member=10, max_total=100, max_members=5)
        b.accept(3)
        b.accept(4)
        assert (b.accepted_count, b.total_bytes) == (2, 7)


# ── E2E: ADB větev přes cli.main ───────────────────────────────────────


def _vcf(name: str) -> bytes:
    """Jedna legitimní VCF karta s deterministicky unikátním telefonem."""
    phone = 8000 + sum(ord(c) for c in name) % 1000
    return (
        f"BEGIN:VCARD\nVERSION:3.0\nFN:{name}\nTEL;TYPE=CELL:+420{phone}\nEND:VCARD\n"
    ).encode()


def _case(tmp_path: Path, monkeypatch) -> str:
    """Prázdná case DB (pattern z test_p1_zip_bounded.py)."""
    from stopa import cli

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    assert cli.main(["case", "new", "P2 ADB"]) == 0
    return next(p.stem for p in tmp_path.glob("*.db") if not p.name.startswith("stopa_"))


def _adb_dump(path: Path, vcfs: dict[str, bytes]) -> Path:
    d = path / "adb-dump"
    d.mkdir(parents=True)
    for name, data in vcfs.items():
        (d / name).write_bytes(data)
    return d


def _contact_titles(tmp_path: Path, case_id: str) -> set[str]:
    from stopa.data.db import CaseDB

    db = CaseDB(tmp_path / f"{case_id}.db")
    try:
        return {t for t in (a.title for a in db.list_artifacts(artifact_type="contact")) if t}
    finally:
        db.close()


class TestAdbBudgetCli:
    def test_count_limit_graceful(self, tmp_path: Path, monkeypatch, capsys):
        """4 vcf soubory + počtový limit 2 → exit 0, warning, zpracovány jen první dva."""
        import stopa.cli.commands.forensics as fx
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        d = _adb_dump(tmp_path, {f"c{i}.vcf": _vcf(f"Kontakt {i}") for i in range(4)})
        monkeypatch.setattr(fx, "_MAX_ARCHIVE_MEMBERS", 2)

        assert cli.main(["import-mobile", case_id, str(d), "--source", "adb"]) == 0
        err = capsys.readouterr().err
        assert "P2 limit: více než 2 souborů" in err

        titles = _contact_titles(tmp_path, case_id)
        assert {"Kontakt 0", "Kontakt 1"} <= titles
        assert "Kontakt 3" not in titles

    def test_total_size_limit_skips_large_vcf(self, tmp_path: Path, monkeypatch, capsys):
        """.vcf přesahující celkový limit se přeskočí (warning), menší projde."""
        import stopa.cli.commands.forensics as fx
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        small = _vcf("SmallFriend")
        big = b"BEGIN:VCARD\nVERSION:3.0\nFN:BigBoss\nEND:VCARD\n" + b"x" * 5000
        d = _adb_dump(tmp_path, {"contacts.vcf": small, "extra.vcf": big})
        # limit mezi velikostí jednoho a obou souborů → big nevejde, small ano
        monkeypatch.setattr(fx, "_MAX_ARCHIVE_TOTAL", len(big) - 1)

        assert cli.main(["import-mobile", case_id, str(d), "--source", "adb"]) == 0
        err = capsys.readouterr().err
        assert "P2 limit: celková velikost ADB dumpu" in err

        titles = _contact_titles(tmp_path, case_id)
        assert "SmallFriend" in titles
        assert "BigBoss" not in titles

    def test_all_skipped_exits_2(self, tmp_path: Path, monkeypatch, capsys):
        """Všechny soubory přeskočeny celkovým limitem → 'Žádné vstupní soubory', exit 2."""
        import stopa.cli.commands.forensics as fx
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        big = b"BEGIN:VCARD\nVERSION:3.0\nFN:BigBoss\nEND:VCARD\n" + b"x" * 5000
        d = _adb_dump(tmp_path, {"contacts.vcf": big})
        monkeypatch.setattr(fx, "_MAX_ARCHIVE_TOTAL", len(big) - 1)

        assert cli.main(["import-mobile", case_id, str(d), "--source", "adb"]) == 2
        err = capsys.readouterr().err
        assert "P2 limit: celková velikost ADB dumpu" in err
        assert "Žádné vstupní soubory" in err

    def test_db_file_counts_against_budget(self, tmp_path: Path, monkeypatch):
        """SQLite DB se počítají do budgetu (počet) — members=1 → jen první soubor."""
        import stopa.cli.commands.forensics as fx
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        d = tmp_path / "adb-mixed"
        db_dir = d / "databases"
        db_dir.mkdir(parents=True)
        conn = sqlite3.connect(db_dir / "contacts2.db")
        conn.execute(
            "CREATE TABLE raw_contacts (_id INTEGER PRIMARY KEY, account_name TEXT)"
        )
        conn.execute("INSERT INTO raw_contacts VALUES (1, 'local')")
        conn.execute(
            "CREATE TABLE data (_id INTEGER PRIMARY KEY, raw_contact_id INTEGER,"
            " mimetype TEXT, data1 TEXT)"
        )
        conn.execute(
            "INSERT INTO data VALUES (1, 1, 'vnd.android.cursor.item/name',"
            " 'Eva Svobodová')"
        )
        conn.commit()
        conn.close()
        (d / "contact.vcf").write_bytes(_vcf("Karel Dvořák"))
        # sort pořadí: contact.vcf < databases/contacts2.db → members=1 pustí jen VCF
        monkeypatch.setattr(fx, "_MAX_ARCHIVE_MEMBERS", 1)

        assert cli.main(["import-mobile", case_id, str(d), "--source", "adb"]) == 0

        titles = _contact_titles(tmp_path, case_id)
        assert "Karel Dvořák" in titles
        assert "Eva Svobodová" not in titles

    def test_default_limits_unchanged_behavior(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        """Produkční defaults (256 MiB / 4 GiB / 20k) — běžný dump projde bez warningů."""
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        d = tmp_path / "adb-default"
        db_dir = d / "databases"
        db_dir.mkdir(parents=True)
        conn = sqlite3.connect(db_dir / "contacts2.db")
        conn.execute(
            "CREATE TABLE raw_contacts (_id INTEGER PRIMARY KEY, account_name TEXT)"
        )
        conn.execute("INSERT INTO raw_contacts VALUES (1, 'local')")
        conn.commit()
        conn.close()
        (d / "contact.vcf").write_bytes(_vcf("Karel Dvořák"))

        assert cli.main(["import-mobile", case_id, str(d), "--source", "adb"]) == 0
        err = capsys.readouterr().err
        assert "P2 limit" not in err
