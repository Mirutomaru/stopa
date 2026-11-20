"""YARA/Sigma matching — čistá doménová vrstva (P3-5).

Doplňuje P2-5 threat intel o dva deklarativní enginy nad případem:

- **YARA** pravidla nad soubory případu. Pravidlový text se kompiluje přes
  volitelný balík ``yara-python`` (bez něj explicitní :class:`RuntimeError`,
  ne tiché přeskočení — AK1). Obsah souborů předává datová vrstva jako
  :data:`YaraTarget.data` (I/O zde není); ``data=None`` = soubor už není na
  disku (chybějící počítá volající).
- **Sigma** šablony nad událostmi časové osy. Deklarativní subset mapovaný
  na pole ``timeline_events``; podmínka = **AND přes zadané klíče, OR uvnitř
  klíče**. Dokument se parsuje jako JSON (vždy) nebo YAML (pokud je
  nainstalovaný PyYAML — volitelná závislost).

Konvence chyb: typová chyba = :class:`TypeError`, semantická = :class:`ValueError`.
Determinismus: všechny výstupy se řadí explicitně → stejný vstup = stejný
výstup nezávisle na pořadí vstupních seznamů (AK2). TLP a stáří pravidel se
respektují jako u IoC (feed item nese ``tlp``/``acquired_at``, P3-5 W2).
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator, model_validator

from .threat_intel import TLP_LEVELS, _ensure_utc

__all__ = [
    "EventTarget",
    "SigmaDetection",
    "SigmaTemplate",
    "YaraHit",
    "YaraTarget",
    "match_yara_files",
    "parse_sigma_templates",
    "parse_yara_rule_names",
    "rule_blocks",
    "rule_tlp_level",
    "sigma_matches",
    "yara_available",
]


# ── YARA ────────────────────────────────────────────────────────────────

#: Hlavička pravidla — ``rule <jmeno>``, volitelně s private/global.
_RULE_HEAD_RE = re.compile(
    r"^\s*(?:private\s+|global\s+)*rule\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE
)

#: TLP v meta bloku pravidla (``tlp = "AMBER"``, uvozovky volitelné).
_META_TLP_RE = re.compile(r'^\s*tlp\s*=\s*"?(WHITE|GREEN|AMBER|RED)"?', re.IGNORECASE | re.MULTILINE)


def yara_available() -> bool:
    """Je volitelný balík ``yara-python`` nainstalován (AK1 — explicitní stav)."""
    try:
        import yara  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class YaraTarget:
    """Jeden soubor ke skenu. ``data=None`` → už není na disku (chybějící)."""

    source_id: str
    rel_path: str
    data: bytes | None = None


@dataclass(frozen=True)
class YaraHit:
    """Shoda (pravidlo, soubor) — výstup se řadí ``(rule, source_id, rel_path)``."""

    rule: str
    source_id: str
    rel_path: str


def parse_yara_rule_names(text: str) -> list[str]:
    """Názvy pravidel v pořadí výskytu (deterministické; duplikáty se drží —

    je chytí kompilátor). TypeError: ne-string.
    """
    if not isinstance(text, str):
        raise TypeError("YARA zdroj musí být string")
    return _RULE_HEAD_RE.findall(text)


def rule_blocks(text: str) -> list[tuple[str, str]]:
    """Pravidlové bloky v pořadí výskytu — ``(námět, text od hlavičky do dalšího

    pravidla / konce souboru)``. Blok slouží k extrakci meta (TLP) bez počítání
    závorek (meta ``tlp = ...`` je dostatečně diskrétní vzor). TypeError: ne-string.
    """
    if not isinstance(text, str):
        raise TypeError("YARA zdroj musí být string")
    matches = list(_RULE_HEAD_RE.finditer(text))
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append((m.group(1), text[m.start():end]))
    return blocks


def rule_tlp_level(block: str) -> str | None:
    """TLP z meta bloku pravidla (``tlp = "AMBER"``) — jinak ``None``."""
    m = _META_TLP_RE.search(block)
    return m.group(1).upper() if m else None


def match_yara_files(rules_text: str, targets: Sequence[YaraTarget]) -> list[YaraHit]:
    """Zkompiluje pravidla jednou (yara-python) a naskenuje všechny soubory.

    Výstup seřazen ``(rule, source_id, rel_path)`` → nezávislý na pořadí vstupu.
    Soubory s ``data=None`` se přeskočí (volající je počítá jako chybějící).

    ValueError: žádné pravidlo / neplatný zdrojový text / chyba matchingu.
    TypeError: chybný typ argumentů. Chybějící yara-python = RuntimeError
    (explicitní stav, ne tiché 0 — AK1).
    """
    if not isinstance(rules_text, str):
        raise TypeError("YARA zdroj musí být string")
    names = parse_yara_rule_names(rules_text)
    if not names:
        raise ValueError("YARA zdroj neobsahuje žádné pravidlo")
    try:
        import yara
    except ImportError as exc:
        raise RuntimeError(
            "balík yara-python není nainstalován (pip install yara-python)"
        ) from exc
    try:
        compiled = yara.compile(source_rules=rules_text)
    except yara.Error as exc:  # SyntaxError/CompileError — semantická chyba pravidla
        raise ValueError(f"Neplatný YARA zdroj: {exc}") from exc

    hits: list[YaraHit] = []
    for t in targets:
        if not isinstance(t, YaraTarget):
            raise TypeError("targets musí být sekvence YaraTarget")
        if t.data is None:  # soubor už není na disku — počítá volající
            continue
        try:
            matched = compiled.match(data=t.data)
        except yara.Error as exc:  # vzácné (data neslučitelná s modulem)
            raise ValueError(f"YARA matching selhal pro {t.rel_path!r}: {exc}") from exc
        hits.extend(
            YaraHit(rule=m.rule, source_id=t.source_id, rel_path=t.rel_path)
            for m in matched
        )
    return sorted(hits, key=lambda h: (h.rule, h.source_id, h.rel_path))


# ── Sigma ───────────────────────────────────────────────────────────────


class SigmaDetection(BaseModel):
    """Deklarativní mapování na pole ``timeline_events``.

    Semantika: **AND přes zadané klíče, OR uvnitř klíče**. Nezadané klíče se
    ignorují; alespoň jedno kritérium vyžaduje :class:`SigmaTemplate`.
    """

    event_type: list[str] | None = None  # přesná shoda s timeline_events.event_type
    title_contains: list[str] | None = None  # case-insensitive substring v title
    path_glob: list[str] | None = None  # fnmatch vzor na rel_path
    anomaly_flag_any: list[str] | None = None  # některý komou oddělený flag přítomen
    ts_start: str | None = None  # ISO UTC (včetně) — nejdříve přípustný čas události
    ts_end: str | None = None  # ISO UTC (včetně)

    def has_criteria(self) -> bool:
        return any(
            v is not None and len(v) > 0
            for v in (
                self.event_type,
                self.title_contains,
                self.path_glob,
                self.anomaly_flag_any,
            )
        ) or self.ts_start is not None or self.ts_end is not None


class SigmaTemplate(BaseModel):
    """Jedna Sigma šablona — STOPA deklarativní subset nad timeline_events.

    Pydantic ValidationError je podtřída ValueError → semantická chyba dle
    konvence projektu (neplatná TLP, prázdný název, žádné kritérium).
    """

    name: str
    description: str = ""
    tlp: str = "GREEN"
    detection: SigmaDetection

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Název šablony musí být nenulový")
        return v

    @field_validator("tlp")
    @classmethod
    def _tlp_level(cls, v: str) -> str:
        if v not in TLP_LEVELS:
            raise ValueError(
                f"Neplatná TLP úroveň: {v!r} (očekáváno {'/'.join(TLP_LEVELS)})"
            )
        return v

    @model_validator(mode="after")
    def _has_criteria(self) -> SigmaTemplate:
        if not self.detection.has_criteria():
            raise ValueError("detection musí mít alespoň jedno kritérium")
        return self


@dataclass(frozen=True)
class EventTarget:
    """Jeden řádek ``timeline_events`` pro Sigma matching (I/O v datové vrstvě)."""

    id: str
    ts_utc: str
    event_type: str = ""
    title: str = ""
    rel_path: str = ""
    anomaly_flags: str = ""


def _parse_ts(value: str | None, ctx: str) -> datetime | None:
    if value is None:
        return None
    try:
        return _ensure_utc(datetime.fromisoformat(value))
    except ValueError as exc:
        raise ValueError(f"Neplatné ISO datum {ctx}: {value!r}") from exc


def _required_ts(value: str, ctx: str) -> datetime:
    """Povinné ISO datum (událost) — None zde není možná."""
    return _parse_ts(value, ctx)  # type: ignore[return-value]


def sigma_matches(tpl: SigmaTemplate, events: Sequence[EventTarget]) -> list[str]:
    """ID událostí splňujících šablonu — seřazené ``(ts_utc, id)``, deterministické.

    Semantika podmínky viz :class:`SigmaDetection` (AND přes klíče, OR uvnitř).
    ValueError: neplatné ts meze. TypeError: chybný typ argumentů.
    """
    if not isinstance(tpl, SigmaTemplate):
        raise TypeError("tpl musí být SigmaTemplate")
    d = tpl.detection
    start = _parse_ts(d.ts_start, "ts_start")
    end = _parse_ts(d.ts_end, "ts_end")

    out: list[str] = []
    ts_dt: dict[str, datetime] = {}
    for e in events:
        if not isinstance(e, EventTarget):
            raise TypeError("events musí být sekvence EventTarget")
        ev_ts = _required_ts(e.ts_utc, f"ts_utc události {e.id!r}")
        ts_dt[e.id] = ev_ts
        if d.event_type is not None and e.event_type not in d.event_type:
            continue
        if d.title_contains is not None:
            title_l = (e.title or "").lower()
            if not any(n.lower() in title_l for n in d.title_contains):
                continue
        if d.path_glob is not None and not any(
            fnmatch.fnmatch(e.rel_path or "", pat) for pat in d.path_glob
        ):
            continue
        if d.anomaly_flag_any is not None:
            flags = {f.strip() for f in (e.anomaly_flags or "").split(",") if f.strip()}
            if not any(f in flags for f in d.anomaly_flag_any):
                continue
        if start is not None and ev_ts < start:
            continue
        if end is not None and ev_ts > end:
            continue
        out.append(e.id)
    return sorted(out, key=lambda i: (ts_dt[i], i))


def _as_item_list(raw: Any, fmt: str) -> list[dict]:
    items = raw if isinstance(raw, list) else [raw]
    if not items:
        raise ValueError(f"Žádné šablony v {fmt} dokumentu")
    for it in items:
        if not isinstance(it, dict):
            raise TypeError(f"Šablona musí být objekt ({fmt}): {it!r}")
    return items  # type: ignore[return-value]


def parse_sigma_templates(doc: str) -> list[SigmaTemplate]:
    """Parsuje dokument Sigma šablon — JSON (vždy) nebo YAML (s PyYAML).

    Dokument = seznam objektů šablon (samotný objekt je také přijat); YAML
    multi-dokumenty se spojí. Pořadí šablon = pořadí v dokumentu.
    ValueError: neplatný/prázdný tvar, neplatná TLP, žádné kritérium.
    TypeError: ne-string / neobjekt položka. Chybějící PyYAML u YAML
    podkladu = explicitní ValueError (JSON funguje bez něj).
    """
    if not isinstance(doc, str):
        raise TypeError("doc musí být string")
    try:
        raw = json.loads(doc)
    except json.JSONDecodeError:
        try:
            import yaml  # volitelná závislost — JSON šablony fungují bez ní
        except ImportError as exc:
            raise ValueError(
                "PyYAML není nainstalován (pip install pyyaml) nebo použijte JSON"
            ) from exc
        try:
            docs = [d for d in yaml.safe_load_all(doc) if d is not None]
        except yaml.YAMLError as exc:
            raise ValueError(f"Neplatný YAML dokument: {exc}") from exc
        return [SigmaTemplate.model_validate(d) for d in _as_item_list(docs, "YAML")]
    return [SigmaTemplate.model_validate(d) for d in _as_item_list(raw, "JSON")]
