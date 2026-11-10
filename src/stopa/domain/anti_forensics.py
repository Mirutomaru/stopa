"""Anti-forensics detection (F1.4) — pure stdlib logic, no DB/CLI deps.

Detekce pokusů o maskování forenzních stop:
  * timestomping (budoucí/impossible MFT timestamps, hromadný touch)
  * log clearing (EVTX Event ID 1102 + mezery v číslách záznamů)
  * USN journal truncation (nízká hustota záznamů, vysoký podíl delete)
  * hidden partitions / poškozená MBR partition table
  * steganografie (LSB statistika PNG/JPG — PIL lazy import)
  * signatury anti-forenzních nástrojů v názvech souborů
  * integrity diskového obrazu (magic byty, ořez)

Čistá funkce :func:`detect_anti_forensics` nad normalizovanými dicty —
orchestrace CLI, převod DB artefaktů a ukládání patří do vrstvy cli.py
(stejný pattern jako net_forensics / mem_forensics).
"""

from __future__ import annotations

import math
import re
import struct
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

PARSER_VERSION = "af1.4"

#: Tolerance pro „budoucí“ timestamps — menší rozdíly jsou běžný clock drift.
FUTURE_TOLERANCE_SECONDS = 60.0

#: Signatury známých anti-forenzních nástrojů (lowercase).
TOOL_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("fslint", "systémová utility pro čištění stop"),
    ("eraser", "šifrování a mazání dat"),
    ("ccleaner", "čištění dočasných souborů a logů"),
    ("bleachbit", "čištění stop (open source)"),
    ("foremost", "carving smazaných souborů"),
    ("photorec", "obnova smazaných souborů"),
    ("scalpel", "specializovaný carving"),
    ("diskwipe", "kompletní wipe disku"),
    ("shred", "unrecoverable file deletion"),
    ("cipherwipe", "šifrovací wipe utility"),
    ("mftedit", "úprava MFT záznamů"),
)

#: Generic vzory podezřelých názvů (regex, lowercase).
TOOL_NAME_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bwipe\b", "wipe utility"),
    (r"\bshred\b", "unrecoverable deletion"),
    (r"erase[r]?\.exe$", "eraser executable"),
)

#: Magic byty známých formátů diskových obrazů: (ext, offset, magic).
IMAGE_FORMATS: tuple[tuple[str, int, bytes], ...] = (
    ("vmdk", 0, b"KDMV"),
    ("vhdx", 0, b"vhdxfile"),
    ("vhd", 512, b"conectix"),
    ("e01", 0, b"E\x0c\x1a\xe4"),
)

#: Typy obrazů bez MBR (raw dd/img je raw sektor — MBR očekáváme).
RAW_IMAGE_EXTS = {"img", "dd", ""}


@dataclass(frozen=True)
class Finding:
    """Jeden nález anti-forensics detekce.

    ``check`` je krátký typ (bez prefixu) — CLI ho mapuje na artifact type
    ``antiforensics/<check>`` podle ROADMAP V2 F1.4 AK.
    """

    check: str  # timestomping | log_clearing | usn_truncation | hidden_partition | …
    severity: str  # low | medium | high | critical
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _parse_ts(value: Any) -> datetime | None:
    """Parsuje ISO string / datetime na UTC-aware; None při neplatném vstupu."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def _ref_time(reference_time: Any) -> datetime:
    """Reference pro budoucí timestamps — explicitní parametr, jinak now()."""
    parsed = _parse_ts(reference_time)
    return parsed or datetime.now(UTC)


# ─────────────────────────── 1. Timestomping ──────────────────────────────


def detect_timestomping(
    files: list[dict[str, Any]], reference_time: Any = None
) -> list[Finding]:
    """Časové anomálie souborových záznamů (timestomping).

    ``files`` — dicty s klíči ``path``, ``name``, ``mtime``/``ctime``/``atime``
    (datetime nebo ISO string), volitelně ``size_bytes``. Detekuje:
      * mtime v budoucnosti vůči referenčnímu času
      * mtime před ctime — fyzikálně nemožný pořad (úprava metadata)
      * hromadně identické MACE sady → bulk touch utility
    """
    ref = _ref_time(reference_time)
    findings: list[Finding] = []
    seen_mace: dict[tuple[str, ...], list[str]] = {}

    for f in files:
        m = _parse_ts(f.get("mtime"))
        c = _parse_ts(f.get("ctime"))
        a = _parse_ts(f.get("atime"))
        path = str(f.get("path") or f.get("name") or "?")

        if m is not None and (ref - m).total_seconds() < -FUTURE_TOLERANCE_SECONDS:
            findings.append(Finding(
                check="timestomping", severity="high",
                description=f"{path}: mtime v budoucnosti ({m.isoformat()})",
                evidence={"path": path, "mtime": m.isoformat(),
                          "reference_time": ref.isoformat()},
            ))

        if m is not None and c is not None and m < c:
            findings.append(Finding(
                check="timestomping", severity="high",
                description=(f"{path}: mtime před ctime — nemožný pořad, "
                             "podezření na úpravu metadata"),
                evidence={"path": path, "mtime": m.isoformat(),
                          "ctime": c.isoformat()},
            ))

        if m and c and a:
            key = (m.replace(microsecond=0).isoformat(),
                   c.replace(microsecond=0).isoformat(),
                   a.replace(microsecond=0).isoformat())
            seen_mace.setdefault(key, []).append(path)

    for key, paths in seen_mace.items():
        if len(paths) >= 5:
            findings.append(Finding(
                check="timestomping", severity="medium",
                description=(f"{len(paths)} souborů sdílí identickou MACE sadu "
                             f"({key[0]}) — podezření na hromadný touch"),
                evidence={"file_count": len(paths), "sample_paths": paths[:5],
                          "mace": list(key)},
            ))

    return findings


# ─────────────────────────── 2. Log clearing (EVTX) ───────────────────────


def detect_log_clearing(events: list[dict[str, Any]]) -> list[Finding]:
    """Čištění Windows logů — Event ID 1102 + mezery v record numbers."""
    findings: list[Finding] = []

    for ev in events:
        try:
            eid = int(ev.get("event_id", -1))
        except (TypeError, ValueError):
            continue
        if eid == 1102:
            findings.append(Finding(
                check="log_clearing", severity="high",
                description=(f"Čištění Windows Security logu (Event ID 1102) — "
                             f"{ev.get('timestamp') or '?'}"),
                evidence={"event_id": eid,
                          "record_id": ev.get("record_id"),
                          "timestamp": str(ev.get("timestamp") or "")},
            ))

    # mezery v číslách záznamů → truncation / smazaná část logu
    nums = sorted({int(e["record_id"]) for e in events
                   if isinstance(e.get("record_id"), int) and e["record_id"] > 0})
    gaps = 0
    missing_total = 0
    worst: tuple[int, int] | None = None
    prev: int | None = None
    for n in nums:
        if prev is not None and n - prev > 1:
            missing = n - prev - 1
            gaps += 1
            missing_total += missing
            if worst is None or missing > (worst[1] - worst[0]):
                worst = (prev, n)
        prev = n
    if gaps and missing_total >= 3:
        findings.append(Finding(
            check="log_clearing",
            severity="high" if missing_total >= 50 else "medium",
            description=(f"EVTX mezera v číslách záznamů: {gaps} mezer, "
                         f"{missing_total} chybějících — truncation/čištění logu"),
            evidence={"gap_count": gaps, "missing_total": missing_total,
                      "worst_gap_from": worst[0] if worst else None,
                      "worst_gap_to": worst[1] if worst else None},
        ))

    return findings


# ─────────────────────────── 3. USN journal truncation ────────────────────


def detect_usn_truncation(usn_records: list[dict[str, Any]]) -> list[Finding]:
    """USN Journal truncation — nízká hustota záznamů na USN span + delete podíl."""
    findings: list[Finding] = []
    usns = sorted(int(r["usn"]) for r in usn_records if isinstance(r.get("usn"), int))
    if len(usns) < 20:
        return findings

    span = usns[-1] - usns[0]
    density = (len(usns) / span) if span > 0 else float(len(usns))
    deletes = sum(1 for r in usn_records if str(r.get("reason", "")).startswith("delete"))
    delete_ratio = deletes / len(usn_records)

    if span >= 100 and density < 0.2:
        findings.append(Finding(
            check="usn_truncation", severity="medium",
            description=(f"USN Journal: nízká hustota záznamů "
                         f"(density={density:.4f} na span {span}) — podezření na "
                         "truncation/přepis journalu"),
            evidence={"record_count": len(usns), "usn_span": span,
                      "density": round(density, 5)},
        ))

    if delete_ratio > 0.5 and deletes >= 10:
        findings.append(Finding(
            check="usn_truncation", severity="high" if delete_ratio > 0.8 else "medium",
            description=(f"USN Journal: {delete_ratio:.0%} záznamů je delete — "
                         "podezření na cílené čištění historie"),
            evidence={"record_count": len(usns), "delete_events": deletes,
                      "delete_ratio": round(delete_ratio, 3)},
        ))

    return findings


# ──────────────────────── 4. Hidden partitions / MBR ──────────────────────


def validate_partition_table(header512: bytes | None, image_ext: str = "") -> list[Finding]:
    """Validace MBR partition table (0x55AA + aspoň jeden platný entry)."""
    if not header512 or len(header512) < 512:
        return []
    sig = struct.unpack_from("<H", header512, 510)[0]
    entries = [header512[446 + i * 16 : 446 + (i + 1) * 16] for i in range(4)]
    nonempty = [e for e in entries if e.strip(b"\x00")]

    ext_l = image_ext.lower().lstrip(".")
    expect_mbr = ext_l not in {"vmdk", "vhdx", "vhd", "e01"}  # raw obraz → MBR čekáme

    if expect_mbr and sig != 0x55AA:
        return [Finding(
            check="hidden_partition", severity="high",
            description=(f"MBR signature 0x55AA chybí (nalezeno {hex(sig)}) — "
                         "podezření na záměrné přepsání partition table"),
            evidence={"signature": hex(sig)},
        )]
    if sig == 0x55AA and not nonempty:
        return [Finding(
            check="hidden_partition", severity="medium",
            description="MBR platný, ale bez jediné partition entry — podezřelá prázdná tabulka",
            evidence={"signature": "0x55aa"},
        )]
    return []


# ──────────────────────── 5. LSB steganografie (PIL) ──────────────────────


def detect_lsb_steganography(image_path: str | None) -> list[Finding]:
    """LSB statistika PNG/JPG — heuristika bez dekodování skryté zprávy.

    PIL lazy import (volitelná runtime závislost). Porovnává entropii LSB
    bitů s očekávanou náhodností: šumová fotografie má LSB ~50/50;
    steganografický vklad nebo ploché oblasti s vymařenými LSB vychylují
    rozložení. Vrací nález jen při výrazné odchylce (snížení false positive).
    """
    if not image_path:
        return []
    try:
        from PIL import Image  # lazy — volitelná runtime závislost
    except ImportError:
        return [Finding(
            check="steganography", severity="low",
            description="PIL není dostupná — LSB stego analýza přeskocena",
            evidence={"path": image_path, "skipped": "no_pil"},
        )]
    try:
        with Image.open(image_path) as img:
            fmt = (img.format or "").lower()
            if fmt not in ("png", "jpeg"):
                return []
            small = img.convert("L").resize((64, 64))
            px = list(small.tobytes())  # single-band "L": každý byte = pixel 0–255
    except Exception:  # noqa: BLE001 — nepodporovaný/poškozený obraz ≠ pád analýzy
        return []

    n = len(px)
    ones = sum(p & 1 for p in px)
    ratio = ones / n if n else 0.5
    skew = abs(ratio - 0.5) * 2  # 0 = vyvážené, 1 = plně vychýlené

    def _shannon(counts: Counter[int]) -> float:
        total = sum(counts.values())
        if total <= 0:
            return 0.0
        return -sum((c / total) * math.log2(c / total) for c in counts.values() if c)

    lsb_ent = _shannon(Counter(p & 1 for p in px))
    gray_ent = _shannon(Counter(px))

    flagged = False
    severity = "medium"
    if skew >= 0.15 and lsb_ent < 0.98:
        # výrazně vychýlené LSB u obrazu s reálným šumem → indikátor vkladu
        flagged = True
    elif gray_ent > 7.0 and skew >= 0.25:
        flagged = True
        severity = "low"

    if not flagged:
        return []
    return [Finding(
        check="steganography", severity=severity,
        description=(f"{fmt.upper()}: podezřelá LSB statistika "
                     f"(lsb_entropy={lsb_ent:.3f}, gray_entropy={gray_ent:.2f}, "
                     f"skew={skew:.3f}) — možná steganografie"),
        evidence={"path": str(image_path), "format": fmt,
                  "lsb_entropy": round(lsb_ent, 4),
                  "gray_entropy": round(gray_ent, 3),
                  "lsb_skew": round(skew, 4)},
    )]


# ──────────────────────── 6. Tool signatures v názvech ────────────────────


def detect_tool_signatures(files: list[dict[str, Any]]) -> list[Finding]:
    """Signatury anti-forenzních nástrojů v názvech souborů."""
    findings: list[Finding] = []
    for f in files:
        name = str(f.get("name") or "").lower()
        if not name:
            continue
        path = str(f.get("path") or name)
        # přesná shoda i po odepsání přípony — nástroje se distribují jako .exe
        stem = name.rsplit(".", 1)[0] if "." in name else name

        hit_exact = any(sig == name or sig == stem for sig, _desc in TOOL_SIGNATURES)
        hit_substr = next((sig for sig, _d in TOOL_SIGNATURES if sig in name), None)
        pattern_hit = next(
            (desc for pat, desc in TOOL_NAME_PATTERNS if re.search(pat, name)), None
        )

        if hit_exact:
            findings.append(Finding(
                check="tool_signature", severity="high",
                description=f"{name}: přesná shoda signatury známého anti-forenzního nástroje",
                evidence={"path": path},
            ))
        elif hit_substr or pattern_hit:
            findings.append(Finding(
                check="tool_signature", severity="medium",
                description=(f"{name}: podezřelý název — "
                             + (hit_substr if hit_substr else pattern_hit)),  # type: ignore[arg-type]
                evidence={"path": path},
            ))
    return findings


# ──────────────────────── 7. Integrity diskového obrazu ───────────────────


def validate_image_header(path: str | None, size_bytes: int) -> list[Finding]:
    """Integrity obrazu disku — ořez + magic byty známých formátů."""
    if not path or size_bytes < 1024:
        return [Finding(
            check="image_integrity", severity="high",
            description=f"Obraz disku je oříznutý nebo příliš malý ({size_bytes} B)",
            evidence={"path": path, "size_bytes": size_bytes},
        )]
    try:
        with open(path, "rb") as fh:
            head = fh.read(512)
    except OSError:
        return []
    if len(head) < 512:
        return [Finding(
            check="image_integrity", severity="high",
            description="Obraz disku má méně než 512 B hlavičky — oříznutý obraz",
            evidence={"path": path, "size_bytes": size_bytes},
        )]

    ext = ""
    base = path.rsplit("/", 1)[-1].lower()
    if "." in base:
        ext = base.rsplit(".", 1)[-1]
    for fmt, off, magic in IMAGE_FORMATS:
        if ext == fmt and head[off : off + len(magic)] != magic:
            return [Finding(
                check="image_integrity", severity="high",
                description=f"Obraz {fmt.upper()} má neplatná magic byta — oříznutý nebo poškozený obraz",
                evidence={"path": path, "expected_format": fmt},
            )]
    return []


# ──────────────────────────── Orchestrace + risk ──────────────────────────


def risk_score(findings: list[Finding]) -> float:
    """Skalár 0–1 podle počtu a závažnosti nálezů."""
    weights = {"critical": 1.0, "high": 0.85, "medium": 0.5, "low": 0.2}
    acc = sum(weights.get(f.severity, 0.2) for f in findings)
    return round(min(1.0, 1.0 - (0.9 ** acc)), 3)


def detect_anti_forensics(
    files: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    usn_records: list[dict[str, Any]] | None = None,
    image_path: str | None = None,
    image_size_bytes: int = 0,
    image_ext: str = "",
    header512: bytes | None = None,
    reference_time: Any = None,
    stego_paths: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Hlavní detekce — vrací report dict s findings + risk.

    Všechny vstupní kolekce jsou normalizované dicty (viz jednotlivé funkce);
    převod z DB artefaktů / FileRecord dělá vrstva cli.py.
    """
    files = files or []
    events = events or []
    usn_records = usn_records or []
    stego_paths = list(stego_paths or [])

    findings: list[Finding] = []
    for check in (
        detect_timestomping(files, reference_time),
        detect_log_clearing(events),
        detect_usn_truncation(usn_records),
        validate_partition_table(header512, image_ext),
        validate_image_header(image_path, image_size_bytes) if image_path else [],
        detect_tool_signatures(files),
    ):
        findings.extend(check)

    for sp in stego_paths:
        findings.extend(detect_lsb_steganography(sp))

    by_check: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_check.setdefault(f.check, []).append({
            "severity": f.severity,
            "description": f.description,
            "evidence": f.evidence,
        })

    return {
        "findings_count": len(findings),
        "risk_score": risk_score(findings),
        "checks_run": list(by_check.keys()),
        "by_check": by_check,
    }
