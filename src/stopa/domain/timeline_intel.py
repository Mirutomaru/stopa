"""Timeline Intelligence 2.0 — ČISTÁ logika, bez IO (STP-018).

Tři analytické vrstvy nad materializovanou timeline (``timeline_events``):

- **Rozpory** (``concurrent_activity``) — stejný subjekt (normalizovaná
  entita: telefon / e-mail / host / hash / účet) se v sliding window
  (default 60 s) objevuje ve dvou událostech S ODLIŠNÝM typem nebo z
  ODLIŠNÉHO souboru → podezřelá souběžná aktivita jednoho subjektu.
- **Duplikáty napříč zdroji** (``cross_source_duplicate``) — stejný obsah
  (typ + normalizovaný title) extrahovaný z více různých souborů/zdrojů →
  dvojnásobná extrakce; provenance (seznam zdrojů) se zachovává.
- **Provenience timestampů** — rozlišení ``source`` (čas z obsahu artifactu)
  vs ``derived`` (čas odvozený ze souborových metadat, např. MACE u NTFS)
  + klasifikace přesnosti (second / millisecond / microsecond / file_metadata).

Vstupem jsou řádky z ``db.list_timeline_events()`` (slovníky se sloupcem
``subject_values`` — normalizované entity uložené při extrakci). Výstup je
deterministický: pořadí skupin a událostí odpovídá chronologickému pořadí
timeline. Žádné IO → 100% offline testovatelné s fixturemi.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime

# Kanonické flagy (stabilní — report / GUI / testy se na ně spoléhají).
FLAG_CONCURRENT_ACTIVITY = "concurrent_activity"
FLAG_CROSS_SOURCE_DUP = "cross_source_duplicate"

DEFAULT_CONTRADICTION_WINDOW_SECONDS = 60.0

# Provenience hodnoty (sloupec timeline_events.ts_origin)
TS_ORIGIN_SOURCE = "source"      # čas z obsahu artifactu (parser ho extrahoval)
TS_ORIGIN_DERIVED = "derived"    # čas odvozený ze souborových metadat (MACE apod.)

# Přesnost timestampů (klasifikace pro report / auditovatelnost)
PRECISION_SECOND = "second"
PRECISION_MILLISECOND = "millisecond"
PRECISION_MICROSECOND = "microsecond"
PRECISION_FILE_METADATA = "file_metadata"  # derived — MACE, přesnost souborového systému
PRECISION_UNKNOWN = "unknown"


def normalize_title(title: str | None) -> str:
    """Kanonický tvar title pro porovnání obsahu (lowercase + whitespace collapse)."""
    if not title:
        return ""
    return " ".join(title.lower().split())


def classify_precision(ts: datetime | None, origin: str = TS_ORIGIN_SOURCE) -> str:
    """Přesnost timestampu podle provenience a rozlišení hodnoty.

    - ``derived`` → ``file_metadata`` (MACE — přesnost souborového systému,
      u NTFS/ext4 v našem modelu na sekundy);
    - ``source``  → odvozeno z µs komponenty: 0 → second, násobek 1000 →
      millisecond, jinak microsecond (epoch µs formáty např. Chrome).
    """
    if ts is None:
        return PRECISION_UNKNOWN
    if origin == TS_ORIGIN_DERIVED:
        return PRECISION_FILE_METADATA
    us = ts.microsecond
    if us == 0:
        return PRECISION_SECOND
    if us % 1000 == 0:
        return PRECISION_MILLISECOND
    return PRECISION_MICROSECOND


def provenance_summary(events: list[dict]) -> dict[str, int]:
    """Souhrn provenience timestampů pro report (počty podle origin + přesnosti)."""
    out = {
        "total": len(events),
        "origin_source": 0,
        "origin_derived": 0,
        "precision_second": 0,
        "precision_millisecond": 0,
        "precision_microsecond": 0,
        "precision_file_metadata": 0,
        "precision_unknown": 0,
    }
    for ev in events:
        origin = ev.get("ts_origin") or TS_ORIGIN_SOURCE
        if origin == TS_ORIGIN_DERIVED:
            out["origin_derived"] += 1
        else:
            out["origin_source"] += 1
        ts_raw = ev.get("ts_utc")
        try:
            ts = datetime.fromisoformat(ts_raw) if ts_raw else None
        except ValueError:
            ts = None
        prec = classify_precision(ts, origin)
        key = {
            PRECISION_SECOND: "precision_second",
            PRECISION_MILLISECOND: "precision_millisecond",
            PRECISION_MICROSECOND: "precision_microsecond",
            PRECISION_FILE_METADATA: "precision_file_metadata",
            PRECISION_UNKNOWN: "precision_unknown",
        }[prec]
        out[key] += 1
    return out


@dataclass(frozen=True)
class ContradictionGroup:
    """Skupina událostí tvořících časový rozpor (souběžná aktivita subjektu)."""

    group_id: str
    subject: str  # normalizovaná hodnota entity, kvůli které vznikl rozpor
    events: tuple[dict, ...]


@dataclass(frozen=True)
class DupGroup:
    """Skupina duplicitních záznamů se stejným obsahem napříč zdroji."""

    group_id: str
    event_type: str
    title_norm: str
    events: tuple[dict, ...]  # provenance: id/source_id/rel_path/ts_utc každého výskytu


@dataclass(frozen=True)
class TimelineIntelResult:
    """Výsledek analýzy — skupiny + per-event aktualizace pro DB."""

    contradictions: tuple[ContradictionGroup, ...] = ()
    dup_groups: tuple[DupGroup, ...] = ()
    # event_id → group_id (pro UPDATE timeline_events)
    event_contradiction_groups: dict[str, str] = field(default_factory=dict)
    event_dup_groups: dict[str, str] = field(default_factory=dict)


def _stable_group_id(prefix: str, seed: object) -> str:
    """Deterministické ID skupiny (hash semene — stabilní napříč běhy)."""
    digest = hashlib.sha256(repr(seed).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def find_contradictions(
    events: list[dict], window_seconds: float = DEFAULT_CONTRADICTION_WINDOW_SECONDS
) -> tuple[ContradictionGroup, ...]:
    """Detekce časových rozporů — souběžné aktivity jednoho subjektu.

    Pravidlo: stejná normalizovaná entita (``subject_values``) se objeví ve
    dvou událostech s |Δt| ≤ window a události mají ODLIŠNÝ ``event_type``
    nebo ODLIŠNÉ ``rel_path`` → rozpor. Stejný typ ze stejného souboru je
    legitimní opakovaná aktivita (např. série zpráv) — neoznačuje se.

    Skupiny jsou tranzitivní uzavření párových rozporů (union-find); pořadí
    skupin i událostí v nich je deterministický chronologický řetězec.
    """
    n = len(events)
    if n < 2:
        return ()

    # index subjektů → pozice událostí (události jsou už seřazené po ts_utc, id)
    by_subject: dict[str, list[int]] = {}
    for i, ev in enumerate(events):
        for subj in ev.get("subject_values") or ():
            if subj:
                by_subject.setdefault(subj, []).append(i)

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            # deterministický root = menší index
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    for subj, idxs in by_subject.items():
        for a_pos in range(len(idxs)):
            i = idxs[a_pos]
            for b_pos in range(a_pos + 1, len(idxs)):
                j = idxs[b_pos]
                # okno je časové — pozice jsou seřazené, stačí porovnávat sousedy dopředu
                dt = _delta_seconds(events[i], events[j])
                if dt is None:
                    continue
                if dt > window_seconds:
                    break  # další události subjektu jsou ještě dál v čase
                ev_i, ev_j = events[i], events[j]
                same_type = ev_i.get("event_type") == ev_j.get("event_type")
                same_file = (ev_i.get("rel_path") or "") == (ev_j.get("rel_path") or "")
                if not (same_type and same_file):
                    union(i, j)

    # komponenty → skupiny (jen s ≥2 událostmi), deterministické ID podle subjektu+členů
    components: dict[int, list[int]] = {}
    for i in range(n):
        components.setdefault(find(i), []).append(i)

    groups: list[ContradictionGroup] = []
    # deterministické pořadí skupin: podle minimálního ts_utc/id první události
    ordered_roots = sorted(
        components.keys(),
        key=lambda r: (events[r].get("ts_utc") or "", events[r].get("id") or ""),
    )
    for root in ordered_roots:
        members = components[root]
        if len(members) < 2:
            continue
        # subjekt skupiny = společná entita prvních dvou členů (pro zobrazení)
        common = _common_subjects(events[members[0]], events[members[1]])
        subject = common[0] if common else "?"
        gid = _stable_group_id("tci", (subject, tuple(members)))
        groups.append(ContradictionGroup(gid, subject, tuple(events[i] for i in sorted(members))))
    return tuple(groups)


def _common_subjects(ev_a: dict, ev_b: dict) -> list[str]:
    sa = set(ev_a.get("subject_values") or ())
    sb = set(ev_b.get("subject_values") or ())
    return sorted(sa & sb)


def _delta_seconds(ev_a: dict, ev_b: dict) -> float | None:
    """|Δt| v sekundách mezi dvěma událostmi (None pokud čas chybí/neplatný)."""
    try:
        ta = datetime.fromisoformat(ev_a["ts_utc"])
        tb = datetime.fromisoformat(ev_b["ts_utc"])
    except (KeyError, TypeError, ValueError):
        return None
    return abs((tb - ta).total_seconds())


def find_cross_source_duplicates(events: list[dict]) -> tuple[DupGroup, ...]:
    """Duplicitní záznamy se stejným obsahem extrahované z více zdrojů.

    Klíč = (event_type, normalizovaný title). Skupina je duplikátem jen pokud
    obsahuje ≥2 RŮZNÉ (source_id, rel_path) páry — opakovaná návštěva stejné
    URL ve stejném souboru (různé časy) je legitimní a neoznačuje se.
    Provenance (všechny výskyty) se zachovává v ``DupGroup.events``.
    """
    by_key: dict[tuple[str, str], list[dict]] = {}
    for ev in events:
        title_norm = normalize_title(ev.get("title"))
        if not title_norm:
            continue  # bez obsahu se porovnávat nedá (prázdné tituly jsou běžné)
        key = (ev.get("event_type") or "", title_norm)
        by_key.setdefault(key, []).append(ev)

    groups: list[DupGroup] = []
    for (etype, title_norm), evs in sorted(
        by_key.items(), key=lambda kv: (kv[1][0].get("ts_utc") or "", kv[1][0].get("id") or "")
    ):
        distinct_sources = {(e.get("source_id"), e.get("rel_path")) for e in evs}
        if len(distinct_sources) < 2:
            continue
        gid = _stable_group_id("dup", (etype, title_norm))
        groups.append(DupGroup(gid, etype, title_norm, tuple(evs)))
    return tuple(groups)


def analyze_timeline(
    events: list[dict], window_seconds: float = DEFAULT_CONTRADICTION_WINDOW_SECONDS
) -> TimelineIntelResult:
    """Kompletní analýza timeline — rozpory + duplikáty + per-event aktualizace.

    ``events`` = řádky z ``db.list_timeline_events()`` (chronologické, se
    sloupcem ``subject_values``). Čistá funkce — žádná IO; volající (pipeline /
    CLI) výsledek materializuje přes ``db.apply_timeline_intel()``.
    """
    contradictions = find_contradictions(events, window_seconds=window_seconds)
    dup_groups = find_cross_source_duplicates(events)

    event_contradiction_groups: dict[str, str] = {}
    for g in contradictions:
        for ev in g.events:
            eid = ev.get("id")
            if eid:
                event_contradiction_groups[eid] = g.group_id

    event_dup_groups: dict[str, str] = {}
    for g in dup_groups:
        for ev in g.events:
            eid = ev.get("id")
            if eid:
                event_dup_groups[eid] = g.group_id

    return TimelineIntelResult(
        contradictions=contradictions,
        dup_groups=dup_groups,
        event_contradiction_groups=event_contradiction_groups,
        event_dup_groups=event_dup_groups,
    )
