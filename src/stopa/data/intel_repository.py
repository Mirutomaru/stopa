"""IntelRepository — IoC feed + matching (P2-5).

Tabulky ``ioc_feed_items`` / ``intel_matches`` (schéma v24): threat intel nad
případem. Kanonizace, STIX 2.1 import/export, klasifikace stáří a deterministický
matching žijí v čisté doménové vrstvě (``domain/threat_intel.py``); tady je jen I/O.

Sdílená connection s facade (WAL, commit) — stejný pattern jako ostatní repozitáře
(``InvestigationRepository``, ``ArtifactRepository``).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from stopa.domain.entities import collect_occurrences
from stopa.domain.threat_intel import (
    MAX_EVIDENCE,
    IntelMatch,
    IoC,
    _ensure_utc,
    classify_age,
    feed_summary,
    ioc_id,
    match_iocs,
)
from stopa.domain.yara_sigma import (
    EventTarget,
    SigmaTemplate,
    YaraHit,
    YaraTarget,
    match_yara_files,
    parse_sigma_templates,
    parse_yara_rule_names,
    rule_blocks,
    rule_tlp_level,
    sigma_matches,
    yara_available,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class IntelRepository:
    """CRUD nad intel tabulkami (P2-5): idempotentní import feedu + re-runnable matching."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── feed ────────────────────────────────────────────────────────
    def import_feed(self, case_id: str, iocs: list[IoC]) -> int:
        """Idempotentní upsert IoC do feedu (stejný UUIDv5 ID → 1 řádek).

        Vrací počet zapsaných řádků. ``acquired_at=None`` se uloží jako aktuální
        čas (sloupec NOT NULL — základ klasifikace stáří).
        """
        now = _now_iso()
        for ioc in iocs:
            self.conn.execute(
                "INSERT OR REPLACE INTO ioc_feed_items"
                " (id, case_id, kind, value, raw_value, tlp, source,"
                "  acquired_at, imported_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ioc_id(ioc),
                    case_id,
                    ioc.kind,
                    ioc.value,
                    ioc.raw_value or None,
                    ioc.tlp,
                    ioc.source or None,
                    ioc.acquired_at.isoformat() if ioc.acquired_at else now,
                    now,
                ),
            )
        self.conn.commit()
        return len(iocs)

    def _load_iocs(self, case_id: str) -> list[IoC]:
        rows = self.conn.execute(
            "SELECT kind, value, raw_value, tlp, source, acquired_at"
            " FROM ioc_feed_items WHERE case_id = ? ORDER BY kind, value",
            (case_id,),
        ).fetchall()
        out: list[IoC] = []
        for r in rows:
            d = dict(r)
            out.append(
                IoC(
                    kind=d["kind"],
                    value=d["value"],
                    raw_value=d.get("raw_value") or "",
                    tlp=d["tlp"],
                    source=d.get("source") or "",
                    acquired_at=datetime.fromisoformat(d["acquired_at"]),
                )
            )
        return out

    def list_feed(self, case_id: str) -> list[dict]:
        """Položky feedu seřazené (kind, value), každá s klasifikací stáří."""
        now = datetime.now(timezone.utc)
        rows = self.conn.execute(
            "SELECT id, kind, value, raw_value, tlp, source, acquired_at, imported_at"
            " FROM ioc_feed_items WHERE case_id = ? ORDER BY kind, value",
            (case_id,),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            d["age"] = classify_age(datetime.fromisoformat(d["acquired_at"]), now)
            out.append(d)
        return out

    def feed_summary(self, case_id: str) -> dict:
        """Shrnutí feedu (doménové ``feed_summary``) pro CLI/Web."""
        return feed_summary(self._load_iocs(case_id))

    # ── matching ────────────────────────────────────────────────────
    def clear_matches(self, case_id: str) -> int:
        cur = self.conn.execute("DELETE FROM intel_matches WHERE case_id = ?", (case_id,))
        return cur.rowcount or 0

    def save_matches(self, case_id: str, matches) -> list[int]:
        """Re-run matching = clear + insert (deterministický stav, bez duplicit)."""
        now = _now_iso()
        self.clear_matches(case_id)
        ids: list[int] = []
        for m in matches:
            cur = self.conn.execute(
                "INSERT INTO intel_matches"
                " (case_id, ioc_id, match_kind, evidence_json,"
                "  first_seen, last_seen, matched_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    m.ioc_id,
                    m.match_kind,
                    json.dumps(list(m.evidence), ensure_ascii=False),
                    m.first_seen,
                    m.last_seen,
                    now,
                ),
            )
            ids.append(int(cur.lastrowid or 0))
        self.conn.commit()
        return ids

    def list_matches(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, ioc_id, match_kind, evidence_json,"
            " first_seen, last_seen, matched_at"
            " FROM intel_matches WHERE case_id = ? ORDER BY id",
            (case_id,),
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            d["evidence"] = json.loads(d.pop("evidence_json") or "[]")
            out.append(d)
        return out


def _load_yara_sources(dir_path: str) -> list[tuple[str, str]]:
    """(jméno souboru, text) všech .yar/.yara souborů v adresáři (P3-5).

    Seřazené podle jména souboru → deterministické pořadí pravidel (AK2).
    ValueError: neadresář. OSError: nečitelný soubor.
    """
    p = Path(dir_path)
    if not p.is_dir():
        raise ValueError(f"YARA adresář neexistuje nebo není adresář: {dir_path!r}")
    out: list[tuple[str, str]] = []
    for f in sorted(p.iterdir(), key=lambda x: x.name):
        if f.suffix.lower() in (".yar", ".yara") and f.is_file():
            out.append((f.name, f.read_text(encoding="utf-8")))
    return out


def _rule_feed_iocs(
    yara_sources: list[tuple[str, str]], sigma_tpls: list[SigmaTemplate], sigma_name: str
) -> list[IoC]:
    """Pravidla jako feed itemy (P3-5): ``value`` = název pravidla (kanonický identifikátor),
    ``raw_value`` = text pravidla / JSON šablony → verze + TLP viditelné ve feedu.
    """
    iocs: list[IoC] = []
    for fname, text in yara_sources:  # seřazené podle jména souboru (AK2)
        for name, block in rule_blocks(text):
            iocs.append(
                IoC(
                    kind="yara_rule",
                    value=name,
                    raw_value=block,
                    tlp=rule_tlp_level(block) or "GREEN",
                    source=fname,
                )
            )
    for tpl in sigma_tpls:  # pořadí dokumentu — deterministické
        iocs.append(
            IoC(
                kind="sigma_tpl",
                value=tpl.name,
                raw_value=json.dumps(tpl.model_dump(), sort_keys=True),
                tlp=tpl.tlp,
                source=sigma_name,
            )
        )
    return iocs


def _file_contents(conn: sqlite3.Connection) -> dict[str, bytes | None]:
    """Obsah souborů ze case storage (``sources.path`` + ``files.rel_path``).

    Chybějící soubor na disku → hodnota ``None`` (YARA engine ho řídí jako
    chybějící — target s ``data=None``, AK1 explicitní stav); I/O chyby neblokují.
    """
    out: dict[str, bytes | None] = {}
    for r in conn.execute(
        "SELECT f.id AS id, s.path AS base, f.rel_path AS rel"
        " FROM files f JOIN sources s ON s.id = f.source_id"
    ):
        d = dict(r)
        p = Path(d["base"]) / d["rel"] if d["rel"] else Path(d["base"])
        try:
            out[d["id"]] = p.read_bytes()
        except OSError:
            out[d["id"]] = None
    return out


def _yara_engine_matches(conn: sqlite3.Connection, yara_sources: list[tuple[str, str]]) -> list[IntelMatch]:
    """YARA pravidla × soubory případu → ``match_kind='yara'`` (jeden záznam na pravidlo).

    Evidence = zasažené soubory seřazené ``(source_id, rel_path)``, stáha MAX_EVIDENCE.
    ValueError: neplatný YARA zdroj; RuntimeError: yara-python není nainstalované (AK1).
    """
    meta: dict[str, tuple[str, str]] = {}
    for fname, text in yara_sources:
        for name, block in rule_blocks(text):
            meta[name] = (rule_tlp_level(block) or "GREEN", fname)
    contents = _file_contents(conn)
    rows = conn.execute(
        "SELECT id, source_id, rel_path FROM files ORDER BY source_id, rel_path"
    ).fetchall()
    targets = [
        YaraTarget(source_id=r["source_id"], rel_path=r["rel_path"], data=contents.get(r["id"]))
        for r in rows
    ]
    hits: list[YaraHit] = []
    for _fname, text in yara_sources:
        if parse_yara_rule_names(text):  # prázdný soubor (jen komentáře) → přeskočit, ne selhat
            hits.extend(match_yara_files(text, targets))
    out: list[IntelMatch] = []
    for rule in sorted({h.rule for h in hits}):  # AK2 — pořadí pravidel nezávislé na zdrojích
        evs = [
            {"rel_path": h.rel_path, "source_id": h.source_id}
            for h in hits
            if h.rule == rule
        ]
        evs.sort(key=lambda e: (e["source_id"], e["rel_path"]))
        tlp, src_name = meta[rule]
        ioc = IoC(kind="yara_rule", value=rule, tlp=tlp, source=src_name)  # kanonický název — validace nemůže selhat
        out.append(
            IntelMatch(
                ioc_id=ioc_id(ioc),
                kind="yara_rule",
                value=rule,
                tlp=tlp,
                source=src_name,
                match_kind="yara",
                evidence=tuple(evs[:MAX_EVIDENCE]),
            )
        )
    return out


def _sigma_engine_matches(db, sigma_tpls: list[SigmaTemplate], sigma_name: str) -> list[IntelMatch]:
    """Sigma šablony × timeline události → ``match_kind='sigma'`` (jeden záznam na šablonu).

    Evidence = ID shodných událostí s časem a titulkem (seřazené časem — AK2),
    stáha MAX_EVIDENCE; first_seen/last_seen = min/max času shodných událostí.
    Deterministické pořadí šablon podle názvu, nezávislé na pořadí dokumentu.
    ValueError: neplatné ISO datum události.
    """
    events = []
    for r in db.list_timeline_events():
        d = dict(r)
        events.append(
            EventTarget(
                id=str(d["id"]),
                ts_utc=d["ts_utc"],
                event_type=d.get("event_type") or "",
                title=d.get("title") or "",
                rel_path=d.get("rel_path") or "",
                anomaly_flags=d.get("anomaly_flags") or "",
            )
        )
    ev_by_id = {e.id: e for e in events}
    out: list[IntelMatch] = []
    for tpl in sorted(sigma_tpls, key=lambda t: t.name):  # AK2 — nezávislé na pořadí dokumentu
        ids = sigma_matches(tpl, events)
        if not ids:
            continue
        ioc = IoC(kind="sigma_tpl", value=tpl.name, tlp=tpl.tlp, source=sigma_name)
        evs = [
            {"id": eid, "ts_utc": ev_by_id[eid].ts_utc, "title": ev_by_id[eid].title}
            for eid in ids[:MAX_EVIDENCE]
        ]
        ts_list = [_ensure_utc(datetime.fromisoformat(ev_by_id[i].ts_utc)) for i in ids]
        out.append(
            IntelMatch(
                ioc_id=ioc_id(ioc),
                kind="sigma_tpl",
                value=tpl.name,
                tlp=tpl.tlp,
                source=sigma_name,
                match_kind="sigma",
                evidence=tuple(evs),
                first_seen=min(ts_list).isoformat(),
                last_seen=max(ts_list).isoformat(),
            )
        )
    return out


def run_intel_match(
    db, case_id: str, yara_dir: str | None = None, sigma_file: str | None = None
) -> dict:
    """Deterministické matching IoC feedu případu × artefakty/entities (+ P3-5 pravidla).

    Tenká IO vrstva nad CaseDB (pattern ``run_correlation``):
    1. načtení feedu z ``ioc_feed_items``,
    2. **P3-5**: YARA zdroje (``yara_dir``, .yar soubory) a Sigma šablony (``sigma_file``,
       JSON/YAML dokument) se upsertnou do feedu jako IoC druhů yara_rule/sigma_tpl
       (text pravidla v ``raw_value`` — verze + TLP viditelné ve feedu); jejich shody
       předřadí dedikované enginy s match_kind ``yara``/``sigma``,
    3. extrakce výskytů entit z artefaktů + záznamy souborů, deterministické matching →
       re-run = clear + insert do ``intel_matches``,
    4. shrnutí pro CLI/Web: summary feedu + počty per match_kind + list hitů;
       hity seřazené deterministicky (entity nejdříve, pak pravidla).

    ValueError: prázdný feed bez pravidel / neplatná YARA adresář nebo Sigma dokument /
    chybějící yara-python při --yara (AK1 explicitní stav) / neplatné ISO datum.
    """
    repo = IntelRepository(db.conn)
    iocs = repo._load_iocs(case_id)

    # P3-5: pravidla → feed itemy (idempotentní upsert; stejný název z více souborů = 1 řádek)
    yara_sources = _load_yara_sources(yara_dir) if yara_dir else []
    sigma_tpls: list[SigmaTemplate] = []
    sigma_name = ""
    if sigma_file:
        sigma_name = Path(sigma_file).name
        with open(sigma_file, encoding="utf-8") as f:
            sigma_tpls = parse_sigma_templates(f.read())

    rule_iocs = _rule_feed_iocs(yara_sources, sigma_tpls, sigma_name)
    if not iocs and not rule_iocs:
        raise ValueError(
            f"případ {case_id!r} nemá IoC feed — nejdřív `stopa intel import` "
            "(nebo --yara DIR / --sigma FILE)"
        )
    if yara_sources and not yara_available():  # AK1 — explicitní stav, ne tiché přeskočit
        raise ValueError("--yara: chybí yara-python (pip install yara-python)")
    if rule_iocs:
        repo.import_feed(case_id, rule_iocs)  # pravidla viditelná ve feedu (TLP/stáří → report)
        iocs = repo._load_iocs(case_id)

    artifacts = db.list_artifacts()
    files = db.list_files()
    occurrences = collect_occurrences(artifacts)
    matches: list[IntelMatch] = match_iocs(iocs, occurrences, files, artifacts)
    if yara_sources:  # dedikovaný engine (základní matching druh pravidla přeskočí)
        matches += _yara_engine_matches(db.conn, yara_sources)
    if sigma_tpls:
        matches += _sigma_engine_matches(db, sigma_tpls, sigma_name)

    repo.save_matches(case_id, matches)
    by_kind: dict[str, int] = {}
    for m in matches:
        by_kind[m.match_kind] = by_kind.get(m.match_kind, 0) + 1
    return {
        "summary": feed_summary(iocs),
        "matches_total": len(matches),
        "by_match_kind": dict(sorted(by_kind.items())),
        "matches": [
            {
                "ioc_id": m.ioc_id,
                "kind": m.kind,
                "value": m.value,
                "tlp": m.tlp,
                "match_kind": m.match_kind,
                "evidence_count": len(m.evidence),
                "first_seen": m.first_seen,
                "last_seen": m.last_seen,
            }
            for m in matches
        ],
    }