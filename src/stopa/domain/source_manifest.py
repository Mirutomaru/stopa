"""P0.4/P1 — Source manifest: deterministický snapshot důkazního zdroje.

Tabulka ``sources`` drží jen ``path + size_bytes``; integrita složky byla
implicitní součtem file hashů a změna na úrovni souborového souboru (symlink,
soubor přidán/odebrán po ingestu) žádným digesetem nechytila. Manifest řeší:

- kanonická serializace seřazeného seznamu položek (rel_path, size, mtime,
  SHA-256, typ objektu, symlink info) → deterministický SHA-256 manifestu;
- verze schématu manifestu (``MANIFEST_VERSION``) pro budoucí rozšíření;
- ověření manifestu při resume / re-ingestu / exportu / integrity kontrole.

Doménová vrstva = čistá logika bez I/O; DB čtení/zápis patří do ``data/``
(``CaseRepository.update_source_manifest``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

#: Verze schématu manifestu — změna serializace = increment (staré manifesty
#: zůstanou ověřitelné do upgradu; audit drží historii starých SHA-256).
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class ManifestEntry:
    """Jedna položka manifestu (soubor v zdroji; symlinky procházka přeskočí)."""

    rel_path: str  # forward slashes, relativní ke kořeni zdroje
    size_bytes: int | None = None
    mtime_utc: str | None = None  # ISO 8601 UTC (legacy řádky mohou mít NULL)
    sha256: str | None = None  # None = dosud nevyhasováno (safe side při ověření)
    entry_type: str = "file"  # "file" / budoucí "dir", "device" …
    symlink_target: str | None = None


def entries_from_rows(rows: list[dict]) -> list[ManifestEntry]:
    """Postaví manifest položky z řádků tabulky ``files`` (seřazeno deterministicky).

    rows — dicts s klíči rel_path/size_bytes/mtime/sha256 (v pořadí z DB).
    Seřazení podle ``rel_path`` je součástí kanonické formy → shoda nezávislá
    na pořadí vrácení řádků SQLite.
    """
    out = [
        ManifestEntry(
            rel_path=r["rel_path"],
            size_bytes=r.get("size_bytes"),
            mtime_utc=r.get("mtime"),
            sha256=r.get("sha256"),
        )
        for r in rows
    ]
    return sorted(out, key=lambda e: e.rel_path)


def canonical_json(entries: list[ManifestEntry], version: int = MANIFEST_VERSION) -> bytes:
    """Kanonická serializace (sort_keys, compact separators, UTF-8).

    Stejné položky → stejný bajtový řetězec nezávisle na pořadí zázpisů a
    Python verzi (JSON s pevným formátováním).
    """
    payload = {
        "version": version,
        "entries": [asdict(e) for e in sorted(entries, key=lambda e: e.rel_path)],
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def manifest_sha256(entries: list[ManifestEntry]) -> str:
    """SHA-256 kanonické serializace (hex)."""
    return hashlib.sha256(canonical_json(entries)).hexdigest()


@dataclass(frozen=True)
class ManifestVerifyResult:
    """Výsledek ověření uloženého manifestu proti aktuálnímu stavu souborů."""

    matched: bool  # True = aktuální řádky reprodukuji uložený manifest přesně
    expected_sha256: str | None  # uložený digest (None = manifest dosud nevytvořen)
    actual_sha256: str  # digest přepočítaný z aktuálních řádek
    file_count: int  # počet položek v aktuálním stavu
    missing_files: tuple[str, ...] = ()  # v manifestu, ale ne v aktuálním stavu
    added_files: tuple[str, ...] = ()  # v aktuálním stavu, ale ne v manifestu


def verify_manifest(
    stored_json: str | None, rows_current: list[dict], expected_sha256: str | None
) -> ManifestVerifyResult:
    """Ověří uložený manifest (JSON + SHA-256) proti aktuálním řádkům ``files``.

    - Chybějící manifest → matched=False s explicitní expected=None (volající
      rozhodne podle politiky; nic netvrdí za ověřené).
    - Porovnání = přesná shoda množiny rel_path + digest; missing/added listy
      umožní auditní záznam pojmenovat konkrétní soubory.
    """
    actual_entries = entries_from_rows(rows_current)
    actual_sha = manifest_sha256(actual_entries)
    if stored_json is None or expected_sha256 is None:
        return ManifestVerifyResult(
            matched=False,
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha,
            file_count=len(actual_entries),
        )
    try:
        payload = json.loads(stored_json)
        stored_paths = {e["rel_path"] for e in payload.get("entries", [])}
    except (json.JSONDecodeError, KeyError, TypeError):
        # poškozený manifest JSON → neověřitelný (matched=False; volající
        # audituje, digest se stejně liší od očekávaného při porovnání)
        return ManifestVerifyResult(
            matched=False,
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha,
            file_count=len(actual_entries),
        )
    current_paths = {e.rel_path for e in actual_entries}
    matched = (
        actual_sha == expected_sha256 and stored_paths == current_paths
    )
    return ManifestVerifyResult(
        matched=matched,
        expected_sha256=expected_sha256,
        actual_sha256=actual_sha,
        file_count=len(actual_entries),
        missing_files=tuple(sorted(stored_paths - current_paths)),
        added_files=tuple(sorted(current_paths - stored_paths)),
    )
