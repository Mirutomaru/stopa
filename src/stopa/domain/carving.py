"""Carving engine — hledání souborů podle magic bytes v nealokovaném prostoru.

Ekvivalent X-Ways Forensics / FTK carving (foremost/binwalk style).
ČISTÁ funkce nad bajty — žádný IO → 100% offline testovatelné.

Strategie:
- Pro každý offset v bufferu zkusí všechny signatury s offsetem 0 (hlavičky).
- Duplicity se potlačí: pokud je na daném offsetu více signatur, vyhraje ta
  s vyšší prioritou (pořadí v SIGNATURES) — stejná logika jako detect_signature.

Odhad velikosti z INTERNÍCH STRUKTUR (ne jen pevné patičky):
- PNG: IEND chunk (musí být poslední).
- JPEG: chůze po segmentech (APPn/SOF/SOS); skenovací data mezi SOS a dalším
  markerem se přeskočí → falešné FF D9 uvnitř dat neklame; fallback na první EOI.
- MP4/MOV (ISO BMFF): chůze po boxech (size+type, largesize==1 → 64b);
  konec = první nevalidní box za posledním validním.
- PDF: poslední %%EOF v omezeném okně + validace přes ``startxref`` offset.
- ZIP/OOXML/APK (docx/xlsx/pptx): EOCD (End Of Central Directory) na konci —
  validace přes offset Central Directory (musí ukazovat na PK\x01\x02 a CD musí
  končit přesně na pozici EOCD) → bezchybný rozsah archivu; ZIP64 podporováno.
- RAR5/RAR4: chůze po blocích až po END_ARCHIVE / ENDARC markeru → přesný konec.

Streaming pro velké obrazy:
- ``carve_file()`` — mmap + klouzavé okno (window/overlap), takže hlavičky na
  hranici bloků se najdou; kandidáti se deduplikují podle absolutního offsetu.
  Velikost se odhaduje nad celým obrazem (mmap slice), ne jen v okně.

Výsledek je seznam ``CarvedFile`` kandidátů; reálné extrakce dělá IO vrstva.
"""

from __future__ import annotations

import mmap
import os
from dataclasses import dataclass
from pathlib import Path

from stopa.domain.signatures import SIGNATURES, _refine_zip

# Maximální rozsah pro odhad velikosti jednoho kandidáta (bytes).
MAX_SIZE_SCAN = 64 * 1024 * 1024


@dataclass(frozen=True)
class CarvedFile:
    """Kandidát na vykarvaný soubor — offset + typ + odhadovaná velikost."""

    offset: int  # absolutní offset v obrazu (carve_file) / bufferu (carve)
    sig_type: str  # kanonický typ (png/jpeg/pdf/zip/...)
    family: str  # rodina (image/document/archive/...)
    size_estimate: int | None = None  # bytes, pokud se dá konec určit


# Signatury s offsetem 0 → rychlá tabulka magic → (typ, rodina) v pořadí priority.
def _header_signatures() -> list[tuple[bytes, str, str]]:
    return [(magic, typ, family) for off, magic, typ, family in SIGNATURES if off == 0]


# Signatury s offsetem > 0 (MP4 'ftyp' na offsetu 4) — validace box hlavičky.
def _offset_signatures() -> list[tuple[int, bytes, str, str]]:
    return [(off, magic, typ, family) for off, magic, typ, family in SIGNATURES if off > 0]


def _valid_bmff_box(data: bytes, pos: int) -> bool:
    """Pos `pos` je začátek ISO BMFF boxu? (4B size + tag na offsetu 4)."""
    if len(data) - pos < 8:
        return False
    size = int.from_bytes(data[pos : pos + 4], "big")
    if size == 1:  # largesize — box sahá dál, stačí validní hlavička
        return True
    return 8 <= size <= len(data) - pos


# ── odhady velikosti z interních struktur ────────────────────────────────

def _png_size(buf: bytes) -> int | None:
    """Velikost PNG = pozice konce IEND chunku (po CRC).

    Chůze po chunkách: [length:4][tag:4][data:length][crc:4] → další na i+12+len.
    Neplatná struktura (negativní délka, tag mimo ASCII) → None.
    """
    n = len(buf)
    if n < 8 + 12:  # minimálně hlavička + jeden chunk
        return None
    i = 8  # za PNG signaturou
    while i + 8 <= n:
        length = int.from_bytes(buf[i : i + 4], "big")
        tag = buf[i + 4 : i + 8]
        end = i + 12 + length  # konec tohoto chunku (po CRC)
        if tag == b"IEND" and end <= n:
            return end  # IEND má vždy délku 0 — kontrola tagu PŘED validací délky
        if not (0 < length < 1 << 24):  # sanity check délky ostatních chunků
            break
        i = end
    # fallback: nevalidní chunk struktura → hledání IEND magiku (poškozené soubory)
    end = buf.find(b"IEND\xae\x42\x60\x82")
    if end != -1:
        return end + 8
    return None


def _jpeg_size(buf: bytes) -> int | None:
    """Chůze po JPEG segmentech; skenovací data (SOS→marker) se přeskočí.

    Vrací offset za EOI, nebo None pokud struktura nedává smysl → volající
    použije fallback (první FF D9).
    """
    i = 2  # za SOI (FFD8)
    n = len(buf)
    while i + 4 <= n:
        if buf[i] != 0xFF:
            i += 1
            continue
        marker = buf[i + 1]
        if marker == 0xD9:  # EOI — konec
            return i + 2
        if marker == 0xDA:  # SOS — skenovací data až do EOI / validního markru
            # v datech je každý FF escapován jako FF 00 (fill byte) nebo FF FF;
            # nevalidní FF xx se PŘESKOČE (poškozený marker), jen EOI končí soubor
            j = i + 4
            while j + 1 <= n:
                if buf[j] != 0xFF:
                    j += 1  # běžné skenovací datum (jeden bajt)
                    continue
                m2 = buf[j + 1]
                if m2 == 0x00 or m2 == 0xFF:
                    j += 1  # fill byte / escapované FF
                    continue
                if m2 >= 0xC0 and m2 != 0xD8:
                    break  # validní marker (EOI nebo jiný) → konec skenování
                j += 2  # nevalidní FF xx → přeskočit
            if j + 1 > n:
                return None
            if buf[j + 1] == 0xD9:  # EOI — soubor končí za ním
                return min(j + 2, n)
            return j  # jiný validní marker → konec skenovacích dat
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            i += 2  # samostatné markery bez délky
            continue
        length = int.from_bytes(buf[i + 2 : i + 4], "big")
        if length < 2 or i + 2 + length > n:
            return None  # poškozená struktura → fallback
        i += 2 + length
    return None


def _mp4_size(buf: bytes) -> int | None:
    """ISO BMFF (MP4/MOV): chůze po boxech; konec = první nevalidní box.

    size==1 → 64bitové largesize; size==0 → box sahá do konce souboru
    (nedá se určit z bufferu → None).
    """
    i = 0
    n = len(buf)
    total = 0
    boxes = 0
    while i + 8 <= n:
        size = int.from_bytes(buf[i : i + 4], "big")
        if size == 1:
            if i + 16 > n:
                return None
            size = int.from_bytes(buf[i + 8 : i + 16], "big")
        elif size == 0:
            break  # box do konce souboru — konec nedá se určit
        if size < 8 or i + size > n:
            break  # nevalidní box → pravděpodobně konec souboru
        total += size
        boxes += 1
        i += size
    # minimálně 2 validní boxy a smysluplná velikost
    if boxes >= 2 and total >= 32:
        return total
    return None


def _pdf_size(buf: bytes) -> int | None:
    """PDF: poslední %%EOF v bufferu + validace přes startxref (pokud je)."""
    eof = buf.rfind(b"%%EOF")
    if eof == -1:
        return None
    size = eof + 5
    # strukturní validace: startxref musí ukazovat na xref tabulku před EOF
    sx = buf.rfind(b"startxref", 0, eof)
    if sx != -1:
        j = sx + len(b"startxref")
        while j < len(buf) and buf[j : j + 1].isspace():
            j += 1
        k = j
        while k < len(buf) and buf[k : k + 1].isdigit():
            k += 1
        if k > j:
            xref_off = int(buf[j:k])
            if 0 < xref_off < size and buf[xref_off : xref_off + 4] == b"xref":
                return size
    return size


# ── ZIP / OOXML / APK — přesný rozsah přes EOCD (End Of Central Directory) ──

def _zip_size(buf: bytes) -> int | None:
    """Přesná velikost ZIP archivu validací End Of Central Directory.

    Strategie: najít první EOCD (PK\\x05\\x06), jehož Central Directory
    strukturně sedí — ``cd_offset + cd_size == pozice_EOCD`` a na
    ``cd_offset`` musí být signatura central directory entry (PK\\x01\\x02).
    Tím se vyloučí cizí EOCD z jiného archivu v obrazu. ZIP64: pokud klasická
    validace selže, zkusí se ZIP64 EOCD locator (PK\\x06\\x07) + record
    (PK\\x06\\x06) s 64bitovými offsety.

    Vrací velikost archivu (začátek → konec EOCD včetně commentu), nebo None.
    """
    n = len(buf)
    if n < 22:
        return None
    pos = buf.find(b"PK\x05\x06")
    for _ in range(4096):  # omezený počet EOCD kandidátů (velké obrazy)
        if pos == -1:
            return None
        eocd_end = pos + 22
        if eocd_end > n:
            return None
        comment_len = int.from_bytes(buf[pos + 20 : pos + 22], "little")
        total = eocd_end + comment_len
        if total > n:
            return None
        cd_size = int.from_bytes(buf[pos + 12 : pos + 16], "little")
        cd_off = int.from_bytes(buf[pos + 16 : pos + 20], "little")
        # strukturní validace: CD musí končit přesně na EOCD a začínat PK\x01\x02
        if (
            cd_size > 0
            and cd_off + cd_size == pos
            and buf[cd_off : cd_off + 4] == b"PK\x01\x02"
        ):
            return total
        # ZIP64: locator PK\x06\x07 těsně před EOCD → 64bitový EOCD record
        loc = pos - 20
        if loc >= 4 and buf[loc : loc + 4] == b"PK\x06\x07":
            z64_off = int.from_bytes(buf[loc + 8 : loc + 16], "little")
            if (
                z64_off + 56 <= n
                and buf[z64_off : z64_off + 4] == b"PK\x06\x06"
            ):
                cd_size64 = int.from_bytes(buf[z64_off + 40 : z64_off + 48], "little")
                cd_off64 = int.from_bytes(buf[z64_off + 48 : z64_off + 56], "little")
                if (
                    cd_size64 > 0
                    and cd_off64 + cd_size64 == z64_off
                    and buf[cd_off64 : cd_off64 + 4] == b"PK\x01\x02"
                ):
                    return total
        pos = buf.find(b"PK\x05\x06", pos + 4)
    return None


# ── RAR — chůze po blocích až po END markeru ───────────────────────────────

def _rar_varint(buf: bytes, i: int) -> tuple[int | None, int]:
    """RAR5 VarInt: 7bitové skupiny, MSB = pokračování. Vrací (hodnota, konec)."""
    value = 0
    shift = 0
    n = len(buf)
    while i < n and shift <= 63:
        b = buf[i]
        value |= (b & 0x7F) << shift
        i += 1
        if not (b & 0x80):
            return value, i
        shift += 7
    return None, i


def _rar5_size(buf: bytes) -> int | None:
    """RAR5: chůze po blocích; konec = End of archive header (type 5).

    Marker je 8 B ``Rar!\\x1a\\x07\\x01\\x00`` (dle 7-Zip kMarker). Blok dle specu
    rarlab.com/technote.htm: CRC32(4) + HeaderSize(vint), pak tělo o HeaderSize
    bajtech začínající HeaderType(vint) + Flags(vint); DataSize(vint) jen pokud je
    flag 0x0002 (data area následuje za tělem). RAR nic nečte za END headerem.
    Jakákoli nevalidní struktura → None (fallback na neznámou velikost).
    """
    n = len(buf)
    if buf[:8] != b"Rar!\x1a\x07\x01\x00":
        return None
    i = 8
    for _ in range(8192):  # sanity limit počtu bloků
        if i + 4 > n:
            return None
        hs, j = _rar_varint(buf, i + 4)  # HeaderSize — tělo začíná na j
        if hs is None or hs < 2 or j + hs > n:
            return None
        body_end = j + hs
        htype, k = _rar_varint(buf, j)  # HeaderType (první pole těla)
        flags, m = _rar_varint(buf, k)
        if htype is None or flags is None or m > body_end:
            return None
        pos = m
        if flags & 0x0001:  # Extra area size — přeskočit (DataSize za ním)
            _eas, pos2 = _rar_varint(buf, pos)
            if _eas is None or pos2 > body_end:
                return None
            pos = pos2
        data_size = 0
        if flags & 0x0002:  # Data area size — data následují za tělem hlavičky
            ds, p = _rar_varint(buf, pos)
            if ds is None or p > body_end:
                return None
            data_size = ds
        end = body_end + data_size
        if htype == 5:  # End of archive — RAR nic nečte za tímto blokem
            return end if end <= n else None
        i = end
    return None


def _rar4_size(buf: bytes) -> int | None:
    """RAR4: chůze po blocích; konec = ENDARC blok (type 0x72).

    Marker je 7 B ``Rar!\\x1a\\x07\\x00``. Blok dle technote: HEAD_CRC(2) + Type(1)
    + Flags(2) + HeadSize(2); AddSize(4) jen pokud je flag 0x8000 (u souborových
    bloků vždy — pak AddSize == PackSize a celá velikost bloku = HeadSize + AddSize).
    Konzervativní sanity checky — pochybnost → None (fallback).
    """
    n = len(buf)
    if buf[:7] != b"Rar!\x1a\x07\x00":
        return None
    i = 7  # za marker blokem (signatura je samostatně ověřena výše)
    for _ in range(8192):
        if i + 7 > n:
            return None
        btype = buf[i + 2]
        flags = int.from_bytes(buf[i + 3 : i + 5], "little")
        head_size = int.from_bytes(buf[i + 5 : i + 7], "little")
        add_size = 0
        if flags & 0x8000:
            if i + 11 > n:
                return None
            add_size = int.from_bytes(buf[i + 7 : i + 11], "little")
        total = head_size + add_size
        if total < 7 or i + total > n:
            return None
        if btype == 0x72:  # ENDARC — konec archivu za tímto blokem
            return i + total
        i += total
    return None


def _rar_size(buf: bytes) -> int | None:
    """RAR (v4/v5) — přesný rozsah podle verze signatury.

    RAR5 marker má 8 B (``...\\x01\\x00``), RAR4 jen 7 B (``...\\x00``); rozlišení
    podle byte na pozici 6 (0x01 = v5, 0x00 = v4).
    """
    if len(buf) > 7 and buf[6] == 0x01:
        return _rar5_size(buf)
    return _rar4_size(buf)


# Typy vzniklé zip refine (docx/xlsx/...) sdílejí ZIP strukturu.
_ZIP_TYPES = {"zip", "docx", "xlsx", "pptx", "ooxml", "apk"}


def _estimate_size(data: bytes, offset: int, sig_type: str) -> int | None:
    """Odhad velikosti vykarvaného souboru podle interních struktur.

    ``data`` musí začínat na ``offset`` (hlavička kandidáta).
    """
    if sig_type == "png":
        return _png_size(data)
    if sig_type == "jpeg":
        est = _jpeg_size(data)
        if est is not None:
            return est
        # fallback: první EOI marker (FF D9) — jednoduché JPEG bez segmentů
        end = data.find(b"\xff\xd9", 2)
        if end != -1:
            return end + 2
    elif sig_type == "iso_bmff":
        return _mp4_size(data)
    elif sig_type == "pdf":
        return _pdf_size(data)
    if sig_type in _ZIP_TYPES:  # zip/docx/xlsx/pptx/ooxml/apk — EOCD validace
        return _zip_size(data)
    if sig_type == "rar":
        return _rar_size(data)
    return None


def _add_candidate(
    out: list[CarvedFile],
    seen_offsets: set[int],
    data: bytes,
    pos: int,
    typ: str,
    family: str,
    min_size: int,
) -> None:
    """Přidá kandidáta na offset `pos` (dedup + zip refine + min_size filtr)."""
    if pos in seen_offsets:
        return
    size_est = _estimate_size(data[pos :], 0, typ)
    final_typ, final_family = typ, family
    if typ == "zip":
        refined = _refine_zip(data[pos : pos + 65536])
        if refined:
            final_typ, final_family = refined
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


def carve(data: bytes, min_size: int = 64) -> list[CarvedFile]:
    """Najde všechny kandidáty na soubory v bufferu podle magic bytes.

    ``min_size`` — minimální odhadovaná velikost (bytes); kandidáti bez odhadu
    se berou vždy (konec se určí až při extrakci).

    Signatury s offsetem 0 se hledají přímo; signatury s offsetem > 0 (MP4
    'ftyp' na offsetu 4) se validují přes ``_valid_bmff_box`` — kandidát
    začíná na začátku boxu, ne na magiku.
    """
    if not data:
        return []
    out: list[CarvedFile] = []
    seen_offsets: set[int] = set()

    # 1) signatury s offsetem 0 — rychlé hledání magic
    for magic, typ, family in _header_signatures():
        ml = len(magic)
        pos = data.find(magic)
        while pos != -1:
            _add_candidate(out, seen_offsets, data, pos, typ, family, min_size)
            pos = data.find(magic, pos + ml)

    # 2) signatury s offsetem > 0 — validace kontextu (box hlavička)
    for off, magic, typ, family in _offset_signatures():
        pos = data.find(magic)
        while pos != -1:
            start = pos - off  # začátek kandidáta (začátek boxu)
            if start >= 0 and _valid_bmff_box(data, start):
                _add_candidate(out, seen_offsets, data, start, typ, family, min_size)
            pos = data.find(magic, pos + len(magic))

    # seřadit podle offsetu pro deterministický výstup
    out.sort(key=lambda c: c.offset)
    return out


def carve_by_family(data: bytes, family: str, min_size: int = 64) -> list[CarvedFile]:
    """Filtr carving výsledků podle rodiny (image/document/archive/...)."""
    return [c for c in carve(data, min_size=min_size) if c.family == family]


def carve_file(
    path: Path | str,
    window: int = 16 * 1024 * 1024,
    overlap: int = 64 * 1024,
    min_size: int = 64,
) -> list[CarvedFile]:
    """Streaming carving celého obrazu přes mmap + klouzavé okno.

    - Okno ``window`` (výchozí 16 MB) s překryvem ``overlap`` (64 KB) → hlavičky
      na hranici bloků se najdou; kandidáti se deduplikují podle absolutního offsetu.
    - Odhad velikosti běží nad celým obrazem (mmap slice do MAX_SIZE_SCAN),
      ne jen v okně → přesné koncové markery i u velkých souborů.

    Vrací kandidáty seřazené podle absolutního offsetu.
    """
    if overlap >= window:
        raise ValueError("overlap musí být menší než window")
    out: list[CarvedFile] = []
    seen_offsets: set[int] = set()
    with open(path, "rb") as f:
        size_file = os.fstat(f.fileno()).st_size
        if size_file == 0:
            return []
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            total = len(mm)
            pos = 0
            while pos < total:
                end = min(pos + window, total)
                chunk = bytes(mm[pos:end])
                for c in carve(chunk, min_size=min_size):
                    abs_off = pos + c.offset
                    if abs_off in seen_offsets:
                        continue
                    seen_offsets.add(abs_off)
                    # přesný odhad nad celým obrazem (ne jen v okně)
                    size_est = _estimate_size(
                        bytes(mm[abs_off : abs_off + MAX_SIZE_SCAN]), 0, c.sig_type
                    )
                    out.append(
                        CarvedFile(
                            offset=abs_off,
                            sig_type=c.sig_type,
                            family=c.family,
                            size_estimate=size_est if size_est is not None else c.size_estimate,
                        )
                    )
                if end == total:
                    break
                pos = end - overlap  # klouzavé okno s překryvem
        finally:
            mm.close()
    out.sort(key=lambda c: c.offset)
    return out
