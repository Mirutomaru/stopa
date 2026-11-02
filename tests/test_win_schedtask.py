"""ETAPA B vlna 1 — testy Windows Scheduled Tasks XML parseru.

ČISTÉ funkce (parse_scheduled_task_xml / build_scheduled_task_artifacts) +
IO entrypoint (extract_scheduled_task_artifacts přes tmp_path). Žádný regipy, žádné sítě.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stopa.artifacts.win_schedtask import (
    PARSER_VERSION,
    build_scheduled_task_artifacts,
    extract_scheduled_task_artifacts,
    is_scheduled_task_file,
    parse_scheduled_task_xml,
)

# ── syntetické fixtures ────────────────────────────────────────────────

TASK_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>2026-11-01T08:30:00</Date>
    <Author>JAN\\Admin</Author>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <Enabled>true</Enabled>
      <StartBoundary>2026-11-01T08:30:00</StartBoundary>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Actions Context="Author">
    <Exec>
      <Command>C:\\Windows\\System32\\malware.exe</Command>
      <Arguments>--silent --install</Arguments>
    </Exec>
  </Actions>
</Task>
""".encode("utf-16")  # reálné task XML jsou UTF-16 LE s BOM

# task bez akcí ani triggerů → parser by měl vrátit None (prázdný výsledek)
EMPTY_TASK = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Date>2026-11-01T08:30:00</Date>
  </RegistrationInfo>
</Task>
""".encode("utf-16")

# ne-task XML (jiný root)
OTHER_XML = b'<?xml version="1.0"?><WLANProfile xmlns="x"><name>w</name></WLANProfile>'


# ── is_scheduled_task_file (detekce) ───────────────────────────────────

def test_is_schedtask_by_path_and_content():
    name = "Windows/System32/Tasks/MyTask.xml"
    assert is_scheduled_task_file(name, TASK_XML[:2048]) is True


def test_is_schedtask_rejects_other_xml():
    # cesta sedí (Tasks), ale obsah není task → False
    assert is_scheduled_task_file("Windows/System32/Tasks/x.xml", OTHER_XML) is False


def test_is_schedtask_requires_tasks_path():
    # bez Tasks v cestě a bez scheduledtask v názvu → False
    assert is_scheduled_task_file("random/task.xml", TASK_XML[:2048]) is False


# ── parse_scheduled_task_xml (čistá funkce) ───────────────────────────

def test_parse_full_task():
    tasks = parse_scheduled_task_xml(TASK_XML)
    assert len(tasks) == 1
    t = tasks[0]
    assert t.author == "JAN\\Admin"
    assert t.registration_date.startswith("2026-11-01")
    # trigger — typ + start boundary
    assert any("calendar" in tr.lower() for tr in t.triggers)
    # akce — command + arguments
    assert len(t.actions) == 1
    assert "malware.exe" in t.actions[0]["command"]
    assert "--silent" in t.actions[0]["arguments"]


def test_parse_empty_task_returns_none():
    tasks = parse_scheduled_task_xml(EMPTY_TASK)
    # bez akcí/triggerů/autora → prázdný výsledek
    assert tasks == []


def test_parse_non_task_xml_empty():
    assert parse_scheduled_task_xml(OTHER_XML) == []


def test_parse_garbage_raises():
    with pytest.raises(ValueError):
        parse_scheduled_task_xml(b"\x00\x01garbage")


# ── build_scheduled_task_artifacts (čistá funkce) ─────────────────────

def test_build_artifacts():
    tasks = parse_scheduled_task_xml(TASK_XML)
    arts = build_scheduled_task_artifacts(tasks)
    assert len(arts) == 1
    a = arts[0]
    assert a.artifact_type == "scheduled_task"
    assert a.parser_version == PARSER_VERSION
    assert a.timestamp is not None  # registration_date → ISO timestamp
    assert any("malware.exe" in str(act.get("command", "")) for act in a.details.get("actions", []))


def test_build_artifacts_empty():
    assert build_scheduled_task_artifacts([]) == []


# ── extract_scheduled_task_artifacts (IO přes tmp_path) ───────────────

def test_extract_task_file(tmp_path: Path):
    p = tmp_path / "MyTask.xml"
    p.write_bytes(TASK_XML)
    arts = extract_scheduled_task_artifacts(p)
    assert len(arts) == 1
    # jméno doplněno ze stem souboru (XML nemá <Name>)
    assert arts[0].details.get("engine") == "scheduled_task"


def test_extract_missing_file(tmp_path: Path):
    assert extract_scheduled_task_artifacts(tmp_path / "nope.xml") == []
