"""P3-4 Evidence Storage Manager — doménová vrstva (čistá logika, bez I/O).

Životný cyklus originálního úložiště důkazů případu: inventář s integritním
stavem, kapacitní rozpočet a deterministický export/import manifest podepsaný
Ed25519 (re-use ``domain/integrity.py``). Originály se nikdy neupravují — tato
vrstva jen klasifikuje naměřené hodnoty proti referenčním hashům; disk I/O
patří do ``data/evidence_storage_repository.py``.

Stavy inventáře (uzavřená množina):
    verified     — soubor na disku odpovídá referenčnímu SHA-256
    corrupt      — hash se liší od referenčního (poškozený originál)
    missing      — soubor neexistuje na očekávané cestě
    no_reference — legacy řádek bez referenčního hashu (neověřitelný;
                   konzervativní rozlišení proti tichému "verified")

Manifest: kanonické JSON (seřazené klíče, položky seřazené podle
``(source_id, rel_path)``), SHA-256 + podpis Ed25519 přes
``integrity.sign_hash``/``verify_signature``. Import cizího manifestu =
fail-closed při neověřeném podpisu / chybějícím poli; pořadí položek v importu
není relevantní (kanonický payload je řazen).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# ── stavy inventáře ───────────────────────────────────────────────────────────

STATUS_VERIFIED = "verified"
STATUS_CORRUPT = "corrupt"
STATUS_MISSING = "missing"
STATUS_NO_REFERENCE = "no_reference"

STATUSES: tuple[str, ...] = (
    STATUS_VERIFIED,
    STATUS_CORRUPT,
    STATUS_MISSING,
    STATUS_NO_REFERENCE,
)

# ── manifest ─────────────────────────────────────────────────────────────────

MANIFEST_FORMAT_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def classify_entry(expected_sha256: str | None, actual_sha256: str | None) -> str:
    """Klasifikuje jeden soubor inventáře (čistá funkce).

    ``expected_sha256`` = referenční hash (DB / importovaný manifest),
    ``actual_sha256`` = naměřený hash (None, pokud soubor na disku chybí).
    Porovnání je case-insensitive (hexdigesty jsou konvenčně malá písmena).
    """
    if expected_sha256 is None:
        return STATUS_NO_REFERENCE
    if actual_sha256 is None:
        return STATUS_MISSING
    if expected_sha256.strip().lower() == actual_sha256.strip().lower():
        return STATUS_VERIFIED
    return STATUS_CORRUPT


@dataclass(frozen=True)
class EvidenceEntry:
    """Jeden soubor inventáře — referenční + naměřené hodnoty.

    ``status`` je odvozené (frozen dataclass → metoda, ne stav).
    """

    source_id: str
    rel_path: str
    expected_sha256: str | None = None
    expected_size: int | None = None
    actual_sha256: str | None = None
    actual_size: int | None = None

    @property
    def status(self) -> str:
        return classify_entry(self.expected_sha256, self.actual_sha256)


@dataclass(frozen=True)
class InventoryReport:
    """Agregace inventáře (čistá funkce ``build_report``)."""

    total_files: int = 0
    verified: int = 0
    corrupt: int = 0
    missing: int = 0
    no_reference: int = 0
    expected_bytes: int = 0  # součet referenčních velikostí (DB metadata)
    actual_bytes: int = 0  # součet naměřených velikostí (jen přítomné soubory)


def build_report(entries: Sequence[EvidenceEntry]) -> InventoryReport:
    """Agreguje inventář do souhrnu — čistá funkce, deterministická."""
    verified = corrupt = missing = no_reference = 0
    expected_bytes = actual_bytes = 0
    for e in entries:
        status = e.status
        if status == STATUS_VERIFIED:
            verified += 1
        elif status == STATUS_CORRUPT:
            corrupt += 1
        elif status == STATUS_MISSING:
            missing += 1
        else:
            no_reference += 1
        expected_bytes += e.expected_size or 0
        actual_bytes += e.actual_size or 0
    return InventoryReport(
        total_files=len(entries),
        verified=verified,
        corrupt=corrupt,
        missing=missing,
        no_reference=no_reference,
        expected_bytes=expected_bytes,
        actual_bytes=actual_bytes,
    )


@dataclass(frozen=True)
class CapacityReport:
    """Kapacitní rozpočet — used vs budget (utilizace zaokrouhlená na 6 míst)."""

    used_bytes: int
    budget_bytes: int | None = None
    utilization: float | None = None
    over_budget: bool = False


def capacity_report(used_bytes: int, budget_bytes: int | None = None) -> CapacityReport:
    """Vypočítá kapacitní report. ``budget_bytes=None`` → bez rozpočtu."""
    if not isinstance(used_bytes, int) or isinstance(used_bytes, bool):
        raise TypeError("used_bytes musí být int")
    if used_bytes < 0:
        raise ValueError("used_bytes nesmí být záporné")
    if budget_bytes is None:
        return CapacityReport(used_bytes=used_bytes)
    if not isinstance(budget_bytes, int) or isinstance(budget_bytes, bool):
        raise TypeError("budget_bytes musí být int nebo None")
    if budget_bytes <= 0:
        raise ValueError("budget_bytes musí být > 0")
    utilization = round(used_bytes / budget_bytes, 6)
    return CapacityReport(
        used_bytes=used_bytes,
        budget_bytes=budget_bytes,
        utilization=utilization,
        over_budget=used_bytes > budget_bytes,
    )


# ── manifest (deterministický JSON + Ed25519 podpis) ──────────────────────────


def _validate_entry_tuple(
    idx: int, entry: object
) -> tuple[str, str, str, int]:
    """Validuje jednu položku manifestu; vrací normalizovanou trojici+size."""
    if not isinstance(entry, (tuple, list)) or len(entry) != 4:
        raise ValueError(f"manifest entry #{idx}: očekávám (source_id, rel_path, sha256, size)")
    source_id, rel_path, sha256, size = entry
    for label, value in (("source_id", source_id), ("rel_path", rel_path)):
        if not isinstance(value, str) or not value:
            raise ValueError(f"manifest entry #{idx}: {label} musí být neprázdný string")
    if not isinstance(sha256, str) or not _SHA256_RE.match(sha256):
        raise ValueError(f"manifest entry #{idx}: sha256 musí být 64 hex znaků")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError(f"manifest entry #{idx}: size musí být int >= 0")
    return source_id, rel_path, sha256.lower(), size


def manifest_payload(
    case_id: str,
    public_key_b64: str,
    entries: Sequence[tuple[str, str, str, int]],
) -> dict[str, Any]:
    """Sestaví kanonický payload manifestu pro podpis (deterministický).

    Položky se normalizují (sha256 → malá písmena) a seřadí podle
    ``(source_id, rel_path)``; duplicita klíče = ``ValueError``. Všechny
    semantické chyby vstupů = ``ValueError`` (fail-closed).
    """
    if not isinstance(case_id, str) or not case_id.strip():
        raise ValueError("manifest: case_id musí být neprázdný string")
    if not isinstance(public_key_b64, str) or not public_key_b64.strip():
        raise ValueError("manifest: public_key_b64 musí být neprázdný string")

    seen: set[tuple[str, str]] = set()
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(entries):
        source_id, rel_path, sha256, size = _validate_entry_tuple(idx, raw)
        key = (source_id, rel_path)
        if key in seen:
            raise ValueError(f"manifest: duplicitní položka {rel_path!r} (source {source_id})")
        seen.add(key)
        normalized.append(
            {"source_id": source_id, "rel_path": rel_path, "sha256": sha256, "size": size}
        )
    normalized.sort(key=lambda e: (e["source_id"], e["rel_path"]))

    return {
        "format_version": MANIFEST_FORMAT_VERSION,
        "case_id": case_id,
        "public_key_b64": public_key_b64,
        "entries": normalized,
    }


def manifest_hash(payload: Mapping[str, Any]) -> str:
    """Deterministický SHA-256 payloadu — kanonické JSON (seřazené klíče).

    Stejný obsah = stejný hash bez ohledu na pořadí klíčů dictu.
    """
    canonical = json.dumps(
        dict(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def sign_manifest(private_b64: str, payload: Mapping[str, Any]) -> str:
    """Podpis manifestu Ed25519 (base64) — re-use ``integrity.sign_hash``."""
    from stopa.domain.integrity import sign_hash

    return sign_hash(private_b64, manifest_hash(payload))


@dataclass(frozen=True)
class ManifestVerification:
    """Výsledek fail-closed ověření importovaného manifestu."""

    ok: bool
    reason: str | None = field(default=None)


def verify_manifest(manifest: Any) -> ManifestVerification:
    """Fail-closed ověření importovaného manifestu.

    Kontroluje strukturu (format_version, povinná pole, validita položek),
    pak rekonstruuje kanonický payload a ověří podpis vloženým veřejným
    klíčem. Libovolná odchylka = ``ok=False`` s důvodem.
    """
    if not isinstance(manifest, Mapping):
        return ManifestVerification(False, "manifest není objekt")

    version = manifest.get("format_version")
    if version != MANIFEST_FORMAT_VERSION:
        return ManifestVerification(
            False, f"nepodporovaná format_version (očekáváno {MANIFEST_FORMAT_VERSION})"
        )

    case_id = manifest.get("case_id")
    public_key_b64 = manifest.get("public_key_b64")
    signature_b64 = manifest.get("signature_b64")
    if not isinstance(case_id, str) or not case_id.strip():
        return ManifestVerification(False, "chybí case_id")
    if not isinstance(public_key_b64, str) or not public_key_b64.strip():
        return ManifestVerification(False, "chybí public_key_b64")
    if not isinstance(signature_b64, str) or not signature_b64.strip():
        return ManifestVerification(False, "chybí signature_b64")

    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        return ManifestVerification(False, "chybí entries (seznam)")

    tuples: list[tuple[str, str, str, int]] = []
    for idx, item in enumerate(raw_entries):
        if not isinstance(item, Mapping):
            return ManifestVerification(False, f"entry #{idx} není objekt")
        try:
            tuples.append(
                _validate_entry_tuple(
                    idx, (item.get("source_id"), item.get("rel_path"), item.get("sha256"), item.get("size"))
                )
            )
        except ValueError as exc:
            return ManifestVerification(False, str(exc))

    try:
        payload = manifest_payload(case_id, public_key_b64, tuples)
    except ValueError as exc:
        return ManifestVerification(False, str(exc))

    from stopa.domain.integrity import verify_signature

    digest = manifest_hash(payload)
    try:
        verified = verify_signature(public_key_b64, digest, signature_b64)
    except (ValueError, TypeError):
        # binascii.Error ⊂ ValueError; špatná délka klíče → ValueError
        return ManifestVerification(False, "neplatné kódování veřejného klíče")
    if not verified:
        return ManifestVerification(False, "ověření podpisu selhalo")
    return ManifestVerification(True, None)


def export_manifest(
    case_id: str,
    public_key_b64: str,
    private_b64: str,
    entries: Sequence[tuple[str, str, str, int]],
) -> dict[str, Any]:
    """Sestaví podepsaný manifest (kanonický payload + ``signature_b64``).

    Veřejný klíč je součástí podepsaného payloadu (self-contained trust
    anchor — příjemce ověří podpis klíčem přímo z manifestu).
    """
    payload = manifest_payload(case_id, public_key_b64, entries)
    return {**payload, "signature_b64": sign_manifest(private_b64, payload)}
