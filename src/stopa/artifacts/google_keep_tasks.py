"""ETAPA B vlna 13 — Google Keep Notes + Tasks parser (cloud export / warrant return).

AXIOM ekvivalenty: ``CloudGoogleKeepArtifact`` + ``CloudGoogleTasksArtifact``
(``Magnet.Artifacts.Cloud.Google.WarrantReturn.Keep.*``) — poznámky a úkoly
z Google účtu.

Podporované formáty (defenzivní parsing, auto-detekce typu)::

    1. Keep notes (Takeout „Keep" export)::

        {"notes": [
            {"title": "Nákup", "text": "mléko, chléb",
             "creationTime": "2024-10-03T09:00:00Z",
             "modificationTime": "2024-10-03T10:00:00Z",
             "labels": ["doma"]}, ...]}

    2. Tasks (Takeout „Tasks" export)::

        {"tasks": [
            {"title": "Odeslat fakturu", "dueDate": "2024-10-05T17:00:00Z",
             "completed": false, "listId": "work"}, ...]}

Jeden záznam = jeden artifact (``document_metadata``,
``details.engine='google_keep_tasks'``, ``kind='keep_note'|'task'``).
Neznámá pole se ignoruje.

Detekce: **name-based** — Google marker + klíčová slova keep/tasks;
v dispatchi pre-pass na celé cestě PŘED basename chainem (generic basenames
kolidují s ostatními detektory).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stopa.domain.json_bounded import bounded_json_loads
from stopa.domain.times import from_unix
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_ITEMS_PER_FILE = 5_000


@dataclass
class GoogleKeepTaskRecord:
    """Jedna Keep poznámka nebo Task úkol."""

    kind: str = "keep_note"  # keep_note | task
    title: str | None = None
    text: str | None = None
    created_s: float | None = None
    modified_s: float | None = None
    due_s: float | None = None
    completed: bool | None = None
    labels: list[str] = field(default_factory=list)


def _to_str(value: Any) -> str | None:
    """Tolerantní konverze na non-empty string."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_list(value: Any) -> list[Any]:
    """Normalizuje pole / scalar / None na list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _to_epoch(value: Any) -> float | None:
    """Tolerantní konverze času na epoch sekundy.

    Podporuje: int/float (sekundy i milisekundy), ISO 8601 stringy
    (s ``Z`` i offsetem). Neznámé tvary → None.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (ValueError, TypeError):
        text = _to_str(value)
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return float(dt.timestamp())
    # milisekundy — heuristika: epoch > 1e12 už jsou ms (rok ~33658)
    if abs(num) >= 10**12:
        num /= 1000.0
    return num if num > 0 else None


def parse_google_keep_tasks(data: bytes) -> list[GoogleKeepTaskRecord]:
    """ČISTÝ parser — Google Keep/Tasks JSON → záznamy.

    Raises:
        ValueError: Neplatné JSON.
        TypeError: Platné JSON, ale bez poznámek/úkolů.
    """
    try:
        payload = bounded_json_loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Neplatné JSON: {e}") from e

    records: list[GoogleKeepTaskRecord] = []

    def add_note(item: dict[str, Any]) -> None:
        title = _to_str(item.get("title"))
        text = _to_str(
            item.get("text", item.get("content", item.get("note")))
        )
        created_s = _to_epoch(
            item.get("creationTime", item.get("created", item.get("createTime")))
        )
        modified_s = _to_epoch(
            item.get("modificationTime", item.get("modified", item.get("updateTime")))
        )
        labels: list[str] = []
        for raw in _as_list(item.get("labels")):
            if isinstance(raw, dict):
                lab = _to_str(raw.get("name", raw.get("label")))
            else:
                lab = _to_str(raw)
            if lab:
                labels.append(lab)
        if not title and not text:
            return
        records.append(
            GoogleKeepTaskRecord(
                kind="keep_note",
                title=title,
                text=text,
                created_s=created_s,
                modified_s=modified_s,
                labels=labels,
            )
        )

    def add_task(item: dict[str, Any]) -> None:
        title = _to_str(
            item.get("title", item.get("name", item.get("task")))
        )
        due_s = _to_epoch(
            item.get("dueDate", item.get("due", item.get("deadline")))
        )
        completed_raw = item.get("completed")
        completed: bool | None = None
        if isinstance(completed_raw, bool):
            completed = completed_raw
        elif isinstance(completed_raw, str):
            low = completed_raw.strip().lower()
            if low in ("true", "yes", "1"):
                completed = True
            elif low in ("false", "no", "0"):
                completed = False
        created_s = _to_epoch(
            item.get("creationTime", item.get("created"))
        )
        list_id = _to_str(item.get("listId", item.get("list")))
        if not title:
            return
        records.append(
            GoogleKeepTaskRecord(
                kind="task",
                title=title,
                created_s=created_s,
                due_s=due_s,
                completed=completed,
                labels=[list_id] if list_id else [],
            )
        )

    items: list[dict[str, Any]] = []
    is_tasks = False
    if isinstance(payload, dict):
        notes_val = payload.get("notes")
        tasks_val = payload.get("tasks", payload.get("items"))
        if isinstance(notes_val, list):
            items = [x for x in notes_val if isinstance(x, dict)]
        elif isinstance(tasks_val, list):
            items = [x for x in tasks_val if isinstance(x, dict)]
            is_tasks = True
    elif isinstance(payload, list):
        items = [x for x in payload if isinstance(x, dict)]

    for item in items[:MAX_ITEMS_PER_FILE]:
        if is_tasks:
            add_task(item)
        else:
            # plošný formát — rozlišit podle klíčů (task má dueDate/completed)
            if any(k in item for k in ("dueDate", "completed")) and "text" not in item:
                add_task(item)
            else:
                add_note(item)

    records = records[:MAX_ITEMS_PER_FILE]
    if not records:
        raise TypeError("Nenalezeny Google Keep poznámky / Tasks úkoly")
    return records


def build_google_keep_artifacts(
    records: list[GoogleKeepTaskRecord],
) -> list[Artifact]:
    """ČISTÁ funkce: z Keep/Tasks záznamů vytvoří artifacty."""
    artifacts: list[Artifact] = []
    for r in records:
        details: dict[str, Any] = {
            "engine": "google_keep_tasks",
            "kind": r.kind,
        }
        if r.text:
            details["text"] = r.text[:500]
        if r.labels:
            details["labels"] = r.labels
        if r.completed is not None:
            details["completed"] = r.completed

        title = (r.title or "(bez názvu)")
        prefix = "Google Task" if r.kind == "task" else "Google Keep Note"
        ts = None
        anchor = r.created_s or r.due_s
        if anchor is not None:
            try:
                ts = from_unix(anchor)
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="document_metadata",
                timestamp=ts,
                title=f"{prefix}: {title}"[:120],
                details=details,
                confidence=0.8 if r.title else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_google_keep_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Google Keep/Tasks JSON → document_metadata artifacty."""
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("GoogleKeep %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        records = parse_google_keep_tasks(data)
    except (ValueError, TypeError) as e:
        logger.debug("GoogleKeep %s: %s", path.name, e)
        return []

    return build_google_keep_artifacts(records)


def is_google_keep_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Google Keep/Tasks exportu.

    Vyžaduje Google marker (``google``/``takeout``) v názvu/cestě +
    klíčová slova keep/tasks — generic ``notes.json`` bez markery nepadne,
    aby se nekradly cizí poznámky.
    """
    lower = name.lower()
    if not any(k in lower for k in ("google", "takeout")):
        return False
    if not any(k in lower for k in ("keep", "task", "note")):
        return False
    if head:
        h = head[:2048].lstrip().lower()
        if not h.startswith((b"{", b"[")):
            return False
    return True
