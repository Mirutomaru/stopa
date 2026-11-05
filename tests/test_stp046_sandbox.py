"""STP-046 / ETAPA E vlna 1 — testy parser sandbox kontraktu.

Pokrývají: validaci ``SandboxConfig``, strukturální validaci payloadu,
konstrukci argv dceřiného procesu, klasifikaci selhání (priorita) a E2E běhy
``run_extractor_sandboxed()`` přes REÁLNÝ subprocess s dočasnými worker moduly
(hang → timeout, výjimka → crash, špatný payload → bad_payload, velký výsledek
→ truncated). Vše offline a deterministické (timeouty < 2 s).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from stopa.domain.sandbox import (
    CATEGORY_BAD_PAYLOAD,
    CATEGORY_CRASH,
    CATEGORY_TIMEOUT,
    CATEGORY_TRUNCATED,
    SandboxConfig,
    SandboxPayloadError,
    build_worker_command,
    failure_category,
    run_extractor_sandboxed,
    sandbox_available,
    validate_artifact_payload,
)

# ---------------------------------------------------------------------------
# SandboxConfig — validace limitů
# ---------------------------------------------------------------------------


def test_config_defaults():
    cfg = SandboxConfig()
    assert cfg.timeout_s > 0
    assert cfg.max_result_bytes >= 1


@pytest.mark.parametrize("timeout", [0, -1])
def test_config_timeout_must_be_positive(timeout):
    with pytest.raises(ValueError, match="timeout_s"):
        SandboxConfig(timeout_s=timeout)


def test_config_max_result_bytes_must_be_at_least_one():
    with pytest.raises(ValueError, match="max_result_bytes"):
        SandboxConfig(max_result_bytes=0)


# ---------------------------------------------------------------------------
# validate_artifact_payload — strukturální validace JSON kontraktu
# ---------------------------------------------------------------------------


def test_validate_valid_payload():
    payload = [
        {"artifact_type": "browser_history", "title": "x"},
        {"artifact_type": "chat_message"},
    ]
    assert validate_artifact_payload(payload) == payload


def test_validate_empty_list_ok():
    assert validate_artifact_payload([]) == []


def test_validate_rejects_non_list():
    with pytest.raises(SandboxPayloadError, match="array"):
        validate_artifact_payload({"artifact_type": "x"})


def test_validate_rejects_non_dict_item():
    with pytest.raises(SandboxPayloadError, match="položka 0"):
        validate_artifact_payload(["string"])


@pytest.mark.parametrize("item", [{"title": "x"}, {"artifact_type": ""}, {"artifact_type": 5}])
def test_validate_rejects_missing_or_empty_artifact_type(item):
    with pytest.raises(SandboxPayloadError, match="artifact_type"):
        validate_artifact_payload([item])


# ---------------------------------------------------------------------------
# build_worker_command — argv dceřiného procesu
# ---------------------------------------------------------------------------


def test_build_worker_command_default_python():
    cmd = build_worker_command("stopa.artifacts.sqlite_recover", "recover_deleted_rows", "/tmp/x.db")
    assert cmd[0] == sys.executable
    assert cmd[1:] == ["-m", "stopa.sandbox_worker", "stopa.artifacts.sqlite_recover",
                       "recover_deleted_rows", "/tmp/x.db"]


def test_build_worker_command_custom_python():
    cmd = build_worker_command("mod", "fn", Path("/data/file.bin"), python="/usr/bin/python3")
    assert cmd[0] == "/usr/bin/python3"
    assert cmd[-1] == "/data/file.bin"


# ---------------------------------------------------------------------------
# failure_category — klasifikace s prioritou timeout > truncated > bad_payload > crash
# ---------------------------------------------------------------------------


def test_failure_category_priority():
    # timeout má přednost před vším ostatním
    assert failure_category(True, True, True, 1) == CATEGORY_TIMEOUT
    # truncated před bad_payload a crashem
    assert failure_category(False, True, True, 0) == CATEGORY_TRUNCATED
    # bad_payload před crashem
    assert failure_category(False, False, True, 1) == CATEGORY_BAD_PAYLOAD
    # jen crash (returncode != 0 bez ostatních flagů)
    assert failure_category(False, False, False, 3) == CATEGORY_CRASH


# ---------------------------------------------------------------------------
# sandbox_available — backend detekce
# ---------------------------------------------------------------------------


def test_sandbox_worker_module_discoverable():
    assert sandbox_available() is True


# ---------------------------------------------------------------------------
# E2E: run_extractor_sandboxed přes reálný subprocess s dočasnými moduly
# ---------------------------------------------------------------------------

HANG_MODULE = """
import time


def hang(path):
    time.sleep(5)
    return []
"""

CRASH_MODULE = """
def boom(path):
    raise ValueError("parser explodoval")
"""

BAD_PAYLOAD_MODULE = """
class Fake:
    def model_dump(self, mode=None):
        return {"title": "bez artifact_type"}


def bad(path):
    return [Fake()]
"""

TRUNCATED_MODULE = """
class Big:
    def model_dump(self, mode=None):
        return {"artifact_type": "t", "details": {"pad": "x" * 200}}


def big(path):
    return [Big()]
"""


@pytest.fixture()
def worker_mod(tmp_path):
    """Dočasný importovatelný modul (PYTHONPATH) pro sandbox worker."""

    def _make(name: str, source: str) -> dict[str, str]:
        mod_file = tmp_path / f"{name}.py"
        mod_file.write_text(source, encoding="utf-8")
        return {"PYTHONPATH": str(tmp_path)}

    return _make


def test_e2e_success_empty_artifacts(worker_mod):
    """Reálný extraktor (sqlite_recover) na ne-SQLite souboru → ok + []."""
    src = Path("/tmp/stopa_sandbox_plain.txt")
    src.write_text("hello world", encoding="utf-8")
    res = run_extractor_sandboxed(
        "stopa.artifacts.sqlite_recover", "recover_deleted_rows", src,
        config=SandboxConfig(timeout_s=10),
    )
    assert res.ok is True
    assert res.category is None
    assert res.error is None
    assert res.artifacts == ()


def test_e2e_timeout(worker_mod):
    env = worker_mod("sb_hang", HANG_MODULE)
    res = run_extractor_sandboxed(
        "sb_hang", "hang", "/tmp/x", config=SandboxConfig(timeout_s=0.5), env_extra=env,
    )
    assert res.ok is False
    assert res.category == CATEGORY_TIMEOUT
    assert "timeout" in (res.error or "")


def test_e2e_crash(worker_mod):
    env = worker_mod("sb_crash", CRASH_MODULE)
    res = run_extractor_sandboxed(
        "sb_crash", "boom", "/tmp/x", config=SandboxConfig(timeout_s=10), env_extra=env,
    )
    assert res.ok is False
    assert res.category == CATEGORY_CRASH
    assert "ValueError" in (res.error or "")


def test_e2e_bad_payload(worker_mod):
    env = worker_mod("sb_bad", BAD_PAYLOAD_MODULE)
    res = run_extractor_sandboxed(
        "sb_bad", "bad", "/tmp/x", config=SandboxConfig(timeout_s=10), env_extra=env,
    )
    assert res.ok is False
    assert res.category == CATEGORY_BAD_PAYLOAD


def test_e2e_truncated(worker_mod):
    env = worker_mod("sb_big", TRUNCATED_MODULE)
    res = run_extractor_sandboxed(
        "sb_big", "big", "/tmp/x", config=SandboxConfig(timeout_s=10, max_result_bytes=50),
        env_extra=env,
    )
    assert res.ok is False
    assert res.category == CATEGORY_TRUNCATED


def test_e2e_missing_module_is_crash(tmp_path):
    """Neexistující modul → ImportError v workeru → crash (ne výjimka nahoru)."""
    res = run_extractor_sandboxed(
        "sb_neexistuje", "fn", "/tmp/x", config=SandboxConfig(timeout_s=10),
        env_extra={"PYTHONPATH": str(tmp_path)},
    )
    assert res.ok is False
    assert res.category == CATEGORY_CRASH
