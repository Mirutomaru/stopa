"""P2-4 Investigation Workspace — čistá doménová vrstva (bez I/O).

Tři prvky forenzního pracovního prostoru znalce:

- **Poznámka** ukotvená na artefakt / entity / timeline event
  (``validate_note``) — typový nesoulad = ``TypeError``, semantická chyba =
  ``ValueError``.
- **Úkol** s jednoduchým stavovým automatem open → in_progress → done
  (``validate_task``, validace ISO data splatnosti).
- **Revize hypotézy** — append-only řetězec s hash chain: každá revize nese
  ``prev_hash`` + deterministický SHA-256 nad předchozím hashem a kanonickým
  JSON payloadem. Tamper detekce bez LLM (``next_revision``,
  ``verify_revisions``).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

REF_KINDS = ("artifact", "entity", "timeline_event")
TASK_STATUSES = ("open", "in_progress", "done")

# První revize řetězce odkazuje na GENESIS (konvence shodná s audit_log chain).
GENESIS_HASH = "GENESIS"


def validate_note(ref_kind: str, ref_id: str, text: str) -> tuple[str, str, str]:
    """Validuje poznámku; vrací normalizované ``(kind, id, text)``.

    Typový nesoulad → ``TypeError``, semantické chyby (neznámý druh ukotvení,
    prázdné ID/text) → ``ValueError``.
    """
    if not isinstance(ref_kind, str):
        raise TypeError("ref_kind musí být str")
    if ref_kind not in REF_KINDS:
        raise ValueError(f"neplatný druh ukotvení poznámky: {ref_kind!r}")
    if not isinstance(ref_id, str) or not ref_id.strip():
        raise ValueError("prázdné ID referencované entity")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("poznámka bez textu")
    return ref_kind, ref_id.strip(), text


def validate_task(
    title: str,
    status: str = "open",
    assignee: str | None = None,
    due: str | None = None,
) -> tuple[str, str, str | None, datetime | None]:
    """Validuje úkol; vrací ``(title, status, assignee, parsed_due)``.

    Typový nesoulad → ``TypeError``, semantické chyby (prázdný název, neplatný
    stav, ne-ISO datum) → ``ValueError``.
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("úkol bez názvu")
    if status not in TASK_STATUSES:
        raise ValueError(f"neplatný stav úkolu: {status!r}")
    if assignee is not None and not isinstance(assignee, str):
        raise TypeError("assignee musí být str nebo None")
    parsed_due: datetime | None = None
    if due is not None:
        if not isinstance(due, str):
            raise TypeError("due musí být ISO string nebo None")
        try:
            parsed_due = datetime.fromisoformat(due)
        except ValueError as exc:
            raise ValueError(f"neplatné datum splatnosti (ISO): {due!r}") from exc
    return title.strip(), status, assignee, parsed_due


def canonical_json(obj: object) -> str:
    """Deterministický JSON tvar pro hashování (seřazené klíče, bez mezer)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def revision_payload(claim: str, author: str | None) -> str:
    """Kanonický payload revize (claim + autor)."""
    return canonical_json({"claim": claim.strip(), "author": author})


def compute_revision_hash(prev_hash: str, payload: str) -> str:
    """Deterministický SHA-256 nad předchozím hashem a payloadem."""
    return hashlib.sha256(f"{prev_hash}|{payload}".encode()).hexdigest()


def next_revision(
    hypothesis_id: str,
    claim: str,
    author: str | None = None,
    existing: list[dict] | None = None,
) -> dict:
    """Vypočítá příští řádek revize hypotézy (append-only).

    ``existing`` = aktuální revize této hypotézy (list dictů se ``seq``/``hash``),
    typicky z repozitáře. Vrací dict připravený k insertu (bez ``case_id`` a
    ``created_at`` — ty doplní data vrstva). Semantické chyby → ``ValueError``.
    """
    if not isinstance(hypothesis_id, str) or not hypothesis_id.strip():
        raise ValueError("prázdné ID hypotézy")
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("revize hypotézy bez obsahu")
    existing = list(existing or [])
    last = max((r for r in existing), key=lambda r: int(r["seq"]), default=None)
    seq = (int(last["seq"]) + 1) if last is not None else 1
    prev_hash = GENESIS_HASH if last is None else str(last["hash"])
    payload = revision_payload(claim, author)
    return {
        "hypothesis_id": hypothesis_id.strip(),
        "seq": seq,
        "content_json": json.dumps({"claim": claim.strip(), "author": author}, ensure_ascii=False),
        "prev_hash": prev_hash,
        "hash": compute_revision_hash(prev_hash, payload),
    }


def verify_revisions(rows: list[dict]) -> int | None:
    """Ověří append-only řetězce revizí; vrací index prvního porušeného článku.

    Zkontrolováno: (1) ``seq`` spojitě od 1, (2) ``prev_hash`` = hash
    předchozího řádku (první = GENESIS), (3) ``hash`` odpovídá SHA-256 nad
    prev + kanonickým payloadem uloženým v ``content_json``. Správný řetězec
    → ``None``.
    """
    ordered = sorted(rows, key=lambda r: int(r["seq"]))
    for i, row in enumerate(ordered):
        if int(row.get("seq", -1)) != i + 1:
            return i
    for i, row in enumerate(ordered):
        expected_prev = GENESIS_HASH if i == 0 else str(ordered[i - 1]["hash"])
        if str(row.get("prev_hash")) != expected_prev:
            return i
        try:
            content = json.loads(row["content_json"])
        except (TypeError, ValueError):
            return i
        payload = revision_payload(str(content.get("claim", "")), content.get("author"))
        if compute_revision_hash(expected_prev, payload) != str(row.get("hash")):
            return i
    return None
