"""F1.3 — Síťová forenzika: Scapy PCAP integrace (ROADMAP V2 Fáze 1).

Pokrývá:
  * domain ``net_forensics`` — FlowKey kanonizace, TCP reassembly (seřazení po
    seq, gap explicitní), HTTP/FTP/SMB extrakce, IoC rules (min. 5 patternů:
    dns_tunneling / c2_beaconing / suspicious_url_path / base64_blob_payload /
    unusual_high_port_tcp), fingerprint guard (PII).
  * data ``pcap_io`` — scapy lazy import, PcapUnavailable/PcapParseError,
    normalizace paketů (TCP/UDP/DNS QNAME), max_packets guard.
  * CLI E2E — syntetický capture (scapy wrpcap) → artefakty v case DB +
    extrahované soubory do extracted/network/ (STOPA_DB_DIR, offline).

Offline: žádné reálné capture; pakety se generují scapy build() in-mem.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# scapy je volitelné ([net]) — bez něj se celý soubor přeskočí (P4-1 min profil)
try:
    from scapy.layers.dns import DNS, DNSQR
    from scapy.layers.inet import IP, TCP, UDP
    from scapy.packet import Raw
    from scapy.utils import wrpcap

    HAS_SCAPY = True
except ImportError:  # profil bez extra [net] (min CI)
    HAS_SCAPY = False

# ── domain imports (bez scapy) ─────────────────────────────────────────────
from stopa.domain.net_forensics import (
    BEACON_MIN_REQUESTS,
    IOC_PATTERNS,
    FlowKey,
    detect_beaconing,
    detect_dns_tunneling,
    detect_ftp,
    detect_high_port_tcp,
    detect_http_ioc,
    detect_smb,
    extract_http,
    fingerprint_value,
    group_flows,
    reassemble_flows,
    reassemble_stream,
    run_ioc_rules,
    statistics_median,
    summarize,
)

pytestmark = pytest.mark.skipif(not HAS_SCAPY, reason="volitelné extra [net] (scapy) chybí")

# ════════════════════════ helpers: syntetické záznamy ═════════════════════


def _rec(**kw):
    """Rychlý PacketRecord bez scapy."""
    from stopa.data.pcap_io import PacketRecord

    base = {"no": 0, "time": None, "proto": "tcp", "src_ip": "1.1.1.1",
            "dst_ip": "2.2.2.2", "src_port": 1234, "dst_port": 80}
    base.update(kw)
    return PacketRecord(**base)  # type: ignore[arg-type]


def _http_stream(body: bytes = b"SECRET-DATA-12345") -> bytes:
    """Request + odpověď s Content-Disposition filename (reasamblovaný tvar)."""
    req = b"GET /downloads/report.pdf HTTP/1.1\r\nHost: evil.example\r\n\r\n"
    resp_hdrs = (b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\n"
                 b"Content-Disposition: attachment; filename=\"report.pdf\"\r\n"
                 b"\r\n")
    return req + resp_hdrs + body


# ════════════════════════ 1. FlowKey kanonizace ═══════════════════════════


class TestFlowKey:
    def test_canonical_order(self):
        k1 = FlowKey.from_endpoints(("9.9.9.9", 4000), ("1.1.1.1", 80))
        k2 = FlowKey.from_endpoints(("1.1.1.1", 80), ("9.9.9.9", 4000))
        assert k1 == k2

    def test_label(self):
        k = FlowKey.from_endpoints(("1.1.1.1", 5555), ("2.2.2.2", 80))
        assert "1.1.1.1:5555" in k.label() and "2.2.2.2:80" in k.label()

    def test_group_flows_direction_agnostic(self):
        recs = [
            _rec(no=1, src_ip="1.1.1.1", dst_ip="2.2.2.2"),
            _rec(no=2, src_ip="2.2.2.2", dst_ip="1.1.1.1", src_port=80, dst_port=1234),
        ]
        flows = group_flows(recs)
        assert len(flows) == 1


# ════════════════════════ 2. TCP reassembly ═══════════════════════════════


class TestReassembly:
    def test_empty(self):
        st = reassemble_stream([])
        assert st.data == b""

    def test_in_order(self):
        recs = [
            _rec(no=1, time=1.0, tcp_seq=100, payload=b"AAAA"),
            _rec(no=2, time=2.0, tcp_seq=104, payload=b"BBBB"),
        ]
        st = reassemble_stream(recs)
        assert st.data == b"AAAABBBB"
        assert st.packet_count == 2

    def test_out_of_order_by_time_sorted_by_seq(self):
        recs = [
            _rec(no=1, time=5.0, tcp_seq=104, payload=b"BBBB"),
            _rec(no=2, time=1.0, tcp_seq=100, payload=b"AAAA"),
        ]
        st = reassemble_stream(recs)
        assert st.data == b"AAAABBBB"

    def test_gap_filled_with_nul_capped(self):
        recs = [
            _rec(no=1, time=1.0, tcp_seq=100, payload=b"AA"),
            _rec(no=2, time=2.0, tcp_seq=5_000, payload=b"BB"),  # obrovská mezera
        ]
        st = reassemble_stream(recs)
        assert st.data.startswith(b"AA\x00")
        assert len(st.data) <= 2 + 4096 + 2

    def test_no_payload_packets_ignored(self):
        recs = [_rec(no=1, time=1.0, tcp_seq=None, payload=b""),
                _rec(no=2, time=2.0, tcp_seq=5, payload=b"X")]
        st = reassemble_stream(recs)
        assert st.data == b"X"

    def test_flows_bidirectional(self):
        recs = [
            _rec(no=1, time=1.0, src_ip="1.1.1.1", dst_ip="2.2.2.2",
                 tcp_seq=100, payload=b"CZ"),
            _rec(no=2, time=2.0, src_ip="2.2.2.2", dst_ip="1.1.1.1",
                 src_port=80, dst_port=1234, tcp_seq=50, payload=b"ODP"),
        ]
        flows = reassemble_flows(recs)
        assert len(flows) == 1
        key = next(iter(flows))
        st = flows[key]
        assert b"CZ" in st.data and b"ODP" in st.data


# ════════════════════════ 3. HTTP / FTP / SMB extrakce ════════════════════


class TestExtraction:
    def test_http_content_disposition(self):
        files = extract_http(_http_stream(b"%PDF-1.4 fake"), "flow")
        assert len(files) == 1
        assert files[0].filename == "report.pdf"
        assert files[0].content_type == "application/pdf"
        assert files[0].size_bytes == len(b"%PDF-1.4 fake")
        assert len(files[0].sha256_prefix) == 16

    def test_http_no_request(self):
        assert extract_http(b"\x00\x01garbage", "flow") == []

    def test_http_url_path_fallback_filename(self):
        stream = (b"GET /files/backup.tar.gz HTTP/1.1\r\nHost: h\r\n\r\n"
                  b"HTTP/1.1 200 OK\r\nContent-Type: application/gzip\r\n\r\nTARBALL")
        files = extract_http(stream, "flow")
        assert len(files) == 1 and files[0].filename == "backup.tar.gz"

    def test_ftp_commands(self):
        stream = b"STOR upload.exe\r\nRETR data.bin\r\nLIST\r\njunk\r\n"
        cmds = detect_ftp(stream)
        assert any("upload.exe" in c for c in cmds)
        assert any("data.bin" in c for c in cmds)

    def test_smb_header(self):
        stream = b"\x00\x11" * 8 + b"\xfe\x53\x4d\x42" + b"\x00" * 16
        hits = detect_smb(stream)
        assert len(hits) == 1

    def test_smb_absent(self):
        assert detect_smb(b"HTTP/1.1 plain") == []


# ════════════════════════ 4. IoC rules (min. 5 patternů) ══════════════════


class TestIoc:
    def test_registry_has_min_5_patterns(self):
        assert len(IOC_PATTERNS) >= 5

    def test_dns_tunneling_long_subdomain(self):
        recs = [_rec(no=1, proto="udp", src_port=5353, dst_port=53,
                     dns_qname="a" * 40 + ".evil-c2.com")]
        hits = detect_dns_tunneling(recs)
        assert len(hits) == 1 and "fingerprint" in hits[0]

    def test_dns_normal_not_flagged(self):
        recs = [_rec(no=1, proto="udp", src_port=5353, dst_port=53,
                     dns_qname="www.google.com")]
        assert detect_dns_tunneling(recs) == []

    def test_beaconing_regular_intervals(self):
        recs = [
            _rec(no=i, time=float(i * 60), src_ip="10.0.0.5", dst_ip="8.8.4.4",
                 dst_port=443)
            for i in range(BEACON_MIN_REQUESTS + 2)
        ]
        hits = detect_beaconing(recs)
        assert len(hits) == 1 and hits[0]["dst_ip"] == "8.8.4.4"

    def test_irregular_not_beacon(self):
        recs = [
            _rec(no=1, time=1.0, dst_port=443),
            _rec(no=2, time=50.0, dst_port=443),
            _rec(no=3, time=999.0, dst_port=443),
        ]
        assert detect_beaconing(recs) == []

    def test_http_suspicious_url_path(self):
        flags = detect_http_ioc(b"plain body", "http://x/shell.php?id=1")
        assert "suspicious_url_path" in flags

    def test_http_base64_blob(self):
        blob = b"A" * 200
        flags = detect_http_ioc(blob, "http://ok.example/")
        assert "base64_blob_payload" in flags

    def test_high_port_tcp(self):
        recs = [_rec(no=1, dst_port=39999)]
        assert len(detect_high_port_tcp(recs)) == 1
        assert detect_high_port_tcp([_rec(no=1, dst_port=443)]) == []

    def test_run_ioc_rules_shape(self):
        recs = [_rec(no=1, proto="udp", src_port=5300, dst_port=53,
                     dns_qname="b" * 40 + ".tunnel.example")]
        out = run_ioc_rules(recs, {})
        assert set(out) >= {"dns_tunneling", "c2_beaconing", "http_ioc",
                            "unusual_high_port_tcp", "patterns_total"}
        assert len(out["dns_tunneling"]) == 1


# ════════════════════════ 5. Fingerprint / PII guard ══════════════════════


class TestFingerprint:
    def test_prefix_length_and_deterministic(self):
        a = fingerprint_value("sensitive-value")
        b = fingerprint_value("sensitive-value")
        assert a == b and len(a) == 8

    def test_different_values_differ(self):
        assert fingerprint_value("x1") != fingerprint_value("x2")


# ════════════════════════ 6. Summarize / misc ═════════════════════════════


class TestSummarize:
    def test_counts(self):
        recs = [_rec(no=1), _rec(no=2, proto="udp", dns_qname="a.b")]
        s = summarize(recs)
        assert s["tcp"] == 1 and s["udp"] == 1 and s["dns_queries"] == 1

    def test_median(self):
        assert statistics_median([3.0, 1.0, 2.0]) == 2.0
        assert statistics_median([1.0, 2.0, 3.0, 4.0]) == 2.5


# ════════════════════════ 7. data/pcap_io (scapy) ═════════════════════════


class TestPcapIo:
    def test_scapy_available(self):
        from stopa.data import pcap_io

        assert pcap_io.scapy_available() is True

    def test_read_pcap_roundtrip(self, tmp_path: Path):
        from stopa.data.pcap_io import read_pcap

        p = IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1234, dport=80, seq=100) / Raw(b"hello")
        q = IP(src="10.0.0.2", dst="10.0.0.1") / UDP(sport=53, dport=4444)
        f = tmp_path / "t.pcap"
        wrpcap(str(f), [p, q])

        recs = read_pcap(f)
        assert len(recs) == 2
        assert recs[0].proto == "tcp" and recs[0].payload == b"hello"
        assert recs[1].proto == "udp"

    def test_dns_qname_extracted(self, tmp_path: Path):
        from stopa.data.pcap_io import read_pcap

        pkt = (IP(src="1.2.3.4", dst="8.8.8.8") / UDP(sport=5300, dport=53)
               / DNS(id=1, qr=0, qd=DNSQR(qname="EVIL.EXAMPLE.COM.")))
        f = tmp_path / "dns.pcap"
        wrpcap(str(f), [pkt])
        recs = read_pcap(f)
        assert recs[0].dns_qname == "evil.example.com"

    def test_missing_file(self, tmp_path: Path):
        from stopa.data import pcap_io

        with pytest.raises(pcap_io.PcapParseError):
            pcap_io.read_pcap(tmp_path / "nope.pcap")

    def test_max_packets_guard(self, tmp_path: Path):

        pkts = [IP() / TCP(sport=100 + i, dport=80) for i in range(5)]
        f = tmp_path / "many.pcap"
        wrpcap(str(f), pkts)
        recs = read_pcap_ok(f, 2)
        assert len(recs) <= 2


def read_pcap_ok(path: Path, n: int):
    from stopa.data.pcap_io import read_pcap

    return read_pcap(path, max_packets=n)


# ════════════════════════ 8. CLI E2E (scapy capture → case DB) ════════════


@pytest.fixture()
def pcap_case(tmp_path: Path, monkeypatch):
    """Syntetický capture + case DB — vše offline."""
    from stopa.data.db import CaseDB
    from stopa.models import Case

    # HTTP download s Content-Disposition + DNS tunneling QNAME + beacon
    http_req = (b"GET /malware/payload.exe?token=1 HTTP/1.1\r\nHost: c2.evil.example\r\n\r\n")
    http_resp = (b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n"
                 b'Content-Disposition: attachment; filename="payload.exe"\r\n\r\n')
    body = b"MZ\x90\x00-fake-pe-" + b"A" * 64

    pkts = []
    seq = 1000
    # TCP: request + odpověď (payload rozdělený do paketů) — reassembly test
    parts = [http_req, http_resp, body]
    for i, part in enumerate(parts):
        pkts.append(IP(src="192.168.1.50", dst="45.77.12.9") /
                    TCP(sport=51000, dport=80, seq=seq) / Raw(part))
        seq += len(part)
    # DNS tunneling (dlouhý subdoménový QNAME)
    pkts.append(IP(src="192.168.1.50", dst="45.77.12.9") / UDP(sport=5300, dport=53) /
                DNS(id=7, qr=0, qd=DNSQR(qname=("c" * 40) + ".tunnel.evil.example.")))
    # beacon: pravidelné spojení na vysoký port (>32767 → ioc_unusual_high_port)
    for i in range(BEACON_MIN_REQUESTS + 2):
        pkts.append(IP(src="192.168.1.50", dst="45.77.12.9") /
                    TCP(sport=51000, dport=39000, seq=i) / Raw(b"hb"))

    pcap_file = tmp_path / "capture.pcap"
    wrpcap(str(pcap_file), pkts)

    monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
    case = Case(name="F1.3 E2E", examiner="Tester")
    db = CaseDB(str(tmp_path / f"{case.id}.db"))
    try:
        db.add_case(case)
    finally:
        db.close()
    return tmp_path, pcap_file, case.id


class TestCliE2e:
    def test_full_run_stores_artifacts(self, pcap_case, capsys):
        from stopa.cli import main

        _tmp_path, pcap_file, case_id = pcap_case
        rc = main(["pcap-analyze", case_id, str(pcap_file)])
        assert rc == 0

    def test_json_output_valid(self, pcap_case, capsys):
        from stopa.cli import main

        _tmp_path, pcap_file, case_id = pcap_case
        rc = main(["pcap-analyze", "--json", case_id, str(pcap_file)])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out[out.index("{"):])
        assert data["total_packets"] >= 5
        assert "ioc_counts" in data

    def test_missing_pcap_exit_2(self, tmp_path: Path, monkeypatch, capsys):
        from stopa.cli import main

        monkeypatch.setenv("STOPA_DB_DIR", str(tmp_path))
        rc = main(["pcap-analyze", "case-x", str(tmp_path / "nope.pcap")])
        assert rc == 2

    def test_extracted_file_written(self, pcap_case, capsys):
        from stopa.cli import main

        _tmp_path, pcap_file, case_id = pcap_case
        rc = main(["pcap-analyze", "--json", case_id, str(pcap_file)])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out[out.index("{"):])
        assert any("payload.exe" in p for p in data["extracted_files"])

    def test_artifacts_in_db(self, pcap_case):
        from stopa.data.db import CaseDB

        tmp_path, pcap_file, case_id = pcap_case
        rc = _main_pcap(case_id, str(pcap_file))
        assert rc == 0
        db = CaseDB(str(tmp_path / f"{case_id}.db"))
        try:
            arts = db.list_artifacts(limit=500) if hasattr(db, "list_artifacts") else []
        finally:
            db.close()
        types = {a.artifact_type for a in arts}
        assert "network_flow" in types
        assert any(t.startswith("ioc_") for t in types)

    def test_idempotent_rerun(self, pcap_case):
        """Re-analyza stejného capture — source se neduplikuje."""
        from stopa.data.db import CaseDB

        tmp_path, pcap_file, case_id = pcap_case
        assert _main_pcap(case_id, str(pcap_file)) == 0
        assert _main_pcap(case_id, str(pcap_file)) == 0
        db = CaseDB(str(tmp_path / f"{case_id}.db"))
        try:
            sources = [s for s in db.list_sources(case_id) if s.path == str(pcap_file)]
        finally:
            db.close()
        assert len(sources) == 1


def _main_pcap(case_id: str, pcap_path: str) -> int:
    from stopa.cli import main

    return main(["pcap-analyze", "--json", case_id, pcap_path])
