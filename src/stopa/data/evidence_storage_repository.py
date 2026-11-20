"""P3-4 Evidence Storage Manager — data vrstva (I/O nad doménou).

Úložiště originálních důkazů případu = unie všech registrovaných zdrojů
(``sources.path`` + ``files.rel_path``) — interpretace „kvarentény per case"
v kontextu STOPA ingestu, který čte originály in-place (bez kopií).

Zásady:
    * **read-only rehash** — originál se otevírá jen pro čtení a nikdy
      neupravuje; I/O chyba při čtení = soubor chybí (konzervativně);
    * inventář z DB stavu (``files.sha256``) nebo z importovaného manifestu
      (explicitní reference — cizí kvarenténa po přenosu);
    * export = fail-closed: před podpisem se provede rehash, při missing/
      corrupt položkách se manifest nepodepíše;
    * manifest se perzistuje do ``meta`` klíče (žádný DDL → aditivní).

Doménová logika (stavové klasifikace, kapacita, kanonický manifest) =
``domain/evidence_storage.py`` — zde jen disk/DB přístup.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from stopa.data.audit_repository import AuditRepository
from stopa.domain.evidence_storage import (
    EvidenceEntry,
    build_report,
    capacity_report,
    verify_manifest,
)
from stopa.domain.evidence_storage import (
    export_manifest as domain_export_manifest,
)

_CHUNK_SIZE = 1024 * 1024  # 1 MiB — streamovací rehash bez držení souboru v RAM

META_KEY_REFERENCE = "evidence_reference_manifest"


def _hash_file(path: Path) -> tuple[str, int]:
    """SHA-256 + velikost souboru — **read-only** (originál se neupravuje)."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


class EvidenceStorageRepository:
    """Tenká I/O vrstva P3-4 nad case DB + disk (kvarenténa = zdrojové cesty)."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    # ── pomocné dotazy ───────────────────────────────────────────────────────

    def _case_files(self, case_id: str) -> list[tuple[str, str, str, str | None, int | None]]:
        """Inventář z DB stavu: (source_id, source_path, rel_path, sha256, size)."""
        row = self.conn.execute("SELECT id FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise ValueError(f"Případ neexistuje: {case_id}")
        return [
            (r["source_id"], r["path"], r["rel_path"], r["sha256"], r["size_bytes"])
            for r in self.conn.execute(
                "SELECT f.source_id, s.path, f.rel_path, f.sha256, f.size_bytes"
                " FROM files f JOIN sources s ON s.id = f.source_id"
                " WHERE s.case_id = ? ORDER BY f.source_id, f.rel_path",
                (case_id,),
            )
        ]

    def _source_paths(self, case_id: str) -> dict[str, str]:
        """Mapa source_id → fyzikální kořen (pro reference mimo DB inventář)."""
        return {
            r["id"]: r["path"]
            for r in self.conn.execute(
                "SELECT id, path FROM sources WHERE case_id = ?", (case_id,)
            )
        }

    # ── verify / report ──────────────────────────────────────────────────────

    def verify(self, case_id: str, reference: dict[tuple[str, str], tuple[str, int]] | None = None):
        """Read-only rehash inventáře proti referenci.

        Bez ``reference`` = DB stav (files.sha256). S ``reference`` = kontrola
        importované kvarentény: iteruje se nad položkami reference (ne DB);
        neznámý source_id v reference = soubor chybí (konzervativně).
        Vrací list[EvidenceEntry] seřazené podle (source_id, rel_path).
        """
        if reference is not None:
            self._case_files(case_id)  # validace existence případu (ValueError)
            source_paths = self._source_paths(case_id)
            entries: list[EvidenceEntry] = []
            for (sid, rp), (expected_sha, expected_size) in sorted(reference.items()):
                actual_sha, actual_size = None, None
                root = source_paths.get(sid)
                if root is not None:
                    try:
                        actual_sha, actual_size = _hash_file(Path(root) / rp)
                    except OSError:
                        pass  # nečitelný soubor = chybí (konzervativně)
                entries.append(
                    EvidenceEntry(
                        source_id=sid,
                        rel_path=rp,
                        expected_sha256=expected_sha,
                        expected_size=expected_size,
                        actual_sha256=actual_sha,
                        actual_size=actual_size,
                    )
                )
            return entries

        entries = []
        for sid, spath, rp, ref_sha, ref_size in self._case_files(case_id):
            actual_sha, actual_size = None, None
            try:
                actual_sha, actual_size = _hash_file(Path(spath) / rp)
            except OSError:
                pass  # nečitelný soubor = chybí (konzervativně)
            entries.append(
                EvidenceEntry(
                    source_id=sid,
                    rel_path=rp,
                    expected_sha256=ref_sha,
                    expected_size=ref_size,
                    actual_sha256=actual_sha,
                    actual_size=actual_size,
                )
            )
        return entries

    def report_meta(self, case_id: str, budget_bytes: int | None = None) -> dict[str, Any]:
        """Kapacitní report z DB metadata (bez disk I/O)."""
        row = self.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(f.size_bytes), 0) AS bytes"
            " FROM files f JOIN sources s ON s.id = f.source_id WHERE s.case_id = ?",
            (case_id,),
        ).fetchone()
        if self.conn.execute("SELECT id FROM cases WHERE id = ?", (case_id,)).fetchone() is None:
            raise ValueError(f"Případ neexistuje: {case_id}")
        capacity = capacity_report(int(row["bytes"]), budget_bytes)
        return {
            "total_files": int(row["n"]),
            "total_bytes": int(row["bytes"]),
            "capacity": {
                "used_bytes": capacity.used_bytes,
                "budget_bytes": capacity.budget_bytes,
                "utilization": capacity.utilization,
                "over_budget": capacity.over_budget,
            },
        }

    # ── export / import manifestu ────────────────────────────────────────────

    def export_manifest(
        self, case_id: str, pre_verified: list[EvidenceEntry] | None = None
    ) -> dict[str, Any]:
        """Podepsaný manifest aktuálního stavu kvarentény (fail-closed).

        Před podpisem se provede read-only rehash; při missing/corrupt
        položkách ``ValueError`` (manifest se nepodepíše). Položky = soubory
        přítomné na disku s naměřeným hashem (seřazené deterministicky).
        Klíč = Ed25519 pár případu (``ensure_integrity_key``, idempotentní;
        bez balíku ``cryptography`` → RuntimeError z domény).
        """
        entries = self.verify(case_id) if pre_verified is None else pre_verified
        report = build_report(entries)
        if report.missing or report.corrupt:
            raise ValueError(
                f"pre-export verifikace selhala: {report.missing} chybějících, "
                f"{report.corrupt} poškozených souborů"
            )
        present = [e for e in entries if e.actual_sha256 is not None]
        manifest_entries: list[tuple[str, str, str, int]] = []
        for e in present:
            assert e.actual_sha256 is not None  # filtrováno výše — Pyright narrowing
            manifest_entries.append((e.source_id, e.rel_path, e.actual_sha256, e.actual_size or 0))

        audit = AuditRepository(self.conn)
        private_b64, public_b64 = audit.ensure_integrity_key()
        return domain_export_manifest(case_id, public_b64, private_b64, manifest_entries)

    def import_manifest(self, case_id: str, manifest: Any) -> dict[str, Any]:
        """Import cizího podepsaného manifestu (fail-closed) + perzistence do meta."""
        result = verify_manifest(manifest)
        if not result.ok:
            raise ValueError(f"ověření manifestu selhalo: {result.reason}")
        self._case_files(case_id)  # validace existence případu (ValueError)
        payload = json.dumps(manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (META_KEY_REFERENCE, payload),
        )
        self.conn.commit()
        return manifest

    def stored_manifest(self, case_id: str) -> dict[str, Any] | None:
        """Poslední importovaný reference manifest (meta), pokud existuje."""
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (META_KEY_REFERENCE,)
        ).fetchone()
        if row is None:
            return None
        try:
            data = json.loads(row["value"])
        except json.JSONDecodeError as exc:  # poškozený meta řádek → fail-closed výše
            raise ValueError(f"poškozený reference manifest v meta: {exc}") from exc
        return data if isinstance(data, dict) else None
