"""P2-4 Investigation Workspace — CLI příkazy (workspace note/task/hypo-rev).

Pracovní prostor znalce nad případem: poznámky ukotvené na artefakt/entity/
timeline event, úkoly se stavovým automatem a revize hypotéz jako append-only
hash chain. Logika žije v doménové vrstvě (``domain/investigation_workspace``)
a repozitáři (``data/investigation_repository``); tady je jen CLI hrana.

Exit kódy: 0 = OK; 1 = chyba / neznámý případ / semantická chyba;
2 = ``hypo-rev list --check-chain`` s porušeným řetězcem (jako P0-1 provenance).
"""

from __future__ import annotations

import argparse
import json

from stopa.cli._util import _open_db
from stopa.domain.investigation_workspace import REF_KINDS


def _json_mode(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json", False)) or getattr(args, "format", None) == "json"


def _parse_ref(ref: str) -> tuple[str, str]:
    """Rozparsuje ``kind:id``; semantické chyby → ValueError."""
    kind, sep, ref_id = ref.partition(":")
    if not sep or not kind.strip() or not ref_id.strip():
        raise ValueError(f"reference musí být ve tvaru druh:id (druh ∈ {', '.join(REF_KINDS)})")
    return kind, ref_id


def _repo(db):
    from stopa.data.investigation_repository import InvestigationRepository

    return InvestigationRepository(db.conn)


# ── note ─────────────────────────────────────────────────────────────────────


def cmd_workspace_note_add(args: argparse.Namespace) -> int:
    """Přidá poznámku ukotvenou na referenci (``--ref druh:id``)."""
    db = _open_db(args.case_id)
    try:
        kind, ref_id = _parse_ref(args.ref)
        note_id = _repo(db).add_note(
            args.case_id, kind, ref_id, args.text, author=args.author
        )  # ValueError/TypeError → CLI hrana níže
    except (ValueError, TypeError) as exc:
        raise SystemExit(str(exc))
    finally:
        db.close()
    if _json_mode(args):
        print(json.dumps({"id": note_id}, ensure_ascii=False))
    else:
        print(f"Poznámka {note_id} uložena ({kind}:{ref_id})")
    return 0


def cmd_workspace_note_list(args: argparse.Namespace) -> int:
    """Seznam poznámků případu."""
    db = _open_db(args.case_id)
    try:
        rows = _repo(db).list_notes(args.case_id)
    finally:
        db.close()
    if _json_mode(args):
        print(json.dumps(rows, ensure_ascii=False))
    else:
        for r in rows:
            print(f"[{r['id']}] {r['ref_kind']}:{r['ref_id']} — {r['text']} ({r['author'] or '-'})")
        if not rows:
            print("žádné poznámky")
    return 0


# ── task ─────────────────────────────────────────────────────────────────────


def cmd_workspace_task_add(args: argparse.Namespace) -> int:
    """Přidá úkol (default open)."""
    db = _open_db(args.case_id)
    try:
        repo = _repo(db)
        task_id = repo.add_task(
            args.case_id, args.title, assignee=args.assignee, due=args.due
        )  # ValueError/TypeError → CLI hrana níže
    except (ValueError, TypeError) as exc:
        raise SystemExit(str(exc))
    finally:
        db.close()
    if _json_mode(args):
        print(json.dumps({"id": task_id}, ensure_ascii=False))
    else:
        print(f"Úkol {task_id} vytvořen (open)")
    return 0


def cmd_workspace_task_set_status(args: argparse.Namespace) -> int:
    """Přepíše stav úkolu (open/in_progress/done)."""
    db = _open_db(args.case_id)
    try:
        row = _repo(db).set_task_status(args.case_id, args.task_id, args.status)
    except ValueError as exc:
        raise SystemExit(str(exc))
    finally:
        db.close()
    if _json_mode(args):
        print(json.dumps(row, ensure_ascii=False))
    else:
        print(f"Úkol {args.task_id}: {row['status']}")
    return 0


def cmd_workspace_task_list(args: argparse.Namespace) -> int:
    """Seznam úkolů případu."""
    db = _open_db(args.case_id)
    try:
        rows = _repo(db).list_tasks(args.case_id)
    finally:
        db.close()
    if _json_mode(args):
        print(json.dumps(rows, ensure_ascii=False))
    else:
        for r in rows:
            extra = f" assignee={r['assignee']}" if r["assignee"] else ""
            due = f" due={r['due']}" if r["due"] else ""
            print(f"[{r['id']}] ({r['status']}) {r['title']}{extra}{due}")
        if not rows:
            print("žádné úkoly")
    return 0


# ── hypo-rev (append-only hash chain) ───────────────────────────────────────


def cmd_workspace_hypo_rev_add(args: argparse.Namespace) -> int:
    """Přidá příští revizi hypotézy (claim + autor → deterministický hash)."""
    db = _open_db(args.case_id)
    try:
        row = _repo(db).add_hypo_revision(
            args.case_id, args.hypothesis, args.claim, author=args.author
        )  # ValueError/TypeError → CLI hrana níže
    except (ValueError, TypeError) as exc:
        raise SystemExit(str(exc))
    finally:
        db.close()
    if _json_mode(args):
        print(json.dumps(row, ensure_ascii=False))
    else:
        print(f"Revize hypotézy {args.hypothesis} seq={row['seq']} hash={row['hash'][:12]}…")
    return 0


def cmd_workspace_hypo_rev_list(args: argparse.Namespace) -> int:
    """Seznam revizí hypotéz; ``--check-chain`` ověří hash chain (exit 2 = porušení)."""
    from stopa.domain.investigation_workspace import verify_revisions

    db = _open_db(args.case_id)
    try:
        rows = _repo(db).list_hypo_revisions(args.case_id, args.hypothesis)
    finally:
        db.close()
    if args.check_chain:
        broken_at = verify_revisions(rows)
        if broken_at is not None:
            print(f"Řetězec revizí PORUŠEN na pozici {broken_at} (seq={rows[broken_at]['seq']})")
            return 2
        print(f"Řetězec revizí OK ({len(rows)} revizí)")
    if _json_mode(args):
        print(json.dumps(rows, ensure_ascii=False))
    else:
        for r in rows:
            author = f" ({r['author']})" if r["author"] else ""
            claim = json.loads(r["content_json"]).get("claim", "")
            print(f"[{r['hypothesis_id']} seq={r['seq']}] {claim}{author} hash={r['hash'][:12]}…")
        if not rows:
            print("žádné revize hypotéz")
    return 0
