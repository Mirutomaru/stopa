"""STP-081 / vlna 37 — deterministický builder fixtury Apache/Nginx combined log.

Spustí se jednou; výstup ``access_sample.log`` se pinuje SHA-256 v manifestu
(drift důkazu = vstupní chyba). Obsah pokrývá smlouvu §C1–§C7:

- plné řádky (user, bytes, referer, UA),
- ``"-"`` pro user/bytes/referer/UA (explicitní None po normalizaci),
- leading-zeros size (``0461``) i nulové (``0``),
- TZ offsety +0200 / +0000 / -0530 (epoch matematika obou cest),
- request bez HTTP verze (protocol = None, §C7),
- **duplicitní řádek** (párování §3.2),
- poškozené/pokračovací řádky (obě cesty je přeskočí).

Determinismus: pevný list řádků + ``\\n``; žádný čas, žádný náhodný vstup.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

LINE_FULL = (
    '192.168.1.10 - alice [07/Aug/2003:19:48:56 +0200] '
    '"GET /index.html HTTP/1.1" 200 1461 "http://www.example.com/start.html" '
    '"Mozilla/4.08 [en] (Win98; I ;Nav)"'
)

LINES: list[str] = [
    # §C1–§C3 — plný záznam s user, referer a UA
    LINE_FULL,
    # bytes 0 + referer "-" — POST s query stringem
    '192.168.1.10 - alice [07/Aug/2003:19:48:56 +0200] "POST /submit.php?next=1 HTTP/1.1" 302 0 "-" "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"',
    # user bob, bytes "-", UA "-", protocol HTTP/1.0
    '10.0.0.5 bob - [07/Aug/2003:19:48:57 +0200] "HEAD /health HTTP/1.0" 200 - "-" "-"',
    # TZ offset +0000 — stejný wall-clock jako L1, jiná epocha (§C6)
    '203.0.113.7 - - [07/Aug/2003:19:48:56 +0000] "GET /tz-zero.html HTTP/1.1" 200 461 "-" "curl/8.1.2"',
    # TZ offset -0530 (záporný) + query s & a + (§C6)
    '198.51.100.23 - carol [07/Aug/2003:14:18:56 -0530] "GET /tz-negative.html?q=a+b&x=1 HTTP/1.1" 404 512 "-" "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"',
    # request bez HTTP verze — protocol None (§C7), jen 2 tokeny
    '198.51.100.99 - - [07/Aug/2003:19:48:56 +0200] "GET /no-protocol" 200 10 "-" "-"',
    # leading-zeros size — int normalizace obou cest (0461 → 461)
    '203.0.113.8 - dave [07/Aug/2003:20:00:00 +0200] "GET /leading-zero.html HTTP/1.1" 200 0461 "-" "curl/8.1.2"',
    # duplicitní řádek (byte-identická kopie L1) — párování §3.2
    LINE_FULL,
    # pokračovací/poškozené řádky — obě cesty je přeskočí:
    "garbage continuation line without structure",
    '192.168.1.10 - alice [07/Foo/2003:19:48:56 +0200] "GET /bad-month HTTP/1.1" 200 1 "-" "-"',
    '192.168.1.10 - alice [07/Aug/2003:19:48:56 +0200] "GET /short-status HTTP/1.1" 20 1 "-" "-"',
    '192.168.1.10 - alice [7/Aug/2003:19:48:56 +0200] "GET /one-digit-day HTTP/1.1" 200 1 "-" "-"',
    '192.168.1.10 - alice [07/Aug/2003:19:48:56 +0200] "GET /unclosed-ua HTTP/1.1" 200 1 "-" "Mozilla',
    "",
]

#: Očekávaný počet validních událostí (řádky 1–8, z toho řádek 8 = duplikát L1).
EXPECTED_EVENTS = 8


def build(out_path: Path) -> str:
    """Zapíše fixturu; vrátí SHA-256 hex (pro pin v manifestu)."""
    data = "\n".join(LINES) + "\n"
    out_path.write_bytes(data.encode("utf-8"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    target = Path(__file__).parent / "access_sample.log"
    sha = build(target)
    print(f"{target} {len(LINES)} raw lines, expected events={EXPECTED_EVENTS}")
    print(f"SHA256={sha}")
