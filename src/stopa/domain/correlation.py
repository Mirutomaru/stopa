"""STOPA E4 — Correlation Engine (čistá doménová logika).

Tři pravidla propojení entit (ROADMAP E4 bod 3, ARCHITECTURE_PROPOSAL §6):

- ``same_contact``    (verified) — stejná kontaktní entita (phone/email) se
  objeví ve 2+ různých artifactech → potvrzený kontakt. entity_a == entity_b
  (self-link: „tato hodnota je ověřena napříč N důkazy“).
- ``temporal_overlap`` (inferred) — časová okna aktivit DVOU RŮZNÝCH entit na
  RŮZNÝCH zdrojích se překrývají (v toleranci) → hypotéza „stejná osoba na
  obou zařízeních“ (SECURITY_AND_EVIDENCE_INTEGRITY: analytickká hypotéza).
- ``hash_match``      (verified) — identický SHA-256 souboru napříč různými
  zdroji → tentýž soubor na více zařízeních. entity_a == entity_b.

Každé propojení nese **evidence list** (artifact/file ID + cesta + detail) —
dohledatelnost každého nálezu (pravidlo „přímý přechod z grafu na důkaz“).

Výsledek je deterministický: skupiny se řadí hodnotou entity, páry
temporal_overlap lexicograficky kanonickými ID. Spuštění korelace = explicitní
krok ``stopa correlate <case>`` (ne při extrakci — reprodukovatelnost).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from stopa.domain.entities import EntityOccurrence, collect_occurrences
from stopa.models import FileRecord

# výchozí tolerance překryvu časových oken (aktivita na zařízeních se neshoduje v sekundu)
DEFAULT_OVERLAP_TOLERANCE = timedelta(minutes=30)
# strop evidence listu — pro dohledatelnost, ne pro úplnost (ta je v DB)
MAX_EVIDENCE = 25

CONTACT_KINDS = ("phone", "email")


def _occ_key(o: EntityOccurrence) -> tuple:
    """Deterministické řazení výskytů (nezávislé na pořadí vstupních artifactů)."""
    return (
        o.value,
        o.source_id or "",
        0 if o.ts_utc is None else 1,
        str(o.ts_utc),
        o.artifact_id,
    )


def _sorted_occurrences(occurrences: list[EntityOccurrence]) -> list[EntityOccurrence]:
    return sorted(occurrences, key=_occ_key)


def entity_id(kind: str, value: str) -> str:
    """Kanonický identifikátor entity pro tabulku correlations.

    >>> entity_id("phone", "+420777123456")
    'tel:+420777123456'
    """
    prefix = {"phone": "tel"}.get(kind, kind)
    return f"{prefix}:{value}"


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@dataclass(frozen=True)
class CorrelationResult:
    """Jedno propojení — entity_a/entity_b jsou kanonická ID (entity_id())."""

    entity_a: str
    entity_b: str
    relation: str  # same_contact | temporal_overlap | hash_match
    confidence: str  # verified | inferred
    evidence: tuple[dict, ...] = ()


# ── pravidlo 1: same_contact (verified) ───────────────────────────


def _artifact_evidence(occurrences: list[EntityOccurrence]) -> list[dict]:
    """Evidence z výskytů — deduplikováno po artifactu, strop MAX_EVIDENCE."""
    out: list[dict] = []
    seen: set[str] = set()
    for o in _sorted_occurrences(occurrences):
        if o.artifact_id in seen:
            continue
        seen.add(o.artifact_id)
        out.append(
            {
                "artifact_id": o.artifact_id,
                "rel_path": o.rel_path,
                "detail": f"{o.kind}={o.value}",
            }
        )
        if len(out) >= MAX_EVIDENCE:
            break
    return out


def same_contact_rules(occurrences: list[EntityOccurrence]) -> list[CorrelationResult]:
    """Stejná phone/email entita ve 2+ různých artifactech → verified self-link."""
    groups: dict[tuple[str, str], list[EntityOccurrence]] = {}
    for o in occurrences:
        if o.kind in CONTACT_KINDS:
            groups.setdefault((o.kind, o.value), []).append(o)

    results: list[CorrelationResult] = []
    for (kind, value), occs in sorted(groups.items(), key=lambda kv: kv[0]):
        distinct_artifacts = {o.artifact_id for o in occs}
        if len(distinct_artifacts) >= 2:
            eid = entity_id(kind, value)
            results.append(
                CorrelationResult(eid, eid, "same_contact", "verified", tuple(_artifact_evidence(occs)))
            )
    return results


# ── pravidlo 2: temporal_overlap (inferred) ───────────────────────


def _source_time_ranges(occurrences: list[EntityOccurrence]) -> dict[tuple[str, str], tuple[datetime, datetime]]:
    """Časové okno [min, max] pro každý (entity value, source)."""
    ranges: dict[tuple[str, str], tuple[datetime, datetime]] = {}
    for o in occurrences:
        if o.ts_utc is None or not o.source_id:
            continue
        key = (o.value, o.source_id)
        lo, hi = ranges.get(key, (o.ts_utc, o.ts_utc))
        ranges[key] = (min(lo, o.ts_utc), max(hi, o.ts_utc))
    return ranges


def _windows_overlap(
    a: tuple[datetime, datetime], b: tuple[datetime, datetime], tolerance: timedelta
) -> bool:
    """Překryv oken s tolerancí (okna se mohou dotýkat v rámci tolerance)."""
    return a[0] <= b[1] + tolerance and b[0] <= a[1] + tolerance


def temporal_overlap_rules(
    occurrences: list[EntityOccurrence],
    tolerance: timedelta = DEFAULT_OVERLAP_TOLERANCE,
) -> list[CorrelationResult]:
    """Různé entity na různých zdrojích s překrývajícími se okny aktivit → inferred.

    Pár (X na zdroji A, Y na zdroji B), X ≠ Y a A ≠ B: pokud se jejich časová
    okna překrývají v toleranci, je to hypotéza stejné osoby na obou zařízeních.
    """
    ranges = _source_time_ranges(occurrences)
    # (value, source) → kind pro kanonické ID
    kinds: dict[str, str] = {}
    for o in occurrences:
        kinds.setdefault(o.value, o.kind)

    # uspořádané položky pro determinismus
    items = sorted(ranges.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    results: list[CorrelationResult] = []
    seen_pairs: set[tuple[str, str]] = set()

    for i in range(len(items)):
        (value_a, source_a), window_a = items[i]
        for j in range(i + 1, len(items)):
            (value_b, source_b), window_b = items[j]
            if value_a == value_b or source_a == source_b:
                continue  # stejná entita / stejný zdroj → jiné pravidlo
            if not _windows_overlap(window_a, window_b, tolerance):
                continue
            id_a = entity_id(kinds[value_a], value_a)
            id_b = entity_id(kinds[value_b], value_b)
            pair = (id_a, id_b) if id_a <= id_b else (id_b, id_a)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            evidence = [
                {
                    "artifact_id": o.artifact_id,
                    "rel_path": o.rel_path,
                    "detail": f"{o.kind}={o.value} na zdroji {source_a}",
                }
                for o in _sorted_occurrences(occurrences)
                if o.value == value_a and o.source_id == source_a and o.ts_utc is not None
            ][:MAX_EVIDENCE]
            evidence += [
                {
                    "artifact_id": o.artifact_id,
                    "rel_path": o.rel_path,
                    "detail": f"{o.kind}={o.value} na zdroji {source_b}",
                }
                for o in _sorted_occurrences(occurrences)
                if o.value == value_b and o.source_id == source_b and o.ts_utc is not None
            ][:MAX_EVIDENCE]
            results.append(
                CorrelationResult(pair[0], pair[1], "temporal_overlap", "inferred", tuple(evidence))
            )
    return results


# ── pravidlo 3: hash_match (verified) ─────────────────────────────


def hash_match_rules(files: list[FileRecord]) -> list[CorrelationResult]:
    """Identický SHA-256 napříč různými zdroji → verified self-link.

    Duplikáty v rámci jednoho zdroje řeší dedupe (files.is_duplicate_of);
    sem patří jen soubory, které se objeví na více zařízeních/zdrojích.
    """
    groups: dict[str, list[FileRecord]] = {}
    for f in files:
        if f.sha256:
            groups.setdefault(f.sha256.lower(), []).append(f)

    results: list[CorrelationResult] = []
    for h, recs in sorted(groups.items()):
        sources = {f.source_id for f in recs}
        if len(sources) < 2:
            continue
        eid = entity_id("hash", h)
        evidence = [
            {
                "file_id": f.id,
                "rel_path": f.rel_path,
                "source_id": f.source_id,
                "detail": f"SHA-256 {h[:16]}… ({f.size_bytes} B)",
            }
            for f in sorted(recs, key=lambda r: (r.source_id or "", r.rel_path))[:MAX_EVIDENCE]
        ]
        results.append(CorrelationResult(eid, eid, "hash_match", "verified", tuple(evidence)))
    return results


# ── veřejné API ───────────────────────────────────────────────────


def correlate(
    occurrences: list[EntityOccurrence],
    files: list[FileRecord],
    *,
    overlap_tolerance: timedelta = DEFAULT_OVERLAP_TOLERANCE,
) -> list[CorrelationResult]:
    """Všechna pravidla najednou (deterministické pořadí výsledků)."""
    out = same_contact_rules(occurrences)
    out += temporal_overlap_rules(occurrences, tolerance=overlap_tolerance)
    out += hash_match_rules(files)
    return out


def entity_rows_from_occurrences(occurrences: list[EntityOccurrence]) -> list[tuple]:
    """Agregace pro tabulku entities: (kind, value, raw_value, first_seen, last_seen).

    Časy jsou ISO UTC stringy (None pokud entita nemá timestampy). Řazení po
    (kind, value) → deterministický upsert.
    """
    agg: dict[tuple[str, str], tuple[list[str], datetime | None, datetime | None]] = {}
    for o in occurrences:
        key = (o.kind, o.value)
        raws, lo, hi = agg.get(key, ([], None, None))
        if o.raw_value and o.raw_value not in raws:
            raws.append(o.raw_value)
        if o.ts_utc is not None:
            lo = o.ts_utc if lo is None else min(lo, o.ts_utc)
            hi = o.ts_utc if hi is None else max(hi, o.ts_utc)
        agg[key] = (raws, lo, hi)

    out: list[tuple] = []
    for (kind, value), (raws, lo, hi) in sorted(agg.items()):
        # deterministický raw — lexikograficky první (nezávislé na pořadí vstupů)
        out.append((kind, value, min(raws) if raws else None, _iso(lo), _iso(hi)))
    return out


def run_correlation(db, case_id: str, *, overlap_tolerance: timedelta = DEFAULT_OVERLAP_TOLERANCE) -> dict:
    """Explicitní krok korelace (ROADMAP E4 bod 4) — tenká IO vrstva nad CaseDB.

    1. extrakce entit z artifactů → upsert do ``entities`` (idempotentní),
    2. výpočet pravidel,
    3. re-run = clear + insert (deterministický stav, bez duplicit).

    Vrací shrnutí pro CLI/GUI: počty entit a propojení podle typu.
    """
    artifacts = db.list_artifacts()
    files = db.list_files()
    occurrences = collect_occurrences(artifacts)

    n_entities = db.upsert_entities(case_id, entity_rows_from_occurrences(occurrences))
    results = correlate(occurrences, files, overlap_tolerance=overlap_tolerance)
    db.clear_correlations(case_id)
    for r in results:
        db.add_correlation(case_id, r.entity_a, r.entity_b, r.relation, r.confidence, list(r.evidence))

    by_relation: dict[str, int] = {}
    for r in results:
        by_relation[r.relation] = by_relation.get(r.relation, 0) + 1
    return {
        "entities": n_entities,
        "correlations_total": len(results),
        "by_relation": by_relation,
    }
