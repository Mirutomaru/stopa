"""ETAPA B vlna 1 — Windows Scheduled Tasks parser.

AXIOM ekvivalent: ``ScheduledTasksArtifact``.

Podporovaný formát: **Task Scheduler XML** — soubory z
``C:\\Windows\\System32\\Tasks\\*.xml`` (Windows Vista+). Kořenový element
``<Task>`` obsahuje registraci (autor, datum), spouštěče a akce
(spouštěný příkaz + argumenty) — forenzně cenné pro persistence a
identifikaci spuštěných aplikací.

Detekce: **name-based** (soubor v adresáři ``Tasks``, XML s kořenem
``<Task>`` obsahujícím ``RegistrationInfo``/``Actions``) — XML nemá magic
bytes, AXIOM Hunter pattern jako u iCloud Messages / WLAN profilů.

Artifact type: ``scheduled_task`` — jeden task = jeden artifact.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stopa.domain.xml_bounded import XmlLimitError, bounded_xml_parse
from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_TASKS_PER_FILE = 50


@dataclass
class ScheduledTask:
    """Jeden plánovaný úkol — registrace, spouštěče, akce."""

    name: str = ""
    author: str = ""
    registration_date: str = ""
    principal_user: str = ""
    triggers: list[str] = field(default_factory=list)
    actions: list[dict[str, str]] = field(default_factory=list)


def _local(tag: str) -> str:
    """XML tag bez namespace (``{ns}Task`` → ``task``)."""
    return (tag or "").split("}")[-1].lower()


def _find(elem: ET.Element, path: str) -> ET.Element | None:
    """Namespace-agnostické find (path bez prefixu)."""
    for node in elem.iter():
        if _local(node.tag) == path.lower():
            return node
    return None


def _parse_task(root: ET.Element) -> ScheduledTask | None:
    """ČISTÝ parser jednoho ``<Task>`` elementu."""
    task = ScheduledTask()

    # registrace — <RegistrationInfo><Date>, <Author>
    reg = root.find(".//{http://schemas.microsoft.com/windows/2004/02/mit/task}RegistrationInfo")
    if reg is None:
        for node in root.iter():
            if _local(node.tag) == "registrationinfo":
                reg = node
                break
    if reg is not None:
        date_el = reg.find("{http://schemas.microsoft.com/windows/2004/02/mit/task}Date")
        if date_el is None:
            for child in reg:
                if _local(child.tag) == "date" and child.text:
                    task.registration_date = child.text.strip()[:32]
                    break
        elif date_el.text:
            task.registration_date = date_el.text.strip()[:32]
        author_el = reg.find("{http://schemas.microsoft.com/windows/2004/02/mit/task}Author")
        if author_el is None:
            for child in reg:
                if _local(child.tag) == "author" and child.text:
                    task.author = child.text.strip()[:128]
                    break
        elif author_el.text:
            task.author = author_el.text.strip()[:128]

    # principál — <Principal><LogonType> + user z registrace/akcí
    principal = root.find(".//{http://schemas.microsoft.com/windows/2004/02/mit/task}Principal")
    if principal is None:
        for node in root.iter():
            if _local(node.tag) == "principal":
                principal = node
                break

    # spouštěče — <Triggers><CalendarTrigger>... (typ + interval)
    triggers_el = root.find(".//{http://schemas.microsoft.com/windows/2004/02/mit/task}Triggers")
    if triggers_el is None:
        for node in root.iter():
            if _local(node.tag) == "triggers":
                triggers_el = node
                break
    if triggers_el is not None:
        for trig in triggers_el:
            ttype = _local(trig.tag)
            if not ttype or ttype == "triggers":
                continue
            desc = ttype.replace("trigger", "")
            # interval — <Enabled> + <StartBoundary>
            start = ""
            for child in trig.iter():
                if _local(child.tag) == "startboundary" and child.text:
                    start = child.text.strip()[:32]
                    break
            task.triggers.append(f"{desc}{(' ' + start) if start else ''}")

    # akce — <Actions><Exec><Command>, <Arguments>
    actions_el = root.find(".//{http://schemas.microsoft.com/windows/2004/02/mit/task}Actions")
    if actions_el is None:
        for node in root.iter():
            if _local(node.tag) == "actions":
                actions_el = node
                break
    if actions_el is not None:
        for action in actions_el:
            if _local(action.tag) != "exec":
                continue
            cmd, args = "", ""
            for child in action:
                tag = _local(child.tag)
                if tag == "command" and child.text:
                    cmd = child.text.strip()[:256]
                elif tag == "arguments" and child.text:
                    args = child.text.strip()[:256]
            if cmd or args:
                task.actions.append({"command": cmd, "arguments": args})

    # jméno — z atributu nebo cesty souboru (pipeline doplní)
    name_el = root.find(".//{http://schemas.microsoft.com/windows/2004/02/mit/task}Name")
    if name_el is not None and name_el.text:
        task.name = name_el.text.strip()[:128]

    if not (task.actions or task.triggers or task.author):
        return None
    return task


def parse_scheduled_task_xml(data: bytes) -> list[ScheduledTask]:
    """ČISTÝ parser — XML obsah → tasks.

    Raises:
        ValueError: Neplatné XML nebo chybějící Task kořen.
    """
    try:
        # P1 security — důkazový XML s limitem hloubky a entit
        root = bounded_xml_parse(data)
    except (ET.ParseError, XmlLimitError) as e:
        raise ValueError(f"Neplatné Scheduled Task XML: {e}") from e

    if _local(root.tag) != "task":
        # obálka s více tasky (zřídka) — zkusí se iterovat
        candidates = [n for n in root if _local(n.tag) == "task"]
    else:
        candidates = [root]

    tasks: list[ScheduledTask] = []
    for elem in candidates[:MAX_TASKS_PER_FILE]:
        try:
            t = _parse_task(elem)
        except Exception as e:  # noqa: BLE001 — jeden poškozený task nepotopí soubor
            logger.warning("ScheduledTask: chyba elementu (%s)", e)
            continue
        if t is not None:
            tasks.append(t)

    return tasks


def is_scheduled_task_file(name: str, head: bytes = b"") -> bool:
    """Name-based detekce Scheduled Task XML (AXIOM Hunter pattern)."""
    lower = name.lower()
    if not lower.endswith(".xml"):
        return False
    # typické umístění: ...\\Tasks\\<task>.xml — nebo explicitní jméno
    parts = [p for p in lower.replace("\\", "/").split("/") if p]
    if "tasks" not in parts and "scheduledtask" not in lower:
        return False
    if head:
        h = head[:4096].lstrip()
        # task XML bývá UTF-16 LE s BOM — odstraň null bajty pro textovou kontrolu
        if h.startswith((b"\xff\xfe", b"\xfe\xff")):
            h = h.lstrip(b"\xff\xfe").replace(b"\x00", b"")
        if b"<" not in h or (b"task" not in h.lower()):
            return False
    return True


def build_scheduled_task_artifacts(tasks: list[ScheduledTask]) -> list[Artifact]:
    """ČISTÁ funkce: z tasků vytvoří artifacty (scheduled_task)."""
    artifacts: list[Artifact] = []
    for t in tasks:
        label = t.name or (t.actions[0]["command"] if t.actions else "(bez názvu)")
        details: dict[str, Any] = {"engine": "scheduled_task"}
        if t.author:
            details["author"] = t.author
        if t.registration_date:
            details["registration_date"] = t.registration_date
        if t.triggers:
            details["triggers"] = t.triggers[:10]
        if t.actions:
            details["actions"] = t.actions[:10]

        # registrace jako timestamp (ISO z XML — parsuje se defenzivně)
        ts = None
        if t.registration_date:
            try:
                from datetime import datetime

                ts = datetime.fromisoformat(t.registration_date.replace("Z", "+00:00"))
            except ValueError:
                ts = None

        artifacts.append(
            Artifact(
                artifact_type="scheduled_task",
                timestamp=ts,
                title=f"Plánovaný úkol: {label}",
                details=details,
                confidence=0.85 if t.actions else 0.6,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_scheduled_task_artifacts(path: Path) -> list[Artifact]:
    """Pipeline entrypoint — Scheduled Task XML → scheduled_task artifacty.

    Chyby (poškozené XML, IO) → log + prázdný výsledek, nikdy ne výjimka.
    """
    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("ScheduledTask %s: nelze číst (%s)", path, e)
        return []

    if not data:
        return []

    try:
        tasks = parse_scheduled_task_xml(data)
    except ValueError as e:
        logger.debug("ScheduledTask %s: %s", path, e)
        return []

    # jméno tasku — z cesty souboru (pipeline nezná kontext, ale rel_path ano)
    if tasks and not tasks[0].name:
        stem = path.stem
        for t in tasks:
            if not t.name:
                t.name = stem

    return build_scheduled_task_artifacts(tasks)
