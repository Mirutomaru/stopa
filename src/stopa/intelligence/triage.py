"""F3.2 — Triage profily: předpřipravené agendy pro typické případy.

Deterministický signálový engine nad case DB (bez LLM) se 4 profily:
**Ransomware, Insider Threat, CSAM/Média, Exfiltrace**. Každý profil =
vážený seznam signálů + práh detekce + hypotéza template (kompatibilní s
F3.1 `generate_hypothesis`).

Signály čtou jen data, která STOPA už do case DB ukládá:
- ``artifact_type`` — přesné typy artefaktů (antiforensics/*, crypto_*, …)
- ``artifact_text`` — podřetězec v title/details_json (IoC pravidla…)
- ``timeline_flag`` — kanonické flagy nesrovnalostí v timeline_events
- ``file_pattern`` — regex nad name/rel_path souborů (+ min_count)
- ``entity_pattern`` — regex nad value_normalized entit daného kindu

**Detekce:** score ≥ threshold A min. 2 různé signály (FPR guard).
AK F3.2: každý profil detekuje min. 8/10 syntetických pozitiv; FPR < 5 %
na syntetických negativách. Vše offline deterministicky — viz
``tests/test_f32_triage_profiles.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from stopa.data.db import CaseDB

#: Max. počet evidenčních ID na signál (auditovatelnost bez nafouknutí)
MAX_EVIDENCE = 5
#: Kapce skenování souborů pro file_pattern (case DB je omezená velikostí)
FILE_SCAN_CAP = 10_000


# ── modely ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SignalSpec:
    """Jeden deterministický signál profilu.

    ``kind`` ∈ artifact_type | artifact_text | timeline_flag | file_pattern |
    entity_pattern. ``patterns`` = tuple LIKE vzorů (artifact_type); jinak se
    používá ``pattern`` (substring pro text/flag, regex pro file/entity).
    """

    key: str
    weight: int  # > 0 — váha signálu ve skóre profilu
    kind: str
    pattern: str = ""
    patterns: tuple[str, ...] = ()
    min_count: int = 1  # signál započet jen pokud počet shod ≥ této hodnoty
    entity_kind: str = ""  # entity_pattern: omezení na konkrétní kind ("" = jakýkoliv)
    description: str = ""


@dataclass(frozen=True)
class TriageProfile:
    """Předpřipravená agenda: signály + práh + hypotéza template."""

    key: str
    title: str
    description: str
    signals: tuple[SignalSpec, ...]
    threshold: int  # minimální skóre pro detekci
    min_signals: int = 2  # FPR guard: aspoň tolik RŮZNÝCH signálů musí zapálit
    hypothesis_template: str = ""  # sloty {case_id} {score} {signals}


@dataclass(frozen=True)
class MatchedSignal:
    """Vyhodnocený signál s důkazy (ID artefaktů/souborů/entit)."""

    spec: SignalSpec
    count: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ProfileReport:
    """Výsledek vyhodnocení jednoho profilu nad jedním case DB."""

    profile: TriageProfile
    matched: tuple[MatchedSignal, ...]
    score: int

    @property
    def detected(self) -> bool:
        return self.score >= self.profile.threshold and len(self.matched) >= self.profile.min_signals

    @property
    def signal_summary(self) -> str:
        if not self.matched:
            return "žádné signály"
        return "; ".join(f"{m.spec.key}(x{m.count})" for m in self.matched)

    def hypothesis(self, case_id: str) -> str:
        """Vyplněná hypotéza (sloty {case_id} {score} {signals})."""
        return self.profile.hypothesis_template.format(
            case_id=case_id, score=self.score, signals=self.signal_summary
        )


# ── vyhodnocování signálů (direktní SQL — data layer) ────────────────────────


def _source_case_filter(case_id: str) -> tuple[str, list[Any]]:
    """WHERE fragment + parametry omezující dotaz na zdroje daného případu."""
    return "s.case_id = ?", [case_id]


def _signal_artifact_type(db: CaseDB, case_id: str, spec: SignalSpec) -> tuple[int, list[str]]:
    conds, params = [], []
    for pat in (spec.patterns or ([spec.pattern] if spec.pattern else ())):
        conds.append("a.artifact_type LIKE ?")
        params.append(pat)
    where_cf, cf_params = _source_case_filter(case_id)
    sql = (
        "SELECT a.id FROM artifacts a JOIN sources s ON s.id = a.source_id"
        f" WHERE {where_cf} AND ({' OR '.join(conds)}) ORDER BY a.id LIMIT 500"
    )
    rows = db.conn.execute(sql, cf_params + params).fetchall()
    return len(rows), [r["id"] for r in rows]


def _signal_artifact_text(db: CaseDB, case_id: str, spec: SignalSpec) -> tuple[int, list[str]]:
    where_cf, cf_params = _source_case_filter(case_id)
    like = f"%{spec.pattern}%"
    sql = (
        "SELECT a.id FROM artifacts a JOIN sources s ON s.id = a.source_id"
        f" WHERE {where_cf} AND (a.title LIKE ? OR a.details_json LIKE ?)"
        " ORDER BY a.id LIMIT 500"
    )
    rows = db.conn.execute(sql, cf_params + [like, like]).fetchall()
    return len(rows), [r["id"] for r in rows]


def _signal_timeline_flag(db: CaseDB, case_id: str, spec: SignalSpec) -> tuple[int, list[str]]:
    where_cf, cf_params = _source_case_filter(case_id)
    sql = (
        "SELECT e.id FROM timeline_events e JOIN sources s ON s.id = e.source_id"
        f" WHERE {where_cf} AND e.anomaly_flags LIKE ? ORDER BY e.id LIMIT 500"
    )
    rows = db.conn.execute(sql, cf_params + [f"%{spec.pattern}%"]).fetchall()
    return len(rows), [r["id"] for r in rows]


def _signal_file_pattern(db: CaseDB, case_id: str, spec: SignalSpec) -> tuple[int, list[str]]:
    where_cf, cf_params = _source_case_filter(case_id)
    sql = (
        "SELECT f.id, f.name, f.rel_path FROM files f JOIN sources s ON s.id = f.source_id"
        f" WHERE {where_cf} LIMIT ?"
    )
    rx = re.compile(spec.pattern)
    hits: list[str] = []
    for r in db.conn.execute(sql, cf_params + [FILE_SCAN_CAP]):
        if rx.search(r["name"] or "") or rx.search(r["rel_path"] or ""):
            hits.append(r["id"])
    return len(hits), hits


def _signal_entity_pattern(db: CaseDB, case_id: str, spec: SignalSpec) -> tuple[int, list[str]]:
    params: list[Any] = [case_id]
    kind_filter = ""
    if spec.entity_kind:
        kind_filter = " AND e.kind = ?"
        params.append(spec.entity_kind)
    sql = (
        "SELECT e.id, e.value_normalized FROM entities e"
        f" WHERE e.case_id = ?{kind_filter} LIMIT 5000"
    )
    rx = re.compile(spec.pattern)
    hits: list[str] = []
    for r in db.conn.execute(sql, params):
        if rx.search(r["value_normalized"] or ""):
            hits.append(r["id"])
    return len(hits), hits


_SIGNAL_FUNCS = {
    "artifact_type": _signal_artifact_type,
    "artifact_text": _signal_artifact_text,
    "timeline_flag": _signal_timeline_flag,
    "file_pattern": _signal_file_pattern,
    "entity_pattern": _signal_entity_pattern,
}


# ── veřejné API ───────────────────────────────────────────────────────────────


def evaluate_profile(db: CaseDB, case_id: str, profile: TriageProfile) -> ProfileReport:
    """Vyhodnotí jeden profil nad case DB → report se skóre a důkazy."""
    matched: list[MatchedSignal] = []
    score = 0
    for spec in profile.signals:
        func = _SIGNAL_FUNCS.get(spec.kind)
        if func is None:
            raise ValueError(f"{profile.key}: neznámý kind signálu {spec.kind!r}")
        count, evidence = func(db, case_id, spec)
        if count >= max(1, spec.min_count):
            matched.append(MatchedSignal(spec=spec, count=count, evidence_ids=tuple(evidence[:MAX_EVIDENCE])))
            score += spec.weight
    return ProfileReport(profile=profile, matched=tuple(matched), score=score)


def run_triage(db: CaseDB, case_id: str, profiles: tuple[TriageProfile, ...] | None = None) -> list[ProfileReport]:
    """Vyhodnotí všechny (nebo zadané) profily; seřazeno dle skóre sestupně."""
    chosen = profiles if profiles is not None else PROFILES
    reports = [evaluate_profile(db, case_id, p) for p in chosen]
    return sorted(reports, key=lambda r: (-r.score, r.profile.key))


def get_profile(key: str) -> TriageProfile:
    """Profil podle klíče; ValueError při neznámém."""
    for p in PROFILES:
        if p.key == key:
            return p
    raise ValueError(f"neznámý triage profil {key!r} (dostupné: {[p.key for p in PROFILES]})")


# ── 4 profily (AK F3.2) ───────────────────────────────────────────────────────

RANSOMWARE = TriageProfile(
    key="ransomware",
    title="Ransomware infekce",
    description=(
        "Hromadné šifrování souborů: timestomping, ransom extenze/poznámky,"
        " kryptowallety pro vyjednávání o výkupném, C2 komunikace."
    ),
    signals=(
        SignalSpec(
            key="timestomp_artifact", weight=2, kind="artifact_type",
            patterns=("antiforensics/timestomping",),
            description="bulk-touch / nemožný pořad M<C (F1.4)",
        ),
        SignalSpec(
            key="timeline_timestomp_flag", weight=1, kind="timeline_flag", pattern="timestomp",
            description="flag timestomping v timeline (substring — pokrývá timestomp/timestomping)",
        ),
        SignalSpec(
            key="ransom_extensions", weight=2, kind="file_pattern",
            pattern=r"(?i)\.(locked|crypt|wcry|locky|encr(?:y)?pted?)\b",
            description="typické ransom extenze (.locked/.crypt/…)",
        ),
        SignalSpec(
            key="ransom_note", weight=1, kind="file_pattern",
            pattern=r"(?i)(restore_me|recover(?:y)?_me|decrypt[_-]?me|readme\.(?:html|pdf))",
            description="ransom poznámka (RECOVERY/README)",
        ),
        SignalSpec(
            key="crypto_wallets", weight=2, kind="artifact_type",
            patterns=("crypto_wallet", "crypto_detection"),
            description="kryptowallety/detekce (K1) — cíl výkupného",
        ),
        SignalSpec(
            key="c2_beaconing", weight=1, kind="artifact_text", pattern="c2_beaconing",
            description="C2 beaconing IoC (F1.3)",
        ),
    ),
    threshold=3,
    hypothesis_template=(
        "Podezření na RANSOMWARE infekci v případě {case_id} (skóre {score}): {signals}. "
        "Doporučený postup: analýza paměťového dumpu, kontrola C2 provozu, identifikace"
        " peněžovky pro výkupné."
    ),
)

INSIDER_THREAT = TriageProfile(
    key="insider_threat",
    title="Insider threat (vnitřní zaměstnanec)",
    description=(
        "Skryté úniky: hromadné mazání (USN truncation), skrytí stop (timestomping),"
        " odpojitelná média, komunikace přes osobní schránky."
    ),
    signals=(
        SignalSpec(
            key="usn_truncation", weight=2, kind="artifact_type",
            patterns=("antiforensics/usn_truncation",),
            description="USN journal truncation / delete podíl (F1.4)",
        ),
        SignalSpec(
            key="timestomp_artifact", weight=1, kind="artifact_type",
            patterns=("antiforensics/timestomping",),
            description="skryté úpravy časových razítek (F1.4)",
        ),
        SignalSpec(
            key="removable_media", weight=2, kind="artifact_type",
            patterns=("drive_activity",),
            description="aktivita odpojitelných médií (USB/drive_activity)",
        ),
        SignalSpec(
            key="personal_mailbox", weight=1, kind="entity_pattern", entity_kind="email",
            pattern=r"(?i)@(gmail|yahoo|outlook)\.",
            description="osobní e-mailová schránka mezi entitami případu",
        ),
    ),
    threshold=3,
    hypothesis_template=(
        "Podezření na INSIDER THREAT v případě {case_id} (skóre {score}): {signals}. "
        "Doporučený postup: ověření odpojitelných médií, rozsahu hromadného mazání"
        " a komunikace přes osobní schránky."
    ),
)

CSAM_MEDIA = TriageProfile(
    key="csam_media",
    title="Média / CSAM indikátory",
    description=(
        "Nahromaděná média s stopami skrytí: steganografie, hromadné obrázky,"
        " audio nahrávky, skryté partice."
    ),
    signals=(
        SignalSpec(
            key="steganography", weight=2, kind="artifact_type",
            patterns=("antiforensics/steganography",),
            description="LSB steganografie PNG/JPG (F1.4)",
        ),
        SignalSpec(
            key="image_cluster", weight=2, kind="file_pattern", min_count=5,
            pattern=r"(?i)\.(jpe?g|png|gif|webp|bmp)$",
            description="≥5 obrázkových souborů v jednom case",
        ),
        SignalSpec(
            key="voice_recordings", weight=1, kind="artifact_type",
            patterns=("voice_recording",),
            description="audio nahrávky (voice_recording artefakty)",
        ),
        SignalSpec(
            key="hidden_partition", weight=1, kind="artifact_type",
            patterns=("antiforensics/hidden_partition",),
            description="skrytá/partition table anomálie (F1.4)",
        ),
    ),
    threshold=3,
    hypothesis_template=(
        "Indikátory MEDIA/CSAM v případě {case_id} (skóre {score}): {signals}. "
        "Doporučený postup: verifikace hashů proti známým souborům, review metadata"
        " obrázků, hloubková steganografická analýza."
    ),
)

EXFILTRATION = TriageProfile(
    key="exfiltration",
    title="Exfiltrace dat (unik ven)",
    description=(
        "Odchod dat: hromadné přílohy, cloud uploady, velké base64 payloady,"
        " mazání po zkopírování."
    ),
    signals=(
        SignalSpec(
            key="base64_blob", weight=2, kind="artifact_text", pattern="base64_blob_payload",
            description="velké base64 payloady v provozu (F1.3 IoC)",
        ),
        SignalSpec(
            key="bulk_attachments", weight=2, kind="artifact_type",
            patterns=("email_attachment",), min_count=3,
            description="≥3 e-mailové přílohy (hromadné odesílání)",
        ),
        SignalSpec(
            key="cloud_bulk_upload", weight=1, kind="artifact_type",
            patterns=("cloud_file",), min_count=5,
            description="≥5 cloud souborů (bulk upload)",
        ),
        SignalSpec(
            key="usn_truncation", weight=1, kind="artifact_type",
            patterns=("antiforensics/usn_truncation",),
            description="mazání po zkopírování (USN truncation)",
        ),
    ),
    threshold=3,
    hypothesis_template=(
        "Podezření na EXFILTRACI dat v případě {case_id} (skóre {score}): {signals}. "
        "Doporučený postup: objemová analýza odchodového provozu, přehled příloh"
        " a cloud uploadů."
    ),
)

#: Všechny profily F3.2 (pořadí = výchozí pro run_triage)
PROFILES: tuple[TriageProfile, ...] = (RANSOMWARE, INSIDER_THREAT, CSAM_MEDIA, EXFILTRATION)


__all__ = [
    "CSAM_MEDIA",
    "EXFILTRATION",
    "INSIDER_THREAT",
    "MAX_EVIDENCE",
    "PROFILES",
    "RANSOMWARE",
    "MatchedSignal",
    "ProfileReport",
    "SignalSpec",
    "TriageProfile",
    "evaluate_profile",
    "get_profile",
    "run_triage",
]
