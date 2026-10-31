"""Disk image processing pipeline — FÁZE 5 (X-Ways Forensics / The Sleuth Kit).

Orchestrace nad IO vrstvou ``data/tsk.py`` a čistou logikou
``domain/image_types.py`` + ``domain/carving.py``:

1. Detekce typu obrazu (E01/AFF4/RAW-DD + podkladový file system) — čistá funkce.
2. Partice/volume přes TSK ``mmls``.
3. Soubory v každé partici přes TSK ``fls -r -l -p`` → upsert do case DB jako
   FileRecord (rel_path = cesta v obrazu) + signatura z extrahovaného obsahu.
4. Jeden artifact ``disk_image`` s přehledem particí a počtem souborů (timeline).
5. Volitelné carving nealokovaného prostoru — STREAMING přes mmap (sliding window,
   odhady velikosti z interních struktur JPEG/MP4/PDF).

Vše defenzivní: chybějící TSK / neplatný obraz → chyby v ``errors``, ne traceback.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from stopa.data.db import CaseDB
from stopa.data.tsk import (
    Partition,
    TskError,
    extract_file,
    image_partitions,
    list_files,
)
from stopa.domain.carving import carve_file
from stopa.domain.image_types import detect_image_type, filesystem_fstype, is_container
from stopa.domain.signatures import detect_signature
from stopa.models import Artifact, FileRecord, ProcessingProfile

_log = logging.getLogger(__name__)

# Kolik bajtů obsahu extrahovat pro signaturu (hlavička stačí).
_SIG_HEAD = 65_536


@dataclass
class ImageSummary:
    """Výsledek zpracování jednoho diskového obrazu."""

    image_type: str | None = None
    description: str | None = None
    partitions: list[Partition] = field(default_factory=list)
    files_total: int = 0
    bytes_total: int = 0
    signatures_detected: int = 0
    carved_candidates: int = 0
    errors: list[str] = field(default_factory=list)
    fde_unlocked: bool = False  # FÁZE 6b — obraz byl FDE a dešifrovaný heslem


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1] or path


def process_disk_image(
    db: CaseDB,
    source_id: str,
    image_path: Path | str,
    profile: ProcessingProfile,
    carve_free: bool = False,
) -> ImageSummary:
    """Zpracuje diskový obraz a zapíše soubory + artifact do case DB.

    ``carve_free`` — pokud True, prohledá celý obraz carving engine (magic bytes)
    a přidá počet kandidátů (pro nealokovaný prostor / smazané soubory).
    """
    image_path = Path(image_path).expanduser()
    summary = ImageSummary()

    if not image_path.exists():
        summary.errors.append(f"Obraz neexistuje: {image_path}")
        return summary

    # 1) typ obrazu (čistá funkce, stačí hlavička)
    try:
        head = image_path.open("rb").read(4096)
    except OSError as e:
        summary.errors.append(f"Chyba čtení obrazu: {e}")
        return summary
    det = detect_image_type(head)
    if det:
        summary.image_type, summary.description = det

    # 1b) kontejner (E01/AFF4) → extrakce obsahu do dočasného RAW souboru.
    #     TSK čte jen RAW/partice; obsah kontejneru se musí nejdřív rozbalit.
    work_path = image_path
    extracted_raw: Path | None = None
    if is_container(summary.image_type):
        from stopa.data.ewf_container import EwfError, ewf_available, read_container

        if not ewf_available():
            summary.errors.append(
                f"Kontejner {summary.image_type} detekován, ale libewf/libafflib "
                "nedostupné (nainstalujte runtime knihovny)"
            )
            return summary
        try:
            raw = read_container(image_path, summary.image_type)
        except EwfError as e:
            summary.errors.append(f"Čtení kontejneru ({summary.image_type}): {e}")
            return summary
        import tempfile

        fd, tmp_name = tempfile.mkstemp(suffix=".img", prefix="stopa-ewf-")
        os.close(fd)
        extracted_raw = Path(tmp_name)
        try:
            extracted_raw.write_bytes(raw)
        except OSError as e:
            summary.errors.append(f"Zápis extrahovaného obrazu: {e}")
            return summary
        work_path = extracted_raw

    # 2) particie (TSK mmls) — defenzivně
    try:
        summary.partitions = image_partitions(work_path)
    except TskError as e:
        summary.errors.append(f"mmls: {e}")

    # 2b) fallback bez partition table — čistý FS na offsetu 0 (mobilní oddíl,
    #     FDE plaintext): mmls nic nenajde → celý obraz = jedna syntetická partice.
    if not summary.partitions:
        work_head = work_path.open("rb").read(4096)
        fstype = filesystem_fstype(work_head)
        if fstype:
            size_sectors = work_path.stat().st_size // 512
            summary.partitions.append(
                Partition(
                    index=0,
                    offset_sectors=0,
                    size_sectors=size_sectors,
                    desc=f"syntetická (celý obraz, {fstype})",
                    fstype=fstype,
                )
            )

    # 3) soubory v každé partici → FileRecord + signatura
    for part in summary.partitions:
        try:
            files = list_files(work_path, partition=part)
        except TskError as e:
            summary.errors.append(f"fls (partice {part.index}): {e}")
            continue
        for f in files:
            if f.file_type != "r":  # jen běžné soubory (d=lom, v=volume meta)
                continue
            rel_path = f.path.lstrip("/")
            name = _basename(f.path)
            size = f.size or 0
            sig_type: str | None = None
            if profile.signature_analysis and size > 0:
                try:
                    content = extract_file(work_path, f.meta_addr, partition=part)
                    det2 = detect_signature(content[:_SIG_HEAD])
                    if det2:
                        sig_type = det2[0]
                except TskError as e:
                    summary.errors.append(f"icat {rel_path}: {e}")
            rec = FileRecord(
                source_id=source_id,
                rel_path=rel_path,
                name=name,
                size_bytes=size,
                signature_type=sig_type,
                extension=os.path.splitext(name)[1].lstrip(".").lower() or None,
                meta_addr=f.meta_addr,  # GUI File Inspector: hex dump přes icat
            )
            db.upsert_file(rec)
            summary.files_total += 1
            summary.bytes_total += size
            if sig_type:
                summary.signatures_detected += 1

    # 4) artifact disk_image (timeline přehled + GUI partition map)
    part_desc = "; ".join(
        f"[{p.index}] {p.desc} @ sektor {p.offset_sectors}" for p in summary.partitions
    ) or "bez particí"
    art = Artifact(
        source_id=source_id,
        rel_path=image_path.name,
        artifact_type="disk_image",
        title=f"Disk image: {summary.description or 'neznámý typ'} ({summary.files_total} souborů)",
        details={
            "image_type": summary.image_type,
            "description": summary.description,
            "partitions": part_desc,
            # strukturovaná partition mapa pro GUI (vizuální mapa + legendy)
            "partition_map": [
                {
                    "index": p.index,
                    "offset_sectors": p.offset_sectors,
                    "size_sectors": p.size_sectors,
                    "desc": p.desc,
                    "fstype": p.fstype,
                }
                for p in summary.partitions
            ],
            "files_total": summary.files_total,
            "bytes_total": summary.bytes_total,
            "signatures_detected": summary.signatures_detected,
        },
    )
    db.upsert_artifact(art)  # file_id=None → jen source (idempotentní upsert)

    # 5) carving — STREAMING přes mmap (sliding window), ne read_bytes() celého obrazu
    if carve_free:
        try:
            summary.carved_candidates = len(carve_file(work_path))
        except OSError as e:
            summary.errors.append(f"carving čtení: {e}")

    # 6) cleanup extrahovaného RAW (E01/AFF4 kontejner) — TSK už s ním hotovo
    if extracted_raw is not None and extracted_raw.exists():
        try:
            extracted_raw.unlink()
        except OSError as e:
            _log.debug("cleanup extrahovaného obrazu %s selhal: %s", extracted_raw, e)

    db.commit()
    return summary


def _fde_plaintext_to_tmp(plaintext: bytes) -> tuple[Path | None, str]:
    """Zapíše dešifrovaný plaintext do dočasného souboru pro TSK pipeline.

    Vrací ``(cesta, "")`` při úspěchu nebo ``(None, popis_chyby)`` při selhání.
    TSK čte z cesty (ne z paměti), takže plaintext musí být na disku.
    """
    import tempfile

    try:
        fd, tmp_name = tempfile.mkstemp(suffix=".img", prefix="stopa-fde-")
        os.close(fd)
        Path(tmp_name).write_bytes(plaintext)
        return Path(tmp_name), ""
    except OSError as e:
        return None, f"FDE plaintext zápis: {e}"


def _fde_key_material(password: str | None, keyfile: Path | str | None) -> bytes:
    """Rozřeší heslo / extrahovaný klíč na bajty (pro FBE + STOPAFDE).

    ``keyfile`` má prioritu (importovaného klíče); jinak se použije ``password``.
    Žádný → prázdné bytes (dešifrování selže srozumitelně v domain vrstvě).
    """
    if keyfile is not None:
        kf = Path(keyfile).expanduser()
        if not kf.exists():
            from stopa.domain.fde import FdeError

            raise FdeError(f"Klíčový soubor neexistuje: {kf}")
        return kf.read_bytes()
    if password is not None:
        return password.encode("utf-8") if isinstance(password, str) else password
    return b""


def process_mobile_image(
    db: CaseDB,
    source_id: str,
    image_path: Path | str,
    profile: ProcessingProfile,
    password: str | None = None,
    keyfile: Path | str | None = None,
    carve_free: bool = False,
) -> ImageSummary:
    """Mobilní physical obraz (FÁZE 6b + B2) — FDE/FBE/LUKS detekce + unlock.

    Detekuje a dešifruje tři formáty podle magic na offsetu 0:
      * ``STOPAFBE`` → Android FBE (AES-256-XTS sektorová, čistý Python)
      * ``LUKS\\xba\\xbe`` → LUKS/dm-crypt (cryptsetup, vyžaduje root + loop device)
      * ``STOPAFDE`` → proprietární testovací formát (PBKDF2→AES-256-CBC)

    Dešifrovaný plaintext jde do dočasného souboru a přes něj běžný
    ``process_disk_image`` (TSK). Bez FDE/FBE/LUKS (běžný RAW/E01) jde rovnou.
    Chybějící/špatné heslo → chyba v ``errors``.
    """
    from stopa.domain.fde import FdeError, decrypt_image, is_fde_image
    from stopa.domain.fde_fbe import decrypt_fbe, is_fbe_image
    from stopa.domain.fde_luks import decrypt_luks, is_luks_image

    image_path = Path(image_path).expanduser()
    summary = ImageSummary()

    if not image_path.exists():
        summary.errors.append(f"Obraz neexistuje: {image_path}")
        return summary

    # 1) FDE/FBE/LUKS detekce (stačí hlavička — všechny magics jsou ≤8 B na offsetu 0)
    try:
        head = image_path.open("rb").read(96)
    except OSError as e:
        summary.errors.append(f"Chyba čtení obrazu: {e}")
        return summary

    work_path = image_path
    if is_fbe_image(head):
        # FÁZE B2 — Android FBE (AES-XTS sektorová)
        full = image_path.read_bytes()
        try:
            key = _fde_key_material(password, keyfile)
            plaintext, header = decrypt_fbe(full, key)
        except FdeError as e:
            summary.errors.append(f"FDE unlock selhal (FBE): {e}")
            return summary
        work_path, desc = _fde_plaintext_to_tmp(plaintext)
        if work_path is None:
            summary.errors.append(desc)
            return summary
    elif is_luks_image(head):
        # FÁZE B2 — LUKS/dm-crypt (cryptsetup, vyžaduje root + loop device)
        try:
            plaintext, header = decrypt_luks(image_path, password=password, keyfile=keyfile)
        except FdeError as e:
            summary.errors.append(f"LUKS unlock selhal: {e}")
            return summary
        work_path, desc = _fde_plaintext_to_tmp(plaintext)
        if work_path is None:
            summary.errors.append(desc)
            return summary
    elif is_fde_image(head):
        # FÁZE 6b — STOPAFDE (AES-256-CBC, proprietární testovací formát)
        full = image_path.read_bytes()
        try:
            key = _fde_key_material(password, keyfile)
            plaintext, header = decrypt_image(full, key)
        except FdeError as e:
            summary.errors.append(f"FDE unlock selhal: {e}")
            return summary
        work_path, desc = _fde_plaintext_to_tmp(plaintext)
        if work_path is None:
            summary.errors.append(desc)
            return summary

    # FDE/FBE/LUKS metadata (typ + popis) — jen pokud se něco dešifrovalo
    if work_path != image_path:
        summary.fde_unlocked = True
        if is_fbe_image(head):
            summary.image_type = "fde"
            summary.description = f"FBE obraz (fs={header.fs_type}) — AES-XTS, dešifrován heslem"
        elif is_luks_image(head):
            summary.image_type = "luks"
            summary.description = f"LUKS v{header.version} obraz — dešifrován cryptsetup"
        else:
            summary.image_type = "fde"
            summary.description = f"FDE obraz (fs={header.fs_type}) — dešifrován heslem"

    try:
        inner = process_disk_image(db, source_id, work_path, profile, carve_free=carve_free)
    finally:
        if work_path != image_path and work_path.exists():
            work_path.unlink(missing_ok=True)

    # sloučí výsledky (FDE metadata + vnitřní disk image výsledek)
    summary.partitions = inner.partitions
    summary.files_total = inner.files_total
    summary.bytes_total = inner.bytes_total
    summary.signatures_detected = inner.signatures_detected
    summary.carved_candidates = inner.carved_candidates
    summary.errors.extend(inner.errors)
    if not summary.image_type:  # nebyl FDE → typ z vnitřní detekce
        summary.image_type, summary.description = inner.image_type, inner.description
    return summary
