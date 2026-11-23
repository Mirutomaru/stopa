"""STOPA P2-5 — Threat Intelligence Workspace (čistá doménová logika).

Rozšíření F6.2 STIX exportu a F3.2 IoC signálů o **stáří intel dat** a
obousměrný STIX 2.1 formát pro feedy:

- :class:`IoC` — indikátor s druhy ``ip | domain | hash | url``, TLP značkou,
  zdrojem a ``acquired_at`` (kdy bylo intel datum získáno). Hodnota se
  normalizuje na kanonický tvar (E4 kanonika): hosty přes
  :func:`stopa.domain.entities.normalize_url_host`, hashe přes
  :func:`stopa.domain.entities.normalize_hash`, IP přes ``ipaddress``.
- **Stáří** = ``now − acquired_at`` s konfigurovatelnými prahy:
  ``fresh`` (mladší než fresh_days) / ``stale`` / ``old`` — hranice jsou
  striktní (přesně na prahu = starší třída).
- **STIX 2.1 bundle** import/export obousměrně v kanonickém tvaru: objekty
  seřazené ID, deterministické UUIDv5 ID, ``json.dumps(sort_keys=True)`` →
  roundtrip ``import(export(X)) == export(X)`` (AK P2-5).
- **Matching** IoC × case artefakty/entity — přesné na kanonických tvarech:
  hash ↔ entitní výskyty + SHA-256 souborů, domain/url ↔ ``url_host`` entity,
  ip ↔ sken volného textu artefaktů. Výsledek je deterministický (pořadí
  nezávislé na pořadí vstupů).

ATT&CK techniky ↔ artefakty mapuje existující F6.3 (:mod:`stopa.domain.mitre_attack`).
YARA/Sigma = volitelná extra závislost s graceful degradation (licenční poznámka
v ``docs/P2_DESIGNS.md``).
"""

from __future__ import annotations

import ipaddress
import json
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from stopa.domain.entities import EntityOccurrence, normalize_hash, normalize_url_host
from stopa.domain.json_bounded import bounded_json_loads
from stopa.models import Artifact, FileRecord

#: Druhy IoC — E4 kanonika + P3-5 pravidlové druhy (feed item nese samotné
#: pravidlo: value = název, raw_value = zdrojový soubor; STIX je nenesou).
IOC_KINDS = ("ip", "domain", "hash", "url", "yara_rule", "sigma_tpl")

#: Pravidlové druhy (P3-5) — YARA pravidla a Sigma šablony.
RULE_KINDS = ("yara_rule", "sigma_tpl")

#: Druhy s STIX třídou — bundle nese jen indikátorové hodnoty, ne pravidla.
_STIX_KINDS = tuple(k for k in IOC_KINDS if k not in RULE_KINDS)

#: TLP 1.0 úrovně sdílení (uppercase — kanonický tvar v DB i STIX expanzi).
TLP_LEVELS = ("WHITE", "GREEN", "AMBER", "RED")

#: Výchozí prahy stáří intel dat (dny) — konfigurovatelné parametrem.
DEFAULT_FRESH_DAYS = 30
DEFAULT_STALE_DAYS = 90

#: Strop evidence listu (konzistentně s E4 korelačním engine).
MAX_EVIDENCE = 25

# Deterministický namespace pro UUIDv5 ID IoC i bundle (offline, bez RNG).
_IOC_NS = uuid.UUID("6b7f1c8e-9a3d-5e2f-b4c1-d0a5e8f32107")

#: IPv4/IPv6 sken volného textu pro IP IoC (tokeny se validují přes ipaddress).
_IP_RE = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b|[0-9A-Fa-f:]*:[0-9A-Fa-f:.]+")

# STIX indicator pattern — jeden tvar na druh IoC (deterministický parsing).
_PATTERN_IP4 = re.compile(r"\[ipv4-addr:value = '([^']+)'\]")
_PATTERN_IP6 = re.compile(r"\[ipv6-addr:value = '([^']+)'\]")
_PATTERN_DOMAIN = re.compile(r"\[domain-name:value = '([^']+)'\]")
_PATTERN_HASH = re.compile(r"\[file:hashes\.'(MD5|SHA-1|SHA-256)' = '([0-9a-fA-F]+)'\]")

_ALGO_TO_LEN = {"MD5": 32, "SHA-1": 40, "SHA-256": 64}
_LEN_TO_ALGO = {32: "MD5", 40: "SHA-1", 64: "SHA-256"}


def _ensure_utc(dt: datetime) -> datetime:
    """Naive datetime = UTC (konzistentně s E4 korelačním engine)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return _ensure_utc(dt).isoformat()


# ── IoC model + kanonizace ───────────────────────────────────────


def canonical_value(kind: str, value: str) -> str:
    """Kanonický tvar hodnoty pro daný druh IoC (E4 kanonika).

    - ``ip``: normalizace přes :mod:`ipaddress` (IPv6 lowercase komprimovaný;
      IPv4 s vedoucími nulami = ValueError — ambiguita, Python ≥ 3.9.5).
    - ``domain``/``url``: hostname bez schématu/portu/cesty, lowercase
      (:func:`normalize_url_host`).
    - ``hash``: hex lowercase 32/40/64 (MD5/SHA-1/SHA-256) s tolerancí
      prefixů ``sha256:<hex>`` / ``md5=<hex>``.

    >>> canonical_value("url", "https://Example.COM:8443/path?q=1")
    'example.com'
    """
    if kind == "ip":
        try:
            return str(ipaddress.ip_address(value.strip()))
        except ValueError as exc:
            raise ValueError(f"Neplatná IP adresa IoC: {value!r}") from exc
    if kind in ("domain", "url"):
        n = normalize_url_host(value)
        if n is None:
            raise ValueError(f"Neplatný host IoC ({kind}): {value!r}")
        return n
    if kind == "hash":
        n = normalize_hash(value)
        if n is None:
            raise ValueError(f"Neplatný hash IoC (hex 32/40/64): {value!r}")
        return n
    if kind in RULE_KINDS:  # P3-5: název pravidla je už kanonický (identifikátor)
        v = value.strip()
        if not v or any(c.isspace() for c in v):
            raise ValueError(f"Neplatný název pravidla ({kind}): {value!r}")
        return v
    raise ValueError(f"Neznámý druh IoC: {kind!r} (očekáváno {'/'.join(IOC_KINDS)})")


@dataclass(frozen=True)
class IoC:
    """Jeden indikátor kompromitace s TLP, zdrojem a dobou získání.

    ``value`` je vždy kanonický tvar — konstruktor normalizuje (viz
    :func:`canonical_value`) a fail-closed validuje druh i TLP.
    """

    kind: str
    value: str  # kanonický tvar
    raw_value: str = ""  # původní tvar z feedu
    tlp: str = "GREEN"
    source: str = ""  # zdroj intel dat (feed/proces)
    acquired_at: datetime | None = None  # kdy bylo datum získáno (naive = UTC)

    def __post_init__(self) -> None:
        if self.kind not in IOC_KINDS:
            raise ValueError(f"Neznámý druh IoC: {self.kind!r}")
        if self.tlp not in TLP_LEVELS:
            raise ValueError(f"Neplatná TLP úroveň: {self.tlp!r} (očekáváno {'/'.join(TLP_LEVELS)})")
        object.__setattr__(self, "value", canonical_value(self.kind, self.value))


def _stix_class(kind: str) -> str:
    """STIX třída IoC — domain i url sdílí jeden pattern (domain-name),
    proto sdílejí i ID prostor. Roundtrip bundle je ztrátový jen pro druh
    „url“ (vrací se jako „domain“) a pro ``raw_value`` (display metadata)."""
    return "host" if kind in ("domain", "url") else kind


def ioc_id(ioc: IoC) -> str:
    """Deterministické UUIDv5 ID IoC — double-import feedu = 1 řádek (idempotence).

    Základ = STIX třída + kanonická hodnota → ID je stabilní přes roundtrip
    bundle (url→domain má stejné ID jako domain se stejným hostem).
    """
    return str(uuid.uuid5(_IOC_NS, f"ioc:{_stix_class(ioc.kind)}:{ioc.value}"))


# ── stáří intel dat ──────────────────────────────────────────────


def classify_age(
    acquired_at: datetime,
    now: datetime,
    fresh_days: int = DEFAULT_FRESH_DAYS,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> str:
    """Klasifikace stáří intel dat podle věku ``now − acquired_at``.

    Hranice jsou striktní: věk < fresh_days → ``fresh``, věk < stale_days →
    ``stale``, jinak ``old`` (přesně na prahu = starší třída). Naive časy
    se interpretují jako UTC. Konfigurovatelné prahy umožňují odlišné
    politiké per feed bez změny kódu.

    >>> from datetime import timedelta, timezone
    >>> t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    >>> classify_age(t0, t0 + timedelta(days=29), fresh_days=30)
    'fresh'
    >>> classify_age(t0, t0 + timedelta(days=30), fresh_days=30)
    'stale'
    """
    age = _ensure_utc(now) - _ensure_utc(acquired_at)
    if age < timedelta(days=fresh_days):
        return "fresh"
    if age < timedelta(days=stale_days):
        return "stale"
    return "old"


# ── STIX 2.1 bundle import/export (kanonický tvar) ───────────────


def _pattern_for(ioc: IoC) -> str:
    """STIX indicator pattern per druh IoC (deterministický, jeden tvar)."""
    if ioc.kind == "ip":
        addr_type = "ipv4-addr" if ":" not in ioc.value else "ipv6-addr"
        return f"[{addr_type}:value = '{ioc.value}']"
    if ioc.kind in ("domain", "url"):
        return f"[domain-name:value = '{ioc.value}']"
    algo = _LEN_TO_ALGO[len(ioc.value)]
    return f"[file:hashes.'{algo}' = '{ioc.value}']"


def export_bundle(iocs: Sequence[IoC]) -> str:
    """Export IoC do STIX 2.1 bundle v kanonickém (deterministickém) tvaru.

    Objekty se řadí UUID ID, bundle id je UUIDv5 nad seřazenými ID objektů a
    serializace ``json.dumps(sort_keys=True, ensure_ascii=False)`` → stejný
    vstup = stejný string nezávisle na pořadí seznamu :data:`iocs`.

    Vlastní extenze nesou metadata STOPA: ``x_stopa_source`` (zdroj intel dat)
    a ``x_stopa_tlp`` (TLP úroveň). ``name`` je deterministická funkce STIX
    třídy + kanonické hodnoty → roundtrip ``import(export(X)) == export(X)``
    drží i pro druh „url“ (vrací se jako „domain“, stejné ID a pattern).
    ``raw_value`` je display metadata — přes bundle se nenesie. P3-5: pravidlové
    druhy (yara_rule/sigma_tpl) jsou STOPA-lokální — bundle nese jen indikátorové
    hodnoty (:data:`_STIX_KINDS`), pravidla zůstávají v feedu s plným textem.
    """
    objects = []
    for ioc in sorted(iocs, key=ioc_id):
        if ioc.kind not in _STIX_KINDS:  # P3-5: pravidla nemají STIX třídu
            continue
        created = _iso(ioc.acquired_at) or datetime.now(timezone.utc).isoformat()
        name = f"[{_stix_class(ioc.kind)}] {ioc.value}"
        objects.append(
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": ioc_id(ioc),
                "name": name,
                "pattern": _pattern_for(ioc),
                "pattern_type": "stix",
                "created": created,
                "modified": created,
                "x_stopa_source": ioc.source,
                "x_stopa_tlp": ioc.tlp,
            }
        )
    bundle = {
        "type": "bundle",
        "id": str(uuid.uuid5(_IOC_NS, "stopa-bundle:" + ",".join(o["id"] for o in objects))),
        "objects": objects,
    }
    return json.dumps(bundle, sort_keys=True, ensure_ascii=False)


def import_bundle(text: str) -> list[IoC]:
    """Import STIX 2.1 bundle do IoC (fail-closed formátová disciplína).

    Očekává kořen ``{"type": "bundle", "objects": […]}``; zpracovává objekty
    ``indicator`` s patterny generovanými :func:`_pattern_for` (jiný tvar =
    ValueError — determinismus roundtripu), ostatní typy objektů se skáčou.
    Výstup je seřazen UUID ID IoC → ``export(import(export(X))) == export(X)``.

    Neznámé/rozporné pattern, chybějící bundle kořen nebo neplatné JSON =
    ValueError, chybějící ``objects`` seznam = TypeError (feed s cizím dialektem
    STIX selže explicitně, ne tichě).
    """
    try:
        doc = bounded_json_loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Neplatné JSON bundle: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("type") != "bundle":
        raise ValueError("Kořen bundle musí mít type='bundle'")
    objects = doc.get("objects")
    if not isinstance(objects, list):
        raise TypeError("Bundle chybí pole 'objects' (seznam)")

    iocs: list[IoC] = []
    for obj in objects:
        if not isinstance(obj, dict) or obj.get("type") != "indicator":
            continue  # marking-definition apod. — deterministicky přeskočit
        pattern = obj.get("pattern") or ""
        kind_value = _parse_pattern(pattern)
        if kind_value is None:
            raise ValueError(f"Neznámý indicator pattern: {pattern!r}")
        kind, value = kind_value
        created = obj.get("created")
        acquired_at = datetime.fromisoformat(created) if isinstance(created, str) else None
        iocs.append(
            IoC(
                kind=kind,
                value=value,
                raw_value="",  # name nese jen zobrazení; kanonický tvar je v patternu
                tlp=str(obj.get("x_stopa_tlp") or "GREEN"),
                source=str(obj.get("x_stopa_source") or ""),
                acquired_at=acquired_at,
            )
        )
    return sorted(iocs, key=ioc_id)


def _parse_pattern(pattern: str) -> tuple[str, str] | None:
    """Rozpoznání patternu generovaného :func:`_pattern_for` → (kind, value)."""
    m = _PATTERN_IP4.search(pattern)
    if m:
        return "ip", m.group(1)
    m = _PATTERN_IP6.search(pattern)
    if m:
        return "ip", m.group(1)
    m = _PATTERN_HASH.search(pattern)
    if m:
        algo, hexval = m.group(1), m.group(2).lower()
        if len(hexval) != _ALGO_TO_LEN[algo]:
            raise ValueError(f"Hash délka neodpovídá algoritmu {algo}: {hexval!r}")
        return "hash", hexval
    m = _PATTERN_DOMAIN.search(pattern)
    if m:
        # domain i url sdílí pattern — druh se neurčuje z patternu,
        # kanonická hodnota je identická; default = 'domain' (viz export).
        return "domain", m.group(1)
    return None


# ── matching IoC × case artefakty/entity ────────────────────────


@dataclass(frozen=True)
class IntelMatch:
    """Jeden deterministický hit IoC v case DB (přesný kanonický tvar).

    ``match_kind`` odpovídá CHECK constraintu tabulky ``intel_matches``:
    ``entity`` (kanonická entita), ``file_hash`` (SHA-256 souboru) nebo
    ``artifact_text`` (IP ve volném textu artefaktů). Evidence je seřazené a
    omezeno na :data:`MAX_EVIDENCE` položek.
    """

    ioc_id: str
    kind: str  # druh IoC
    value: str  # kanonický tvar IoC
    tlp: str
    source: str
    match_kind: str  # entity | file_hash | artifact_text
    evidence: tuple[dict, ...] = field(default=())
    first_seen: str | None = None
    last_seen: str | None = None


def _time_range_iso(ts_list: list[datetime]) -> tuple[str | None, str | None]:
    if not ts_list:
        return None, None
    lo, hi = min(ts_list), max(ts_list)
    return _iso(lo), _iso(hi)


def _evidence_cap(items: list[dict], keys_order: Sequence[str]) -> tuple[dict, ...]:
    """Seřazené deduplikované evidence se stropem MAX_EVIDENCE (determinismus)."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for ev in items:
        key = tuple(str(ev.get(k) or "") for k in keys_order)
        if key in seen:
            continue
        seen.add(key)
        out.append({k: (ev.get(k) if ev.get(k) is not None else "") for k in keys_order})
        if len(out) >= MAX_EVIDENCE:
            break
    return tuple(sorted(out, key=lambda d: str(d.get("artifact_id") or d.get("file_id") or "")))


def _match_entity(occurrences: Sequence[EntityOccurrence], ioc: IoC) -> list[dict]:
    """Evidence z entitních výskytů s kanonickou hodnotou = value IoC."""
    out = []
    for o in occurrences:
        if (o.kind == "hash" and ioc.kind == "hash") or (
            o.kind == "url_host" and ioc.kind in ("domain", "url")
        ):
            hit = o.value == ioc.value
        else:
            continue
        if hit:
            out.append(
                {
                    "artifact_id": o.artifact_id,
                    "file_id": o.file_id or "",
                    "rel_path": o.rel_path or "",
                    "_ts": o.ts_utc,
                }
            )
    return out


def _match_file_hash(files: Sequence[FileRecord], ioc: IoC) -> list[dict]:
    """Evidence ze SHA-256 souborů (hash IoC — lowercase hex)."""
    if ioc.kind != "hash":
        return []
    out = []
    for f in files:
        if f.sha256 and f.sha256.lower() == ioc.value:
            out.append(
                {
                    "artifact_id": "",  # hash souboru není vázan na artifact
                    "file_id": f.id,
                    "rel_path": f.rel_path or "",
                    "_ts": f.mtime,
                }
            )
    return out


def _match_ip_text(artifacts: Sequence[Artifact], ioc: IoC) -> list[dict]:
    """IP IoC ve volném textu artefaktů (title + stringové details).

    Hledá se přesný kanonický tvar jako token (lookaround brání podřetězcům —
    „10.0.0.1“ neshodí uvnitř „110.0.0.123“). IPv4/IPv6 normalizace už proběhla
    v konstruktoru IoC, zde je jen deterministický sken.
    """
    if ioc.kind != "ip":
        return []
    pat = re.compile(r"(?<![\d.:A-Fa-f])" + re.escape(ioc.value) + r"(?![\d.:])")
    out = []
    for a in artifacts:
        texts: list[str] = [a.title or ""]
        for v in (a.details or {}).values():
            if isinstance(v, str):
                texts.append(v)
        if any(pat.search(t) for t in texts):
            out.append(
                {
                    "artifact_id": a.id,
                    "file_id": a.file_id or "",
                    "rel_path": a.rel_path or "",
                    "_ts": a.timestamp,
                }
            )
    return out


def _finalize(ioc: IoC, match_kind: str, evidence_raw: list[dict]) -> IntelMatch | None:
    if not evidence_raw:
        return None
    keys = ("artifact_id", "file_id", "rel_path")
    ts_list = [e["_ts"] for e in evidence_raw if e.get("_ts") is not None]
    first_seen, last_seen = _time_range_iso(ts_list)
    capped = _evidence_cap(evidence_raw, keys_order=keys)
    return IntelMatch(
        ioc_id=ioc_id(ioc),
        kind=ioc.kind,
        value=ioc.value,
        tlp=ioc.tlp,
        source=ioc.source,
        match_kind=match_kind,
        evidence=capped,
        first_seen=first_seen,
        last_seen=last_seen,
    )


def match_iocs(
    iocs: Sequence[IoC],
    occurrences: Sequence[EntityOccurrence] = (),
    files: Sequence[FileRecord] = (),
    artifacts: Sequence[Artifact] | None = None,
) -> list[IntelMatch]:
    """Deterministický matching IoC × case artefakty/entity.

    Pravidla (přesné na kanonických tvarech — E4 kanonika):

    - ``hash`` IoC ↔ entitní výskyty druhu ``hash`` + SHA-256 záznamů souborů
      (dvě samostatné match záznamy: ``entity`` a ``file_hash``).
    - ``domain``/``url`` IoC ↔ entity druhu ``url_host`` (URL se normalizuje na
      hostname — cesta/port/schéma se ignorují).
    - ``ip`` IoC ↔ sken volného textu artefaktů (vyžaduje :data:`artifacts`;
      bez nich IP matching deterministicky nevystihne nic).

    Pravidla druhů ``yara_rule``/``sigma_tpl`` (P3-5) se zde záměrně přeskočí —
    skenují je dedikované enginy v datové vrstvě (``run_intel_match``, match_kind
    ``yara``/``sigma``).

    Výstup je seřazen ``(ioc_id, match_kind)`` → nezávislý na pořadí vstupních
    seznamů. ATT&CK techniky ↔ artefakty mapuje F6.3 (mitre_attack), ne zde.
    """
    results: list[IntelMatch] = []
    for ioc in sorted(iocs, key=ioc_id):
        if ioc.kind in RULE_KINDS:
            continue  # P3-5: pravidla skenují dedikované enginy (yara/sigma)
        candidates: list[tuple[str, list[dict]]] = [
            ("entity", _match_entity(occurrences, ioc)),
            ("file_hash", _match_file_hash(files, ioc)),
        ]
        if artifacts is not None and ioc.kind == "ip":
            candidates.append(("artifact_text", _match_ip_text(artifacts, ioc)))
        for match_kind, evidence_raw in sorted(candidates):
            m = _finalize(ioc, match_kind, evidence_raw)
            if m is not None:
                results.append(m)
    return results


def feed_summary(iocs: Sequence[IoC], now: datetime | None = None) -> dict[str, Any]:
    """Shrnutí feedu pro CLI/Web — počty per druh a stáří (deterministické).

    ``now`` je injektovatelné pro offline determinismus testů (default = UTC
    aktuální čas); stáří se klasifikuje výchozími prahy 30/90 dní.
    """
    now_dt = _ensure_utc(now or datetime.now(timezone.utc))
    by_kind: dict[str, int] = {}
    by_age: dict[str, int] = {"fresh": 0, "stale": 0, "old": 0}
    for ioc in iocs:
        by_kind[ioc.kind] = by_kind.get(ioc.kind, 0) + 1
        if ioc.acquired_at is not None:
            by_age[classify_age(ioc.acquired_at, now_dt)] += 1
    return {
        "total": len(list(iocs)),
        "by_kind": dict(sorted(by_kind.items())),
        "by_age": by_age,
        "tlp_levels": sorted({ioc.tlp for ioc in iocs}),
    }
