"""STP-073 — diferenciální reference (pilot vlna 1, design §2/§6).

Vlastní vrstva mezi ``artifacts`` (extrakce) a ``domain/differential``
(normalizace + komparace): pro každý podporovaný parser drží **adaptér** se
dvěma nezávislými cestami nad stejným vstupem — STOPA extraktor vs. referenční
čtení z manifestu. I/O zde patří (čte soubory); čistá logika zůstává v doméně.

Pilotní pokrytí (vlny 29–31): ``sqlite`` (Chrome/Edge History, STP-073),
``netstat`` (Windows netstat -ano / Unix ss text, STP-074) a ``file_meta``
(PDF /Info + OOXML docProps, STP-075). Další formáty = další vlny (§7) —
registr je extenzivní, bez rewrites.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DiffrefAdapter:
    """Nezávislé cesty jedné parser rodiny nad stejným vstupním souborem."""

    parser_id: str
    #: STOPA strana: surové entry ``{type, ts?, fields}`` (pre-normalizace §3).
    run_stopa: Callable[[Path], list[dict]]
    #: Referenční strana: dotazy z manifestu → stejné surové entry.
    read_reference: Callable[[Path, Mapping[str, object]], list[dict]]
    #: STP-074 — načtení + validace manifestu per adapter (None = adaptér bez
    #: auto-režimu; CLI fail-fast). Sémantika klíčů se liší formátem.
    load_manifest: Callable[[Path], Mapping[str, object]] | None = None


@dataclass(frozen=True)
class DiffrefResult:
    """Výsledek spuštění obou stran + metadata pro report (design §4/§10)."""

    stopa_entries: tuple[dict, ...]
    ref_entries: tuple[dict, ...]
    join_keys: Mapping[str, tuple[str, ...]]
    reference_tool: str
    input_sha256: str


def _sqlite_stopa(path: Path) -> list[dict]:
    from stopa.diffref.sqlite_ref import run_stopa_sqlite  # líně — I/O vrstva

    return run_stopa_sqlite(path)


def _sqlite_reference(path: Path, manifest: Mapping[str, object]) -> list[dict]:
    from stopa.diffref.sqlite_ref import read_reference_entries

    return read_reference_entries(path, manifest)


def _sqlite_load_manifest(path: Path) -> Mapping[str, object]:
    from stopa.diffref.sqlite_ref import load_manifest  # líně — I/O vrstva

    return load_manifest(path)


def _netstat_stopa(path: Path) -> list[dict]:
    from stopa.diffref.text_ref import run_stopa_netstat  # líně — I/O vrstva

    return run_stopa_netstat(path)


def _netstat_reference(path: Path, manifest: Mapping[str, object]) -> list[dict]:
    from stopa.diffref.text_ref import read_reference_entries

    return read_reference_entries(path, manifest)


def _netstat_load_manifest(path: Path) -> Mapping[str, object]:
    from stopa.diffref.text_ref import load_text_manifest  # líně — I/O vrstva

    return load_text_manifest(path)


def _meta_stopa(path: Path) -> list[dict]:
    from stopa.diffref.meta_ref import run_stopa_filemeta  # líně — I/O vrstva

    return run_stopa_filemeta(path)


def _meta_reference(path: Path, manifest: Mapping[str, object]) -> list[dict]:
    from stopa.diffref.meta_ref import read_reference_entries

    return read_reference_entries(path, manifest)


def _meta_load_manifest(path: Path) -> Mapping[str, object]:
    from stopa.diffref.meta_ref import load_meta_manifest  # líně — I/O vrstva

    return load_meta_manifest(path)


#: Registr adaptérů — extenzivní (nový formát = nový řádek + modul).
DIFFREF_ADAPTERS: dict[str, DiffrefAdapter] = {
    "sqlite": DiffrefAdapter(
        parser_id="sqlite",
        run_stopa=_sqlite_stopa,
        read_reference=_sqlite_reference,
        load_manifest=_sqlite_load_manifest,
    ),
    # STP-074 — pilot vlna 1 část B: textový formát (netstat -ano / ss).
    "net_connections": DiffrefAdapter(
        parser_id="net_connections",
        run_stopa=_netstat_stopa,
        read_reference=_netstat_reference,
        load_manifest=_netstat_load_manifest,
    ),
    # STP-075 — pilot vlna 2: dokumentová metadata (PDF /Info + OOXML docProps).
    "file_meta": DiffrefAdapter(
        parser_id="file_meta",
        run_stopa=_meta_stopa,
        read_reference=_meta_reference,
        load_manifest=_meta_load_manifest,
    ),
}


def resolve_adapter(parser_id: str) -> DiffrefAdapter:
    """Adaptér pro ``parser_id``; explicitní chyba místo tichého fallbacku.

    Raises:
        ValueError: parser nemá diffref adaptér (pilot scope = jen registrované).
    """
    try:
        return DIFFREF_ADAPTERS[parser_id]
    except KeyError:
        registered = ", ".join(sorted(DIFFREF_ADAPTERS)) or "(prázdný)"
        raise ValueError(
            f"parser {parser_id!r} nemá diffref adaptér (registrováno: {registered})"
        ) from None


def run_both_sides(parser_id: str, raw_path: Path) -> tuple[list[dict], DiffrefAdapter]:
    """Spuští STOPA stranu + vrací adaptér (referenční strana = manifest).

    Reference vyžaduje manifest s dotazy — volající (CLI) ho načte a předá
    ``adapter.read_reference``; rozdělení drží I/O na jednom místě.

    Returns:
        (stopa_entries, adapter)

    Raises:
        ValueError: neznámý parser / vstupní chyba extraktoru.
    """
    adapter = resolve_adapter(parser_id)
    return adapter.run_stopa(raw_path), adapter
