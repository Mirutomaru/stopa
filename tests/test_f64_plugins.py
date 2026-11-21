"""F6.4 — plugin ekosystém: manifest doména, loader/sandbox, ukázkové pluginy, CLI/Web E2E.

Pokrytí AK F6.4: 3 ukázkové pluginy; API dokumentace (docs/PLUGINS_API.md);
sandbox běh neověřených pluginů. Testy offline (tmp_path + repositářové plugins/).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from stopa.data.plugin_loader import (
    discover_plugins,
    resolve_ai_tools,
    resolve_extractors,
    resolve_triage_profiles,
    sandbox_exec,
)
from stopa.domain.plugins import (
    manifest_digest,
    parse_manifest,
    sandbox_limits,
    validate_manifest,
)

REPO_PLUGINS = Path(__file__).resolve().parent.parent / "plugins"


def _manifest(name: str = "test-plugin", version: str = "1.0.0", **caps):
    return {"name": name, "version": version, **caps}


# ── Doména: manifest parsing (čistá logika) ───────────────


def test_parse_manifest_minimal():
    m = parse_manifest(_manifest())
    assert m.name == "test-plugin" and m.version == "1.0.0"
    assert m.min_stopa_version == "2.0.0"  # default dle API kontraktu
    assert list(m.capabilities) == []


def test_parse_manifest_full_capabilities():
    raw = _manifest(
        description="popis",
        author="STOPA team",
        min_stopa_version="1.9.0",
        extractors=[{"key": "acc", "module": "mod_a"}],
        triage_profiles=[{"factory": "build_profile", "module": "mod_b"}],
        ai_tools=[{"factory": "build_tools", "module": "mod_c"}],
    )
    m = parse_manifest(raw)
    assert m.description == "popis" and m.author == "STOPA team"
    assert m.min_stopa_version == "1.9.0"
    e = m.extractors[0]
    assert e.key == "acc" and e.module == "mod_a" and e.detect_fn == ""  # detect je volitelná
    t = m.triage_profiles[0]
    assert t.factory == "build_profile" and t.module == "mod_b"
    a = m.ai_tools[0]
    assert a.factory == "build_tools" and a.module == "mod_c"
    assert set(m.capabilities) == {"extractor", "triage_profile", "ai_tool"}


def test_parse_manifest_extractor_defaults():
    e = parse_manifest(_manifest(extractors=[{"key": "k", "module": "m"}])).extractors[0]
    # fixní kontrakt dle PLUGINS_API.md: entry point + deklarovaná verze parseru
    assert e.extract_fn == "extract_artifacts"
    assert e.parser_version == "1.0.0"


@pytest.mark.parametrize(
    "bad", ["UPPER", "x", "-lead", "a" * 65, "with space", "", "a"*1 + "-"*64],
)
def test_name_format_invalid(bad):
    with pytest.raises(ValueError):
        parse_manifest(_manifest(name=bad))


@pytest.mark.parametrize("good", ["abc", "a.b-c_1", "plugin-x.y"])
def test_name_format_valid(good):
    assert parse_manifest(_manifest(name=good)).name == good


def test_missing_required_raises_valueerror():
    with pytest.raises(ValueError):
        parse_manifest({"version": "1.0.0"})  # chybí name
    with pytest.raises(ValueError):
        parse_manifest(_manifest(version=""))  # prázdná verze


@pytest.mark.parametrize(
    "raw",
    [
        ["list", "místo", "dict"],
        _manifest(extractors=["string"]),     # položka extractors není dict
        _manifest(description=42),            # description není str
    ],
)
def test_type_mismatch_raises_typeerror(raw):
    with pytest.raises(TypeError):
        parse_manifest(raw)


def test_required_field_wrong_type_valueerror():
    # _require_str: ne-string name/version → ValueError (neprázdný string)
    with pytest.raises(ValueError):
        parse_manifest({"name": 5, "version": "1"})


def test_duplicate_extractor_keys_raise():
    raw = _manifest(
        extractors=[{"key": "dup", "module": "a"}, {"key": "dup", "module": "b"}]
    )
    with pytest.raises(ValueError):
        parse_manifest(raw)


def test_max_caps_truncated():
    raw = _manifest(extractors=[{"key": f"k{i}", "module": "m"} for i in range(51)])
    m = parse_manifest(raw)  # guard: max 50 na kapacity, bez výjimky
    assert len(m.extractors) == 50


def test_validate_min_version_issue():
    m = parse_manifest(_manifest(min_stopa_version="3.0.0"))
    issues = validate_manifest(m, "2.0.0")
    assert any("min_stopa_version" in i for i in issues)
    # stejná nebo starší minimální verze → bez issue
    m2 = parse_manifest(_manifest(min_stopa_version="1.9.3"))
    assert all("min_stopa_version" not in i for i in validate_manifest(m2, "2.0.0"))


def test_validate_min_version_rc_suffix():
    # rc suffix se ignoruje při srovnání (2.1.3-rc1 > 2.1)
    m = parse_manifest(_manifest(min_stopa_version="2.1.3-rc1"))
    issues = validate_manifest(m, "2.1")
    assert any("min_stopa_version" in i for i in issues)


def test_validate_no_caps_warning():
    issues = validate_manifest(parse_manifest(_manifest()), "2.0.0")
    assert len(issues) == 1 and "žádné kapacity" in issues[0]


# ── Doména: P4-3 plugin API verzirování (api_version) ─────


def test_parse_manifest_api_version_default():
    """P4-3: chybějící api_version → výchozí "1", bez upozornění."""
    m = parse_manifest(_manifest())
    assert m.api_version == "1"
    assert all("api_version" not in i for i in validate_manifest(m, "2.0.0"))


def test_validate_api_version_matrix():
    """P4-3 AK: 1 → akcept; mimo rozsah / nečíselné → upozornění (ne odmítnutí)."""
    ok = parse_manifest(_manifest(api_version="1"))
    assert all("api_version" not in i for i in validate_manifest(ok, "2.0.0"))
    future = parse_manifest(_manifest(api_version="2"))
    assert any(
        "api_version" in i and "rozsah" in i for i in validate_manifest(future, "2.0.0")
    )
    below = parse_manifest(_manifest(api_version="0"))
    assert any(
        "api_version" in i and "rozsah" in i for i in validate_manifest(below, "2.0.0")
    )
    non_numeric = parse_manifest(_manifest(api_version="x1"))
    assert any(
        "api_version" in i and "celé číslo" in i
        for i in validate_manifest(non_numeric, "2.0.0")
    )


@pytest.mark.parametrize("bad", [5, True, ["1"], None])
def test_parse_manifest_api_version_wrong_type(bad):
    """P4-3: typový nesoulad = TypeError (konzistentní s F6.4 manifest sémantikou)."""
    with pytest.raises(TypeError):
        parse_manifest(_manifest(api_version=bad))


def test_digest_sensitive_to_api_version():
    """P4-3: api_version je součást podepsaného kontraktu → digest + determinismus."""
    base = manifest_digest(parse_manifest(_manifest()))
    assert base == manifest_digest(parse_manifest(_manifest()))  # deterministický
    other = manifest_digest(parse_manifest(_manifest(api_version="2")))
    assert other != base


# ── Doména: sandbox limity ────────────────────────────────


def test_sandbox_limits_defaults():
    l = sandbox_limits(None)
    assert (l.timeout_s, l.max_mem_mb, l.extra_env) == (120, 512, {})


def test_sandbox_limits_custom_and_invalid():
    l = sandbox_limits({"timeout_s": 5, "max_mem_mb": 64, "extra_env": {"A": "b"}})
    assert (l.timeout_s, l.max_mem_mb, l.extra_env) == (5, 64, {"A": "b"})
    with pytest.raises(TypeError):
        sandbox_limits({"extra_env": "ne-dict"})


# ── Loader: discovery (tmp_path + repositářové pluginy) ───


def test_discover_real_sample_plugins():
    found = discover_plugins(dirs=[REPO_PLUGINS], settings={}, stopa_version="2.0.0")
    assert set(found) == {
        "example-accesslog",
        "example-crypto-triage",
        "example-ai-tool",
    }
    caps = {k: tuple(v.capabilities) for k, v in found.items()}
    assert caps["example-accesslog"] == ("extractor",)
    assert caps["example-crypto-triage"] == ("triage_profile",)
    assert caps["example-ai-tool"] == ("ai_tool",)
    # ukázkové pluginy musí mít validní manifesty bez issues (verze 2.0.0 OK)
    for p in found.values():
        assert not p.issues, f"{p.name}: {p.issues}"


def test_discover_exposes_api_version(tmp_path):
    """P4-3: discover průchodem api_version z manifestu (explicitní deklarace)."""
    d = tmp_path / "api-explicit"
    d.mkdir()
    (d / "plugin.json").write_text(
        json.dumps(_manifest(name="api-explicit", api_version="1")), encoding="utf-8"
    )
    found = discover_plugins(dirs=[tmp_path], settings={}, stopa_version="2.0.0")
    assert found["api-explicit"].api_version == "1"


def test_discover_verified_allowlist():
    settings = {"plugins_verified": ["example-accesslog"]}
    found = discover_plugins(dirs=[REPO_PLUGINS], settings=settings, stopa_version="2.0.0")
    assert found["example-accesslog"].verified is True
    assert found["example-crypto-triage"].verified is False


def test_discover_first_wins_collision(tmp_path):
    root_a = tmp_path / "rootA"
    root_b = tmp_path / "rootB"
    for root, ver in ((root_a, "1.0.0"), (root_b, "2.0.0")):
        d = root / "dup"
        d.mkdir(parents=True)
        (d / "plugin.json").write_text(
            json.dumps({"name": "dup-plugin", "version": ver}), encoding="utf-8"
        )
    found = discover_plugins(dirs=[root_a, root_b], settings={}, stopa_version="2.0.0")
    assert set(found) == {"dup-plugin"}
    assert found["dup-plugin"].version == "1.0.0"  # první výhra


def test_discover_broken_manifest_no_crash(tmp_path):
    (tmp_path / "bad-json").mkdir()
    (tmp_path / "bad-json" / "plugin.json").write_text("{oops", encoding="utf-8")
    (tmp_path / "no-name").mkdir()
    (tmp_path / "no-name" / "plugin.json").write_text(
        json.dumps({"version": "1.0.0"}), encoding="utf-8"
    )
    found = discover_plugins(dirs=[tmp_path], settings={}, stopa_version="2.0.0")
    # poškozený manifest = issues záznam, ne selhání celého skenu
    assert set(found) == {"bad-json", "no-name"}
    for p in found.values():
        assert p.version == "0.0.0" and not p.verified and len(p.issues) == 1


# ── Ukázkové pluginy: chování přes reálné resolvers ───────

ACCESSLOG_LINES = [
    '192.168.1.10 - alice [17/Nov/2026:10:00:00 +0100] "GET /index.html HTTP/1.1" 200 532',
    '192.168.1.10 - alice [17/Nov/2026:10:05:11 +0100] "GET /index.html HTTP/1.1" 404 211',
    '10.0.0.5 - - [17/Nov/2026:11:30:00 +0100] "POST /api/login HTTP/1.1" 302 0',
]


@pytest.fixture()
def accesslog_file(tmp_path):
    f = tmp_path / "access.log"
    f.write_text("\n".join(ACCESSLOG_LINES) + "\n", encoding="utf-8")
    return f


def _resolved_accesslog():
    manifest = parse_manifest(
        json.loads((REPO_PLUGINS / "example-accesslog" / "plugin.json").read_text())
    )
    exts = resolve_extractors(REPO_PLUGINS / "example-accesslog", manifest.name, manifest.extractors)
    assert len(exts) == 1 and exts[0].spec.key == "accesslog"
    return exts[0]


def test_accesslog_detection_and_extraction(accesslog_file, tmp_path):
    r = _resolved_accesslog()
    assert r.detect_fn is not None and r.detect_fn(accesslog_file) is True

    arts = r.extract_fn(accesslog_file)
    by_title = {a.title: a for a in arts}
    # agregace per (ip, method, path): 2× GET /index.html + 1× POST /api/login
    assert len(arts) == 2
    grp = by_title["Access log: 2× GET /index.html"]
    assert grp.artifact_type == "event_log_entry"
    assert grp.parser_version == "1.0.0"
    assert grp.details["count"] == 2 and grp.details["statuses"] == [200, 404]
    # +0100 → UTC konverze (forenzní determinismus)
    assert str(grp.details["first_ts"]).startswith("2026-11-17T09:00:00")

    neg = tmp_path / "neg.txt"
    neg.write_text("hello world\nfoo bar\nggg\n", encoding="utf-8")
    assert r.detect_fn(neg) is False and r.extract_fn(neg) == []


def test_accesslog_max_groups_cap(tmp_path):
    f = tmp_path / "big.log"
    lines = [
        f'10.0.{i // 256}.{i % 256} - - [17/Nov/2026:10:00:00 +0100] '
        f'"GET /p{i} HTTP/1.1" 200 1'
        for i in range(600)
    ]
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    arts = _resolved_accesslog().extract_fn(f)
    assert len(arts) == 500  # MAX_GROUPS kapce


def test_crypto_triage_profile():
    manifest = parse_manifest(
        json.loads((REPO_PLUGINS / "example-crypto-triage" / "plugin.json").read_text())
    )
    profiles = resolve_triage_profiles(
        REPO_PLUGINS / "example-crypto-triage", manifest.name, manifest.triage_profiles
    )
    assert len(profiles) == 1
    prof = profiles[0]
    assert prof.key == "crypto_exfiltration"
    assert prof.title == "Exfiltrace kryptomajetku"
    assert len(prof.signals) == 4
    assert all(s.weight > 0 for s in prof.signals)


def test_ai_tool_spec_and_handler():
    manifest = parse_manifest(
        json.loads((REPO_PLUGINS / "example-ai-tool" / "plugin.json").read_text())
    )
    tools = resolve_ai_tools(REPO_PLUGINS / "example-ai-tool", manifest.name, manifest.ai_tools)
    assert [t.name for t in tools] == ["artifact_type_breakdown"]
    handler = tools[0].handler

    fake_db = SimpleNamespace(
        list_artifacts=lambda limit=None: (
            [SimpleNamespace(artifact_type=t) for t in ("a", "b", "a")][:limit]
            if limit is not None else []
        )
    )
    out = handler(fake_db, "case-x", {})  # default limit 2000
    assert out["total_scanned"] == 3 and out["truncated"] is False
    assert out["by_type"] == {"a": 2, "b": 1}  # deterministické řazení

    from stopa.intelligence.tool_agent import ToolError

    with pytest.raises(ToolError):
        handler(fake_db, "case-x", {"limit": 0})
    with pytest.raises(ToolError):
        handler(fake_db, "case-x", {"limit": 10_001})


# ── Sandbox: subprocess běh neověřených pluginů ────────────


@pytest.fixture()
def plugins_env(monkeypatch):
    monkeypatch.setenv("STOPA_PLUGINS_DIR", str(REPO_PLUGINS))


def test_sandbox_exec_triage_profile(plugins_env):
    payload = sandbox_exec(["example-crypto-triage", "--cap", "triage_profile"])
    assert payload.get("ok") is True
    # profily putovají JSON-safe (profile_to_dict) — klíč musí být v serializaci
    assert "crypto_exfiltration" in json.dumps(payload["result"], ensure_ascii=False)


def test_sandbox_exec_extractor(plugins_env, accesslog_file):
    payload = sandbox_exec(
        [
            "example-accesslog",
            "--cap", "extractor",
            "--key", "accesslog",
            "--file", str(accesslog_file),
        ]
    )
    assert payload.get("ok") is True
    dump = json.dumps(payload["result"], ensure_ascii=False)
    assert "event_log_entry" in dump and "Access log:" in dump


def test_sandbox_timeout(tmp_path, monkeypatch):
    d = tmp_path / "slow-plugin"
    d.mkdir()
    (d / "plugin.json").write_text(
        json.dumps(_manifest(name="slow-plugin", extractors=[{"key": "k", "module": "m"}])),
        encoding="utf-8",
    )
    (d / "m.py").write_text(
        "import time\n"
        "def extract_artifacts(path):\n"
        "    time.sleep(3)\n"
        "    return []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STOPA_PLUGINS_DIR", str(tmp_path))
    f = tmp_path / "in.log"
    f.write_text("x\ny\nz\n", encoding="utf-8")
    with pytest.raises(ValueError, match="timeout"):
        sandbox_exec(
            ["slow-plugin", "--cap", "extractor", "--key", "k", "--file", str(f)],
            limits=sandbox_limits({"timeout_s": 1}),
        )


def test_sandbox_child_error_unknown_plugin(plugins_env):
    with pytest.raises(ValueError, match="nenalezen"):
        sandbox_exec(["neexistujici-plugin", "--cap", "triage_profile"])


# ── CLI E2E (in-process main) ─────────────────────────────


@pytest.fixture()
def cli_env(monkeypatch, tmp_path):
    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    monkeypatch.setenv("STOPA_PLUGINS_DIR", str(REPO_PLUGINS))
    return tmp_path


def test_cli_plugin_list_json(cli_env, capsys):
    from stopa.cli import main

    rc = main(["plugin", "list", "--json"])
    assert rc == 0
    env_data = json.loads(capsys.readouterr().out)
    assert env_data["ok"] is True and env_data["count"] == 3
    names = {p["name"] for p in env_data["plugins"]}
    assert names == {"example-accesslog", "example-crypto-triage", "example-ai-tool"}
    # P4-3: api_version v JSON payloadi (ukázkové pluginy bez explicitního pole → default)
    assert all(p["api_version"] == "1" for p in env_data["plugins"])


def test_cli_plugin_verify_add_remove(cli_env):
    from stopa.cli import main

    assert main(["plugin", "verify", "example-accesslog", "--add"]) == 0
    settings = json.loads((cli_env / "settings.json").read_text(encoding="utf-8"))
    assert settings["plugins_verified"] == ["example-accesslog"]

    assert main(["plugin", "verify", "example-accesslog", "--remove"]) == 0
    settings = json.loads((cli_env / "settings.json").read_text(encoding="utf-8"))
    assert settings["plugins_verified"] == []
    # druhý remove bez položky → rc 1 (idempotentní hlášení)
    assert main(["plugin", "verify", "example-accesslog", "--remove"]) == 1


def test_cli_plugin_run_extractor_sandbox(cli_env, accesslog_file, capsys):
    from stopa.cli import main

    rc = main(
        [
            "plugin", "run", "example-accesslog",
            "--cap", "extractor", "--key", "accesslog",
            "--file", str(accesslog_file),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    # neověřený plugin → sandbox režim + reálné artefakty ve výstupu
    assert "sandbox" in out and "event_log_entry" in out


# ── Web E2E: GET /api/plugins ─────────────────────────────


def test_web_api_plugins(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from stopa.web.app import create_app

    monkeypatch.setenv("STOPA_PLUGINS_DIR", str(REPO_PLUGINS))
    app = create_app(db_dir=tmp_path)
    with TestClient(app) as c:
        r = c.get("/api/plugins")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True and data["count"] == 3
    names = {p["name"] for p in data["plugins"]}
    assert names == {"example-accesslog", "example-crypto-triage", "example-ai-tool"}
    # bez allowlistu v settings → žádné ověřené pluginy
    assert all(p["verified"] is False for p in data["plugins"])
    # P4-3: api_version i ve Web payloadi (default "1")
    assert all(p["api_version"] == "1" for p in data["plugins"])
