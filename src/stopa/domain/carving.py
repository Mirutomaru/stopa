"""Carving engine — hledání souborů podle magic bytes v nealokovaném prostoru.

Ekvivalent X-Ways Forensics / FTK carving (foremost/binwalk style).
ČISTÁ funkce nad bajty — žádný IO → 100% offline testovatelné.

Strategie:
- Pro každý offset v bufferu zkusí všechny signatury s offsetem 0 (hlavičky).
- Duplicity se potlačí: pokud je na daném offsetu více signatur, vyhraje ta
  s vyšší prioritou (pořadí v SIGNATURES) — stejná logika jako detect_signature.
- Pro některé typy odhadneme konec (PNG IEND, JPEG EOI, PDF %%EOF) → velikost.

Výsledek je seznam ``CarvedFile`` kandidátů; reálné extrakce dělá IO vrstva.
"""

from __future__ import annotations

from dataclasses import dataclass

from stopa.domain.signatures import SIGNATURES, _refine_zip


@dataclass(frozen=True)
class CarvedFile:
    """Kandidát na vykarvaný soubor — offset + typ + odhadovaná velikost."""

    offset: int
    sig_type: str  # kanonický typ (png/jpeg/pdf/zip/...)
    family: str  # rodina (image/document/archive/...)
    size_estimate: int | None = None  # bytes, pokud se dá konec určit


# Signatury s offsetem 0 → rychlá tabulka magic → (typ, rodina) v pořadí priority.
def _header_signatures() -> list[tuple[bytes, str, str]]:
    return [(magic, typ, family) for off, magic, typ, family in SIGNATURES if off == 0]


# Konecové markery pro odhad velikosti (typ → hledaný konec).
def _estimate_size(data: bytes, offset: int, sig_type: str) -> int | None:
    """Odhad velikosti vykarvaného souboru podle koncového markeru."""
    start = offset
    if sig_type == "png":
        # IEND chunk: 49 45 4E 44 AE 42 60 82 (poslední 8 bajtů PNG)
        end = data.find(b"IEND\xae\x42\x60\x82", start + 8)
        if end != -1:
            return end + 8 - start
    elif sig_type == "jpeg":
        # EOI marker FF D9 (hledáme od offsetu 2, aby se nesešlo v hlavičce)
        end = data.find(b"\xff\xd9", start + 2)
        if end != -1:
            return end + 2 - start
    elif sig_type == "pdf":
        # %%EOF — poslední výskyt před koncem bufferu (PDF může mít trailer)
        end = data.rfind(b"%%EOF")
        if end != -1 and end > start:
            return end + 5 - start
    return None


def carve(data: bytes, min_size: int = 64) -> list[CarvedFile]:
    """Najde všechny kandidáty na soubory v bufferu podle magic bytes.

    ``min_size`` — minimální odhadovaná velikost (bytes); kandidáti bez odhadu
    se berou vždy (konec se určí až při extrakci).
    """
    if not data:
        return []
    headers = _header_signatures()
    out: list[CarvedFile] = []
    seen_offsets: set[int] = set()

    for magic, typ, family in headers:
        ml = len(magic)
        # Najdi všechny výskyty magiku v bufferu (ne-překrývající se)
        pos = data.find(magic)
        while pos != -1:
            if pos not in seen_offsets:
                size_est = _estimate_size(data, pos, typ)
                # zip refine (docx/xlsx/apk) — stejná logika jako detect_signature
                final_typ, final_family = typ, family
                if typ == "zip":
                    refined = _refine_zip(data[pos : pos + 65536])
                    if refined:
                        final_typ, final_family = refined
                # filtrování podle min_size (jen pokud máme odhad)
                if size_est is None or size_est >= min_size:
                    seen_offsets.add(pos)
                    out.append(
                        CarvedFile(
                            offset=pos,
                            sig_type=final_typ,
                            family=final_family,
                            size_estimate=size_est,
                        )
                    )
            pos = data.find(magic, pos + ml)

    # seřadit podle offsetu pro deterministický výstup
    out.sort(key=lambda c: c.offset)
    return out


def carve_by_family(data: bytes, family: str, min_size: int = 64) -> list[CarvedFile]:
    """Filtr carving výsledků podle rodiny (image/document/archive/...)."""
    return [c for c in carve(data, min_size=min_size) if c.family == family]
