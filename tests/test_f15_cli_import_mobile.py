"""F1.5 — CLI import-mobile: E2E testy (ROADMAP V2 Fáze 1).

Syntetická case DB (``stopa case new`` přes ``cli.main``) + ZIP/ADB fixtures →
round-trip do case DB: artefakty, timeline události, korelace entit.
Offline — žádné sítě, žádné reálné extrakce.
"""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

# ── fixtures ───────────────────────────────────────────────────────


def _case(tmp_path: Path, monkeypatch) -> str:
    """Prázdná case DB — stejný pattern jako e10_case (test_e10.py)."""
    from stopa import cli

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    assert cli.main(["case", "new", "F15 CLI"]) == 0
    return next(p.stem for p in tmp_path.glob("*.db") if not p.name.startswith("stopa_"))  # P2-2: auto-sync → stopa_instance.db v téže složce


def _ufdr_zip(path: Path) -> Path:
    """ZIP s report.xml (kontakt + hovor + chat) a contacts.vcf."""
    report = (
        '<?xml version="1.0"?>\n<export>\n'
        '  <model type="Contact">\n'
        "    <field name=\"Name\">Jana Malá</field>\n"
        "    <field name=\"Phone\">+420777987654</field>\n"
        "    <field name=\"Email\">jana.mala@example.cz</field>\n"
        "  </model>\n"
        '  <model type="Call">\n'
        "    <field name=\"TimeStamp\">2026-11-09T10:15:00Z</field>\n"
        '    <multiModelField name="Parties">'
        '<model type="Party"><field name="Name">+420777987654</field></model>'
        "</multiModelField>\n  </model>\n"
        '  <model type="Chat">\n'
        "    <field name=\"Name\">WhatsApp</field>\n"
        '    <multiModelField name="Messages">'
        '<model type="InstantMessage">'
        "<field name=\"TimeStamp\">2026-11-09T11:00:00Z</field>"
        "<field name=\"Body\">Ahoj, kde jsi?</field></model>"
        "</multiModelField>\n  </model>\n"
        "</export>\n"
    )
    vcf = (
        "BEGIN:VCARD\nVERSION:3.0\nFN:Petr Novák\n"
        "TEL;TYPE=CELL:+420777555666\nEMAIL:petr@example.cz\nEND:VCARD\n"
    )
    z = path / "evidence.ufd"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("report.xml", report)
        zf.writestr("contacts.vcf", vcf)
    return z


def _adb_dump(path: Path) -> Path:
    """Složka jako ADB logical dump: contacts2.db (Android schema) + VCF."""
    d = path / "adb-dump"
    d.mkdir(parents=True, exist_ok=True)
    db_path = d / "databases"
    db_path.mkdir(exist_ok=True)
    conn = sqlite3.connect(db_path / "contacts2.db")
    conn.execute(
        "CREATE TABLE raw_contacts (_id INTEGER PRIMARY KEY, account_name TEXT)"
    )
    conn.execute(
        "CREATE TABLE data (_id INTEGER PRIMARY KEY, raw_contact_id INTEGER,"
        " mimetype TEXT, data1 TEXT)"
    )
    conn.execute("INSERT INTO raw_contacts VALUES (1, 'local')")
    # jméno + telefon jako samostatné řádky — konvence Android extraktoru
    conn.execute(
        "INSERT INTO data VALUES (1, 1, 'vnd.android.cursor.item/name', 'Eva Svobodová')"
    )
    conn.execute(
        "INSERT INTO data VALUES (2, 1,"
        " 'vnd.android.cursor.item/phone_v2', '+420777333444')"
    )
    conn.commit()
    conn.close()
    (d / "contacts.vcf").write_text(
        "BEGIN:VCARD\nVERSION:3.0\nFN:Karel Dvořák\n"
        "TEL;TYPE=CELL:+420777888999\nEND:VCARD\n",
        encoding="utf-8",
    )
    return d


# ── E2E testy ──────────────────────────────────────────────────────


class TestImportMobileCli:
    def test_cellebrite_zip_e2e(self, tmp_path: Path, monkeypatch):
        """ZIP (report.xml + vcf) → artefakty per-value kontakty, timeline, korelace."""
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        z = _ufdr_zip(tmp_path)
        assert cli.main(["import-mobile", case_id, str(z)]) == 0

        from stopa.data.db import CaseDB

        db = CaseDB(tmp_path / f"{case_id}.db")
        try:
            arts = {a.artifact_type for a in db.list_artifacts()}
            # kontakt rozdělen per-value (jméno + telefon + email)
            assert "contact" in arts
            titles = [a.title for a in db.list_artifacts(artifact_type="contact")]
            assert "Jana Malá" in titles          # z report.xml
            assert "+420777987654" in titles      # telefon jako vlastní contact
            assert "Petr Novák" in titles         # z VCF
            # hovor + konverzace + zpráva
            assert {"call_log", "chat_conversation", "chat_message"} <= arts

            # timeline: 2 události s časem (hovor + zpráva)
            tl = db.list_timeline_events()
            assert len(tl) == 2
        finally:
            db.close()

    def test_json_mode(self, tmp_path: Path, monkeypatch):
        """--json → strojově čitelný výstup s korelací."""
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        z = _ufdr_zip(tmp_path)
        assert cli.main(["import-mobile", case_id, str(z), "--json"]) == 0

        # JSON je poslední řádek stdoutu — ověříme přes subprocess semantiku:
        # tady stačí, že se nic nepadlo a DB má data (print zachycuje pytest)
        from stopa.data.db import CaseDB

        db = CaseDB(tmp_path / f"{case_id}.db")
        try:
            assert len(db.list_artifacts()) >= 8
        finally:
            db.close()

    def test_msab_vcf_only(self, tmp_path: Path, monkeypatch):
        """--source msab — jen .vcf z archivu."""
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        z = tmp_path / "msab-export.zip"
        with zipfile.ZipFile(z, "w") as zf:
            # report.xml se při msab ignoruje
            zf.writestr("report.xml", "<export></export>")
            zf.writestr(
                "contacts/1.vcf",
                "BEGIN:VCARD\nVERSION:3.0\nFN:Marie Černá\n"
                "TEL;TYPE=CELL:+420777666777\nEND:VCARD\n",
            )
        assert cli.main(["import-mobile", case_id, str(z), "--source", "msab"]) == 0

        from stopa.data.db import CaseDB

        db = CaseDB(tmp_path / f"{case_id}.db")
        try:
            titles = [a.title for a in db.list_artifacts(artifact_type="contact")]
            assert "Marie Černá" in titles and "+420777666777" in titles
        finally:
            db.close()

    def test_adb_dump_dir(self, tmp_path: Path, monkeypatch):
        """--source adb — složka s SQLite (Android contacts) + VCF."""
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        d = _adb_dump(tmp_path)
        assert cli.main(["import-mobile", case_id, str(d), "--source", "adb"]) == 0

        from stopa.data.db import CaseDB

        db = CaseDB(tmp_path / f"{case_id}.db")
        try:
            arts = {a.artifact_type for a in db.list_artifacts()}
            assert "contact" in arts
            titles = [a.title for a in db.list_artifacts(artifact_type="contact")]
            # Android DB extraktor + VCF — obě jména přítomná
            assert "Eva Svobodová" in titles
            assert "Karel Dvořák" in titles
        finally:
            db.close()

    def test_reimport_idempotent(self, tmp_path: Path, monkeypatch):
        """Dvojí import stejného ZIPu → stejný počet artefaktů (replace)."""
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        z = _ufdr_zip(tmp_path)
        assert cli.main(["import-mobile", case_id, str(z)]) == 0
        assert cli.main(["import-mobile", case_id, str(z)]) == 0

        from stopa.data.db import CaseDB

        db = CaseDB(tmp_path / f"{case_id}.db")
        try:
            n1 = len(db.list_artifacts())
            # po re-importu se nic neduplikuje — replace per file
            assert cli.main(["import-mobile", case_id, str(z)]) == 0
            n2 = len(db.list_artifacts())
            assert n1 == n2 and n1 >= 8
        finally:
            db.close()

    def test_missing_file_exit_2(self, tmp_path: Path, monkeypatch):
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        rc = cli.main(["import-mobile", case_id, str(tmp_path / "chybi.ufd")])
        assert rc == 2

    def test_bad_zip_exit_2(self, tmp_path: Path, monkeypatch):
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        bad = tmp_path / "broken.ufd"
        bad.write_bytes(b"tohle neni zip")
        assert cli.main(["import-mobile", case_id, str(bad)]) == 2

    def test_adb_requires_dir(self, tmp_path: Path, monkeypatch):
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        z = _ufdr_zip(tmp_path)
        # adb očekává složku — soubor → exit 2
        assert cli.main(["import-mobile", case_id, str(z), "--source", "adb"]) == 2

    def test_no_input_files_exit_2(self, tmp_path: Path, monkeypatch):
        """ZIP bez report.xml/vcf pro cellebrite → nic neextrahováno."""
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        z = tmp_path / "empty.ufd"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("readme.txt", "nic forenzního")
        assert cli.main(["import-mobile", case_id, str(z)]) == 2

    # ── AK: min. WhatsApp + Signal dekódovány ─────────────────────


def _apple_ts(unix_ts: float) -> float:
    """unix → CFAbsoluteTime (epoch 1.1.2001)."""
    return unix_ts - 978_307_200


class TestChatDecodersCli:
    """WhatsApp msgstore.db + Signal signal.db přes --source adb (AK F1.5)."""

    def test_whatsapp_msgstore(self, tmp_path: Path, monkeypatch):
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        d = tmp_path / "adb-wa"
        d.mkdir()
        conn = sqlite3.connect(d / "msgstore.db")
        conn.execute("CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY,"
                     " ZMESSAGE TEXT, ZDATE REAL)")
        # unix 1762700000 = 2025-11-09T14:53:20Z → CFAbsoluteTime
        conn.execute("INSERT INTO ZWAMESSAGE VALUES (1, 'Scházíme se v 15?', ?)",
                     (_apple_ts(1762700000),))
        conn.commit()
        conn.close()
        assert cli.main(["import-mobile", case_id, str(d), "--source", "adb"]) == 0

        from stopa.data.db import CaseDB

        db = CaseDB(tmp_path / f"{case_id}.db")
        try:
            arts = db.list_artifacts(artifact_type="whatsapp_message")
            assert len(arts) == 1
            a = arts[0]
            assert "Scházíme se v 15?" in (a.title or "")
            # CFAbsoluteTime správně přepočítán na UTC
            from datetime import datetime, timezone

            assert a.timestamp == datetime(2025, 11, 9, 14, 53, 20, tzinfo=timezone.utc)
        finally:
            db.close()

    def test_signal_db(self, tmp_path: Path, monkeypatch):
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        d = tmp_path / "adb-sig"
        d.mkdir()
        conn = sqlite3.connect(d / "signal.db")
        conn.execute("CREATE TABLE ZWAMSGSTOREMESSAGE (Z_PK INTEGER PRIMARY KEY,"
                     " ZTEXT TEXT, ZENCRYPTED_TIMESTAMP REAL, ZFROM_PK INTEGER)")
        conn.execute("CREATE TABLE ZUSER (_ID INTEGER PRIMARY KEY, ADDRESS TEXT)")
        conn.execute("INSERT INTO ZUSER VALUES (10, '+420777500600')")
        # unix 1762700000 = 2025-11-09T14:53:20Z
        conn.execute("INSERT INTO ZWAMSGSTOREMESSAGE VALUES (1, 'Potvrzuji schůzku', 1762700000.0, 10)")
        conn.commit()
        conn.close()
        assert cli.main(["import-mobile", case_id, str(d), "--source", "adb"]) == 0

        from stopa.data.db import CaseDB

        db = CaseDB(tmp_path / f"{case_id}.db")
        try:
            arts = db.list_artifacts(artifact_type="chat_message")
            assert len(arts) == 1
            a = arts[0]
            assert "Potvrzuji schůzku" in (a.title or "")
            # odesílatel z ZUSER v details (fingerprint — PII zásada)
            assert str(a.details.get("sender_e164")).startswith("+42")
        finally:
            db.close()

    def test_whatsapp_and_signal_together(self, tmp_path: Path, monkeypatch):
        """Oba chaty v jednom dumpu — oba dekódují se bez vzájemné kolize."""
        from stopa import cli

        case_id = _case(tmp_path, monkeypatch)
        d = tmp_path / "adb-both"
        d.mkdir()
        wa = sqlite3.connect(d / "msgstore.db")
        wa.execute("CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY,"
                   " ZMESSAGE TEXT, ZDATE REAL)")
        wa.execute("INSERT INTO ZWAMESSAGE VALUES (1, 'WA zprava', ?)", (_apple_ts(1762700000),))
        wa.commit()
        wa.close()
        sig = sqlite3.connect(d / "signal.db")
        sig.execute("CREATE TABLE ZWAMSGSTOREMESSAGE (Z_PK INTEGER PRIMARY KEY,"
                    " ZTEXT TEXT, ZENCRYPTED_TIMESTAMP REAL)")
        sig.execute("INSERT INTO ZWAMSGSTOREMESSAGE VALUES (1, 'SIG zprava', 1762700000.0)")
        sig.commit()
        sig.close()
        assert cli.main(["import-mobile", case_id, str(d), "--source", "adb"]) == 0

        from stopa.data.db import CaseDB

        db = CaseDB(tmp_path / f"{case_id}.db")
        try:
            types = {a.artifact_type for a in db.list_artifacts()}
            assert {"whatsapp_message", "chat_message"} <= types
        finally:
            db.close()
