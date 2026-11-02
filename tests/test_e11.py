"""E11 — AI Forensic Assistant: prompt buildery, parsování, LM Studio klient, web E2E.

- domain testy = čistá logika (bez IO) — prompty, parse_nl_search, citace
- klient testy = httpx.MockTransport (žádný reálný server)
- web E2E = TestClient + monkeypatchovaný LmStudioClient (offline degradation
  bez patche — mrtvý port → available=False / HTTP 503)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

# ════════════════════════════════════════════════════════════════
# domain — prompt buildery (čistá logika)
# ════════════════════════════════════════════════════════════════

class TestPromptBuilders:
    def test_nl_search_prompt_contains_syntax_and_case(self):
        from stopa.domain.ai_assistant import build_nl_search_prompt

        msgs = build_nl_search_prompt("kde jsou fotky?", "Případ X")
        assert len(msgs) == 2 and msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
        sys_text = msgs[0]["content"]
        for token in ("size:>1MB", "mtime:", "ext:jpg", "in-artifact:", "Případ X"):
            assert token in sys_text
        assert msgs[1]["content"] == "kde jsou fotky?"

    def test_summary_prompt_includes_stats_and_sample_ids(self):
        from stopa.domain.ai_assistant import build_summary_prompt

        sample = [
            {"id": "art-x1", "artifact_type": "browser_history",
             "title": "navštívená stránka", "timestamp": "2026-03-01T10:00:00"},
        ]
        msgs = build_summary_prompt("C1", {"files": 42, "bytes": 999},
                                    {"browser_history": 7}, sample)
        user = msgs[1]["content"]
        assert "art-x1" in user and "navštívená stránka" in user
        assert "files: 42" in user and "browser_history: 7" in user

    def test_explain_prompt_includes_artifact_fields(self):
        from stopa.domain.ai_assistant import build_explain_prompt

        art = {"id": "art-x9", "artifact_type": "sms_message", "title": "zpráva",
               "rel_path": "msg.db", "timestamp": "2026-01-05T08:00:00",
               "confidence": 0.9, "anomaly_flags": ["future_time"],
               "details": {"address": "+4201"}}
        msgs = build_explain_prompt(art)
        user = msgs[1]["content"]
        for token in ("art-x9", "sms_message", "msg.db", "future_time", "+4201"):
            assert token in user


# ════════════════════════════════════════════════════════════════
# domain — parsování odpovědí
# ════════════════════════════════════════════════════════════════

class TestParseNlSearch:
    def test_plain_json(self):
        from stopa.domain.ai_assistant import parse_nl_search

        text = json.dumps({"query": "pdf size:>1MB", "explanation": "PDF větší než 1 MB",
                           "confidence": 0.85})
        query, explanation, confidence = parse_nl_search(text)
        assert query == "pdf size:>1MB"
        assert explanation == "PDF větší než 1 MB"
        assert confidence == pytest.approx(0.85)

    def test_fenced_json_with_prose_and_bad_confidence(self):
        from stopa.domain.ai_assistant import parse_nl_search

        text = ("Jistě, tady je dotaz:\n```json\n"
                '{"query": "heslo ext:txt", "explanation": "x", "confidence": 1.7}\n```\nHotovo.')
        query, _exp, confidence = parse_nl_search(text)
        assert query == "heslo ext:txt"
        assert confidence is None  # 1.7 mimo rozsah 0..1

    def test_missing_json_raises(self):
        from stopa.domain.ai_assistant import AiParseError, parse_nl_search

        with pytest.raises(AiParseError):
            parse_nl_search("žádný json tady není")


class TestExtractCitations:
    def test_validates_dedupes_and_cleans_text(self):
        from stopa.domain.ai_assistant import extract_citations

        text = ("Nalezeno [art:a1b2c3] a znovu [art:a1b2c3], "
                "neplatné [art:zzz999] i krátké [art:x].")
        clean, cited = extract_citations(text, {"a1b2c3", "d4e5f6"})
        assert cited == ["a1b2c3"]  # deduplikace + pořadí prvního výskytu
        assert "[art:" not in clean and "zzz999" not in clean

    def test_accepts_dict_of_valid_ids(self):
        from stopa.domain.ai_assistant import extract_citations

        text = "viz [art:aaa111] a [art:bbb222]"
        _clean, cited = extract_citations(text, {"aaa111": {}, "bbb222": {}})
        assert cited == ["aaa111", "bbb222"]


class TestParseConfidence:
    def test_variants(self):
        from stopa.domain.ai_assistant import parse_confidence

        assert parse_confidence('{"confidence": 0.7}') == pytest.approx(0.7)
        assert parse_confidence("confidence: 1") == 1.0
        assert parse_confidence("bez confidence") is None
        assert parse_confidence("confidence: 2.5") is None  # mimo rozsah


# ════════════════════════════════════════════════════════════════
# data — LM Studio klient (httpx.MockTransport, bez reálného serveru)
# ════════════════════════════════════════════════════════════════

def _install_mock(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Nahradí ``httpx.Client`` v modulu mock transportem (bez reálného serveru)."""
    import stopa.data.lmstudio_client as mod

    real_client_cls = httpx.Client  # zachytit PŘED patchem (sdílený modul)

    class _MockedClient:
        def __init__(self, *args, **kwargs):
            kwargs.pop("transport", None)
            self._inner = real_client_cls(transport=httpx.MockTransport(handler))

        def __enter__(self):
            return self._inner.__enter__()

        def __exit__(self, *a):
            return self._inner.__exit__(*a)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(mod.httpx, "Client", _MockedClient)


class TestLmStudioClient:
    def test_health_available_and_chat_uses_discovered_model(self, monkeypatch):
        from stopa.data.lmstudio_client import AiSettings, LmStudioClient

        calls: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "qwen-7b-instruct"}]})
            body = json.loads(request.content)
            calls.append(body)
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "odpověď"}}]}
            )

        _install_mock(monkeypatch, handler)
        client = LmStudioClient(AiSettings(base_url="http://mock/v1"))
        assert client.health() == {"available": True, "model": "qwen-7b-instruct"}
        out = client.chat([{"role": "user", "content": "a?"}])
        assert out == "odpověď"
        assert calls[0]["model"] == "qwen-7b-instruct"  # auto-discovery

    def test_health_offline_returns_unavailable(self, monkeypatch):
        from stopa.data.lmstudio_client import AiSettings, LmStudioClient

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        _install_mock(monkeypatch, handler)
        client = LmStudioClient(AiSettings(base_url="http://mock/v1"))
        assert client.health() == {"available": False, "model": None}

    def test_chat_connection_error_raises_unavailable(self, monkeypatch):
        from stopa.data.lmstudio_client import AiSettings, LmStudioClient, LmStudioUnavailable

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        _install_mock(monkeypatch, handler)
        client = LmStudioClient(AiSettings(base_url="http://mock/v1"))
        with pytest.raises(LmStudioUnavailable):
            client.chat([{"role": "user", "content": "a?"}])

    def test_chat_empty_content_raises_unavailable(self, monkeypatch):
        from stopa.data.lmstudio_client import AiSettings, LmStudioClient, LmStudioUnavailable

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "m1"}]})
            return httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]})

        _install_mock(monkeypatch, handler)
        client = LmStudioClient(AiSettings(base_url="http://mock/v1"))
        with pytest.raises(LmStudioUnavailable):
            client.chat([{"role": "user", "content": "a?"}])


# ════════════════════════════════════════════════════════════════
# web E2E — TestClient + syntetická case DB
# ════════════════════════════════════════════════════════════════

CASE_ID = "c1"


@pytest.fixture()
def ai_case_db(tmp_path: Path):
    """Case DB se 3 soubory (velký jpg, malý txt, pdf) + 2 artifacty."""
    from stopa.data.db import CaseDB
    from stopa.models import Artifact, FileRecord

    db = CaseDB(str(tmp_path / f"{CASE_ID}.db"))
    src_id = "src-e11"
    now = "2026-01-01T00:00:00"  # deterministické (bez utcnow → DTZ003)
    db.conn.execute(
        "INSERT INTO cases (id, name, created_at) VALUES (?, 'E11', ?)", (CASE_ID, now)
    )
    db.conn.execute(
        "INSERT INTO sources (id, case_id, kind, path, added_at)"
        " VALUES (?, ?, 'folder', '/tmp/e11', ?)",
        (src_id, CASE_ID, now),
    )
    db.conn.commit()

    def mkfile(name: str, size: int, mtime_iso: str, ext: str) -> FileRecord:
        rec = FileRecord(
            id=f"file-{name}", source_id=src_id, rel_path=name, name=name,
            size_bytes=size, mtime=mtime_iso,
            sha256=hashlib.sha256(name.encode()).hexdigest(), extension=ext,
        )
        db.upsert_file(rec)
        return rec

    big = mkfile("velky.jpg", 2 * 1024**2, "2026-03-10T12:00:00", "jpg")
    small = mkfile("maly.txt", 100, "2025-12-01T08:00:00", "txt")
    pdf = mkfile("dokument.pdf", 6 * 1024**2, "2026-05-20T15:30:00", "pdf")

    art1 = Artifact(
        id="art-x1", source_id=src_id, file_id=big.id, rel_path="velky.jpg",
        artifact_type="exif_photo", timestamp="2026-03-10T12:05:00",
        title="EXIF: fotograf JaneDoe", details={"author": "JaneDoe"}, confidence=0.9,
    )
    art2 = Artifact(
        id="art-x2", source_id=src_id, file_id=pdf.id, rel_path="dokument.pdf",
        artifact_type="pdf_metadata", timestamp=None, title="PDF autor: M.M.",
        details={"author": "M.M."}, confidence=0.6,
    )
    db.upsert_artifact(art1)
    db.upsert_artifact(art2)

    yield db, {"big": big, "small": small, "pdf": pdf}
    db.close()


@pytest.fixture()
def ai_client(ai_case_db: tuple, tmp_path: Path):
    from stopa.web.app import create_app

    return TestClient(create_app(db_dir=tmp_path))


class _FakeAiClient:
    """Nahrazení LmStudioClient — `response` se vrací pro každý chat()."""

    response = "default"

    def __init__(self, *a, **k) -> None:
        pass

    def health(self) -> dict:
        return {"available": True, "model": "fake-model"}

    def chat(self, messages, max_tokens=None) -> str:
        return self.response


def _patch_ai(monkeypatch: pytest.MonkeyPatch, response: str) -> None:
    import stopa.web.app as app_mod

    fake = type("Fake", (_FakeAiClient,), {"response": response})
    monkeypatch.setattr(app_mod, "LmStudioClient", fake)


class TestAiWebEndpoints:
    def test_status_offline_graceful(self, ai_client):
        """Bez LM Studio (mrtvý port) → available=False, ne chyba."""
        r = ai_client.get("/api/ai/status")
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"available", "model"}
        if not body["available"]:
            assert body["model"] is None

    def test_status_offline_dead_port(self, ai_client, monkeypatch):
        monkeypatch.setenv("STOPA_LMSTUDIO_URL", "http://127.0.0.1:9/v1")  # discard port
        body = ai_client.get("/api/ai/status").json()
        assert body == {"available": False, "model": None}

    def test_nl_search_e2e_returns_query_and_file_citations(self, ai_client, monkeypatch):
        _patch_ai(monkeypatch, json.dumps(
            {"query": "size:>1MB", "explanation": "Soubory větší než 1 MB", "confidence": 0.9}
        ))
        r = ai_client.post(f"/api/cases/{CASE_ID}/ai/query",
                           json={"mode": "nl_search", "question": "co je velké?"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["query"] == "size:>1MB"
        assert body["confidence"] == pytest.approx(0.9)
        cited_paths = {c["rel_path"] for c in body["citations"]}
        assert cited_paths == {"velky.jpg", "dokument.pdf"}  # maly.txt (100 B) vynechan
        assert all(c["file_id"].startswith("file-") for c in body["citations"])

    def test_summary_citations_validated_against_sample(self, ai_client, monkeypatch):
        _patch_ai(monkeypatch, "Případ obsahuje [art:art-x1] i falešné [art:nope99].")
        r = ai_client.post(f"/api/cases/{CASE_ID}/ai/query", json={"mode": "summary"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert "[art:" not in body["answer"]  # tokeny vyčištěné z textu
        assert [c["artifact_id"] for c in body["citations"]] == ["art-x1"]

    def test_explain_known_and_unknown_artifact(self, ai_client, monkeypatch):
        _patch_ai(monkeypatch, "EXIF metadata s autorem. [art:art-x1]")
        r = ai_client.post(f"/api/cases/{CASE_ID}/ai/query",
                           json={"mode": "explain", "artifact_id": "art-x1"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["citations"][0]["artifact_id"] == "art-x1"

        r404 = ai_client.post(f"/api/cases/{CASE_ID}/ai/query",
                              json={"mode": "explain", "artifact_id": "art-unknown"})
        assert r404.status_code == 404

    def test_unknown_mode_400(self, ai_client, monkeypatch):
        _patch_ai(monkeypatch, "{}")
        r = ai_client.post(f"/api/cases/{CASE_ID}/ai/query", json={"mode": "teleport"})
        assert r.status_code == 400
