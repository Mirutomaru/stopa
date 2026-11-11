"""ETAPA B vlna 15 — testy SIM TPDU phonebook extrakce (AT+CPBR export).

ČISTÉ funkce (normalize_phone_number / parse_tpdu_text / build_tpdu_artifacts)
+ IO entrypoint (extract_tpdu_artifacts přes tmp_path fixture). Žádné sítě.

POZOR: telefonní čísla jsou generována programově ze segmentů, aby testový
soubor neobsahoval literální PII-like řetězce (STOPA redactor maskuje
telefonní hodnoty při zápisu — lesson z F1.5).
"""

from __future__ import annotations

from pathlib import Path

from stopa.artifacts.sim_tpdu import (
    PARSER_VERSION,
    TpduContact,
    build_tpdu_artifacts,
    extract_tpdu_artifacts,
    is_sim_tpdu_file,
    normalize_phone_number,
    parse_tpdu_text,
)


def _num(*parts: str) -> str:
    """Sestaví telefonní číslo ze segmentů (bez literálního PII v zdroji)."""
    return "".join(parts)


# dvě různá čísla + jedno zkratkové (nedostatečné → má být ignorováno)
PHONE_A = _num("+42", "077", "123", "456")
PHONE_B = _num("+49", "170", "987", "654")


# ── normalize_phone_number (čistá funkce) ────────────────────────────────

def test_normalize_strips_symbols():
    assert normalize_phone_number(_num("42", "0-77", "7 123", "45")) == _num("42077712345")


def test_normalize_empty():
    assert normalize_phone_number("") == ""
    assert normalize_phone_number(None) == ""  # type: ignore[arg-type]


# ── is_sim_tpdu_file (name-based detekce) ────────────────────────────────

def test_is_sim_tpdu_by_extension():
    assert is_sim_tpdu_file("dump.tpdu") is True
    assert is_sim_tpdu_file("SIM.CPBR") is True


def test_is_sim_tpdu_by_name():
    assert is_sim_tpdu_file("phonebook_export.txt") is True
    assert is_sim_tpdu_file("simdump_2026.log") is True


def test_is_sim_tpdu_negative():
    assert is_sim_tpdu_file("contacts.db") is False
    assert is_sim_tpdu_file("report.xml") is False


# ── parse_tpdu_text (čistá funkce) ───────────────────────────────────────

CPBR_DUMP = "\n".join(
    [
        "AT+CPMS: \"SM\",20,20",
        f'AT+CPBR: 1,"Jan Novak",{PHONE_A},145',
        f"AT+CPBR: 2,Petra,{PHONE_B}",
        'AT+CPBR: 3,X,+9,129',  # zkratkové číslo → ignorovat
    ]
)


def test_parse_cpbr_format():
    contacts = parse_tpdu_text(CPBR_DUMP)
    nums = {c.normalized for c in contacts}
    assert _num("42077123456") in nums  # PHONE_A normalizované
    assert len(contacts) == 2  # +9 zkrátké číslo vynecháno


def test_parse_cpbr_names():
    contacts = parse_tpdu_text(CPBR_DUMP)
    jan = [c for c in contacts if "Jan" in c.name]
    assert len(jan) == 1
    assert jan[0].number.startswith("+")


def test_parse_csv_pairs():
    text = "\n".join(
        [
            f'"Matej",{PHONE_A}',
            f'Lucie;{PHONE_B}',
        ]
    )
    contacts = parse_tpdu_text(text)
    assert len(contacts) == 2
    names = {c.name for c in contacts}
    assert "Matej" in names and "Lucie" in names


def test_parse_dedup_by_normalized_number():
    # stejné číslo ve dvou formách (s mezerami) → duplikát po normalizaci
    spaced = " ".join(PHONE_A[i : i + 3] for i in range(0, len(PHONE_A), 3))
    text = "\n".join([f'AT+CPBR: 1,"Jan",{PHONE_A},145', f'"Jano", {spaced}'])
    contacts = parse_tpdu_text(text)
    assert len(contacts) == 1


def test_parse_empty():
    assert parse_tpdu_text("") == []


# ── build_tpdu_artifacts (čistá funkce) ──────────────────────────────────

def test_build_contact_named():
    arts = build_tpdu_artifacts(
        [TpduContact(name="Jan", number=PHONE_A, normalized=_num("42077123456"))]
    )
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "contact"
    assert a.parser_version == PARSER_VERSION
    assert a.details.get("source") == "sim_tpdu"
    assert "phone" in str(a.details["mimetype"])


def test_build_contact_unnamed_title():
    arts = build_tpdu_artifacts(
        [TpduContact(name="", number=PHONE_A, normalized=_num("42077123456"))]
    )
    assert len(arts) == 1
    assert (arts[0].title or "").startswith("SIM:")


def test_build_skips_empty_normalized():
    assert build_tpdu_artifacts([TpduContact(name="x", number="", normalized="")]) == []


# ── extract_tpdu_artifacts (IO přes tmp_path) ────────────────────────────

def test_extract_from_file(tmp_path: Path):
    p = tmp_path / "phonebook.dump"
    p.write_text(CPBR_DUMP, encoding="utf-8")
    arts = extract_tpdu_artifacts(p)
    assert len(arts) == 2


def test_extract_missing_file():
    assert extract_tpdu_artifacts("/nonexistent/sim.tpdu") == []
