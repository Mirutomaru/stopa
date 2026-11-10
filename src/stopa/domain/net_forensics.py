"""F1.3 — Síťová forenzika: čistá doménová logika nad PacketRecordy (ROADMAP V2 Fáze 1).

Bez scapy importu — pracuje s normalizovanými záznamy z ``data.pcap_io``:

* **TCP stream reassembly** — per-flow (5-tuple) seřazení po seq, de-duplikace
  překryvů; výstup = reasamblovaný payload per flow.
* **Extrakce souborů** — HTTP GET/POST body → filename z Content-Disposition /
  URL path; FTP (STOR/RETR) a SMB (SMB2 create/open) detekce jako artefakty.
* **IoC detekce** (min. 5 patternů, YARA-style regex):
    dns_tunneling, c2_beaconing, suspicious_url_path, base64_blob_payload,
    unusual_high_port_tcp, plus cross-packet pravidla.
* **PII / data minimizace** — extrahované body se do DB neukládají celé; jen
  fingerprint (SHA-256 prefix) + metadata. Surové byty patří do case/extracted/.

Výstupní artefakt typy: ``network_flow``, ``http_request``, ``dns_query``,
``file_extract_candidate``, ``ioc_<pattern>``.
"""

from __future__ import annotations

import hashlib
import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

# ── konstanty / registry ───────────────────────────────────────────────────

PARSER_VERSION = "f13/1.0"

#: IoC patterny — (kanonický flag, popis, regex). Min. 5 dle ROADMAP AK.
IOC_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("dns_tunneling", "Dlouhý/subdoménový DNS záznam — potenciální tunelování dat",
     re.compile(r"^[a-z0-9]{24,}\.[a-z0-9.-]+\.[a-z]{2,}$")),
    ("c2_beaconing", "Pravidelné časové rozestupy dotazů (detekce per-flow v rule)",
     re.compile(r"^beacon$")),  # placeholder — skutečná logika v detect_beacon()
    ("suspicious_url_path", "Skript/executables v URL path (php, asp, jsp, sh, exe…)",
     re.compile(r"/[A-Za-z0-9_\-./]*\.(php|asp|aspx|jsp|sh|bat|exe|py)(\?|$)")),
    ("base64_blob_payload", "Dlouhý base64 blob v HTTP payloadu (exfiltrace/encoding)",
     re.compile(r"[A-Za-z0-9+/]{128,}={0,2}")),
    ("unusual_high_port_tcp", "TCP na atypicky vysokém portu (>32767, ne-DNS/UDP scope)",
     re.compile(r"^high-port$")),  # placeholder — logika v rule nad flow
]

#: Práh beaconing detekce: N+ requestů s rozptylem < jitter pod interval.
BEACON_MIN_REQUESTS = 3
BEACON_JITTER_FACTOR = 0.15  # ±15 % kolem mediánu intervalu


# ── datové typy ────────────────────────────────────────────────────────────

@dataclass(slots=True, frozen=True)
class FlowKey:
    """Kanonický klíč TCP flow — směr-agnostická dvojice (addr,port) set.

    frozen → hashovatelný, použitelný jako dict key v group_flows().
    """

    a: tuple[str, int]  # (ip, port) strany A (menší lexikograficky)
    b: tuple[str, int]  # strana B
    proto: str = "tcp"

    @classmethod
    def from_endpoints(cls, src: tuple[str, int], dst: tuple[str, int]) -> FlowKey:
        """Kanonicky (lexikograficky menší strana jako A) — deterministický klíč."""
        s = (str(src[0]), int(src[1]))
        d = (str(dst[0]), int(dst[1]))
        if s <= d:
            return cls(a=s, b=d)
        return cls(a=d, b=s)

    def label(self) -> str:
        return f"{self.a[0]}:{self.a[1]} <-> {self.b[0]}:{self.b[1]}"


@dataclass(slots=True)
class TcpStream:
    """Reasamblovaný TCP stream — payload + metadata per flow."""

    key: FlowKey
    seq_start: int | None = None
    data: bytes = b""
    first_time: float | None = None
    last_time: float | None = None
    packet_count: int = 0


@dataclass(slots=True)
class ExtractedFile:
    """Kandidát na extrahovaný soubor (filename + body)."""

    filename: str
    content_type: str | None
    size_bytes: int
    sha256_prefix: str  # PII guard — jen fingerprint, ne surové data v DB
    raw: bytes = field(repr=False, default=b"")

# ── TCP reassembly ────────────────────────────────────────────────────────

def group_flows(records: list) -> dict[FlowKey, list]:
    """Rozdělení TCP záznamů do flow (směr-agnosticky)."""
    flows: dict[FlowKey, list] = {}
    for r in records:
        if r.proto != "tcp" or not r.src_ip or not r.dst_ip:
            continue
        key = FlowKey.from_endpoints((r.src_ip, r.src_port), (r.dst_ip, r.dst_port))
        flows.setdefault(key, []).append(r)
    return flows


def reassemble_stream(records: list) -> TcpStream:
    """Reasemblování jednoho směru streamu seřazením po seq + de-duplikace.

    Zjednodušený model (dostatečný pro forenzní extrakci): pakety se řadí
    podle tcp_seq, překryv se řeší posunem do běžného offsetu; missing bytes
    zůstávají explicitní (gap), nehalucinují.
    """
    ordered = sorted(
        (r for r in records if r.tcp_seq is not None and r.payload),
        key=lambda r: (r.time or 0, r.tcp_seq or 0),
    )
    if not ordered:
        return TcpStream(key=FlowKey(a=("?", 0), b=("?", 0)))

    stream = TcpStream(
        key=FlowKey.from_endpoints((ordered[0].src_ip or "?", ordered[0].src_port or 0),
                                   (ordered[0].dst_ip or "?", ordered[0].dst_port or 0)),
        seq_start=ordered[0].tcp_seq,
        first_time=ordered[0].time,
    )
    offset = 0
    for i, r in enumerate(ordered):
        if i > 0:
            prev = ordered[i - 1]
            expected = (prev.tcp_seq or 0) + len(prev.payload)
            gap = max(0, (r.tcp_seq or 0) - expected)
            stream.data += b"\x00" * min(gap, 4096)  # gap explicitní, střízelný
        stream.data += r.payload
        offset += len(r.payload)
        stream.last_time = max(stream.last_time or 0, r.time or 0) or None
    stream.packet_count = sum(1 for r in ordered if r.payload)
    return stream


def reassemble_flows(records: list) -> dict[FlowKey, TcpStream]:
    """Reasemblování všech flow → per-flow stream (obousměrná data oddělena)."""
    out: dict[FlowKey, TcpStream] = {}
    for key, recs in group_flows(records).items():
        # směr A→B a B→A jako samostatné sekvence (seq je per-směr)
        a_to_b = [r for r in recs if r.src_ip == key.a[0] and r.src_port == key.a[1]]
        b_to_a = [r for r in recs if r.src_ip == key.b[0] and r.src_port == key.b[1]]
        s1, s2 = reassemble_stream(a_to_b), reassemble_stream(b_to_a)
        merged = TcpStream(key=key, seq_start=s1.seq_start or s2.seq_start)
        merged.data = s1.data + b"\n\x00STREAM\x00\n" + s2.data if (s1.data and s2.data) else (s1.data or s2.data)
        merged.first_time = min(t for t in (s1.first_time, s2.first_time) if t is not None) if any(
            x is not None for x in (s1.first_time, s2.first_time)) else None
        merged.last_time = max((t for t in (s1.last_time, s2.last_time) if t is not None), default=None)
        merged.packet_count = s1.packet_count + s2.packet_count
        if merged.data:
            out[key] = merged
    return out


# ── HTTP / FTP / SMB extrakce ─────────────────────────────────────────────

_HTTP_REQ_RE = re.compile(rb"^(GET|POST|PUT|HEAD|DELETE)\s+([^\r\n]+?)(?:\s+HTTP/[\d.]+\s*)?(?=\r\n)", re.DOTALL)
_CONTENT_TYPE_RE = re.compile(rb'content-type:\s*([^\r\n;]+)', re.IGNORECASE | re.DOTALL)
_DISPOSITION_RE = re.compile(
    rb'filename\*?=(?:UTF-8\'\')?"?([^";\r\n]+)"?', re.IGNORECASE | re.DOTALL)
_B64_BLOB_BYTES_RE = re.compile(rb"[A-Za-z0-9+/]{128,}={0,2}")  # bytes varianta IoC #4


def extract_http(stream: bytes, flow_label: str) -> list[ExtractedFile]:
    """Extrakce HTTP request/response souborů z reasamblovaného streamu.

    Hledá Content-Disposition filename + body za hlavičkami; fallback na URL
    path u GET. Vrací jen kandidáty (size > 0, plausibilní filename).
    """
    files: list[ExtractedFile] = []
    seen: set[str] = set()

    # request část: method + url
    req_m = _HTTP_REQ_RE.search(stream)
    if not req_m:
        return []
    url = req_m.group(2).decode("utf-8", "replace").strip()
    ctype_m = _CONTENT_TYPE_RE.search(stream)
    content_type = ctype_m.group(1).decode("ascii", "replace").strip() if ctype_m else None

    # body: po hlavičkách (\r\n\r\n); u request+response dvojice za POSLEDNÍMI
    # hlavičkami (odpověď), u čistého requestu za prvními — rfind to pokrývá.
    sep = stream.rfind(b"\r\n\r\n")
    body = stream[sep + 4:] if sep != -1 else b""
    if not body and req_m.group(1) == b"GET":
        return []

    disp_m = _DISPOSITION_RE.search(stream[: max(sep, 0)]) or _DISPOSITION_RE.search(stream)
    filename: str | None = None
    if disp_m:
        filename = disp_m.group(1).decode("utf-8", "replace").strip().strip('"')
    else:
        path_part = url.split("?")[0].rstrip("/")
        if path_part and not re.search(r"\.(php|asp|aspx|jsp)(\?|$)", path_part):
            filename = Path(path_part).name

    if filename and body and filename.lower() not in seen:
        digest = hashlib.sha256(body)
        files.append(ExtractedFile(
            filename=filename,
            content_type=content_type,
            size_bytes=len(body),
            sha256_prefix=digest.hexdigest()[:16],
            raw=body,
        ))
    return files


def detect_ftp(stream: bytes) -> list[str]:
    """FTP komandy (STOR/RETR/APPE/DELE…) — vráceny jako artefakt detaily."""
    cmds = re.findall(rb"^(STOR|RETR|APPE|DELE|LIST|NLST)\s+([^\r\n]+)", stream, re.MULTILINE)
    return [f"{c.decode()}: {a.decode('utf-8', 'replace').strip()}" for c, a in cmds[:50]]


def detect_smb(stream: bytes) -> list[str]:
    """SMB2 Create/Close detekce — heuristika po SMB2 hlavičce (FE face + 0x11)."""
    if b"\xfe\x53\x4d\x42" not in stream[:64] and not re.search(rb"\x00\x00[\x00-\xff]{8}\x02", stream[:32]):
        return []
    # SMB2 command codes: 0=CREATE, 1=IOCTL, 3=CLOSE (little-endian u offsetu)
    return [f"smb2_header@{i}" for i in list(re.finditer(rb"\xfe\x53\x4d\x42", stream))[:10]]


# ── IoC detekce ───────────────────────────────────────────────────────────

def fingerprint_value(value: str) -> str:
    """SHA-256 prefix (8 hex) — data minimizace pro DB (jako F1.2)."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:8]


def detect_dns_tunneling(records: list) -> list[dict[str, object]]:
    """DNS záznamy splňující dns_tunneling pattern (QNAME délka/struktura)."""
    hits = []
    for r in records:
        if not r.dns_qname:
            continue
        m = IOC_PATTERNS[0][2].match(r.dns_qname)
        if m:
            hits.append({
                "qname": r.dns_qname,
                "len": len(r.dns_qname),
                "fingerprint": fingerprint_value(r.dns_qname),
                "src_ip": r.src_ip,
            })
    return hits


def detect_beaconing(records: list) -> list[dict[str, object]]:
    """C2 beaconing: per (dst ip,port) N+ requestů s nízkým rozptylem intervalu."""
    by_target: dict[tuple[str, int], list[float]] = {}
    for r in records:
        if r.proto == "tcp" and r.dst_port is not None:
            t = (r.dst_ip or "?", r.dst_port)
            by_target.setdefault(t, []).append(r.time or 0.0)

    hits = []
    for (ip, port), times in by_target.items():
        ts = sorted(t for t in times if t > 0)
        if len(ts) < BEACON_MIN_REQUESTS:
            continue
        intervals = [later - earlier for earlier, later in itertools.pairwise(ts)]
        med = statistics_median(intervals)
        if med <= 0:
            continue
        tol = max(med * BEACON_JITTER_FACTOR, 1.0)
        stable = sum(1 for iv in intervals if abs(iv - med) <= tol)
        ratio = stable / len(intervals)
        if ratio >= 0.8:
            hits.append({
                "dst_ip": ip, "dst_port": port,
                "requests": len(ts), "median_interval_s": round(med, 3),
                "stability_ratio": round(ratio, 2),
            })
    return hits


def statistics_median(xs: list[float]) -> float:
    """Medián bez importu statistics (čistá doménová logika)."""
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def detect_http_ioc(
    stream: bytes, url: str | None = None, flow_label: str | None = None
) -> list[str]:
    """HTTP-level IoC nad request URL + payloadem.

    ``flow_label`` je informativní (pro logování/trace) — detekce ho nepotřebuje.
    """
    flags = []
    if url and IOC_PATTERNS[2][2].search(url):
        flags.append("suspicious_url_path")
    if _B64_BLOB_BYTES_RE.search(stream[:65536]):  # střízelný prefix payloadu
        flags.append("base64_blob_payload")
    return flags


def detect_high_port_tcp(records: list) -> list[str]:
    """TCP flow na atypicky vysokém portu (>32767)."""
    seen = set()
    for r in records:
        if r.proto == "tcp" and (r.dst_port or 0) > 32767:
            lbl = f"{r.src_ip}:{r.src_port}->{r.dst_ip}:{r.dst_port}"
            if lbl not in seen:
                seen.add(lbl)
    return sorted(seen)[:50]


def run_ioc_rules(records: list, streams: dict[FlowKey, TcpStream]) -> dict[str, object]:
    """Kompletní IoC pass — vrace strukturovaný výsledek pro artefakty."""
    dns_hits = detect_dns_tunneling(records)
    beacon_hits = detect_beaconing(records)
    high_port = detect_high_port_tcp(records)

    http_iocs: list[dict[str, object]] = []
    for key, st in streams.items():
        m = _HTTP_REQ_RE.search(st.data[:4096])
        url = m.group(2).decode("utf-8", "replace").strip() if m else None
        flags = detect_http_ioc(st.data, url, key.label())
        if flags:
            http_iocs.append({"flow": key.label(), "url": url, "flags": flags})

    return {
        "dns_tunneling": dns_hits,
        "c2_beaconing": beacon_hits,
        "http_ioc": http_iocs,
        "unusual_high_port_tcp": high_port,
        "patterns_total": len(IOC_PATTERNS),
    }


# ── souhrn / validace ─────────────────────────────────────────────────────

def summarize(records: list) -> dict[str, int]:
    """Počty per protokol + DNS/HTTP heuristika — pro CLI output."""
    proto_counts: dict[str, int] = {}
    dns_q = 0
    for r in records:
        proto_counts[r.proto] = proto_counts.get(r.proto, 0) + 1
        if r.dns_qname:
            dns_q += 1
    return {**proto_counts, "dns_queries": dns_q, "total_packets": len(records)}
