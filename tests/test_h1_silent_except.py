"""H1 — Tiché ``except+pass``: explicitní logování / validační status.

A. **AST guard (statický)**: každý pass-only handler v ``src/stopa`` musí mít
   odůvodnění na řádku ``except`` nebo těla (komentář „#"). Pinuje stav auditu
   (bucket A — viz PLAN_BACKLOG H1 F-1..F-5) a brzdí nové tiché regrese.
B. **Behavior pin opravených lokací**: poškozené timestampy v ``list_cases``
   (→ None + warning), chybějící integrity klíč (sign_report → nepodepsáno),
   nečíselné souřadnice Location (detail bez pole + debug log), nevalidní extra
   JSON v l2tcsv (řádek zůstává + debug log).

Offline a deterministické; konvence: trvalá data = warning, bulk extrakce = debug.
"""
from __future__ import annotations

import ast
import hashlib
import logging
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "stopa"


# ── A. AST guard: pass-only handler musí mít odůvodnění ───────────────────────


def _unjustified_pass_only(path: Path) -> list[tuple[str, int]]:
    """Lokace pass-only handlerů bez komentáře na řádku except/těla."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    lines = text.splitlines()
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
            continue
        pass_line = node.body[0].lineno
        span = range(min(node.lineno, pass_line), max(node.lineno, pass_line) + 1)
        if not any("#" in lines[i - 1] for i in span):
            out.append((path.name, node.lineno))
    return out


def test_all_pass_only_handlers_have_rationale() -> None:
    offenders = sorted(
        (name, lineno, str(path.relative_to(SRC.parent)))
        for path in sorted(SRC.rglob("*.py"))
        for name, lineno in _unjustified_pass_only(path)
    )
    assert not offenders, (
        "tiché pass-only except bez odůvodnění (komentář na řádku except/těla): "
        + "; ".join(f"{p}:{ln}" for _, ln, p in offenders)
    )


def test_guard_catches_silent_pass(tmp_path: Path) -> None:
    """Mutace: syntetický soubor se tichým pass → guard ho chytí."""
    (tmp_path / "silent.py").write_text(
        "import json\n"
        "\n"
        "def parse(s):\n"
        "    try:\n"
        '        return json.loads(s)\n'
        "    except ValueError:\n"
        "        pass\n",
        encoding="utf-8",
    )
    assert _unjustified_pass_only(tmp_path / "silent.py") == [("silent.py", 6)]


def test_guard_accepts_commented_and_logged() -> None:
    """Komentář na except řádku i na pass řádku = odůvodněno; log ≠ pass-only."""
    assert _unjustified_pass_only(_tmp_doc()) == []


def _tmp_doc() -> Path:
    import tempfile

    d = Path(tempfile.mkdtemp(prefix="h1guard"))
    (d / "ok.py").write_text(
        "import logging\n"
        "_log = logging.getLogger(__name__)\n"
        "\n"
        "def a():\n"
        '    try:\n'
        '        x = int("1")\n'
        "    except ValueError:  # odůvodněno tady\n"
        "        pass\n"
        "\n"
        "def b():\n"
        "    try:\n"
        '        y = int("2")\n'
        "    except ValueError:\n"
        "        _log.debug(\"fallback\")  # log → není pass-only\n"
        "        pass\n",
        encoding="utf-8",
    )
    return d / "ok.py"


# ── B. Behavior pin opravených lokací ─────────────────────────────────────────


class TestCorruptCaseTimestamps:
    """case_repository.list_cases — poškozené trvalé timestampy → None + warning."""

    def test_degrade_to_none_and_warn(self, tmp_path: Path, caplog) -> None:
        from stopa.data.db import CaseDB
        from stopa.models import Case

        db = CaseDB(tmp_path / "case-h1.db")
        case = Case(id="case-h1", name="H1")
        db.add_case(case)
        db.conn.execute(
            "UPDATE cases SET last_auto_export_at='garbage', created_at='not-a-date' "
            "WHERE id=?",
            (case.id,),
        )
        db.conn.commit()
        with caplog.at_level(logging.WARNING, logger="stopa.data.case_repository"):
            got = [c for c in db.list_cases() if c.id == case.id]
        assert len(got) == 1
        assert got[0].last_auto_export_at is None
        assert "poškozený last_auto_export_at" in caplog.text
        assert "poškozený created_at" in caplog.text

    def test_valid_timestamps_untouched(self, tmp_path: Path, caplog) -> None:
        """BC kontrola: validní řádek bez degradace (žádný warning)."""
        from stopa.data.db import CaseDB
        from stopa.models import Case

        db = CaseDB(tmp_path / "case-h1b.db")
        case = Case(id="case-h1b", name="H1-B")
        db.add_case(case)
        with caplog.at_level(logging.WARNING, logger="stopa.data.case_repository"):
            got = [c for c in db.list_cases() if c.id == case.id]
        assert len(got) == 1 and got[0].created_at is not None
        assert "poškozený" not in caplog.text


class TestCryptoGracefulDegradation:
    """sign_report (reprezentant 6 cryptography lokací) — bez klíče = nepodepsáno."""

    def test_without_key_returns_undsigned(self) -> None:
        from stopa.presentation import crypto_report as cr

        class _NoKeyDB:
            def ensure_integrity_key(self):
                raise RuntimeError("cryptography chybí")

            def integrity_public_key(self):
                return None

        digest, sig, pub = cr.sign_report("obsah reportu", _NoKeyDB())
        assert digest == hashlib.sha256(b"obsah reportu").hexdigest()
        assert sig is None  # explicitní „nepodepsáno“ ve výstupu
        assert pub is None


class TestLocationNonNumericCoords:
    """mobile_forensics Location — nečíselné souřadnice → detail bez pole + debug."""

    def test_nonnumeric_dropped_with_log(self, caplog) -> None:
        from stopa.domain.mobile_forensics import (
            models_to_artifact_specs,
            parse_ufdr_xml,
        )

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?><Report><Extraction>'
            '<model type="Location">'
            "<field name=\"Name\">Praha</field>"
            "<field name=\"Latitude\">abc</field>"
            "<field name=\"Longitude\">14.4378</field>"
            "</model></Extraction></Report>"
        )
        with caplog.at_level(logging.DEBUG, logger="stopa.domain.mobile_forensics"):
            specs = models_to_artifact_specs(parse_ufdr_xml(xml)[0])
        s = specs[0]
        assert s.artifact_type == "location" and s.title == "Praha"
        assert "lat" not in s.details  # nečíselné → pole chybí (explicitní stav)
        assert s.details["lon"] == pytest.approx(14.4378)
        assert "nečíselné Latitude" in caplog.text


class TestPlasoInvalidExtra:
    """plaso_import l2tcsv — nevalidní extra JSON → řádek zůstává + debug log."""

    def test_keeps_row_and_logs(self, caplog) -> None:
        from stopa.domain.plaso_import import parse_l2tcsv

        text = (
            "date,time,timezone,MACB,source,sourcetype,type,user,host,"
            "short,desc,version,filename,inode,notes,format,extra\n"
            '10/30/2026,12:00:00,Z,,STOPA,email,Event Time,,,mail,"",2,m.e,'
            ',,stopa.timeline,{nevalidni json}\n'
        )
        with caplog.at_level(logging.DEBUG, logger="stopa.domain.plaso_import"):
            events = parse_l2tcsv(text)
        assert len(events) == 1
        assert events[0].ts_utc is not None
        assert "nevalidní extra JSON" in caplog.text
