"""F6.4 — Plugin ecosystem: manifest model + validace (čistá logika, bez I/O).

Plugin = adresář s ``plugin.json`` (manifest) a Python moduly. Manifest
deklaruje kapacity; kód se importuje až v data vrstvě (``data/plugin_loader.py``),
aby zůstala doména čistá.

Kontrakt pluginů zrcadlí vestavěnou infrastrukturu:

* **extractor** — modul s ``detect_fn(path) -> bool``,
  ``extract_fn(path) -> list[Artifact]`` a deklarováným ``parser_version``
  (F5.3 pattern pro verzi parseru); detekce podle magiky i/nebo extenze.
* **triage_profile** — modul s factory funkcí vracějící
  ``stopa.intelligence.triage.TriageProfile`` (frozen dataclass).
* **ai_tool** — modul s factory funkcí vracějící
  ``list[ToolSpec]`` (kontrakt F3.1 agent frameworku).

Sandbox: neověřený plugin neběží v hlavním procesu — data vrstva spustí
jeho entry point jako subprocess s limity z :class:`SandboxLimits`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from stopa.domain.integrity import sign_hash, verify_signature

#: Povolené znaky jména pluginu (lowercase slug)
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

#: Maximální počet kapacit jednoho typu na manifest (guard proti bloatu)
MAX_CAPS_PER_TYPE = 50


@dataclass(frozen=True)
class ExtractorSpec:
    """Jeden extractory pluginu.

    ``module`` je relativní modul uvnitř plugin adresáře (importuje se s
    rootem plugin adresáře na sys.path). ``detect_fn`` může být prázdný —
    pak detekce běží jen podle ``extensions`` (name-based fallback, viz
    pipeline `_name_based_match`).
    """

    key: str  # unikátní klíč uvnitř pluginu (namespace pro parser_version)
    module: str
    detect_fn: str = ""
    extract_fn: str = "extract_artifacts"
    parser_version: str = "1.0.0"
    extensions: tuple[str, ...] = ()


@dataclass(frozen=True)
class TriageProfileSpec:
    """Triage profil dodávaný pluginem (F3.2 kontrakt)."""

    module: str
    factory: str = "build_profile"  # funkce vrací TriageProfile


@dataclass(frozen=True)
class AiToolSpec:
    """AI tooly dodávané pluginem (F3.1 ToolSpec kontrakt)."""

    module: str
    factory: str = "build_tools"  # funkce vrací list[ToolSpec]


@dataclass(frozen=True)
class PluginManifest:
    """Validovaný manifest jednoho pluginu."""

    name: str
    version: str
    description: str = ""
    author: str = ""
    min_stopa_version: str = "2.0.0"
    extractors: tuple[ExtractorSpec, ...] = ()
    triage_profiles: tuple[TriageProfileSpec, ...] = ()
    ai_tools: tuple[AiToolSpec, ...] = ()

    @property
    def capabilities(self) -> list[str]:
        """Sekce s aspoň jednou kapacitou (pro UI/CLI přehled)."""
        caps = []
        if self.extractors:
            caps.append("extractor")
        if self.triage_profiles:
            caps.append("triage_profile")
        if self.ai_tools:
            caps.append("ai_tool")
        return caps


@dataclass(frozen=True)
class SandboxLimits:
    """Limity pro sandbox běh neověřeného pluginu (subprocess).

    P0-3 hardening: k RLIMIT_AS+wall-clock timeout přibyly CPU limit,
    omezení velikosti výstupu a volitelná síťová izolace (Linux unshare --net).
    """

    timeout_s: int = 120          # wall-clock strop (s)
    max_mem_mb: int = 512         # RLIMIT_AS — strop virtuální paměti (MB)
    cpu_seconds: int | None = 60  # RLIMIT_CPU — strop CPU času; None = bez limitu
    max_output_mb: int = 32       # strop stdout+stderr (MB); překrok → ValueError
    network_isolated: bool = False  # Linux: obal `unshare --net` (vyžaduje práva/user ns)
    extra_env: dict[str, str] = field(default_factory=dict)


def _version_tuple(v: str) -> tuple[int, ...]:
    """'2.1.3-rc1' → (2, 1, 3); nečíselné prefixy se ignorují."""
    parts: list[int] = []
    for chunk in v.split(".")[:4]:
        m = re.match(r"^(\d+)", chunk.strip())
        if not m:
            break
        parts.append(int(m.group(1)))
    return tuple(parts) or (0,)


def _require_str(data: dict, key: str, ctx: str) -> str:
    val = data.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ValueError(f"{ctx}: pole {key!r} musí být neprázdný string")
    return val.strip()


def _opt_str(data: dict, key: str, ctx: str, default: str = "") -> str:
    val = data.get(key, default)
    if not isinstance(val, str):
        raise TypeError(f"{ctx}: pole {key!r} musí být string")
    return val


def _opt_str_tuple(data: dict, key: str, ctx: str) -> tuple[str, ...]:
    val = data.get(key, [])
    if isinstance(val, str):
        val = (val,)
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise ValueError(f"{ctx}: pole {key!r} musí být seznam stringů")
    return tuple(val)


def parse_extractor_spec(raw: dict, ctx: str) -> ExtractorSpec:
    """Parse + validace jednoho extractor záznamu manifestu (typ nesoulad = TypeError)."""
    if not isinstance(raw, dict):
        raise TypeError(f"{ctx}: extractory musí být objekty")
    return ExtractorSpec(
        key=_require_str(raw, "key", ctx),
        module=_require_str(raw, "module", ctx),
        detect_fn=_opt_str(raw, "detect_fn", ctx),
        extract_fn=_opt_str(raw, "extract_fn", ctx, default="extract_artifacts"),
        parser_version=_opt_str(raw, "parser_version", ctx, default="1.0.0"),
        extensions=tuple(e.lower() for e in _opt_str_tuple(raw, "extensions", ctx)),
    )


def parse_triage_spec(raw: dict, ctx: str) -> TriageProfileSpec:
    """Parse + validace triage profile záznamu manifestu (typ nesoulad = TypeError)."""
    if not isinstance(raw, dict):
        raise TypeError(f"{ctx}: triage_profiles musí být objekty")
    return TriageProfileSpec(
        module=_require_str(raw, "module", ctx),
        factory=_opt_str(raw, "factory", ctx, default="build_profile"),
    )


def parse_ai_tool_spec(raw: dict, ctx: str) -> AiToolSpec:
    """Parse + validace ai tool záznamu manifestu (typ nesoulad = TypeError)."""
    if not isinstance(raw, dict):
        raise TypeError(f"{ctx}: ai_tools musí být objekty")
    return AiToolSpec(
        module=_require_str(raw, "module", ctx),
        factory=_opt_str(raw, "factory", ctx, default="build_tools"),
    )


def parse_manifest(data: object) -> PluginManifest:
    """Parse + validace manifestu z JSON slovníku.

    Chybová sémantika (F6.x konvence): TypeError pro typový nesoulad
    (objekt vs. seznam), ValueError pro chybějící/neprázdná pole — vždy
    s cestou pole v hlášce.
    """
    if not isinstance(data, dict):
        raise TypeError("manifest: očekáván JSON objekt")
    name = _require_str(data, "name", "manifest")
    if not NAME_RE.match(name):
        raise ValueError(
            f"manifest: jméno {name!r} nesplňuje formát (a-z 0-9 . _ -, 2–64 znaků)"
        )
    version = _require_str(data, "version", "manifest")

    def _caps_list(key: str) -> list[dict]:
        val = data.get(key, [])
        if isinstance(val, dict):
            val = [val]
        if not isinstance(val, list):
            raise TypeError(f"manifest: pole {key!r} musí být seznam")
        return val

    extractors_raw = _caps_list("extractors")[:MAX_CAPS_PER_TYPE]
    triage_raw = _caps_list("triage_profiles")[:MAX_CAPS_PER_TYPE]
    tools_raw = _caps_list("ai_tools")[:MAX_CAPS_PER_TYPE]

    extractors = tuple(
        parse_extractor_spec(r, f"manifest.extractors[{i}]")
        for i, r in enumerate(extractors_raw)
    )
    triage_profiles = tuple(
        parse_triage_spec(r, f"manifest.triage_profiles[{i}]")
        for i, r in enumerate(triage_raw)
    )
    ai_tools = tuple(parse_ai_tool_spec(r, f"manifest.ai_tools[{i}]") for i, r in enumerate(tools_raw))

    # unikátnost klíčů extractorů uvnitř pluginu
    keys = [e.key for e in extractors]
    if len(keys) != len(set(keys)):
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        raise ValueError(f"manifest: duplicitní klíče extractorů {dupes}")

    return PluginManifest(
        name=name,
        version=version,
        description=_opt_str(data, "description", "manifest"),
        author=_opt_str(data, "author", "manifest"),
        min_stopa_version=_opt_str(data, "min_stopa_version", "manifest", default="2.0.0"),
        extractors=extractors,
        triage_profiles=triage_profiles,
        ai_tools=ai_tools,
    )


def validate_manifest(m: PluginManifest, stopa_version: str) -> list[str]:
    """Semantická validace po parse; prázdný seznam = OK.

    Kontroluje kompatibilitu min_stopa_version a nenulový počet kapacit
    (plugin bez kapacit je platný jen jako stub — vráti upozornění).
    """
    issues: list[str] = []
    if _version_tuple(m.min_stopa_version) > _version_tuple(stopa_version):
        issues.append(
            f"min_stopa_version {m.min_stopa_version} > aktuální {stopa_version}"
        )
    if not m.capabilities:
        issues.append("plugin nedeklaruje žádné kapacity (extractors/triage_profiles/ai_tools)")
    return issues


def sandbox_limits(data: object) -> SandboxLimits:
    """Parse limitů sandboxu z settings slovníku (defaulty 120 s / 512 MB / 60 CPU s).

    P0-3: nové klíče ``cpu_seconds`` (None = bez limitu), ``max_output_mb``,
    ``network_isolated``. Typový nesoulad → TypeError, semantická chyba → ValueError
    (konzistentní s F6.4 manifest sémantikou).
    """
    if not isinstance(data, dict):
        data = {}
    timeout_s = int(data.get("timeout_s", 120))
    max_mem_mb = int(data.get("max_mem_mb", 512))
    cpu_raw = data.get("cpu_seconds", 60)
    if cpu_raw is not None:
        if isinstance(cpu_raw, bool) or not isinstance(cpu_raw, int):
            raise TypeError("sandbox.cpu_seconds musí být integer (nebo null)")
        if cpu_raw <= 0:
            raise ValueError("sandbox.cpu_seconds musí být kladné číslo")
    max_output_mb = data.get("max_output_mb", 32)
    if isinstance(max_output_mb, bool) or not isinstance(max_output_mb, int):
        raise TypeError("sandbox.max_output_mb musí být integer")
    if max_output_mb <= 0:
        raise ValueError("sandbox.max_output_mb musí být kladné číslo")
    net_raw = data.get("network_isolated", False)
    if not isinstance(net_raw, bool):
        raise TypeError("sandbox.network_isolated musí být boolean")
    extra_raw = data.get("extra_env", {})
    if not isinstance(extra_raw, dict):
        raise TypeError("sandbox.extra_env musí být objekt")
    return SandboxLimits(
        timeout_s=timeout_s,
        max_mem_mb=max_mem_mb,
        cpu_seconds=cpu_raw,
        max_output_mb=max_output_mb,
        network_isolated=net_raw,
        extra_env={str(k): str(v) for k, v in extra_raw.items()},
    )


# ---------------------------------------------------------------------------
# P2-7 — Plugin Marketplace: Ed25519 podpis + trust model (čistá doména)
# ---------------------------------------------------------------------------


def _manifest_canonical(m: PluginManifest) -> dict[str, Any]:
    """Kanonický tvar manifestu pro hashování (deterministické pole)."""
    return {
        "name": m.name,
        "version": m.version,
        "description": m.description,
        "author": m.author,
        "min_stopa_version": m.min_stopa_version,
        "extractors": [asdict(e) for e in m.extractors],
        "triage_profiles": [asdict(t) for t in m.triage_profiles],
        "ai_tools": [asdict(a) for a in m.ai_tools],
    }


def manifest_digest(m: PluginManifest) -> str:
    """Deterministický SHA-256 manifestu (kanonické JSON, seřazené klíče).

    Stejný manifest = stejný digest na jakékoli platformě a kdykoli —
    podklad pro podpis. Změna libovolného pole manifestu (i popisu) → jiný
    digest.
    """
    payload = json.dumps(
        _manifest_canonical(m), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sign_plugin(manifest: PluginManifest, private_b64: str) -> str:
    """Ed25519 podpis nad digested manifestem (base64)."""
    return sign_hash(private_b64, manifest_digest(manifest))


def verify_plugin_signature(public_b64: str, digest_hex: str, sig_b64: str) -> bool:
    """Ověří Ed25519 podpis proti danému digestu.

    Fail-closed: libovolně deformovaný vstup (ne base64, špatná délka…) →
    ``False``, nevyrábí výjimky — volající rozhoduje o exit kódu.
    """
    try:
        return verify_signature(public_b64, digest_hex, sig_b64)
    except Exception:  # noqa: BLE001 — fail-closed na deformovaný vstup
        return False


@dataclass(frozen=True)
class TrustDecision:
    """Rozhodnutí trust modelu marketplace.

    ``root_label`` = který pinovaný kořenový klíč podpis potvrdil; None =
    žádný z pinovaných kořenů nepodpisoval (neznámý podepsatel).
    """

    trusted: bool
    root_label: str | None = None


def check_trust(sig_b64: str, digest_hex: str, roots: Mapping[str, str]) -> TrustDecision:
    """Ověří podpis proti pinovaným kořenovým klíčům marketplace (offline).

    Kořeny se procházejí v deterministickém pořadí (seřazeno podle labelu) —
    při více platných podpisech vyhrává lexikálně první label. Prázdná sada
    nebo žádný shoda → :class:`TrustDecision` s ``trusted=False``.

    Trust model P2-7: marketplace root key + pinning — ověřitelné offline,
    bez sítě a bez CA hierarchie.
    """
    for label in sorted(roots):
        if verify_plugin_signature(roots[label], digest_hex, sig_b64):
            return TrustDecision(trusted=True, root_label=label)
    return TrustDecision(trusted=False)
