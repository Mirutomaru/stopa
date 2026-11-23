"""P1 security — limity ZIP bomb pro import-mobile archívy (Cell S2, §6 master promptu).

``_archive_members`` v ``cmd_import_mobile`` dříve měl jen per-member limit 256 MiB;
chyběl celkový limit a limit počtu členů → archiv s tisíci členy mohl OOM.

Limity (``_MAX_ARCHIVE_MEMBER/_TOTAL/_MEMBERS``) jsou module globály čtené v době
volání → testy je monkeypatchují na malé hodnoty (deterministické + rychlé);
produkční defaults zůstávají (256 MiB / 4 GiB / 20_000).

Offline E2E přes ``cli.main`` — stejný pattern jako test_f15_cli_import_mobile.py.
"""

from __future__ import annotations

import zipfile
from pathlib import Path


def _vcf(name: str) -> bytes:
    """Jedna legitimní VCF karta s deterministicky unikátním telefonem."""
    phone = 7000 + sum(ord(c) for c in name) % 10000
    return (
        f"BEGIN:VCARD\nVERSION:3.0\nFN:{name}\nTEL;TYPE=CELL:+420{phone}\nEND:VCARD\n"
    ).encode()


def _case(tmp_path: Path, monkeypatch) -> str:
    """Prázdná case DB (pattern z test_f15_cli_import_mobile.py)."""
    from stopa import cli

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    assert cli.main(["case", "new", "P1 ZIP"]) == 0
    return next(p.stem for p in tmp_path.glob("*.db") if not p.name.startswith("stopa_"))


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    z = path / "evidence.ufd"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():  # pořadí = pořadí v infolistu
            zf.writestr(name, data)
    return z


def _contact_titles(tmp_path: Path, case_id: str) -> set[str]:
    from stopa.data.db import CaseDB

    db = CaseDB(tmp_path / f"{case_id}.db")
    try:
        return {t for t in (a.title for a in db.list_artifacts(artifact_type="contact")) if t}
    finally:
        db.close()


class TestZipLimitsCli:
    def test_member_count_limit_graceful(self, tmp_path: Path, monkeypatch, capsys):
        """5 vcf členů + počtový limit 2 → exit 0, warning, zpracovány jen první dva."""
        import stopa.cli.commands.forensics as fx
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        z = _zip(tmp_path, {f"c{i}.vcf": _vcf(f"Kontakt {i}") for i in range(5)})
        monkeypatch.setattr(fx, "_MAX_ARCHIVE_MEMBERS", 2)

        assert cli.main(["import-mobile", case_id, str(z)]) == 0
        assert "P1 limit: více než 2 členů" in capsys.readouterr().err

        titles = _contact_titles(tmp_path, case_id)
        assert {"Kontakt 0", "Kontakt 1"} <= titles
        assert "Kontakt 4" not in titles

    def test_total_size_limit_skips_large_member(self, tmp_path: Path, monkeypatch, capsys):
        """Člen přesahující celkový limit se přeskočí (warning), zbytek projde."""
        import stopa.cli.commands.forensics as fx
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        small = _vcf("SmallFriend")
        big = b"BEGIN:VCARD\nVERSION:3.0\nFN:BigBoss\nEND:VCARD\n" + b"x" * 5000
        z = _zip(tmp_path, {"contacts.vcf": small, "extra.vcf": big})
        # limit mezi velikostí jednoho a obou členů → big nevejde, small ano
        monkeypatch.setattr(fx, "_MAX_ARCHIVE_TOTAL", len(small) + len(big) - 1)

        assert cli.main(["import-mobile", case_id, str(z)]) == 0
        err = capsys.readouterr().err
        assert "P1 limit: celková velikost archívu" in err and "extra.vcf" in err

        titles = _contact_titles(tmp_path, case_id)
        assert "SmallFriend" in titles
        assert "BigBoss" not in titles

    def test_total_size_limit_all_skipped_exits_2(self, tmp_path: Path, monkeypatch, capsys):
        """Všechny členy přeskočeny → 'Žádné vstupní soubory' + exit 2 (ne crash)."""
        import stopa.cli.commands.forensics as fx
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        big = b"BEGIN:VCARD\nVERSION:3.0\nFN:Huge\nEND:VCARD\n" + b"y" * 5000
        z = _zip(tmp_path, {"contacts.vcf": big})
        monkeypatch.setattr(fx, "_MAX_ARCHIVE_TOTAL", len(big) - 1)

        assert cli.main(["import-mobile", case_id, str(z)]) == 2
        err = capsys.readouterr().err
        assert "P1 limit: celková velikost archívu" in err
        assert "Žádné vstupní soubory" in err
        assert _contact_titles(tmp_path, case_id) == set()

    def test_per_member_limit_still_applies(self, tmp_path: Path, monkeypatch):
        """Regrese (původní chování zachováno): člen > per-member limit se ticho skipne."""
        import stopa.cli.commands.forensics as fx
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        small = _vcf("Tiny")
        big = b"BEGIN:VCARD\nVERSION:3.0\nFN:Huge\nEND:VCARD\n" + b"z" * 5000
        z = _zip(tmp_path, {"contacts.vcf": small, "big.vcf": big})
        monkeypatch.setattr(fx, "_MAX_ARCHIVE_MEMBER", len(big) - 1)

        assert cli.main(["import-mobile", case_id, str(z)]) == 0

        titles = _contact_titles(tmp_path, case_id)
        assert "Tiny" in titles
        assert "Huge" not in titles


class TestZipLimitsDirBranch:
    def test_dir_count_limit(self, tmp_path: Path, monkeypatch):
        """Složková větev (_archive_members, rozbalený export) sdílí budget logiku.

        Pozn.: --source adb má vlastní rglob smyčku (necháváme beze změny), proto
        testuje se cellebrite na složce — přesně ta cesta jde přes _archive_members.
        """
        import stopa.cli.commands.forensics as fx
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        d = tmp_path / "uzdoby"  # rozbalený export (složka místo .ufd)
        d.mkdir()
        for i in range(4):
            (d / f"c{i}.vcf").write_bytes(_vcf(f"DirKontakt {i}"))

        monkeypatch.setattr(fx, "_MAX_ARCHIVE_MEMBERS", 2)
        assert cli.main(["import-mobile", case_id, str(d)]) == 0

        titles = _contact_titles(tmp_path, case_id)
        assert {"DirKontakt 0", "DirKontakt 1"} <= titles
        assert "DirKontakt 3" not in titles
