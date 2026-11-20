"""STOPA — Artifact Version Comparison (P3-2).

Kanonní **path-based JSON diff** dvou verzí téhož logického artefaktu napříč
běhy/reparse: co se změnilo, kde (cesta) a proč (parser_version obou verzí).

Čistá logika bez I/O — vstupy jsou ``ArtifactRecord`` (normalizovaná verze
řádku z tabulky ``artifacts``), výstup je deterministické porovnání. Datová
vrstva (``data/artifact_compare_repository.py``) načte řádky z case DB;
prezentace (CLI/Web) mapuje výsledek na exit kód / HTTP status.

Základ: F5.3 parser versioning (``parser_version`` per artefakt), P0-1
provenance lineage (``parent_artifact_id`` — kontext, ne podmínka srovnání).

Semantika chyb podle konvence projektu: typová chyba = ``TypeError``,
semantická (jiný ``artifact_key``) = ``ValueError``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ArtifactRecord:
    """Normalizovaná verze artefaktu pro srovnání (z řádku ``artifacts``).

    Pole odpovídají sloupcům tabulky; ``details`` = rozparsované
    ``details_json`` (JSON objekt). Časy jsou ISO řetězce, jak jsou uloženy.
    """

    id: str
    artifact_type: str
    details: Mapping[str, Any] = field(default_factory=dict)
    source_id: str | None = None
    file_id: str | None = None
    rel_path: str | None = None
    timestamp: str | None = None  # čas události (ISO) — obsah artefaktu
    title: str | None = None
    confidence: float | None = None
    parser_version: str | None = None  # F5.3 — verze extraktoru, který vygeneroval
    extracted_at: str | None = None  # kdy byl extrahován (UTC) — "run/mtime"
    anomaly_flags: tuple[str, ...] = ()
    parent_artifact_id: str | None = None  # P0-1 lineage (kontext pro výstup)

    def artifact_key(self) -> tuple[str, str]:
        """Kanonní identita logického artefaktu napříč verzemi.

        ``(artifact_type, rel_path)`` — stejný typ + stejná cesta ve zdroji.
        ``source_id`` je částí klíče NE (verze mohou pocházet z různých
        zachytení téhož důkazu; pak je rozdíl vidět v metadata diff).
        """
        return (self.artifact_type, self.rel_path or "")


@dataclass(frozen=True)
class JsonDiffEntry:
    """Jedna změna na JSON cestě (deterministické pořadí — viz ``diff_json``).

    ``old``/``new`` jsou None respektive u druhého konce podle ``kind``:
    added → old=None, removed → new=None. Hodnoty po JSON normalizaci
    (srovnatelné a serializovatelné).
    """

    path: str  # např. "exif.Make" / "items[0].url"; "" = celý dokument
    kind: str  # added | removed | changed
    old: Any = None
    new: Any = None


#: Srovnávaná metadata ve fixním pořadí (deterministický výstup).
#: "run id" designu ≈ ``extracted_at`` + ``parser_version`` (artifact nese
#: přímé op ID jen přes provenance_json — ten zůstává pod /provenance endpointem);
#: "mtime" ≈ ``extracted_at`` (čas extrakce, nikoli event time).
METADATA_FIELDS: tuple[str, ...] = (
    "parser_version",  # F5.3 — vysvětlení „proč“ změny (verze extraktoru)
    "source_id",  # jiné zachytí = běžná příčina rozdílů
    "file_id",
    "timestamp",  # čas události
    "confidence",
    "extracted_at",  # kdy byl artefakt vyextrahován (run/mtime)
    "anomaly_flags",
    "title",
)

#: Metadata pole určující **identitu verze** — jejich změna obrací ``identical``.
#: Ostatní METADATA_FIELDS jsou kontext zachycení (zdroj, čas extrakce, …) a
#: sice se hlásí v metadata_diffs, ale shodu detailů + parser_version nevyvracejí:
#: stejný obsah extrahovaný z jiného zachytí je stále ta sama verze artefaktu.
VERSION_DETERMINING_FIELDS: tuple[str, ...] = ("parser_version",)


@dataclass(frozen=True)
class ArtifactComparison:
    """Výsledek srovnání dvou verzí téhož logického artefaktu.

    ``identical`` = prázdný JSON diff I žádné změněné pole z
    ``VERSION_DETERMINING_FIELDS`` (parser_version) — exit 0 CLI. Kontextové
    metadata (source_id, extracted_at, …) se hlásí v ``metadata_diffs``, ale
    shodu nevyvracejí. ``parser_versions`` = (verze A, verze B) — AK3: každá
    změna je vysvětlitelná verzemi extraktorů, které ji vyprodukovaly.
    """

    key: tuple[str, str]  # sdílené artifact_key (ověřeno shodné)
    identical: bool
    json_diffs: tuple[JsonDiffEntry, ...] = ()
    metadata_diffs: tuple[tuple[str, Any, Any], ...] = ()  # (pole, stará, nová)
    parser_versions: tuple[str | None, str | None] = (None, None)


def _norm(value: Any) -> Any:
    """JSON normalizace hodnoty (round-trip) → srovnatelné plain struktury.

    Zajišťuje determinismus nezávisle na typu kontejneru (dict/odkaz na
    mapping) a řazení klíčů; ``None`` prochází beze změny.
    """
    if value is None:
        return None
    return json.loads(json.dumps(value, sort_keys=True))


def _diff(old_v: Any, new_v: Any, path: str, out: list[JsonDiffEntry]) -> None:
    """Rekurzivní diff po cestách (dict→klíče, list→indexy, skaláry → ==)."""
    old_m = isinstance(old_v, Mapping) and not isinstance(old_v, (str, bytes))
    new_m = isinstance(new_v, Mapping) and not isinstance(new_v, (str, bytes))
    if old_m or new_m:  # strukturální rozdíl typů (dict vs. něco jiného)
        if old_m and new_m:
            for k in sorted(set(old_v) | set(new_v), key=str):
                p = f"{path}.{k}" if path else str(k)
                if k not in old_v:
                    out.append(JsonDiffEntry(p, "added", None, _norm(new_v[k])))
                elif k not in new_v:
                    out.append(JsonDiffEntry(p, "removed", _norm(old_v[k]), None))
                else:
                    _diff(_norm(old_v[k]), _norm(new_v[k]), p, out)
        else:
            out.append(JsonDiffEntry(path or "", "changed", _norm(old_v), _norm(new_v)))
        return

    if isinstance(old_v, list) or isinstance(new_v, list):
        old_l = list(old_v) if isinstance(old_v, list) else []
        new_l = list(new_v) if isinstance(new_v, list) else []
        for i in range(max(len(old_l), len(new_l))):
            p = f"{path}[{i}]" if path else f"[{i}]"
            if i >= len(old_l):
                out.append(JsonDiffEntry(p, "added", None, _norm(new_l[i])))
            elif i >= len(new_l):
                out.append(JsonDiffEntry(p, "removed", _norm(old_l[i]), None))
            else:
                _diff(_norm(old_l[i]), _norm(new_l[i]), p, out)
        return

    if old_v != new_v:
        out.append(JsonDiffEntry(path or "", "changed", _norm(old_v), _norm(new_v)))


def diff_json(old: Mapping[str, Any], new: Mapping[str, Any]) -> tuple[JsonDiffEntry, ...]:
    """Path-based rekurentní diff dvou JSON objektů (P3-2 AK2).

    - **dict**: unie klíčů v řazeném pořadí — klíč na jedné straně → jediný
      added/removed záznam na nejvyšším bodě odlišnosti (s celou hodnotou),
      lišící se hodnota = changed (cesta k nejhlubšímu listu);
    - **list**: prvek po prvku podle indexu (``pole[0]``) — delší strana má
      navíc added/removed položky;
    - **skalár / strukturální rozdíl typů** (dict vs. list atd.): changed s
      oběma normalizovanými hodnotami.

    Výstup je deterministicky seřazen cestou (+ druhem) — stejné vstupy vedou
    k byte-přesně stejnému výsledku nezávisle na pořadí klíčů ve vstupech.
    """
    if not isinstance(old, Mapping):
        raise TypeError(f"stará verze musí být JSON objekt (mapping), je {type(old).__name__}")
    if not isinstance(new, Mapping):
        raise TypeError(f"nová verze musí být JSON objekt (mapping), je {type(new).__name__}")
    out: list[JsonDiffEntry] = []
    _diff(_norm(dict(old)), _norm(dict(new)), "", out)
    return tuple(sorted(out, key=lambda e: (e.path, e.kind)))


def compare_artifacts(a: ArtifactRecord, b: ArtifactRecord) -> ArtifactComparison:
    """Srovná dvě verze téhož logického artefaktu (P3-2 návrh).

    Validace podle konvence projektu: typová chyba = ``TypeError``; semantická —
    liší se ``artifact_key`` („jiný artefakt“) = ``ValueError``.

    Provenance (AK3): výsledek vždy nese ``parser_versions`` obou verzí, takže
    každá změna je forenzně vysvětlitelná verzí extraktoru (F5.3).
    """
    if not isinstance(a, ArtifactRecord):
        raise TypeError(f"verze A musí být ArtifactRecord, je {type(a).__name__}")
    if not isinstance(b, ArtifactRecord):
        raise TypeError(f"verze B musí být ArtifactRecord, je {type(b).__name__}")
    for label, rec in (("A", a), ("B", b)):
        d = rec.details
        if not isinstance(d, Mapping) or isinstance(d, (str, bytes)):
            raise TypeError(
                f"verze {label}.details musí být JSON objekt (mapping), je {type(d).__name__}"
            )
    key_a = a.artifact_key()
    key_b = b.artifact_key()
    if key_a != key_b:
        raise ValueError(
            f"jiný artefakt: klíč {key_a[0]}::{key_a[1] or '(bez cesty)'} "
            f"≠ {key_b[0]}::{key_b[1] or '(bez cesty)'}"
        )
    json_diffs = diff_json(a.details, b.details)
    metadata_diffs: list[tuple[str, Any, Any]] = []
    for name in METADATA_FIELDS:
        va = getattr(a, name)
        vb = getattr(b, name)
        if va != vb:
            metadata_diffs.append((name, va, vb))
    changed_fields = {f for (f, _o, _n) in metadata_diffs}
    identical = not json_diffs and not (changed_fields & set(VERSION_DETERMINING_FIELDS))
    return ArtifactComparison(
        key=key_a,
        identical=identical,
        json_diffs=json_diffs,
        metadata_diffs=tuple(metadata_diffs),
        parser_versions=(a.parser_version, b.parser_version),
    )


def comparison_to_dict(cmp: ArtifactComparison) -> dict[str, Any]:
    """JSON-safe reprezentace pro CLI ``--json`` a Web odpověď (P3-2)."""
    return {
        "identical": cmp.identical,
        "key": list(cmp.key),  # [artifact_type, rel_path]
        "parser_versions": {"a": cmp.parser_versions[0], "b": cmp.parser_versions[1]},
        "json_diffs": [
            {"path": e.path, "kind": e.kind, "old": e.old, "new": e.new}
            for e in cmp.json_diffs
        ],
        "metadata_diffs": [[f, o, n] for (f, o, n) in cmp.metadata_diffs],
    }
