#!/usr/bin/env python3
"""B1 — verifikace pinu stopa_core wheels (verze + SHA-256) proti manifestu a pyproject.toml.

Zdroj pravdy pro URL/verzi je ``pyproject.toml`` (extra ``carving``); manifest
``.github/wheel_pins.json`` musí sedět s ním **obousobně** a doložit SHA-256
skutečných release assetů (fail-closed: jakákoli shoda/rozpor → exit ≠ 0).

Režimy:
    python scripts/verify_rust_wheel.py                 # plná kontrola (stahování obou platforem)
    python scripts/verify_rust_wheel.py --no-download   # offline: jen konzistence URL/pin
    python scripts/verify_rust_wheel.py --installed     # B4: fail-closed nainstalovaný aktivní core
    python scripts/verify_rust_wheel.py --update-manifest  # přegenerovat SHA-256 manifestu

Používá jen stdlib (urllib, tomllib) — běží i v minimálním CI prostředí.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as md
import json
import logging
import re
import sys
import urllib.request
from pathlib import Path
from typing import NoReturn

import tomllib

REPO = Path(__file__).resolve().parent.parent
_log = logging.getLogger("stopa.verify_rust_wheel")
MANIFEST_PATH = REPO / ".github" / "wheel_pins.json"
PYPROJECT_PATH = REPO / "pyproject.toml"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def fail(msg: str) -> NoReturn:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"OK:   {msg}")


def pyproject_carving_urls() -> list[str]:
    """URL wheels z extra ``carving`` v pyproject.toml (porad, bez markerů)."""
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    deps = data["project"]["optional-dependencies"].get("carving", [])
    urls: list[str] = []
    for dep in deps:
        if "@" not in dep:
            continue
        url = dep.split("@ ", 1)[1].split(" ;")[0].strip()
        urls.append(url)
    return urls


def load_manifest() -> dict:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"manifest {MANIFEST_PATH.name} nečitelný: {exc}")
    return manifest


def download_sha256(url: str) -> tuple[str, int]:
    """Streamované stažení → (sha256 hex, velikost v bytech)."""
    h = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(url, timeout=300) as resp:
        while chunk := resp.read(1 << 20):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def check_consistency(manifest: dict, urls: list[str]) -> None:
    """pyproject ↔ manifest obousobní shoda URL + pin/markery v každé URL."""
    version = manifest.get("version")
    if not isinstance(version, str) or not version:
        fail("manifest: chybí/křivé 'version'")
    wheels = manifest.get("wheels", {})
    if set(wheels) != {"x86_64", "aarch64"}:
        fail(f"manifest: očekávám klíče x86_64+aarch64, mám {sorted(wheels)}")
    man_urls = [w.get("url", "") for w in wheels.values()]
    if sorted(man_urls) != sorted(urls):
        fail(
            "URL se neshodují pyproject↔manifest:\n  pyproject: "
            + "\n   ".join(sorted(urls))
            + "\n  manifest:  "
            + "\n   ".join(sorted(man_urls))
        )
    for name, entry in wheels.items():
        url = entry.get("url", "")
        sha = entry.get("sha256", "")
        size = entry.get("size_bytes", 0)
        if f"/v{version}/" not in url:
            fail(f"{name}: URL nepíná release v{version}")
        for marker in ("cp310-abi3", "manylinux_2_28"):
            if marker not in url:
                fail(f"{name}: chybí marker {marker} v URL")
        if not _SHA256_RE.match(sha):
            fail(f"{name}: SHA-256 není 64hex: {sha!r}")
        if not isinstance(size, int) or size <= 0:
            fail(f"{name}: size_bytes nevalidní")
    ok(f"pyproject↔manifest konzistentní (pin v{version}, {len(urls)} wheels)")


def check_hashes(manifest: dict, platforms: list[str]) -> None:
    for name in platforms:
        entry = manifest["wheels"][name]
        actual_sha, actual_size = download_sha256(entry["url"])
        if actual_sha != entry["sha256"]:
            fail(f"{name}: SHA-256 mismatch — manifest {entry['sha256'][:16]}… ≠ stáhnuté {actual_sha[:16]}…")
        if actual_size != entry["size_bytes"]:
            fail(f"{name}: velikost mismatch — manifest {entry['size_bytes']} B ≠ stáhnuté {actual_size} B")
        ok(f"{name}: SHA-256 + velikost ověřeny ({actual_size} B)")


def _core_actual_version(mod) -> str:
    """Verze importovaného stopa_core — __version__ → dist metadata → rust_version()."""
    v = getattr(mod, "__version__", None)
    if isinstance(v, str) and v:
        return v
    try:
        return md.version("stopa-core")
    except md.PackageNotFoundError:  # metadata chybí (bezprostřední instalace wheelu) → další cesta
        _log.debug("dist metadata stopa-core nenalezeno, zkusím rust_version()")
    rv = getattr(mod, "rust_version", None)
    if callable(rv):
        try:
            return str(rv())
        except Exception as exc:  # noqa: BLE001 — probe verze nesmí skript zabít
            _log.debug("stopa_core.rust_version() selhalo: %s", exc)
    return "?"


def check_imported_core(manifest: dict) -> None:
    try:
        import stopa_core
    except ImportError:
        print("INFO: stopa_core neimportovatelné (čisté-Python fallback prostředí) — skip")
        return
    expected = manifest.get("core_version", "")
    actual = _core_actual_version(stopa_core)
    if actual != expected:
        fail(f"importovaná verze stopa_core {actual} ≠ manifest core_version {expected}")
    ok(f"importované stopa_core {actual} odpovídá manifestu")


def check_installed(manifest: dict) -> None:
    """B4 — fail-closed verifikace nainstalovaného (aktivního) stopa_core.

    Na rozdíl od ``check_imported_core`` (tolerantní INFO/skip pro čisté-Python
    fallback prostředí) zde MUSÍ být wheel importovatelné a jeho verze odpovídat
    manifestu — jinak prostředí není „s aktivním corem“ a gate má selhat.
    """
    expected = manifest.get("core_version", "")
    if not isinstance(expected, str) or not expected:
        fail("manifest: chybí/křivé 'core_version'")
    try:
        import stopa_core
    except ImportError as exc:
        fail(f"--installed: stopa_core neimportovatelné ({exc}) — extra [carving] nezafungovala?")
    actual = _core_actual_version(stopa_core)
    if actual != expected:
        fail(f"nainstalovaná verze stopa_core {actual} ≠ manifest core_version {expected}")
    try:
        from stopa.data import rust_core

        assert rust_core.is_available(), "stopa nainstalováno, ale loader hlásí fallback (wheel existuje)"
    except ImportError:
        _log.debug("stopa nenainstalováno — kontrola loaderu přeskočena")
    ok(f"nainstalované stopa_core {actual} odpovídá manifestu (aktivní core)")


def update_manifest(platforms: list[str]) -> None:
    urls = pyproject_carving_urls()
    if len(urls) != 2:
        fail(f"očekávám 2 carving URL v pyproject, mám {len(urls)}")
    m = re.search(r"/v(\d+\.\d+\.\d+)/", urls[0])
    if not m:
        fail("verze release nečitelná z URL")
    manifest = load_manifest()
    for name in platforms:
        url = next(u for u in urls if f"_{name}.whl" in u)
        sha, size = download_sha256(url)
        manifest["wheels"][name] = {"url": url, "sha256": sha, "size_bytes": size}
    manifest["version"] = m.group(1)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    ok(f"manifest přegenerován (v{m.group(1)}, platformy {platforms})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-download", action="store_true", help="offline režim — jen konzistence URL/pin")
    ap.add_argument(
        "--installed", action="store_true",
        help="B4: fail-closed kontrola nainstalovaného aktivního stopa_core (verze vs manifest)",
    )
    ap.add_argument(
        "--platforms", nargs="+", default=["x86_64", "aarch64"], choices=["x86_64", "aarch64"],
        help="platformy ke kontrole SHA-256 (default: obě)",
    )
    ap.add_argument("--update-manifest", action="store_true", help="přegenerovat SHA-256 manifestu ze stažených wheelů")
    args = ap.parse_args(argv)

    urls = pyproject_carving_urls()
    if not urls:
        fail("pyproject: extra 'carving' neobsahuje žádné URL wheels")
    manifest = load_manifest()
    check_consistency(manifest, urls)
    if args.installed:
        # B4 — aktivní-core prostředí (CI job test-active-core): fail-closed, offline, bez stahování
        check_installed(manifest)
        print("PASS: nainstalovaný aktivní core verifikován (--installed)")
        return 0
    if args.update_manifest:
        update_manifest(args.platforms)
        return 0
    if not args.no_download:
        check_hashes(manifest, args.platforms)
    else:
        ok("offline režim — SHA-256 stahování přeskočeno")
    check_imported_core(manifest)
    print("PASS: stopa_core pin verifikován")
    return 0


if __name__ == "__main__":
    sys.exit(main())
