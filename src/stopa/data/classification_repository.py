"""ClassificationRepository — P3-3 klasifikace souborů (W2 data layer).

Tenká I/O nad čistou doménou :mod:`stopa.domain.classification`: vstupy per
soubor se sbírají z ``files`` + ``artifacts`` (typy entit se re-derivují
deterministicky stejným ``domain.entities.extract_entities`` jako při
extrakci — single source of truth), výsledek se upsertuje do tabulky
``classifications``. Lidský override je aditivní sloupec + append-only záznam
v ``audit_log`` (hash chain) — automatická hodnota vždy zůstává dohledatelná.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone

from stopa import __version__
from stopa.data.audit_repository import AuditRepository
from stopa.domain.classification import CATEGORIES, ClassificationInput, classify
from stopa.domain.entities import extract_entities
from stopa.models import Artifact


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClassificationRepository:
    """I/O vrstva klasifikace souborů (sdílená connection s CaseDB facade)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── vstupy z DB stavu ────────────────────────────────────────
    def _case_files(self, case_id: str) -> list[sqlite3.Row]:
        """Soubory případu (deterministické pořadí pro deterministický výstup)."""
        return self.conn.execute(
            "SELECT f.id, f.rel_path, f.name, f.extension, f.signature_type,"
            " f.bad_extension, f.hash_set_hit"
            " FROM files f JOIN sources s ON f.source_id = s.id"
            " WHERE s.case_id = ? ORDER BY f.rel_path, f.id",
            (case_id,),
        ).fetchall()

    def _file_signals(self, file_row: sqlite3.Row) -> ClassificationInput:
        """Vstup klasifikátoru pro jeden soubor — pouze DB stav, žádné I/O.

        Typy entit se re-derivují z uložených artefaktů stejnou doménovou
        funkcí (``extract_entities``), kterou používá pipeline při extrakci.
        """
        arts = self.conn.execute(
            "SELECT artifact_type, title, details_json FROM artifacts"
            " WHERE file_id = ? ORDER BY id",
            (file_row["id"],),
        ).fetchall()
        kinds: set[str] = set()
        for a in arts:
            art = Artifact(
                artifact_type=a["artifact_type"],
                title=a["title"],
                details=json.loads(a["details_json"] or "{}"),
            )
            for e in extract_entities(art):
                kinds.add(e.kind)
        return ClassificationInput(
            file_name=file_row["name"],
            file_extension=(file_row["extension"] or ""),
            signature_type=file_row["signature_type"],
            bad_extension=bool(file_row["bad_extension"]),
            hash_set_hit=bool(file_row["hash_set_hit"]),  # TEXT: název setu / NULL
            artifact_types=tuple(a["artifact_type"] for a in arts),
            entity_kinds=tuple(sorted(kinds)),
        )

    # ── klasifikace + override ───────────────────────────────────
    def classify_case(self, case_id: str) -> dict:
        """Klasifikuje všechny soubory případu; upsert AUTO polí.

        Re-run je deterministický (stejné vstupy → stejné category/confidence/
        reasons); lidské override sloupce se při re-runu nedotkne. Vrací souhrn.
        """
        now = _utcnow()
        by_category: Counter[str] = Counter()
        needs_review = 0
        rows = self._case_files(case_id)
        for f in rows:
            c = classify(self._file_signals(f))
            self.conn.execute(
                "INSERT INTO classifications (case_id, file_id, rel_path, category,"
                " confidence, reasons_json, needs_review, risk_flags_json,"
                " classified_at, stopa_version)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (file_id) DO UPDATE SET"
                "   category = excluded.category,"
                "   confidence = excluded.confidence,"
                "   reasons_json = excluded.reasons_json,"
                "   needs_review = excluded.needs_review,"
                "   risk_flags_json = excluded.risk_flags_json,"
                "   classified_at = excluded.classified_at,"
                "   stopa_version = excluded.stopa_version",
                (
                    case_id,
                    f["id"],
                    f["rel_path"],
                    c.category,
                    c.confidence,
                    json.dumps(list(c.reasons), ensure_ascii=False),
                    int(c.needs_review),
                    json.dumps(list(c.risk_flags), ensure_ascii=False),
                    now,
                    __version__,
                ),
            )
            by_category[c.category] += 1
            needs_review += int(c.needs_review)
        self.conn.commit()
        return {
            "total_files": len(rows),
            "by_category": dict(sorted(by_category.items())),
            "needs_review_count": needs_review,
        }

    def override(
        self,
        case_id: str,
        classification_id: int,
        category: str,
        actor: str | None = None,
        reason: str | None = None,
    ) -> dict | None:
        """Lidský override klasifikace (AK3: auditovalný + reverzibilní).

        Automatická hodnota zůstává na řádku nezměněná; override je aditivní
        sloupec + append-only audit_log záznam s hash chain. Vrací aktualizovaný
        řádek (dict); ``None`` pokud ID neexistuje v daném případě.
        ValueError — neplatná kategorie / prázdný důvod.
        """
        if category not in CATEGORIES:
            raise ValueError(
                f"neplatná kategorie {category!r} (očekáváno: {', '.join(CATEGORIES)})"
            )
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("override vyžaduje neprázdný důvod")
        row = self.conn.execute(
            "SELECT id, rel_path, category FROM classifications WHERE id = ? AND case_id = ?",
            (classification_id, case_id),
        ).fetchone()
        if row is None:
            return None
        self.conn.execute(
            "UPDATE classifications SET status = 'overridden', override_category = ?,"
            " override_actor = ?, override_reason = ?, overridden_at = ? WHERE id = ?",
            (category, actor, reason, _utcnow(), classification_id),
        )
        AuditRepository(self.conn).log_operation(
            "classification_override",
            actor=actor,
            details={
                "classification_id": classification_id,
                "rel_path": row["rel_path"],
                "auto_category": row["category"],
                "override_category": category,
                "reason": reason,
            },
        )  # log_operation sám commítuje (hash chain)
        return self.get(case_id, classification_id)

    # ── čtení ────────────────────────────────────────────────────
    def list_classifications(self, case_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM classifications WHERE case_id = ? ORDER BY rel_path, id",
            (case_id,),
        ).fetchall()
        return [self._to_dict(r) for r in rows]

    def get(self, case_id: str, classification_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM classifications WHERE id = ? AND case_id = ?",
            (classification_id, case_id),
        ).fetchone()
        return self._to_dict(row) if row is not None else None

    @staticmethod
    def _to_dict(r: sqlite3.Row) -> dict:
        d = dict(r)  # Row → dict (sqlite3.Row nemá .get — P3-5 lekce)
        d["reasons"] = json.loads(d.pop("reasons_json") or "[]")
        d["risk_flags"] = json.loads(d.pop("risk_flags_json") or "[]")
        d["needs_review"] = bool(d.get("needs_review"))
        # efektivní kategorie = override, pokud proběhl; jinak automatická
        d["effective_category"] = d.get("override_category") or d["category"]
        return d
