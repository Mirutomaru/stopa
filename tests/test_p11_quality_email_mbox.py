"""P1-1 pilot — quality sada pro parser ``email_mbox`` (všech 8 kategorií).

Konvence markeru: řádek ``# quality: <kategorie>`` deklaruje pokrytí testu.
Syntetická data přes ``stopa.data.synthetic_factory.make_mbox_file``
(deterministické per seed) + inline mbox s exaktními Date hlavičkami pro tz asercce.
"""

from __future__ import annotations

import calendar
from datetime import datetime
from email.utils import parsedate_to_datetime

from stopa.artifacts.email_mbox import extract_email_artifacts
from stopa.data.synthetic_factory import make_mbox_file


def _epoch(dt: datetime | None) -> float | None:
    """Robustní epoch srovnání bez ohledu na tz-aware/naive razítko."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.timestamp()
    return calendar.timegm(dt.utctimetuple())


# quality: positive
def test_positive_valid_mbox(tmp_path):
    """Validní mbox → email_message artefakty pro každou zprávu."""
    p = make_mbox_file(tmp_path / "m.mbox", seed=4, n_messages=8)
    arts = extract_email_artifacts(p)
    assert len(arts) >= 7  # i=5 má neplatné Date → confidence 0.6, ale artefakt existuje
    assert all(a.artifact_type == "email_message" for a in arts)


# quality: negative
def test_negative_binary_garbage(tmp_path):
    """Binární smetí → bez výjimky (prázdný či částečný výsledek)."""
    p = tmp_path / "garbage.bin"
    p.write_bytes(bytes(range(256)) * 4)
    arts = extract_email_artifacts(p)
    assert isinstance(arts, list)


# quality: negative
def test_negative_no_from_lines(tmp_path):
    """Text bez mbox struktury (žádné From řádky) → bez výjimky."""
    p = tmp_path / "plain.txt"
    p.write_text("jen textový soubor bez mbox struktury\n", encoding="utf-8")
    arts = extract_email_artifacts(p)
    assert isinstance(arts, list)


# quality: boundary
def test_boundary_single_message(tmp_path):
    p = make_mbox_file(tmp_path / "one.mbox", seed=6, n_messages=1)
    arts = extract_email_artifacts(p)
    assert len(arts) == 1


# quality: boundary
def test_boundary_empty_body(tmp_path):
    """Zpráva s prázdným tělem stále produkuje artefakt."""
    p = tmp_path / "empty-body.mbox"
    p.write_text(
        "From user-a@example.com Mon Nov 13 20:00:00 2026\n"
        "To: r@example.org\nSubject: (prázdné tělo)\n"
        "Date: Mon, 13 Nov 2023 22:00:00 +0200\n"
        "Message-ID: <empty@synthetic>\n\n",
        encoding="utf-8",
    )
    arts = extract_email_artifacts(p)
    assert len(arts) == 1


# quality: corrupted
def test_corrupted_truncated_mbox(tmp_path):
    """Oříznutí souboru na třetinu → bez výjimky, ≤ původní počet zpráv."""
    full = make_mbox_file(tmp_path / "full.mbox", seed=7, n_messages=20)
    text = full.read_text(encoding="utf-8")
    cut = tmp_path / "cut.mbox"
    cut.write_text(text[: len(text) // 3], encoding="utf-8")
    arts = extract_email_artifacts(cut)
    assert isinstance(arts, list) and len(arts) <= 20


# quality: tz
def test_tz_date_headers_multiple_offsets(tmp_path):
    """Date hlavičky +0200/-0530/+0000 → exaktní UTC (nezávislý parsování)."""
    p = tmp_path / "tz.mbox"
    lines: list[str] = []
    expected: dict[int, float] = {}
    for idx, date_hdr in enumerate(
        [
            "Mon, 13 Nov 2023 22:00:00 +0200",
            "Tue, 14 Nov 2023 18:30:00 -0530",
            "Wed, 15 Nov 2023 09:00:00 +0000",
        ],
        start=1,
    ):
        lines.append(f"From user-a@example.com {date_hdr}")
        lines.append("To: r@example.org")
        lines.append(f"Subject: tz test {idx}")
        lines.append(f"Date: {date_hdr}")
        lines.append(f"Message-ID: <tz-{idx}@synthetic>")
        lines.append("")
        lines.append("telo zpravy")
        lines.append("")
        expected[idx] = parsedate_to_datetime(date_hdr).timestamp()
    p.write_text("\n".join(lines), encoding="utf-8")
    arts = extract_email_artifacts(p)
    assert len(arts) == 3
    got = sorted(_epoch(a.timestamp) or -1.0 for a in arts)
    want = sorted(expected.values())
    assert all(abs(g - w) < 1.0 for g, w in zip(got, want))


# quality: encoding locale
def test_encoding_rfc2047_decoded_and_unicode_body(tmp_path):
    """RFC 2047 B64/Q předměty se dekódují; Unicode tělo roundtrip."""
    p = make_mbox_file(tmp_path / "enc.mbox", seed=8, n_messages=16)
    arts = extract_email_artifacts(p)
    assert len(arts) >= 15
    blob = " ".join(str(a.title or "") + str(a.details) for a in arts)
    # B64 (i%4==0: i=12 → _SUBJECTS[2]) a Q (i%4==2) dekódované jako plain text
    assert "Připomínky k projektu" in blob
    # Unicode tělo (diakritika) se nepoškozuje
    assert "diakritika" in blob


# quality: locale
def test_locale_czech_values(tmp_path):
    """České hodnoty v hlavičkách i těle zůstanou čitelné."""
    p = tmp_path / "locale.mbox"
    p.write_text(
        "From Odesílatel Čech <od@příklad.cz> Mon Nov 13 20:00:00 2026\n"
        "To: příjemce@example.org\nSubject: Důležité: schůzka v pátek\n"
        "Date: Mon, 13 Nov 2023 22:00:00 +0100\n"
        "Message-ID: <locale@synthetic>\n\n"
        "Hezký den,\nděkuji za potvrzení.\n",
        encoding="utf-8",
    )
    arts = extract_email_artifacts(p)
    assert len(arts) == 1
    blob = str(arts[0].title) + str(arts[0].details)
    assert "Důležité" in blob and "schůzka" in blob


# quality: size
def test_size_300_messages(tmp_path):
    """Limitní velikost — 300 zpráv se vyparsoví bez ztráty."""
    p = make_mbox_file(tmp_path / "big.mbox", seed=9, n_messages=300)
    arts = extract_email_artifacts(p)
    assert len(arts) == 300
