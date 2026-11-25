"""B2 — facade doména: auditní log, integrita (klíče/checkpoints) a case sealing.

Metody přesunuty z monolitu ``db.py`` (ETAPA C pokračování) — CaseDB zůstává
tenkým agregátorem, BC API beze změny (``from stopa.data.db import CaseDB``)."""

from __future__ import annotations


class AuditIntegrityFacadeMixin:
    """Facade mixín — delegace na doménová repozitáře (sdílená Connection z CaseDB)."""

    def log_operation(
        self,
        action: str,
        actor: str | None = None,
        details: dict | None = None,
        *,
        strict: bool = False,  # STP-022 — RBAC minimální (actor povinný)
    ) -> int:
        """Neměnný záznam operace (append-only) + hash chaining (P0 Core C4). Vrací ID řádku."""
        row_id = self.audit_repo.log_operation(action, actor, details, strict=strict)
        if action.startswith("ai_"):  # F4.2 — live push akcí AI agenta (WS; jen prefix ai_)
            self._emit_web_event("ai.action", {"action": action, "actor": actor})
        return row_id

    def verify_audit_chain(self, *, collect_all: bool = False):
        """Ověří celý hash řetězec audit logu. Vrací :class:`ChainReport`.

        B9 — ``collect_all=True`` shrne všechny defekty (přesná lokalizace);
        výchozí zachovává BC chování na prvním defektu.
        """
        return self.audit_repo.verify_audit_chain(collect_all=collect_all)

    # ── Ed25519 kontrolní body (P0 Core C4) ───────────────────

    def ensure_integrity_key(self) -> tuple[str, str]:
        """Vygeneruje Ed25519 klíčový pár případu (idempotentní)."""
        return self.audit_repo.ensure_integrity_key()

    def integrity_public_key(self) -> str | None:
        """Veřejný Ed25519 klíč případu (base64), pokud byl vygenerován."""
        return self.audit_repo.integrity_public_key()

    def add_integrity_checkpoint(self, reason: str) -> int | None:
        """Podpisne hash posledního audit řádku a uloží kontrolní bod."""
        return self.audit_repo.add_integrity_checkpoint(reason)

    def list_integrity_checkpoints(self) -> list[dict]:
        """Kontrolní body (chronologicky) — pro report / nezávislou kontrolu."""
        return self.audit_repo.list_integrity_checkpoints()

    def verify_integrity_checkpoints(self) -> list[dict]:
        """Ověří kontrolní body veřejným klíčem (nezávislá kontrola)."""
        return self.audit_repo.verify_integrity_checkpoints()

    def seal_case(self, reason: str | None = None, actor: str | None = None) -> dict | None:
        """F5.1 — zamkne stav případu (Merkle root + Ed25519); None bez cryptography."""
        return self.seal_repo.seal_case(case_id=self.path.stem, actor=actor, reason=reason)

    # ── cases ────────────────────────────────────────────────

    def list_audit_log(
        self, limit: int | None = 100, offset: int | None = None, actor: str | None = None
    ) -> list[dict]:
        """Audit trail — nejnovější operace první. F4.4: volitelný filtr per user."""
        return self.audit_repo.list_audit_log(limit=limit, offset=offset, actor=actor)
