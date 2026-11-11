"""F1.5 — Mobilní extrakce: testy doménové vrstvy (offline fixture, bez IO).

Covers: UFDR report.xml parser, model→artifact mapping, VCF kontakty,
normalizace pro korelaci entit. Žádné soubory — vše stringy.
"""

from datetime import datetime, timezone

import pytest

from stopa.domain.mobile_forensics import (
    PARSER_VERSION,
    ModelSpec,
    UfedParseError,
    models_to_artifact_specs,
    normalize_email,
    normalize_phone,
    parse_ufdr_xml,
    parse_vcf,
)


def _xml(body: str) -> str:
    return f'<?xml version="1.0" encoding="UTF-8"?><Report><Extraction>{body}</Extraction></Report>'


# ── UFDR XML parser ────────────────────────────────────────────

def test_parse_ufdr_invalid_xml_raises():
    with pytest.raises(UfedParseError):
        parse_ufdr_xml("<report><model>")  # nezavřený tag


def test_parse_ufdr_empty_body_no_models():
    models, unknown = parse_ufdr_xml(_xml(""))
    assert models == [] and unknown == []


def test_parse_ufdr_contact_fields_and_timestamps():
    xml = _xml(
        '<model type="Contact">'
        "<field name=\"Name\">Jan Novák</field>"
        "<field name=\"Phone\">+420777123456</field>"
        "</model>"
    )
    models, unknown = parse_ufdr_xml(xml)
    assert len(models) == 1 and not unknown
    m = models[0]
    assert m.model_type == "Contact"
    assert m.fields["Name"] == "Jan Novák"


def test_parse_ufdr_nested_models_consumed_once():
    """Chat + vnořené IM: top-level vidí jen Chat, dceriny patří rodiči."""
    xml = _xml(
        '<model type="Chat">'
        "<field name=\"Name\">Skupina</field>"
        "<multiModelField name=\"Parties\">"
        '<model type="Party"><field name="Name">Petra</field></model>'
        "</multiModelField>"
        "<multiModelField name=\"Messages\">"
        '<model type="InstantMessage">'
        "<field name=\"Body\">Ahoj</field>"
        "</model>"
        "</multiModelField>"
        "</model>"
    )
    models, _ = parse_ufdr_xml(xml)
    assert [m.model_type for m in models] == ["Chat"]  # IM není top-level
    chat = models[0]
    nested_types = {p.model_type for p in chat.nested}
    assert nested_types == {"Party", "InstantMessage"}


def test_parse_ufdr_namespace_tags():
    """Tagy s XML namespaceu → _localname je stripuje."""
    xml = (
        '<r xmlns="https://ufed.example/ns">'
        '<model type="Contact"><field name="Name">NS Test</field></model>'
        "</r>"
    )
    models, _ = parse_ufdr_xml(xml)
    assert len(models) == 1 and models[0].fields["Name"] == "NS Test"


def test_parse_ufdr_unknown_type_reported_sorted():
    xml = _xml(
        '<model type="Zebra"><field name="A">b</field></model>'
        '<model type="Alpha"><field name="A">b</field></model>'
    )
    models, unknown = parse_ufdr_xml(xml)
    assert len(models) == 2
    assert unknown == ["Alpha", "Zebra"]


def test_parse_ufdr_multifield_joined_capped():
    xml = _xml(
        '<model type="Contact"><multiField name="Tags">'
        + "<v>one</v><v>two</v>" * 10
        + "</multiField></model>"
    )
    models, _ = parse_ufdr_xml(xml)
    tags = models[0].fields["Tags"]
    assert len(tags.split(" | ")) == 8  # strop 8 položek


def test_parse_ufdr_bytes_input():
    xml = _xml('<model type="Contact"><field name="Name">Byte</field></model>')
    models, _ = parse_ufdr_xml(xml.encode("utf-8"))
    assert models[0].fields["Name"] == "Byte"


# ── model → artifact mapping ───────────────────────────────────

def test_map_contact_per_value():
    """Karta → jméno + telefon jako VLASTNÍ contact artifacty (entities.py konvence)."""
    xml = _xml(
        '<model type="Contact">'
        "<field name=\"Name\">Jan Novák</field>"
        "<field name=\"Phone\">+420777123456</field>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    assert [s.title for s in specs] == ["Jan Novák", "+420777123456"]
    name_s, phone_s = specs
    assert all(s.artifact_type == "contact" and s.timestamp is None for s in specs)
    assert name_s.details["engine"] == "ufdr"
    # telefon nese mimetype (entities.py ho mapuje na Entity("phone"))
    assert "phone" in str(phone_s.details["mimetype"])


def test_map_contact_phone_type_not_value():
    """Pole PhoneType='Mobile' není číslo → nevytvoří falešný kontakt."""
    xml = _xml(
        '<model type="Contact">'
        "<field name=\"Name\">Karel</field>"
        "<field name=\"Phone\">+420777128910</field>"
        "<field name=\"PhoneType\">Mobile</field>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    assert [s.title for s in specs] == ["Karel", "+420777128910"]


def test_map_contact_multi_field_split_and_email():
    """multiField ( | spojení) se rozbalí; e-maily → email mimetype."""
    xml = _xml(
        '<model type="Contact">'
        "<field name=\"Name\">Eva</field>"
        "<multiField name=\"Phone\"><v>+420777131122</v><v>+420777133344</v></multiField>"
        "<field name=\"Email\">eva@example.com</field>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    titles = [s.title for s in specs]
    assert titles == ["Eva", "+420777131122", "+420777133344", "eva@example.com"]
    mail_s = specs[-1]
    assert "email" in str(mail_s.details["mimetype"])


def test_map_contact_dedupe_and_invalid_skipped():
    """Duplikát se odstraní; nevalidní telefon (písmena) se neprojeví."""
    xml = _xml(
        '<model type="Contact">'
        "<field name=\"Name\">Ondra</field>"
        "<multiField name=\"Phone\"><v>+42077715678</v><v>+42077715678</v></multiField>"
        "<multiField name=\"Email\"><v>ne-mail</v></multiField>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    assert [s.title for s in specs] == ["Ondra", "+42077715678"]


def test_contact_value_specs_vcf_card():
    """VCF karta → per-value artifacty (jméno + telefony + maile)."""
    from stopa.domain.mobile_forensics import contact_specs_from_card

    card = {"name": "Jana", "phones": ["+420 777 111 222"], "emails": ["jana@x.cz"]}
    specs = contact_specs_from_card(card, engine="msab")
    assert [s.title for s in specs] == ["Jana", "+420 777 111 222", "jana@x.cz"]
    assert all(s.details["engine"] == "msab" for s in specs)


def test_map_call_with_parties_and_timestamp():
    xml = _xml(
        '<model type="Call">'
        "<field name=\"TimeStamp\">2026-11-10T14:30:00Z</field>"
        "<field name=\"Direction\">Incoming</field>"
        "<field name=\"Duration\">125</field>"
        "<multiModelField name=\"Parties\">"
        '<model type="Party"><field name="Name">Petra Dvořáková</field></model>'
        "</multiModelField>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    assert len(specs) == 1
    s = specs[0]
    assert s.artifact_type == "call_log"
    assert s.title == "Petra Dvořáková"
    assert s.timestamp == datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)
    assert s.details["direction"] == "Incoming"
    assert s.details["duration"] == "125"


def test_map_instant_message_top_level_is_sms():
    xml = _xml(
        '<model type="InstantMessage">'
        "<field name=\"Body\">SMS text</field>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    assert specs[0].artifact_type == "sms_message"


def test_map_chat_conversation_with_nested_messages():
    xml = _xml(
        '<model type="Chat">'
        "<field name=\"Name\">WhatsApp: Jana</field>"
        "<multiModelField name=\"Messages\">"
        '<model type="InstantMessage"><field name="Body">první</field></model>'
        '<model type="InstantMessage"><field name="Body">druhá</field></model>'
        "</multiModelField>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    assert [s.artifact_type for s in specs] == ["chat_conversation", "chat_message", "chat_message"]
    conv, m1, m2 = specs
    assert conv.title == "WhatsApp: Jana"
    assert conv.details["participants"] == []  # žádné Party modely
    assert conv.details["message_count"] == 2
    for msg in (m1, m2):
        assert msg.details["conversation"] == "WhatsApp: Jana"


def test_map_email_title_from_subject_or_sender():
    xml = _xml(
        '<model type="Email">'
        "<field name=\"Subject\">Faktura</field>"
        "<field name=\"From\">bob@x.cz</field>"
        "<field name=\"TimeStamp\">2026-11-09T08:00:00Z</field>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    s = specs[0]
    assert s.artifact_type == "email_message"
    assert s.title == "Faktura"
    assert s.details["from"] == "bob@x.cz"


def test_map_email_title_fallback_to_sender():
    """Bug-fix: chybějící Subject → 'Email od X' (priorita operátorů)."""
    xml = _xml(
        '<model type="Email">'
        "<field name=\"From\">alice@example.com</field>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    assert specs[0].title == "Email od alice@example.com"


def test_map_location_floats():
    xml = _xml(
        '<model type="Location">'
        "<field name=\"Name\">Praha</field>"
        "<field name=\"StartTime\">2026-11-10T09:15:00Z</field>"
        "<field name=\"Latitude\">50.0755</field>"
        "<field name=\"Longitude\">14.4378</field>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    s = specs[0]
    assert s.artifact_type == "location" and s.title == "Praha"
    assert s.details["lat"] == pytest.approx(50.0755)
    assert s.details["lon"] == pytest.approx(14.4378)


def test_map_calendar_and_app_usage():
    xml = _xml(
        '<model type="CalendarEntry">'
        "<field name=\"Subject\">Schůzka</field>"
        "<field name=\"StartTime\">2026-11-12T10:00:00Z</field>"
        "</model>"
        '<model type="ApplicationUsage">'
        "<field name=\"Name\">com.whatsapp</field>"
        "<field name=\"LaunchCount\">42</field>"
        "</model>"
    )
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    cal, app = specs
    assert cal.artifact_type == "calendar_event" and cal.title == "Schůzka"
    assert app.artifact_type == "app_execution" and app.details["launchcount"] == 42.0


def test_map_party_alone_no_artifact():
    xml = _xml('<model type="Party"><field name="Name">Osin</field></model>')
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    assert specs == []


def test_map_text_truncated_to_max():
    body = "x" * 600
    xml = _xml(f'<model type="InstantMessage"><field name="Body">{body}</field></model>')
    specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
    assert len(specs[0].title or "") == 500


def test_map_broken_model_does_not_crash_batch():
    """Defenzivní: jeden zlomený model ≠ pád celého importu."""
    good = ModelSpec("Contact", {"Name": "OK"})
    bad = ModelSpec("Contact", {"Name": object()}, ())  # type: ignore[arg-type]
    specs = models_to_artifact_specs([bad, good])
    assert len(specs) == 1 and specs[0].title == "OK"


def test_parser_version_stable():
    assert PARSER_VERSION == "1.0"


# ── VCF kontakty (MSAB / ADB logical) ─────────────────────────

VCARD_SAMPLE = """BEGIN:VCARD
VERSION:3.0
FN:Petr Půda
TEL;TYPE=CELL:+420 605 123 456
EMAIL:petr.puda@example.com
END:VCARD
"""


def test_parse_vcf_basic_card():
    cards = parse_vcf(VCARD_SAMPLE)
    assert len(cards) == 1
    c = cards[0]
    assert c["name"] == "Petr Půda"
    assert c["phones"] == ["+420 605 123 456"]
    assert c["emails"] == ["petr.puda@example.com"]


def test_parse_vcf_continuation_lines():
    text = (
        "BEGIN:VCARD\n"
        "FN:Dlouhý Jméno\n"
        "TEL:\n"
        " +420777987654\n"
        "END:VCARD\n"
    )
    cards = parse_vcf(text)
    assert len(cards) == 1
    assert cards[0]["phones"] == ["+420777987654"]


def test_parse_vcf_multiple_cards_and_dedupe():
    text = (
        "BEGIN:VCARD\nFN:A\nTEL:111\nTEL:111\nEND:VCARD\n"
        "BEGIN:VCARD\nFN:B\nEMAIL:b@x.com\nEND:VCARD\n"
    )
    cards = parse_vcf(text)
    assert len(cards) == 2
    assert cards[0]["phones"] == ["111"]  # duplikát vynechán


def test_parse_vcf_missing_end_flushed():
    text = "BEGIN:VCARD\nFN:Bez Endu\nTEL:+420123\n"
    cards = parse_vcf(text)
    assert len(cards) == 1 and cards[0]["name"] == "Bez Endu"


def test_parse_vcf_empty_card_skipped():
    text = "BEGIN:VCARD\nVERSION:3.0\nEND:VCARD\n"
    assert parse_vcf(text) == []


def test_parse_vcf_cap_500_cards():
    text = "".join(f"BEGIN:VCARD\nFN:C{i}\nTEL:{i}\nEND:VCARD\n" for i in range(600))
    cards = parse_vcf(text)
    assert len(cards) == 500


# ── normalizace pro korelaci entit s kontakty ─────────────────

@pytest.mark.parametrize("raw,expected", [
    ("+420777123456", "+420777123456"),
    ("420 777 123 456", "+420777123456"),
])
def test_normalize_phone(raw: object, expected: object) -> None:
    if isinstance(raw, str):
        assert normalize_phone(raw) == expected


def test_normalize_phone_rejects():
    assert normalize_phone(None) is None
    assert normalize_phone("") is None
    assert normalize_phone("123") is None          # příliš krátké
    assert normalize_phone("+4+2077") is None      # '+' uprostřed


def test_normalize_email_cases():
    assert normalize_email("User@Example.COM") == "user@example.com"
    assert normalize_email(None) is None
    assert normalize_email("") is None
    assert normalize_email("nope@nodot") is None   # chybí tečka v doméně


# ── Signal decoder (Android signal.db — WIP mobile_extract.py) ──

def _signal_db(tmp_path, with_user: bool = True):
    import sqlite3

    from stopa.artifacts.mobile_extract import extract_mobile_artifacts

    db = tmp_path / "signal.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row  # stejný kontrakt jako produkční pipeline (sqlite_extract.py)
    conn.execute(
        "CREATE TABLE ZWAMSGSTOREMESSAGE ("
        "_ID INTEGER PRIMARY KEY, ZTEXT TEXT, ZENCRYPTED_TIMESTAMP REAL, ZFROM_PK INTEGER)"
    )
    if with_user:
        conn.execute("CREATE TABLE ZUSER (_ID INTEGER PRIMARY KEY, ADDRESS TEXT)")
        conn.execute("INSERT INTO ZUSER VALUES (1, '+420777987654')")
        rows = [(1, "Ahoj ze Signalu", 1762700000.0, 1), (2, None, 1762700001.0, 1)]
    else:
        rows = [(1, "Bez user tabulky", 1762700002.0, 99)]
    conn.executemany(
        "INSERT INTO ZWAMSGSTOREMESSAGE VALUES (?,?,?,?)", rows
    )
    conn.commit()

    arts = extract_mobile_artifacts(conn)
    conn.close()
    return arts


def test_signal_decoder_with_sender(tmp_path):
    from datetime import datetime, timezone

    arts = _signal_db(tmp_path, with_user=True)
    assert arts is not None and len(arts) == 1  # NULL ZTEXT vynechaná
    a = arts[0]
    assert a.artifact_type == "chat_message"
    assert a.title == "Ahoj ze Signalu"
    assert a.details["engine"] == "signal"
    assert a.details["sender_e164"] == "+420777987654"
    assert a.timestamp is not None and a.timestamp.tzinfo is not None
    # unix 1762700000 = 2025-11-09T14:53:20Z
    assert a.timestamp == datetime(2025, 11, 9, 14, 53, 20, tzinfo=timezone.utc)


def test_signal_decoder_without_user_table(tmp_path):
    arts = _signal_db(tmp_path, with_user=False)
    assert arts is not None and len(arts) == 1
    a = arts[0]
    assert "sender_e164" not in a.details  # fallback bez ZUSER


def test_signal_decoder_empty_message_filtered(tmp_path):
    """ZTEXT=None se WHERE filtruje; prázdný string → placeholder titulem."""
    import sqlite3

    from stopa.artifacts.mobile_extract import extract_mobile_artifacts

    db = tmp_path / "signal.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row  # stejný kontrakt jako produkční pipeline (sqlite_extract.py)
    conn.execute(
        "CREATE TABLE ZWAMSGSTOREMESSAGE ("
        "_ID INTEGER PRIMARY KEY, ZTEXT TEXT, ZENCRYPTED_TIMESTAMP REAL)"
    )
    conn.executemany("INSERT INTO ZWAMSGSTOREMESSAGE VALUES (?,?,?)", [
        (1, None, 1762700000.0),   # vynecháno WHERE clausem
        (2, "   ", 1762700001.0),  # prázdný → placeholder
    ])
    conn.commit()
    arts = extract_mobile_artifacts(conn)
    conn.close()
    assert arts is not None and len(arts) == 1
    assert arts[0].title == "(prázdná zpráva)"
