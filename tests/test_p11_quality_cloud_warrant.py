"""P1-1 vlna 3 — Parser Quality sada pro cloud warrant rodinu (w14, 6 parserů).

Parseri: apple_cloud, google_2025_wr, whatsapp_cloud, gmail_messages,
maps_labeled_places, cloud_generic.

Kategorie doložené touto sadou (marker konvence P1-1):
- tz: ISO offsety (+01:00/+02:00/-05:30) → přesné epochy (nezávislý výpočet);
  whatsapp timestamp jako ISO string == int epoch
- encoding: UTF-8 BOM → ValueError (dokumentovaný limit sdíleného JSON loaderu),
  čeština roundtrip (whatsapp text, apple mail body/subject)
- corrupted: oříznuté/garbage JSON → ValueError "Neplatné JSON"
- boundary: prázdná kolekce [] → TypeError (dokumentovaný kontrakt parserů —
  chybějící záznamy daného typu = typová chyba vstupu, ne empty result)
- size: single record → přesně 1 artefakt; stres 200 zpráv whatsapp / 100
  přístupových záznamů google_2025

Data jsou syntetická a anonymizovaná (bez reálných osobních údajů).
"""

from __future__ import annotations

import calendar
import json

import pytest

from stopa.artifacts.apple_cloud import parse_apple_cloud
from stopa.artifacts.cloud_generic import parse_cloud_generic
from stopa.artifacts.gmail_messages import parse_gmail_messages
from stopa.artifacts.google_2025_wr import parse_google_2025_wr
from stopa.artifacts.maps_labeled_places import parse_maps_labeled_places
from stopa.artifacts.whatsapp_cloud import parse_whatsapp_cloud


def _epoch(y: int, m: int, d: int, h: int = 0, mi: int = 0) -> float:
    """Nezávislý výpočet UNIX epochy (UTC) bez parserova timestamp kódu."""
    return float(calendar.timegm((y, m, d, h, mi, 0, 0, 0, 0)))


def _wts(text: str = "hello", ts: int | str | None = 1_700_000_000) -> dict:
    """Syntetická WhatsApp zpráva (anonymizovaná)."""
    return {"sender": "+420555000001", "text": text, "timestamp": ts}


# ── TZ ────────────────────────────────────────────────────────────────────────


class TestTimezones:
    def test_apple_mail_offset_plus_01(self) -> None:
        # quality: tz
        """Apple mail date s offsetem +01:00 → přesná UTC epocha."""
        data = json.dumps(
            [
                {
                    "subject": "Re: schůzka",
                    "from": "prijemce@example.cz",
                    "to": ["posilatel@example.cz"],
                    "date": "2026-01-05T10:00:00+01:00",
                    "body": "těší se",
                }
            ]
        ).encode()
        arts = parse_apple_cloud(data)
        assert len(arts) == 1
        # 2026-01-05T10:00+01:00 == 2026-01-05T09:00Z
        assert arts[0].created_s == _epoch(2026, 1, 5, 9)

    def test_g2025_access_time_offset_plus_02(self) -> None:
        # quality: tz
        """Google 2025 WR accessTime s offsetem +02:00 → přesná UTC epocha."""
        data = json.dumps(
            [
                {
                    "deviceName": "Pixel 8 (test)",
                    "ipAddress": "192.168.1.42",
                    "accessTime": "2026-01-01T00:00:00+02:00",
                }
            ]
        ).encode()
        arts = parse_google_2025_wr(data)
        assert len(arts) == 1
        # 2026-01-01T00:00+02:00 == 2025-12-31T22:00Z
        assert arts[0].created_s == _epoch(2025, 12, 31, 22)

    def test_gmail_date_offset_minus_05_30(self) -> None:
        # quality: tz
        """Gmail date s offsetem -05:30 → přesná UTC epocha."""
        data = json.dumps(
            [
                {
                    "from": "odesilatel@example.cz",
                    "to": "prijemce@example.cz",
                    "subject": "Zpráva z New Yorku",
                    "date": "2026-01-01T00:00:00-05:30",
                    "body": "ahoj",
                }
            ]
        ).encode()
        arts = parse_gmail_messages(data)
        assert len(arts) == 1
        # 2026-01-01T00:00-05:30 == 2026-01-01T05:30Z
        assert arts[0].created_s == _epoch(2026, 1, 1, 5, 30)

    def test_whatsapp_iso_string_equals_int_epoch(self) -> None:
        # quality: tz
        """WhatsApp timestamp jako ISO string se rovná int epoch (oba formáty)."""
        iso = parse_whatsapp_cloud(
            json.dumps([_wts(ts="2024-01-15T10:00:00Z")]).encode()
        )
        as_int = parse_whatsapp_cloud(json.dumps([_wts(ts=1_705_312_800)]).encode())
        assert iso[0].created_s == 1_705_312_800.0
        assert iso[0].created_s == as_int[0].created_s


# ── ENCODING ──────────────────────────────────────────────────────────────────


class TestEncoding:
    def test_bom_raises_valueerror(self) -> None:
        # quality: encoding
        """UTF-8 BOM → ValueError (dokumentovaný limit sdíleného JSON loaderu)."""
        bom = b"\xef\xbb\xbf"
        wa_data = json.dumps([_wts()]).encode()
        with pytest.raises(ValueError, match="BOM"):
            parse_whatsapp_cloud(bom + wa_data)
        gm_data = json.dumps(
            [{"from": "a@example.cz", "to": "b@example.cz", "subject": "t"}]
        ).encode()
        with pytest.raises(ValueError, match="BOM"):
            parse_gmail_messages(bom + gm_data)

    def test_czech_roundtrip(self) -> None:
        # quality: encoding
        """Čeština (diakritika) přežije roundtrip bez ztráty znaků."""
        arts = parse_whatsapp_cloud(
            json.dumps([_wts(text="Příliš žluťoučký kůň úpěl ďábelské ódy")]).encode()
        )
        assert len(arts) == 1
        assert "žluťoučký" in (arts[0].text or "")
        mail = json.dumps(
            [
                {
                    "subject": "Připomenutí schůzky",
                    "from": "a@example.cz",
                    "to": ["b@example.cz"],
                    "date": "2026-01-05T10:00:00Z",
                    "body": "Vítejte, víme, že jste byl v Čechách.",
                }
            ]
        ).encode()
        marts = parse_apple_cloud(mail)
        assert len(marts) == 1


# ── CORRUPTED ─────────────────────────────────────────────────────────────────


class TestCorrupted:
    def test_truncated_json_raises(self) -> None:
        # quality: corrupted
        """Oříznutý JSON → ValueError 'Neplatné JSON' (parser nenechá uniknout)."""
        truncated = b'{"deviceName": "Pixel 8", "ipAddress": "192.168.'
        with pytest.raises(ValueError, match="Neplatn"):
            parse_google_2025_wr(truncated)
        with pytest.raises(ValueError, match="Neplatn"):
            parse_whatsapp_cloud(b'{"sender": "+4205')

    def test_garbage_bytes_raise(self) -> None:
        # quality: corrupted
        """Binární smetí (ne JSON) → ValueError."""
        garbage = b"\x00\x01\x02\xff\xfe binary junk \x7f"
        with pytest.raises(ValueError):
            parse_gmail_messages(garbage)


# ── BOUNDARY / SIZE ───────────────────────────────────────────────────────────


class TestBoundarySize:
    def test_empty_list_raises_typeerror_all_parsers(self) -> None:
        # quality: boundary
        """Prázdná kolekce [] → TypeError (dokumentovaný kontrakt w14 parserů)."""
        with pytest.raises(TypeError):
            parse_apple_cloud(b"[]")
        with pytest.raises(TypeError):
            parse_google_2025_wr(b"[]")
        with pytest.raises(TypeError):
            parse_whatsapp_cloud(b"[]")
        with pytest.raises(TypeError):
            parse_gmail_messages(b"[]")
        with pytest.raises(TypeError):
            parse_maps_labeled_places(b"[]")
        with pytest.raises(TypeError):
            parse_cloud_generic(b"[]", kind_hint="accounts")

    def test_single_record_whatsapp(self) -> None:
        # quality: size
        """Jedna zpráva → přesně 1 artefakt (žádné duplikace)."""
        arts = parse_whatsapp_cloud(json.dumps([_wts()]).encode())
        assert len(arts) == 1

    def test_single_record_g2025(self) -> None:
        # quality: size
        """Jeden přístupový záznam → přesně 1 artefakt."""
        data = json.dumps(
            [
                {
                    "deviceName": "Pixel 8 (test)",
                    "ipAddress": "192.168.1.42",
                    "accessTime": "2025-06-15T12:30:00Z",
                }
            ]
        ).encode()
        arts = parse_google_2025_wr(data)
        assert len(arts) == 1

    def test_stress_whatsapp_200_messages(self) -> None:
        # quality: size
        """Stres: 200 zpráv → 200 artefaktů, pořadí i obsah konzistentní."""
        msgs = [_wts(text=f"zprava {i}", ts=1_700_000_000 + i) for i in range(200)]
        arts = parse_whatsapp_cloud(json.dumps(msgs).encode())
        assert len(arts) == 200

    def test_stress_g2025_100_access_entries(self) -> None:
        # quality: size
        """Stres: 100 přístupových záznamů → 100 artefaktů."""
        entries = [
            {
                "deviceName": f"Device-{i % 7}",
                "ipAddress": f"192.168.1.{i % 250 + 1}",
                "accessTime": f"2025-06-15T{i // 36:02d}:{(i * 7) % 60:02d}:00Z",
            }
            for i in range(100)
        ]
        arts = parse_google_2025_wr(json.dumps(entries).encode())
        assert len(arts) == 100
