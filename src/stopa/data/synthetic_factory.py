"""P1-1 — syntetická anonymizovaná data (deterministická per seed).

Generátory syntetických "důkazů" pro parser quality sady: hodnoty jsou
anonymizované (user-a@example.com, example.com…), žádná reálná osobní data.
Stejné ``seed`` → identické bajty výstupu (offline reprodukovatelnost).

I/O vrstva: funkce berou cílovou cestu a vrací ji zpět pro chaînování ve
fixturech. Sémantika chyb: typový nesoulad → ``TypeError``, semantická →
``ValueError``.
"""

from __future__ import annotations

import random
import sqlite3
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

#: anonymizovaný pool hodnot (žádné reálné domény/názvy)
_SENDERS = ("user-a@example.com", "user-b@example.cz", "admin@example.org")
_DOMAINS = ("example.com", "shop.example.cz", "mail.example.net", "docs.example.org")
_SUBJECTS = (
    "Faktura za listopad",
    "Re: schůzka",
    "Připomínky k projektu",
    "Meeting notes",
    "Nastavení sítě",
)

#: fixní časová kotva (2023-11-14T22:13:20Z) — determinismus nezávislý na current time
_BASE_EPOCH = 1_700_000_000

#: offset Windows epochy (1601) od Unix epochy v sekundách
_WINDOWS_OFFSET_S = 11_644_473_600

#: Apple CFAbsoluteTime epocha (2001-01-01 UTC) — unix sekundy
_APPLE_UNIX_OFFSET_S = 978_307_200


def _check_seed(seed: int) -> None:
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise TypeError(f"seed musí být int, got {type(seed).__name__}")


def make_chrome_history_db(path: Path, seed: int = 1, n_visits: int = 20) -> Path:
    """Syntetická Chrome/Edge history DB (urls+visits, µs od Windows epochy).

    Každých 17. visita má ``visit_time=0`` (poškozený záznam — parser musí
    přeskočit bez výjimky, viz ``WHERE visit_time > 0`` v extraktoru).
    """
    _check_seed(seed)
    if n_visits < 1:
        raise ValueError(f"n_visits >= 1, got {n_visits}")
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
        conn.execute(
            "CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER,"
            " visit_time INTEGER, from_visit INTEGER)"
        )
        for i in range(1, n_visits + 1):
            domain = rng.choice(_DOMAINS)
            title = f"{_SUBJECTS[i % len(_SUBJECTS)]} {i}"
            url = f"https://{domain}/page-{i:04d}"
            conn.execute("INSERT INTO urls VALUES (?, ?, ?)", (i, url, title))
            ts = _BASE_EPOCH + i * rng.randint(30, 600)
            visit_time = (ts + _WINDOWS_OFFSET_S) * 1_000_000 if i % 17 else 0
            conn.execute("INSERT INTO visits (url, visit_time) VALUES (?, ?)", (i, visit_time))
        conn.commit()
    finally:
        conn.close()
    return path


def make_firefox_places_db(path: Path, seed: int = 2, n_places: int = 10) -> Path:
    """Syntetická Firefox places DB (moz_places, last_visit_date = ms od Unix epochy)."""
    _check_seed(seed)
    if n_places < 1:
        raise ValueError(f"n_places >= 1, got {n_places}")
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT,"
            " title TEXT, last_visit_date INTEGER)"
        )
        for i in range(1, n_places + 1):
            domain = rng.choice(_DOMAINS)
            url = f"https://{domain}/doc-{i:04d}"
            title = f"{_SUBJECTS[i % len(_SUBJECTS)]} {i}"
            ms = (_BASE_EPOCH + i * rng.randint(30, 600)) * 1_000
            conn.execute(
                "INSERT INTO moz_places (url, title, last_visit_date) VALUES (?, ?, ?)",
                (url, title, ms),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def make_imessage_db(path: Path, seed: int = 3, n_messages: int = 10) -> Path:
    """Syntetická Apple iMessage chat.db (message.date = CFAbsoluteTime od 2001).

    Každých 7. zpráva má ``date=0`` (poškozený záznam → parser přeskočí).
    """
    _check_seed(seed)
    if n_messages < 1:
        raise ValueError(f"n_messages >= 1, got {n_messages}")
    rng = random.Random(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE handle (_id INTEGER PRIMARY KEY, address TEXT)")
        for j, sender in enumerate(_SENDERS, start=1):
            conn.execute("INSERT INTO handle VALUES (?, ?)", (j, sender))
        conn.execute(
            "CREATE TABLE message (_id INTEGER PRIMARY KEY, handle_id INTEGER,"
            " text TEXT, date REAL)"
        )
        for i in range(1, n_messages + 1):
            ts = _BASE_EPOCH + i * rng.randint(60, 900)
            apple_ts = float(ts - _APPLE_UNIX_OFFSET_S) if i % 7 else 0.0
            conn.execute(
                "INSERT INTO message (handle_id, text, date) VALUES (?, ?, ?)",
                (
                    rng.randint(1, len(_SENDERS)),
                    f"zpráva {i} — {_SUBJECTS[i % len(_SUBJECTS)]}",
                    apple_ts,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return path


def _q_encode(subject: str) -> str:
    """RFC 2047 Q encoding pro UTF-8 (mezera → _, ne-ASCII → =XX)."""
    out = []
    for b in subject.encode("utf-8"):
        if b == 0x20:
            out.append("_")
        elif 32 <= b <= 126:
            out.append(chr(b))
        else:
            out.append(f"={b:02x}")
    return "".join(out)


def make_mbox_file(path: Path, seed: int = 4, n_messages: int = 8) -> Path:
    """Syntetické mbox — více zpráv oddělených From řádky.

    Deterministicky míchá: Date hlavičky v různých časových pásmech (včetně
    neplatného data → parser None), RFC 2047 kódované předměty (B64/Q) a
    Unicode text (diakritika, emoji). Hodnoty anonymizované.
    """
    _check_seed(seed)
    if n_messages < 1:
        raise ValueError(f"n_messages >= 1, got {n_messages}")
    rng = random.Random(seed)
    lines: list[str] = []
    for i in range(1, n_messages + 1):
        sender = _SENDERS[i % len(_SENDERS)]
        ts = datetime.fromtimestamp(_BASE_EPOCH + i * rng.randint(60, 900), tz=timezone.utc)
        if i % 5 == 0:
            date_hdr = "Sat 31 Dec 2023 23:59:59"  # bez offsetu → parser None
        else:
            tz = rng.choice(
                [
                    timezone.utc,
                    timezone(timedelta(hours=2)),  # CET/CEST +0200
                    timezone(timedelta(hours=-5, minutes=-30)),  # EST -0530
                ]
            )
            date_hdr = format_datetime(ts.astimezone(tz))
        subject = _SUBJECTS[i % len(_SUBJECTS)]
        if i % 4 == 0:  # RFC 2047 B64
            encoded = b64encode(subject.encode("utf-8")).decode("ascii")
            subject_hdr = f"=?utf-8?B?{encoded}?="
        elif i % 4 == 2:  # RFC 2047 Q (diakritika)
            subject_hdr = f"=?utf-8?Q?{_q_encode(subject)}?="
        else:
            subject_hdr = subject
        body = f"Tělo zprávy {i} — diakritika ščžďň + emoji 🎯\nDruhý odstavec."
        lines.append(f"From {sender} {date_hdr}")
        lines.append(f"To: recipient-{i % 3}@example.org")
        lines.append(f"Subject: {subject_hdr}")
        lines.append(f"Date: {date_hdr}")
        lines.append(f"Message-ID: <synthetic-{seed}-{i}@example.com>")
        lines.append("")
        lines.append(body)
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
