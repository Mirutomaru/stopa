"""P4-5 — AI production robustness (AK dle docs/P4_DESIGNS.md).

- **W1**: ``classify_llm_error`` transient vs. permanent (čistá doména) +
  determinismus ``backoff_delay`` per seed;
- **W2**: retry+backoff+jitter v jádru agenta (jen transient; permanent =
  okamžitě), token budget → explicitní ``status="budget_exceeded"`` +
  truncation marker (ne exception);
- **AK 1**: stream ↔ non-stream identický výsledek (stejná jádrová smyčka);
- **AK 2**: retry deterministický při fixním seedu;
- **W3**: Web SSE ``GET /api/cases/{id}/ai/run/stream``;
- **W4**: eval gate CLI ``stopa ai-eval --suite gold [--json]`` — selže na
  regresi (exit 1), zelená suita → exit 0.

Plně offline: scripted LLM + monkeypatchovaný LM Studio klient, žádná síť.
"""

from __future__ import annotations

import argparse
import io
import json
import random
from collections.abc import Callable
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

CASE_ID = "case-p45"
SRC_ID = "src-p45"


# ── fixtures (stejný vzor jako F3.1) ────────────────────────────────────────


def _seed_case(db, case_id: str, src_id: str) -> None:
    now = "2026-01-01T00:00:00"
    db.conn.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, ?, ?)",
        (case_id, case_id.upper(), now),
    )
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/p45-seed', ?)",
        (src_id, case_id, now),
    )
    db.conn.commit()


@pytest.fixture()
def case_db(tmp_path: Path):
    """Syntetická case DB: soubor + 2 artefakty (stačí pro search_fts)."""
    import hashlib

    from stopa.data.db import CaseDB
    from stopa.data.query_cache import PROCESS_CACHE
    from stopa.models import Artifact, FileRecord, new_id

    db = CaseDB(str(tmp_path / "case-p45.db"))
    _seed_case(db, CASE_ID, SRC_ID)

    rec = FileRecord(
        id=new_id("f"),
        source_id=SRC_ID,
        rel_path="notes.txt",
        name="notes.txt",
        size_bytes=1024,
        mtime=datetime(2026, 1, 1),
        sha256=hashlib.sha256(b"notes").hexdigest(),
        extension="txt",
    )
    db.upsert_file(rec)

    art = Artifact(
        source_id=SRC_ID,
        artifact_type="browser_history",
        timestamp=datetime(2026, 1, 2),
        title="Navštěva platební stránky",
    )
    db.upsert_artifact(art)
    PROCESS_CACHE.invalidate(None)
    yield SimpleNamespace(dir=tmp_path, db=db, file_id=rec.id, art1=art.id)
    PROCESS_CACHE.invalidate(None)
    db.close()


class FakeLLM:
    """Sevřená LLM — skriptované odpovědi / výjimky po sobě (deterministicky)."""

    def __init__(self, *items: str | Exception):
        self.items = list(items)
        self.call_count = 0

    def __call__(self, messages, max_tokens):
        self.call_count += 1
        if not self.items:
            raise AssertionError("FakeLLM: chybí skriptovaná odpověď")
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def act(action: str, params: dict | None = None) -> str:
    return json.dumps({"thought": "krok", "action": action, "params": params or {}}, ensure_ascii=False)


def fin(answer: str) -> str:
    return json.dumps({"thought": "zaver", "final_answer": answer}, ensure_ascii=False)


def _sleeps_collector() -> tuple[list[float], Callable[[float], None]]:
    sleeps: list[float] = []

    def sleep_fn(delay: float) -> None:
        sleeps.append(delay)

    return sleeps, sleep_fn


# ── W1 — klasifikace chyb + backoff (čistá doména) ─────────────────────────


class TestClassifyLlmError:
    def test_transient_markers(self):
        from stopa.domain.ai_orchestrator import classify_llm_error

        for msg in (
            "ReadTimeout: connection timed out",
            "ConnectionResetError: [Errno 104] Connection reset by peer",
            "RateLimitExceeded: too many requests",
            "HTTP 429 Too Many Requests",
            "HTTP 503 Service Unavailable",
            "HTTP 502 Bad Gateway",
            "upstream temporarily unavailable",
        ):
            assert classify_llm_error(Exception(msg)) == "transient", msg

    def test_permanent_http_codes(self):
        from stopa.domain.ai_orchestrator import classify_llm_error

        for code in (400, 401, 403, 404, 422):
            assert classify_llm_error(Exception(f"HTTP {code}")) == "permanent", code

    def test_unknown_message_permanent(self):
        from stopa.domain.ai_orchestrator import classify_llm_error

        assert classify_llm_error(ValueError("bad payload shape")) == "permanent"
        with pytest.raises(TypeError, match="instance výjimky"):
            classify_llm_error("ne výjimka")  # type: ignore[arg-type]


class TestBackoffDelay:
    POLICY = None  # lazy — RetryPolicy je dataclass s validací

    def _policy(self):
        from stopa.domain.ai_orchestrator import RetryPolicy

        return RetryPolicy(max_attempts=5, base_delay_s=0.5, factor=2.0, jitter_pct=0.1)

    def test_deterministic_per_seed(self):
        from stopa.domain.ai_orchestrator import backoff_delay

        policy = self._policy()
        seq_a = [backoff_delay(policy, a, random.Random(42)) for a in (1, 2, 3)]
        seq_b = [backoff_delay(policy, a, random.Random(42)) for a in (1, 2, 3)]
        assert seq_a == seq_b
        # exponenciální základ roste: base * factor^(attempt-1)
        assert seq_a[0] < seq_a[1] < seq_a[2]

    def test_attempt_validation(self):
        from stopa.domain.ai_orchestrator import backoff_delay

        with pytest.raises(ValueError, match="kladné celé číslo"):
            backoff_delay(self._policy(), 0, random.Random(1))


# ── W2 — retry v jádru agenta (AK 2: determinismus per seed) ────────────────


class TestAgentRetry:
    def test_transient_retried_then_success(self, case_db):
        from stopa.data.lmstudio_client import LmStudioError
        from stopa.domain.ai_orchestrator import RetryPolicy
        from stopa.intelligence.tool_agent import run_tool_agent

        llm = FakeLLM(
            LmStudioError("connection reset by peer"),  # transient → retry
            fin(f"Hotovo, viz [file:{case_db.file_id}]."),
        )
        sleeps, sleep_fn = _sleeps_collector()
        res = run_tool_agent(
            llm,
            case_db.db,
            CASE_ID,
            "Otázka",
            retry_policy=RetryPolicy(max_attempts=3, base_delay_s=0.5),
            rng=random.Random(1),
            sleep_fn=sleep_fn,
        )
        assert res.status == "ok"
        assert llm.call_count == 2
        assert len(sleeps) == 1 and sleeps[0] > 0

    def test_permanent_propagates_immediately_no_sleep(self, case_db):
        from stopa.domain.ai_orchestrator import RetryPolicy
        from stopa.intelligence.tool_agent import run_tool_agent

        llm = FakeLLM(ValueError("HTTP 422 Validation Error"))
        sleeps, sleep_fn = _sleeps_collector()
        with pytest.raises(ValueError, match="HTTP 422"):
            run_tool_agent(
                llm,
                case_db.db,
                CASE_ID,
                "Otázka",
                retry_policy=RetryPolicy(max_attempts=3),
                rng=random.Random(1),
                sleep_fn=sleep_fn,
            )
        assert llm.call_count == 1, "permanentní chyba nesmí konzumovat další pokusy"
        assert sleeps == [], "před permanentní chybou se nespí"

    def test_exhausted_attempts_propagate_last_error(self, case_db):
        from stopa.data.lmstudio_client import LmStudioError
        from stopa.domain.ai_orchestrator import RetryPolicy
        from stopa.intelligence.tool_agent import run_tool_agent

        llm = FakeLLM(
            LmStudioError("timeout 1"),
            LmStudioError("timeout 2"),
            LmStudioError("timeout 3"),
        )
        sleeps, sleep_fn = _sleeps_collector()
        with pytest.raises(LmStudioError, match="timeout 3"):
            run_tool_agent(
                llm,
                case_db.db,
                CASE_ID,
                "Otázka",
                retry_policy=RetryPolicy(max_attempts=3),
                rng=random.Random(1),
                sleep_fn=sleep_fn,
            )
        assert llm.call_count == 3
        assert len(sleeps) == 2, "spí se mezi pokusy (ne po posledním)"

    def test_policy_none_single_attempt_legacy(self, case_db):
        """policy=None = chování před P4-5: jediný pokus i při transientní chybě."""
        from stopa.data.lmstudio_client import LmStudioError
        from stopa.intelligence.tool_agent import run_tool_agent

        llm = FakeLLM(LmStudioError("connection reset"))
        sleeps, sleep_fn = _sleeps_collector()
        with pytest.raises(LmStudioError):
            run_tool_agent(llm, case_db.db, CASE_ID, "Otázka", rng=random.Random(1), sleep_fn=sleep_fn)
        assert llm.call_count == 1 and sleeps == []

    def test_retry_deterministic_per_seed_e2e(self, case_db):
        """AK 2: stejný seed → identická sekvence backoff zpoždění."""
        from stopa.data.lmstudio_client import LmStudioError
        from stopa.domain.ai_orchestrator import RetryPolicy
        from stopa.intelligence.tool_agent import run_tool_agent

        def scripted() -> FakeLLM:
            return FakeLLM(
                LmStudioError("timeout a"),
                LmStudioError("timeout b"),
                fin(f"Hotovo, viz [file:{case_db.file_id}]."),
            )

        runs = []
        for _ in range(2):
            sleeps, sleep_fn = _sleeps_collector()
            run_tool_agent(
                scripted(),
                case_db.db,
                CASE_ID,
                "Otázka",
                retry_policy=RetryPolicy(max_attempts=5, base_delay_s=0.5, factor=2.0, jitter_pct=0.3),
                rng=random.Random(99),
                sleep_fn=sleep_fn,
            )
            runs.append(sleeps)
        assert runs[0] == runs[1], "fixní seed → deterministické zpoždění"
        assert len(runs[0]) == 2


# ── W2 — token budget (AK: status, ne exception) ────────────────────────────


class TestTokenBudget:
    def test_budget_exceeded_status_not_exception(self, case_db):
        from stopa.intelligence.tool_agent import BUDGET_TRUNCATION_MARKER, run_tool_agent

        # akční krok spotřebuje budget (odhad promptu >> 5 tokenů) → druhá
        # iterace smyčky skončí explicitním stavem, ne výjimkou.
        llm = FakeLLM(
            act("search_fts", {"query": "notes"}),
            fin("Tohle už nedosáhne."),
        )
        res = run_tool_agent(llm, case_db.db, CASE_ID, "Otázka", token_budget=5)
        assert res.status == "budget_exceeded"
        assert res.final_answer == BUDGET_TRUNCATION_MARKER
        assert len(res.steps) == 1
        assert llm.call_count == 1

    def test_budget_none_unlimited_ok(self, case_db):
        from stopa.intelligence.tool_agent import run_tool_agent

        llm = FakeLLM(fin(f"Hotovo, viz [file:{case_db.file_id}]."))
        res = run_tool_agent(llm, case_db.db, CASE_ID, "Otázka", token_budget=None)
        assert res.status == "ok" and res.final_answer.startswith("Hotovo")

    def test_budget_validation_type_and_value_errors(self, case_db):
        from stopa.intelligence.tool_agent import run_tool_agent

        llm = FakeLLM(fin("x"))
        for bad in (True, 3.5, "10"):  # typová chyba
            with pytest.raises(TypeError, match="token_budget"):
                run_tool_agent(llm, case_db.db, CASE_ID, "Otázka", token_budget=bad)  # type: ignore[arg-type]
        for bad in (0, -4):  # sémantická chyba
            with pytest.raises(ValueError, match="kladné"):
                run_tool_agent(llm, case_db.db, CASE_ID, "Otázka", token_budget=bad)


# ── AK 1 — stream ↔ non-stream identický výsledek ───────────────────────────


def _normalize_for_identity(d: dict) -> dict:
    """Normalizace výsledku pro srovnání stream ↔ non-stream identity.

    Oloupá běhově závislé pole, která nejsou součástí sémantického výstupu:
    ``duration_ms`` (top-level i per krok) a ``audit_row_id`` per krok
    (autoincrement v audit tabulce — druhý běh dostane jiná ID).
    """
    out = {k: v for k, v in d.items() if k != "duration_ms"}
    out["steps"] = [
        {k: v for k, v in s.items() if k not in ("duration_ms", "audit_row_id")}
        for s in d.get("steps", [])
    ]
    return out


class TestStreamNonStreamIdentity:
    def test_identical_result(self, case_db):
        from dataclasses import asdict

        from stopa.intelligence.tool_agent import run_stream, run_tool_agent

        def scripted():
            return FakeLLM(
                act("search_fts", {"query": "notes"}),
                fin(f"Nalezeno: [file:{case_db.file_id}]."),
            )

        plain = run_tool_agent(scripted(), case_db.db, CASE_ID, "Najdi poznámky.")
        events = list(run_stream(scripted(), case_db.db, CASE_ID, "Najdi poznámky."))

        # pořadí událostí: start → step* → final (i finální krok = step event)
        assert [e["type"] for e in events] == ["start", "step", "step", "final"]
        assert events[0]["max_steps"] == 8
        actions = [e.get("action") for e in events if e["type"] == "step"]
        assert actions == ["search_fts", None]

        streamed_result = events[-1]["result"]
        assert _normalize_for_identity(streamed_result) == _normalize_for_identity(asdict(plain))

    def test_budget_status_visible_in_stream(self, case_db):
        from stopa.intelligence.tool_agent import BUDGET_TRUNCATION_MARKER, run_stream

        llm = FakeLLM(act("search_fts", {"query": "notes"}), fin("x"))
        events = list(run_stream(llm, case_db.db, CASE_ID, "Otázka", token_budget=5))
        assert [e["type"] for e in events] == ["start", "step", "final"]
        assert events[-1]["result"]["status"] == "budget_exceeded"
        assert events[-1]["result"]["final_answer"] == BUDGET_TRUNCATION_MARKER

    def test_stream_error_event_grounding(self, case_db):
        """Nevalidní citace → přesně jeden error event (fail-closed)."""
        from stopa.intelligence.tool_agent import run_stream

        llm = FakeLLM(fin("Podle [art:ghost-p45] je to jisté."))
        events = list(run_stream(llm, case_db.db, CASE_ID, "Otázka"))
        assert [e["type"] for e in events] == ["start", "step", "error"]
        assert events[-1]["exc_type"] == "GroundingError"

    def test_stream_error_event_max_steps(self, case_db):
        from stopa.intelligence.tool_agent import run_stream

        llm = FakeLLM(act("search_fts", {"query": "x"}), act("search_fts", {"query": "y"}))
        events = list(run_stream(llm, case_db.db, CASE_ID, "Otázka", max_steps=2))
        assert [e["type"] for e in events] == ["start", "step", "step", "error"]
        assert events[-1]["exc_type"] == "MaxStepsError"


# ── W3 — Web SSE route ───────────────────────────────────────────────────────


def _patch_lmstudio(monkeypatch: pytest.MonkeyPatch, *responses: str) -> None:
    """Nahradí LmStudioClient v routeru ai.py (top-level import)."""
    import stopa.web.routers.ai as ai_router

    class FakeLm:
        def __init__(self, *_a: object, **_k: object) -> None:
            self._responses = list(responses)

        def health(self) -> dict:
            return {"available": True, "model": "fake-model"}

        def chat(self, messages, max_tokens=None):
            if not self._responses:
                raise AssertionError("FakeLm vyčerpan")
            return self._responses.pop(0)

    monkeypatch.setattr(ai_router, "LmStudioClient", FakeLm)


@pytest.fixture()
def web_client(case_db):
    from stopa.web.app import create_app

    return TestClient(create_app(db_dir=case_db.dir))


class TestSseStreamRoute:
    def test_sse_stream_payload(self, case_db, monkeypatch, web_client):
        """200 + text/event-stream; události start → step → final (data: JSON)."""
        _patch_lmstudio(monkeypatch, fin(f"Hotovo, viz [file:{case_db.file_id}]."))
        r = web_client.get(f"/api/cases/{CASE_ID}/ai/run/stream", params={"question": "Shrni."})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/event-stream")

        events = []
        for line in r.text.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
        # start → step (finální krok) → final
        types = [e["type"] for e in events]
        assert types == ["start", "step", "final"], f"očekávám start+step+final, got {types}"
        assert events[-1]["result"]["status"] == "ok"

    def test_sse_stream_404_missing_case(self, monkeypatch, web_client):
        _patch_lmstudio(monkeypatch, fin("x"))
        r = web_client.get("/api/cases/ghost-case-999/ai/run/stream", params={"question": "Q"})
        assert r.status_code == 404

    def test_sse_stream_503_lmstudio_down(self, monkeypatch, web_client):
        import stopa.web.routers.ai as ai_router

        class DownLm:
            def health(self):
                return {"available": False, "model": None}

        monkeypatch.setattr(ai_router, "LmStudioClient", DownLm)
        r = web_client.get(f"/api/cases/{CASE_ID}/ai/run/stream", params={"question": "Q"})
        assert r.status_code == 503


# ── W4 — eval gate CLI (AK: selže na regresi) ───────────────────────────────


class TestAiEvalCli:
    def test_green_suite_exit0(self, monkeypatch):
        monkeypatch.delenv("STOPA_DB_DIR", raising=False)
        from stopa.cli import cmd_ai_eval

        args = argparse.Namespace(suite="gold", json=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_ai_eval(args)
        assert rc == 0, buf.getvalue()
        out = json.loads(buf.getvalue())
        assert out["suite"] == "gold" and out["total"] == 8 and out["passed"] == 8
        assert out["failed"] == []

    def test_regression_exit1(self, monkeypatch):
        """Zlatá odpověď rozbije schéma → gate hlásí selhání role (exit 1)."""
        import stopa.intelligence.ai_eval as ai_eval_mod

        monkeypatch.delenv("STOPA_DB_DIR", raising=False)
        monkeypatch.setitem(ai_eval_mod.GOLDEN_RESPONSES, "qa", "nejde o JSON {x")
        from stopa.cli import cmd_ai_eval

        args = argparse.Namespace(suite="gold", json=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_ai_eval(args)
        assert rc == 1, buf.getvalue()
        out = json.loads(buf.getvalue())
        assert out["failed"] == ["qa"]

    def test_text_mode_lists_failures(self, monkeypatch):
        import stopa.intelligence.ai_eval as ai_eval_mod

        monkeypatch.delenv("STOPA_DB_DIR", raising=False)
        monkeypatch.setitem(ai_eval_mod.GOLDEN_RESPONSES, "network", "{}")
        from stopa.cli import cmd_ai_eval

        args = argparse.Namespace(suite="gold", json=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_ai_eval(args)
        out = buf.getvalue()
        assert rc == 1
        assert "FAIL network" in out and "SUITA gold: 7/8" in out
