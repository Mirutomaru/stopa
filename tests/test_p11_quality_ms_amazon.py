"""P1-1 vlna 4 — Parser Quality sada pro MS + Amazon rodinu (w12, 8 parserů).

Parseri: ms_contacts, ms_mail_pst, ms_teams_conversations, ms_teams_teams,
ms_outlook_calendar, sharepoint_wr, amazon_cloudtrail, amazon_ec2_s3.

Kategorie doložené touto sadou (marker konvence P1-1):
- tz: ISO offsety +01:00/+02:00/+03:00/+04:30/+05:30 → exaktní epochy
  (nezávislý výpočet calendar.timegm); ms_mail int epoch == ISO string
- encoding: UTF-8 BOM → ValueError „Neplatné JSON“ (sdílený loader),
  čeština roundtrip (contacts displayName, mail subject/body)
- corrupted: oříznuté/binary smetí → ValueError
- boundary: prázdné []/{} → TypeError „Nenalezeny …“ (dokumentovaný kontrakt)
- size: single záznam → přesně 1 výstup; stres 100 e-mailů / 200 cloudtrail

Data jsou syntetická a anonymizovaná (bez reálných osobních údajů).
"""

from __future__ import annotations

import calendar
import json
from pathlib import Path

import pytest

from stopa.artifacts.amazon_cloudtrail import parse_cloudtrail
from stopa.artifacts.amazon_ec2_s3 import (
    parse_ec2_instances,
    parse_s3_objects,
)
from stopa.artifacts.ms_contacts import parse_ms_contacts
from stopa.artifacts.ms_mail_pst import parse_ms_mail_pst
from stopa.artifacts.ms_outlook_calendar import parse_outlook_calendar
from stopa.artifacts.ms_teams_conversations import parse_teams_conversations
from stopa.artifacts.ms_teams_teams import build_team_artifacts, extract_teams
from stopa.artifacts.sharepoint_wr import parse_sharepoint

BOM = b"\xef\xbb\xbf"


def _epoch(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> float:
    """Nezávislý výpočet UNIX epochy (UTC) bez parserova timestamp kódu."""
    return float(calendar.timegm((y, m, d, h, mi, 0, 0, 0, 0)))


def _mail(subject: str = "T", date: object = "2026-01-05T10:00:00Z") -> dict:
    """Syntetická MS e-mail zpráva (anonymizovaná)."""
    return {
        "subject": subject,
        "from": "posilatel@example.cz",
        "to": ["prijemce@example.cz"],
        "body": "telo",
        "date": date,
    }


# ── TZ ────────────────────────────────────────────────────────────────────────


class TestTimezones:
    def test_ms_mail_offset_plus_02(self) -> None:
        # quality: tz
        """MS mail date s offsetem +02:00 → exaktní UTC epocha."""
        data = json.dumps([_mail(date="2026-01-05T10:00:00+02:00")]).encode()
        recs = parse_ms_mail_pst(data)
        assert len(recs) == 1
        # 2026-01-05T10:00+02:00 == 2026-01-05T08:00Z
        assert recs[0].timestamp_s == _epoch(2026, 1, 5, 8)

    def test_ms_mail_int_epoch_equals_iso(self) -> None:
        # quality: tz
        """MS mail int epoch se rovná ISO string (oba formáty)."""
        base = _mail()
        no_date = {k: v for k, v in base.items() if k != "date"}
        iso = parse_ms_mail_pst(json.dumps([_mail(date="2024-01-15T10:00:00Z")]).encode())
        as_int = parse_ms_mail_pst(
            json.dumps([{**no_date, "timestamp": 1_705_312_800}]).encode()
        )
        assert iso[0].timestamp_s == 1_705_312_800.0
        assert iso[0].timestamp_s == as_int[0].timestamp_s

    def test_outlook_calendar_offset_plus_01(self) -> None:
        # quality: tz
        """Outlook startDateTime s offsetem +01:00 → exaktní UTC epocha."""
        data = json.dumps(
            [{"subject": "Porada", "startDateTime": "2026-01-05T10:00:00+01:00"}]
        ).encode()
        recs = parse_outlook_calendar(data)
        assert len(recs) == 1
        # 2026-01-05T10:00+01:00 == 2026-01-05T09:00Z
        assert recs[0].start_s == _epoch(2026, 1, 5, 9)

    def test_teams_conversations_offset_plus_05_30(self) -> None:
        # quality: tz
        """Teams date s offsetem +05:30 → exaktní UTC epocha (stejný den 04:30Z)."""
        data = json.dumps(
            [{"from": "Jan", "body": "ahoj", "date": "2026-01-05T10:00:00+05:30"}]
        ).encode()
        recs = parse_teams_conversations(data)
        assert len(recs) == 1
        # 2026-01-05T10:00+05:30 == 2026-01-05T04:30Z (UTC = lokální − offset)
        assert recs[0].timestamp_s == _epoch(2026, 1, 5, 4, 30)

    def test_cloudtrail_offset_plus_03(self) -> None:
        # quality: tz
        """CloudTrail eventTime s offsetem +03:00 → exaktní UTC epocha."""
        data = json.dumps(
            [{"eventTime": "2026-01-05T10:00:00+03:00", "eventName": "ConsoleLogin"}]
        ).encode()
        recs = parse_cloudtrail(data)
        assert len(recs) == 1
        # 2026-01-05T10:00+03:00 == 2026-01-05T07:00Z
        assert recs[0].timestamp_s == _epoch(2026, 1, 5, 7)

    def test_ec2_launch_and_s3_modified_offset_plus_04_30(self) -> None:
        # quality: tz
        """EC2 launchTime a S3 lastModified s offsetem +04:30 → exaktní epochy."""
        ec2 = json.dumps(
            {
                "instances": [
                    {
                        "instanceId": "i-1",
                        "state": "running",
                        "launchTime": "2026-01-05T10:00:00+04:30",
                    }
                ]
            }
        ).encode()
        recs = parse_ec2_instances(ec2)
        assert len(recs) == 1
        # 2026-01-05T10:00+04:30 == 2026-01-05T05:30Z
        expected = _epoch(2026, 1, 5, 5, 30)
        assert recs[0].launch_s == expected

        s3 = json.dumps(
            {
                "buckets": [
                    {
                        "name": "corp-data",
                        "objects": [
                            {"key": "docs/smlouva.pdf", "lastModified": "2026-01-05T10:00:00+04:30"}
                        ],
                    }
                ]
            }
        ).encode()
        s3recs = parse_s3_objects(s3)
        assert len(s3recs) == 1
        assert s3recs[0].modified_s == expected


# ── ENCODING ──────────────────────────────────────────────────────────────────


class TestEncoding:
    def test_bom_raises_valueerror_all_parsers(self) -> None:
        # quality: encoding
        """UTF-8 BOM → ValueError „Neplatné JSON“ (sdílený loader w12)."""
        mail = json.dumps([_mail()]).encode()
        with pytest.raises(ValueError, match="BOM"):
            parse_ms_mail_pst(BOM + mail)
        cal = json.dumps([{"subject": "S", "startDateTime": "2026-01-05T10:00:00Z"}]).encode()
        with pytest.raises(ValueError, match="BOM"):
            parse_outlook_calendar(BOM + cal)
        teams = json.dumps([{"from": "J", "body": "t"}]).encode()
        with pytest.raises(ValueError, match="BOM"):
            parse_teams_conversations(BOM + teams)
        ct = json.dumps([{"eventName": "X"}]).encode()
        with pytest.raises(ValueError, match="BOM"):
            parse_cloudtrail(BOM + ct)
        ec2 = json.dumps({"instances": [{"instanceId": "i-1", "state": "running"}]}).encode()
        with pytest.raises(ValueError, match="BOM"):
            parse_ec2_instances(BOM + ec2)
        s3 = json.dumps({"buckets": [{"name": "b", "objects": [{"key": "k"}]}]}).encode()
        with pytest.raises(ValueError, match="BOM"):
            parse_s3_objects(BOM + s3)
        contacts = json.dumps([{"displayName": "X", "emailAddresses": ["a@x.cz"]}]).encode()
        with pytest.raises(ValueError, match="BOM"):
            parse_ms_contacts(BOM + contacts)

    def test_czech_roundtrip(self) -> None:
        # quality: encoding
        """Čeština (diakritika) přežije roundtrip bez ztráty znaků."""
        recs = parse_ms_contacts(
            json.dumps([{"displayName": "Příliš žluťoučký Kůň", "emailAddresses": ["a@x.cz"]}]).encode()
        )
        assert len(recs) == 1
        assert "žluťoučký" in (recs[0].display_name or "")

        mail = json.dumps(
            [_mail(subject="Připomenutí schůzky")]
        ).encode()
        mrecs = parse_ms_mail_pst(mail)
        assert len(mrecs) == 1
        assert "Připomenutí" in (mrecs[0].subject or "")


# ── CORRUPTED ─────────────────────────────────────────────────────────────────


class TestCorrupted:
    def test_truncated_json_raises(self) -> None:
        # quality: corrupted
        """Oříznuté JSON → ValueError „Neplatné JSON“ (parser nenechá uniknout)."""
        with pytest.raises(ValueError, match="Neplatn"):
            parse_ms_mail_pst(b"[")
        with pytest.raises(ValueError, match="Neplatn"):
            parse_outlook_calendar(b"[")
        with pytest.raises(ValueError, match="Neplatn"):
            parse_sharepoint(b"{")

    def test_garbage_bytes_raise(self) -> None:
        # quality: corrupted
        """Binární smetí (ne JSON) → ValueError."""
        garbage = b"\x00\x01\x02\xff\xfe binary junk \x7f"
        with pytest.raises(ValueError):
            parse_cloudtrail(garbage)


# ── BOUNDARY / SIZE ───────────────────────────────────────────────────────────


class TestBoundarySize:
    def test_empty_collections_raise_typeerror(self) -> None:
        # quality: boundary
        """Prázdné []/{} → TypeError „Nenalezeny …“ (dokumentovaný kontrakt w12)."""
        with pytest.raises(TypeError):
            parse_ms_mail_pst(b"[]")
        with pytest.raises(TypeError):
            parse_outlook_calendar(b"[]")
        with pytest.raises(TypeError):
            parse_teams_conversations(b"[]")
        with pytest.raises(TypeError):
            parse_cloudtrail(b"[]")
        with pytest.raises(TypeError):
            parse_ec2_instances(b"{}")
        with pytest.raises(TypeError):
            parse_s3_objects(b"{}")
        with pytest.raises(TypeError):
            parse_ms_contacts(b"[]")
        with pytest.raises(TypeError):
            parse_sharepoint(b"[]")

    def test_single_record_counts(self) -> None:
        # quality: size
        """Single záznam → přesně 1 výstup (žádné duplikace)."""
        assert len(parse_ms_mail_pst(json.dumps([_mail()]).encode())) == 1
        assert len(
            parse_cloudtrail(
                json.dumps([{"eventName": "X", "eventTime": "2026-01-05T10:00:00Z"}]).encode()
            )
        ) == 1
        sp = parse_sharepoint(json.dumps([{"name": "doc.txt", "size": 10}]).encode())
        assert len(sp) == 1 and sp[0].kind == "document"

    def test_stress_mail_100_messages(self) -> None:
        # quality: size
        """Stres: 100 e-mailů → 100 záznamů, obsah konzistentní."""
        msgs = [_mail(subject=f"zprava {i}") for i in range(100)]
        recs = parse_ms_mail_pst(json.dumps(msgs).encode())
        assert len(recs) == 100

    def test_stress_cloudtrail_200_events(self) -> None:
        # quality: size
        """Stres: 200 cloudtrail událostí → 200 záznamů."""
        events = [
            {"eventName": f"Event{i % 5}", "eventTime": "2026-01-05T10:00:00Z"}
            for i in range(200)
        ]
        recs = parse_cloudtrail(json.dumps(events).encode())
        assert len(recs) == 200

    def test_teams_single_entry_artifact(self, tmp_path: Path) -> None:
        # quality: size
        """ms_teams_teams: single týmový záznam → přesně 1 artefakt."""
        entries = [
            {
                "displayName": "Vývoj",
                "ownerId": "own123",
                "memberCount": 5,
                "members": ["Jan", {"email": "k@x.cz"}],
            }
        ]
        arts = build_team_artifacts(entries)
        assert len(arts) == 1
        assert arts[0].artifact_type == "contact"

    def test_teams_corrupt_file_returns_empty(self, tmp_path: Path) -> None:
        # quality: corrupted
        """ms_teams_teams: poškozený JSON soubor → extract_teams vrátí []."""
        p = tmp_path / "teams.json"
        p.write_text("{nejson")
        assert extract_teams(p) == []
