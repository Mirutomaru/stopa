"""P2-3 Advanced Timeline Intelligence — ČISTÁ logika, bez IO.

Čtyři analytické vrstvy nad materializovanou timeline (``timeline_events``,
řádky z ``db.list_timeline_events()`` — slovníky s ISO ``ts_utc``, seznamem
``subject_values`` a analýtickými skupinami ze STP-018):

- **Normalizace s deklarovanou přesností** (``normalize_to_utc``) — epoch
  s/ms/µs (Chrome), ISO 8601 s offsetem, naive časy s IANA zónou (DST-safe);
  přesnost dle ``timeline_intel.classify_precision``.
- **Gapy a outliery na celé timeline** (IQR + absolutní prah) — Tukey plotny
  Q3 + k·IQR nad meziudálostními intervalemi; outlier = událost izolovaná
  oboustranně (velký gap i před, i za).
- **Cross-source korelace** — sdílená normalizovaná entita v časovém okně z
  odlišných zdrojů (union-find), confidence z E4 úrovní
  (``entity_resolution.CONFIDENCE_LEVELS``) nebo default ``possible``.
- **Vysvětlení nejistoty** — per událost kanonické důvody proč je údaj
  nejisté (nízká confidence, derived čas, slabá přesnost, flagy, analytické
  skupiny) + souhrn pro report/UI.

Determinismus: všechny výstupy se řadí chronologicky / lexikálně; stejné
vstupy = stejný JSON (``TimelineAdvResult.to_dict()``). Žádné IO → offline
testovatelné s fixturemi.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

from stopa.domain.entity_resolution import CONFIDENCE_LEVELS, map_legacy_confidence
from stopa.domain.timeline_intel import classify_precision

# ── Normalizace s deklarovanou přesností ─────────────────────────────────────


@dataclass(frozen=True)
class NormalizedTs:
    """Normalizovaný čas (naive UTC) + deklarovaná přesnost."""

    ts_utc: datetime  # naive UTC — shodné se konvencí timeline_events.ts_utc
    precision: str    # second | millisecond | microsecond | file_metadata | unknown


def _epoch_to_datetime(value: float) -> datetime:
    """Epoch magnitude heuristic: <1e10 s, <1e13 ms, jinak µs (Chrome).

    Přesná celočíselná aritmetika (timedelta z celých jednotek) — bez float
    chyby při extrakci µs komponenty.
    """
    if value < 0:
        raise ValueError(f"epoch musí být nezáporný, dostal {value!r}")
    base = datetime(1970, 1, 1)
    if value >= 1e13:   # µs (Chrome epoch)
        return base + timedelta(microseconds=int(value))
    if value >= 1e10:   # ms
        return base + timedelta(milliseconds=int(value))
    seconds, frac = divmod(float(value), 1.0)
    return base + timedelta(seconds=int(seconds), microseconds=round(frac * 1_000_000))


def normalize_to_utc(
    raw: float | str | datetime, *, tz: str | ZoneInfo | None = None
) -> NormalizedTs:
    """Normalizuje libovolný zdrojový čas do naive UTC s deklarovanou přesností.

    - ``int/float`` → epoch (s/ms/µs dle magnitude — viz ``_epoch_to_datetime``);
    - ``str`` → ISO 8601; s offsetem se převádí, naive se interpretuje v zóně
      ``tz`` (IANA název / ZoneInfo), default UTC. DST-safe přes ``zoneinfo``.
    - ``datetime`` → aware se převádí, naive analogicky podle ``tz``.

    Přesnost deklarujeme z µs komponenty výsledku (``classify_precision``) —
    epoch s celou vteřinou = second, ms násobky = millisecond, jinak microsecond.
    """
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        dt = _epoch_to_datetime(float(raw))
    else:
        try:
            dt = datetime.fromisoformat(str(raw).strip())
        except ValueError as exc:
            raise ValueError(f"nepodporovaný tvar času: {raw!r}") from exc

    if dt.tzinfo is None and tz is not None:
        zone = ZoneInfo(tz) if isinstance(tz, str) else tz
        dt = dt.replace(tzinfo=zone).astimezone(UTC)
    elif dt.tzinfo is not None:
        dt = dt.astimezone(UTC)

    naive_utc = dt.replace(tzinfo=None)
    return NormalizedTs(ts_utc=naive_utc, precision=classify_precision(naive_utc))


# ── Gapy a outliery (IQR + absolutní prah) ───────────────────────────────────

MIN_IQR_SAMPLES = 8   # méně intervalů → IQR statisticky nestabilní
DEFAULT_IQR_K = 1.5   # Tukey plotny: Q3 + k·IQR
DEFAULT_MIN_GAP_SECONDS = 60.0


@dataclass(frozen=True)
class GapInfo:
    """Mezera v timeline mezi dvěma po sobě následujícími událostmi."""

    start_event_id: str
    end_event_id: str
    start_ts: str           # ISO UTC
    end_ts: str             # ISO UTC
    duration_seconds: float


@dataclass(frozen=True)
class OutlierInfo:
    """Událost izolovaná oboustranně (velký gap i před, i za)."""

    event_id: str
    ts_utc: str
    prev_gap_seconds: float
    next_gap_seconds: float


def _parse_events(events: list[dict]) -> list[tuple[str, datetime]]:
    """Řádky → (id, naive UTC) seřazené po čase; tiebreak podle id.

    Události s neplatným ``ts_utc`` se vynechávají (defenzivní — reálné DB
    může obsahovat legacy řádky); výsledek je deterministický.
    """
    out: list[tuple[str, datetime]] = []
    for ev in events:
        try:
            ts = datetime.fromisoformat(ev["ts_utc"])  # key absent → KeyError
        except (KeyError, TypeError, ValueError):
            continue
        eid = str(ev.get("id") or "")
        out.append((eid, ts))
    out.sort(key=lambda pair: (pair[1], pair[0]))
    return out


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Lineární interpolace kvantil nad seřazenou hodnotami (deterministický)."""
    if not sorted_vals:
        return 0.0
    idx = q * (len(sorted_vals) - 1)
    lo = math.floor(idx)   # floor v Py3 vrací int
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _gap_fence(deltas: list[float], iqr_k: float) -> float | None:
    """Tukey plotna Q3 + k·IQR; pod MIN_IQR_SAMPLES → None (jen absolutní prah)."""
    if len(deltas) < MIN_IQR_SAMPLES:
        return None
    s = sorted(deltas)
    q1, q3 = _quantile(s, 0.25), _quantile(s, 0.75)
    return q3 + iqr_k * (q3 - q1)


def _is_gap(delta: float, fence: float | None, min_gap_seconds: float) -> bool:
    return delta >= min_gap_seconds and (fence is None or delta > fence)


def detect_gaps(
    events: list[dict], *, iqr_k: float = DEFAULT_IQR_K,
    min_gap_seconds: float = DEFAULT_MIN_GAP_SECONDS,
) -> tuple[GapInfo, ...]:
    """Gapy na celé timeline — intervaly překračující IQR plotnu a absolutní prah.

    Deterministické chronologické pořadí; gap je vzdálenost mezi po sobě
    následujícími událostmi (O(n log n) díky předchozímu seřazení).
    """
    ordered = _parse_events(events)
    if len(ordered) < 2:
        return ()
    deltas = [(b[1] - a[1]).total_seconds() for a, b in pairwise(ordered)]
    fence = _gap_fence(deltas, iqr_k)
    gaps: list[GapInfo] = []
    prev = ordered[0]
    for cur in ordered[1:]:
        delta = (cur[1] - prev[1]).total_seconds()
        if _is_gap(delta, fence, min_gap_seconds):
            gaps.append(GapInfo(
                start_event_id=prev[0],
                end_event_id=cur[0],
                start_ts=prev[1].isoformat(),
                end_ts=cur[1].isoformat(),
                duration_seconds=round(delta, 6),
            ))
        prev = cur
    return tuple(gaps)


def detect_outliers(
    events: list[dict], *, iqr_k: float = DEFAULT_IQR_K,
    min_gap_seconds: float = DEFAULT_MIN_GAP_SECONDS,
) -> tuple[OutlierInfo, ...]:
    """Outliery — události izolované oboustranně (gap před I za přesahuje prahy).

    První a poslední událost nikdy není outlierem (chybí jedna strana);
    deterministické chronologické pořadí.
    """
    ordered = _parse_events(events)
    if len(ordered) < 3:
        return ()
    deltas = [(b[1] - a[1]).total_seconds() for a, b in pairwise(ordered)]
    fence = _gap_fence(deltas, iqr_k)
    out: list[OutlierInfo] = []
    for i in range(1, len(ordered) - 1):
        prev_gap, next_gap = deltas[i - 1], deltas[i]
        if _is_gap(prev_gap, fence, min_gap_seconds) and _is_gap(next_gap, fence, min_gap_seconds):
            out.append(OutlierInfo(
                event_id=ordered[i][0],
                ts_utc=ordered[i][1].isoformat(),
                prev_gap_seconds=round(prev_gap, 6),
                next_gap_seconds=round(next_gap, 6),
            ))
    return tuple(out)


# ── Cross-source korelace (sdílená entita v okně z odlišných zdrojů) ─────────

DEFAULT_CORRELATION_WINDOW_SECONDS = 300.0
DEFAULT_CONFIDENCE = "possible"   # E4: bez explicitního ověření → možné


@dataclass(frozen=True)
class XCorrelationGroup:
    """Skupina událostí sdílející subjekt napříč zdroji v časovém okně."""

    group_id: str
    subject: str
    confidence: str                       # E4 level (confirmed > strong_candidate > possible > unverified)
    source_ids: tuple[str, ...]           # distinct zdroje skupiny (seřazené)
    event_ids: tuple[str, ...]            # chronologicky


def _stable_group_id(prefix: str, seed: object) -> str:
    return f"{prefix}-{hashlib.sha256(json.dumps(seed).encode('utf-8')).hexdigest()[:16]}"


def entity_confidence_map(correlation_rows: list[dict]) -> dict[str, str]:
    """E4 confidence per entita = nejvyšší rank mezi jejími propojeními.

    Vstup = řádky z ``db.list_correlations(case_id)`` (entity_a/entity_b +
    confidence); staré hodnoty mapuje ``map_legacy_confidence`` (idempotentní).
    Entita bez propojení se nevrací → konzument použije default ``possible``.
    """
    best: dict[str, int] = {}
    for row in correlation_rows or ():
        level = map_legacy_confidence(row.get("confidence"))
        rank = CONFIDENCE_LEVELS.index(level)   # 0 = confirmed (nejvyšší)
        for entity in (row.get("entity_a"), row.get("entity_b")):
            if entity and rank < best.get(entity, len(CONFIDENCE_LEVELS)):
                best[entity] = rank
    return {e: CONFIDENCE_LEVELS[r] for e, r in sorted(best.items())}


def find_cross_source_correlations(
    events: list[dict], *, window_seconds: float = DEFAULT_CORRELATION_WINDOW_SECONDS,
    entity_confidence: dict[str, str] | None = None,
) -> tuple[XCorrelationGroup, ...]:
    """Korelace napříč zdroji — sdílená normalizovaná entita v časovém okně.

    Párové vazby (stejný prvek ``subject_values``, odlišné ``source_id``,
    |Δt| ≤ window) uzavíráme union-findem na komponenty; komponenta je
    korelací jen pokud obsahuje ≥2 distinct zdroje. Výstup = jedna skupina
    na (subjekt, komponentu). Confidence = E4 úroveň sdíleného subjektu z
    volitelného mapování ``entity_confidence`` (např. tabulka entities),
    jinak default ``possible``. Deterministické pořadí: min ts členů, pak id.
    """
    ordered = _parse_events(events)  # chronologicky; tiebreak id
    n = len(ordered)
    if n < 2:
        return ()

    by_eid: dict[str, dict] = {}
    for ev in events:
        eid = str(ev.get("id") or "")
        if eid and eid not in by_eid:
            by_eid[eid] = ev

    def event_at(i: int) -> dict:
        return by_eid[ordered[i][0]]

    by_subject: dict[str, list[int]] = {}
    for i in range(n):
        for subj in event_at(i).get("subject_values") or ():
            if subj:
                by_subject.setdefault(subj, []).append(i)

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for subject in sorted(by_subject):
        idxs = by_subject[subject]   # chronologicky (pozice v ordered)
        for a_pos in range(len(idxs)):
            i = idxs[a_pos]
            src_i = str(event_at(i).get("source_id") or "")
            for b_pos in range(a_pos + 1, len(idxs)):
                j = idxs[b_pos]
                if (ordered[j][1] - ordered[i][1]).total_seconds() > window_seconds:
                    break   # dále už jen dál v čase
                src_j = str(event_at(j).get("source_id") or "")
                if not src_i or src_i == src_j:
                    continue   # stejný (nebo chybějící) zdroj ≠ cross-source
                parent[find(i)] = find(j)

    component_sources: dict[int, set[str]] = {}
    for i in range(n):
        r = find(i)
        src = str(event_at(i).get("source_id") or "")
        if src:
            component_sources.setdefault(r, set()).add(src)

    # defenzivní: jen platné E4 úrovně (confirmed/strong_candidate/possible/unverified)
    conf_map = {k: v for k, v in (entity_confidence or {}).items() if v in CONFIDENCE_LEVELS}
    out: list[XCorrelationGroup] = []
    for subject in sorted(by_subject):
        idxs = by_subject[subject]
        roots: dict[int, list[int]] = {}
        for i in idxs:
            roots.setdefault(find(i), []).append(i)
        for root, members in roots.items():
            if len(component_sources.get(root, set())) < 2:
                continue   # komponenta bez cross-source vazby
            member_eids = tuple(ordered[i][0] for i in sorted(members))
            sources = {
                str(event_at(i).get("source_id") or "") for i in members
            } - {""}
            out.append(XCorrelationGroup(
                group_id=_stable_group_id("xcorr", (subject, member_eids)),
                subject=subject,
                confidence=conf_map.get(subject, DEFAULT_CONFIDENCE),
                source_ids=tuple(sorted(sources)),
                event_ids=member_eids,
            ))

    def first_ts(g: XCorrelationGroup) -> str:
        for i in range(n):
            if ordered[i][0] == g.event_ids[0]:
                return ordered[i][1].isoformat()
        return ""

    out.sort(key=lambda g: (first_ts(g), g.group_id))
    return tuple(out)


# ── Vysvětlení nejistoty per událost ─────────────────────────────────────────

LOW_CONFIDENCE_THRESHOLD = 0.5   # confidence pod touto hodnotou → důvod nejistoty

REASON_LOW_CONFIDENCE = "low_confidence"
REASON_DERIVED_TIMESTAMP = "derived_timestamp"
REASON_WEAK_PRECISION = "weak_precision"
REASON_IN_CONTRADICTION = "in_contradiction"
REASON_CROSS_SOURCE_DUP = "cross_source_duplicate"
REASON_NO_PARSER_VERSION = "no_parser_version"


@dataclass(frozen=True)
class UncertaintyExplanation:
    """Proč je údaj události nejisté — kanonické důvody (seřazené)."""

    event_id: str
    reasons: tuple[str, ...]     # lexikálně seřazené kódové příčiny
    severity: str                # low | medium | high (dle počtu důvodů)


def _flags_of(ev: dict) -> list[str]:
    raw = ev.get("anomaly_flags") or []
    if isinstance(raw, str):   # defenzivní — DB vrací list, legacy řetězec tolerujeme
        return [f for f in raw.split(",") if f]
    return [str(f) for f in raw if f]


def explain_uncertainty(events: list[dict]) -> tuple[UncertaintyExplanation, ...]:
    """Per událost vysvětlení nejistoty z dostupných metadat (bez IO).

    Důvody (kanonické kódy): nízká confidence (<0.5), derived čas (MACE apod.),
    slabá/unknown přesnost timestampu, existující anomaly flagy
    (``anomaly_flag:<flag>``), účast v rozporové/duplikátní skupině, chybějící
    parser_version. Události bez důvodů se nevracejí; pořadí je deterministické
    (seřazeno podle event id, nezávislé na pořadí vstupu).
    """
    out: list[UncertaintyExplanation] = []
    for ev in events:
        eid = str(ev.get("id") or "")
        if not eid:
            continue
        reasons: set[str] = set()

        conf = ev.get("confidence")
        if isinstance(conf, (int, float)) and conf < LOW_CONFIDENCE_THRESHOLD:
            reasons.add(REASON_LOW_CONFIDENCE)

        origin = str(ev.get("ts_origin") or "source")
        if origin == "derived":
            reasons.add(REASON_DERIVED_TIMESTAMP)

        try:
            ts = datetime.fromisoformat(str(ev.get("ts_utc") or ""))
        except (TypeError, ValueError):
            ts = None
        if classify_precision(ts, origin) == "unknown" and origin != "derived":
            reasons.add(REASON_WEAK_PRECISION)

        for flag in _flags_of(ev):
            reasons.add(f"anomaly_flag:{flag}")

        if ev.get("contradiction_group_id"):
            reasons.add(REASON_IN_CONTRADICTION)
        if ev.get("dup_group_id"):
            reasons.add(REASON_CROSS_SOURCE_DUP)
        if not (ev.get("parser_version") or ""):
            reasons.add(REASON_NO_PARSER_VERSION)

        if reasons:
            n = len(reasons)
            severity = "high" if n >= 3 else "medium" if n == 2 else "low"
            out.append(UncertaintyExplanation(eid, tuple(sorted(reasons)), severity))
    out.sort(key=lambda exp: exp.event_id)   # deterministické pořadí nezávislé na vstupu
    return tuple(out)


def uncertainty_summary(explanations: tuple[UncertaintyExplanation, ...]) -> dict:
    """Souhrn nejistoty pro report/UI — počty per důvod a po závažnosti."""
    by_reason: dict[str, int] = {}
    severity_counts = {"low": 0, "medium": 0, "high": 0}
    for exp in explanations:
        severity_counts[exp.severity] += 1
        for reason in exp.reasons:
            base = reason.split(":", 1)[0] if reason.startswith("anomaly_flag:") else reason
            by_reason[base] = by_reason.get(base, 0) + 1
    return {
        "events_flagged": len(explanations),
        "by_severity": severity_counts,
        "by_reason": dict(sorted(by_reason.items())),
    }


# ── Agregátor ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TimelineAdvResult:
    """Kompletní výsledek P2-3 analýzy — deterministický JSON přes to_dict()."""

    gaps: tuple[GapInfo, ...]
    outliers: tuple[OutlierInfo, ...]
    correlations: tuple[XCorrelationGroup, ...]
    uncertainty: tuple[UncertaintyExplanation, ...]

    def to_dict(self) -> dict:
        """Deterministní JSON-safe slovník (stejné vstupy = stejný výstup)."""
        return {
            "gaps": [asdict(g) for g in self.gaps],
            "outliers": [asdict(o) for o in self.outliers],
            "correlations": [asdict(c) for c in self.correlations],
            "uncertainty": [asdict(u) for u in self.uncertainty],
            "summary": {
                "gaps": len(self.gaps),
                "outliers": len(self.outliers),
                "correlation_groups": len(self.correlations),
                **uncertainty_summary(self.uncertainty),
            },
        }


def analyze_timeline_adv(
    events: list[dict], *, gap_iqr_k: float = DEFAULT_IQR_K,
    min_gap_seconds: float = DEFAULT_MIN_GAP_SECONDS,
    correlation_window_seconds: float = DEFAULT_CORRELATION_WINDOW_SECONDS,
    entity_confidence: dict[str, str] | None = None,
) -> TimelineAdvResult:
    """Spustí všechny čtyři vrstvy P2-3 nad timeline (čistá funkce, bez IO)."""
    return TimelineAdvResult(
        gaps=detect_gaps(events, iqr_k=gap_iqr_k, min_gap_seconds=min_gap_seconds),
        outliers=detect_outliers(events, iqr_k=gap_iqr_k, min_gap_seconds=min_gap_seconds),
        correlations=find_cross_source_correlations(
            events, window_seconds=correlation_window_seconds,
            entity_confidence=entity_confidence,
        ),
        uncertainty=explain_uncertainty(events),
    )
