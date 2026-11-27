"""STP-074 — deterministická reference datová sada pro parser ``net_connections``.

Dvě textové fixtury (pilot vlna 1 část B, design §7):

- ``netstat_ano.txt`` — Windows ``netstat -ano`` (Proto/Local/Foreign/State/PID),
- ``ss_an.txt``       — Unix ``ss`` (Netid State Recv-Q Send-Q Local Peer Process).

Determinismus: pevné adresy/porty/PID, LF řádky, UTF-8 bez BOM; SHA-256 pin
každé fixtury se zapisuje do manifestu (fail-fast proti driftu důkazu).

Golden ``expected_<fixture>.json`` = normalizované záznamy (§3 `domain/
differential.normalize_dataset`) referenční cesty — nezávislá STOPA cesta musí
produkovat byte-stejný tvar po JSON serializaci (E2E test STP-074).

Běh: ``python build_fixture.py [outdir]`` (výchozí = adresář tohoto skriptu).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

NETSTAT_ANO = """\
Active Connections


  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:*              LISTENING       792
  TCP    10.0.0.5:443           192.168.1.50:52114     ESTABLISHED     1844
  UDP    0.0.0.0:68             0.0.0.0:*                               4
  TCP    [::]:3389              [::]:*                     LISTENING       512
"""

SS_AN = """\
Netid State   Recv-Q Send-Q Local Address:Port Peer Address:Port Process
udp   UNCONN  0      0      127.0.0.53:53    0.0.0.0:*
tcp   LISTEN  0      4096   *:22             *:*                     users:(("sshd",pid=2001,fd=3))
tcp   ESTAB   0      0      10.0.0.5:51872   192.168.1.4:22          users:(("ssh",pid=2044,fd=5))
udp   UNCONN  0      0      0.0.0.0:68       0.0.0.0:*
"""

FIXTURES: dict[str, str] = {
    "netstat_ano.txt": NETSTAT_ANO,
    "ss_an.txt": SS_AN,
}


def build(outdir: Path) -> None:
    """Vytvoří fixtury + manifest (SHA-256 piny) + goldeny normalizovaných záznamů."""
    from stopa.diffref.text_ref import load_text_manifest, read_reference_entries
    from stopa.domain.differential import JoinKeySpec, normalize_dataset

    outdir.mkdir(parents=True, exist_ok=True)
    pins: dict[str, str] = {}
    for name, content in FIXTURES.items():
        data = content.encode("utf-8")  # LF řádky, bez BOM — deterministicky
        (outdir / name).write_bytes(data)
        pins[name] = hashlib.sha256(data).hexdigest()

    manifest = {
        "version": 1,
        "parser_id": "net_connections",
        "reference_tool": (
            "diffref-text-stdlib/1.0 (hand-written line parsers: "
            "windows_netstat_ano + unix_ss)"
        ),
        # Netstat/ss = snapshot bez časového razítka — na obou cestách ts=None
        # → po normalizaci ts_epoch=null (§3).
        "time_note": "no timestamps in netstat/ss output; both sides emit ts=None",
        "field_contract": (
            "proto=uppercase; local/remote='addr:port' (port absent -> bare address, "
            "IPv6 keeps brackets); remote '*' without port stays '*', empty address "
            "-> '(broadcast)'; state/pid are explicit None when missing"
        ),
        # Identita spojení = proto+local+remote; stav a PID jsou obsahová pole.
        "join_keys": {"network_connection": ["proto", "local", "remote"]},
        "fixtures": [
            {
                "file": name,
                "sha256": pins[name],
                "variant": "windows_netstat_ano" if name == "netstat_ano.txt" else "unix_ss",
            }
            for name in FIXTURES
        ],
    }
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )

    # Goldeny: referenční cesta → sdílená normalizační vrstva (§3) → JSON.
    validated = load_text_manifest(outdir / "manifest.json")
    join_spec: dict[str, JoinKeySpec] = {
        artifact_type: tuple(fields) for artifact_type, fields in manifest["join_keys"].items()
    }
    for name in FIXTURES:
        entries = read_reference_entries(outdir / name, validated)
        records = normalize_dataset(entries, join_keys=join_spec)
        # fields je mappingproxy — asdict() selže; explicitní serializace tvaru golden.
        payload = [
            {"type": record.type, "ts_epoch": record.ts_epoch, "fields": dict(record.fields)}
            for record in records
        ]
        golden = outdir / f"expected_{name.removesuffix('.txt')}.json"
        golden.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(
        "STP-074 reference dataset: "
        + ", ".join(f"{k}={v[:12]}…" for k, v in pins.items())
        + f" — {len(FIXTURES)} fixtur, goldeny OK ({outdir})"
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    build(target)
