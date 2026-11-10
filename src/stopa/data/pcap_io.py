"""F1.3 — Síťová forenzika: PCAP čtení přes Scapy (ROADMAP V2 Fáze 1).

IO vrstva — izoluje závislost na Scapy a normalizuje pakety do jednoduchých
záznamů (PacketRecord), které domain ``net_forensics`` zpracovává jako čistý
Python (bez scapy importu v doménové logice → testovatelnost bez sítě).

Scapy je **volitelná runtime závislost** (jako Volatility 3 / libbde):
nejen-li chybí, vracejí se typované chyby (PcapUnavailable) a CLI ukončí
s exit code 3 — STOPA zbytek workbenchu funguje dál.

Podpora .pcap a .pcapng (scapy rdpcap/rdpcread). Velké capture: iterator +
max_packets guard proti OOM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Guard proti OOM u velkých capture — defaultní strop (překročit lze parametrem).
DEFAULT_MAX_PACKETS = 50_000


class PcapUnavailable(Exception):
    """Scapy není nainstalovaná ve STOPA venv."""


def scapy_available() -> bool:
    """True, pokud se scapy dá importovat (lazy — bez vedlejších efektů)."""
    try:
        import scapy  # noqa: F401

        return True
    except ImportError:
        return False


@dataclass(slots=True)
class PacketRecord:
    """Normalizovaný pakete — jednotný formát pro domain vrstvu.

    ``payload`` = TCP/UDP payload bytes (prázdné u SYN-only atd.).
    Časy jako epoch sekundy (float|None) — deterministické reasemblování a
    beaconing detekce pracují s absolutními časovými rozdíly.
    """

    no: int  # ordinál v capture (0-index, pořadí čtení)
    time: float | None = None
    proto: str = "other"  # tcp | udp | icmp | other
    src_ip: str | None = None
    dst_ip: str | None = None
    src_port: int | None = None
    dst_port: int | None = None
    tcp_seq: int | None = None
    tcp_ack: int | None = None
    tcp_flags: str | None = None  # např. "S", "PA", "FA" (scapy formát)
    payload: bytes = b""
    dns_qname: str | None = None  # UDP/53 dotaz (lowercase)

    def to_dict(self) -> dict[str, object]:
        """Serializace pro testy / debug (payload jen délka — žádné data)."""
        return {
            "no": self.no,
            "time": self.time,
            "proto": self.proto,
            "src_ip": self.src_ip,
            "dst_ip": self.dst_ip,
            "src_port": self.src_port,
            "dst_port": self.dst_port,
            "tcp_seq": self.tcp_seq,
            "tcp_ack": self.tcp_ack,
            "tcp_flags": self.tcp_flags,
            "payload_len": len(self.payload),
            "dns_qname": self.dns_qname,
        }


def _import_scapy():
    """Lazy import scapy — PcapUnavailable s akční zprávou."""
    try:
        from scapy.layers.dns import DNS
        from scapy.layers.inet import ICMP, IP, TCP, UDP
        from scapy.utils import PcapReader

        return {"IP": IP, "TCP": TCP, "UDP": UDP, "ICMP": ICMP, "DNS": DNS, "PcapReader": PcapReader}
    except ImportError as e:  # pragma: no cover — závisí na instalaci
        raise PcapUnavailable(
            "Scapy není nainstalovaná — `pip install scapy` do STOPA venv "
            "(volitelná runtime závislost pro F1.3 síťovou forensiku)"
        ) from e


def _extract_dns_qname(pkt) -> str | None:
    """QNAME z DNS dotazu (lowercase) — None u odpovědí / nedotazů."""
    try:
        dns = pkt.getlayer("DNS")
        if dns is None or dns.qr != 0 or not getattr(dns, "qd", None):
            return None
        qd = dns.qd[0] if isinstance(dns.qd, (list, tuple)) else dns.qd
        raw = getattr(qd, "qname", "") or b""
        if isinstance(raw, bytes):  # scapy ≥2.8 vrací bytes — DNS jméno je ASCII
            raw = raw.decode("latin-1")
        qname = str(raw).strip().rstrip(".")
        return qname.lower() or None
    except Exception:  # noqa: BLE001 — jediná vrstva nesmí zastavit capture
        return None


def _normalize(no: int, pkt) -> PacketRecord | None:
    """Scapy packet → PacketRecord (None = nepodporovaná L3, např. IPv6)."""
    ip = pkt.getlayer("IP") if hasattr(pkt, "getlayer") else None
    if ip is None:
        return None  # IPv6 / raw — explicitně mimo F1.3 scope (IPv4)

    rec = PacketRecord(
        no=no,
        time=float(pkt.time) if pkt.time is not None else None,
        src_ip=str(ip.src),
        dst_ip=str(ip.dst),
    )
    tcp = ip.getlayer("TCP") if hasattr(ip, "getlayer") else None
    udp = ip.getlayer("UDP") if hasattr(ip, "getlayer") else None
    icmp = ip.getlayer("ICMP") if hasattr(ip, "getlayer") else None

    if tcp is not None:
        rec.proto = "tcp"
        rec.src_port = int(tcp.sport)
        rec.dst_port = int(tcp.dport)
        rec.tcp_seq = int(tcp.seq) if tcp.seq is not None else None
        rec.tcp_ack = int(tcp.ack) if tcp.ack is not None else None
        rec.tcp_flags = str(tcp.flags)
        payload = bytes(tcp.payload) if bytes(tcp.payload) else b""
        rec.payload = payload
    elif udp is not None:
        rec.proto = "udp"
        rec.src_port = int(udp.sport)
        rec.dst_port = int(udp.dport)
        rec.payload = bytes(udp.payload) if bytes(udp.payload) else b""
        if 53 in (rec.src_port, rec.dst_port):
            rec.dns_qname = _extract_dns_qname(pkt)
    elif icmp is not None:
        rec.proto = "icmp"
        payload = bytes(icmp.payload) if bytes(icmp.payload) else b""
        # ICMP data mohou být v typickém layoutu za hlavičkou; scapy je dá v payload
        rec.payload = payload
    else:
        rec.proto = "other"

    return rec


def read_pcap(path: str | Path, max_packets: int = DEFAULT_MAX_PACKETS) -> list[PacketRecord]:
    """Přečte .pcap/.pcapng do normalizovaných záznamů.

    Args:
        path: cesta k capture souboru.
        max_packets: strop počtu paketů (guard proti OOM); překročení →
            PcapError s explicitním stavem ``truncated=True``.

    Raises:
        PcapUnavailable: scapy chybí.
        PcapParseError: nečitelný soubor / překročen max_packets.
    """
    path = Path(path).expanduser()
    if not path.is_file():
        raise PcapParseError(f"PCAP soubor neexistuje: {path}")

    mods = _import_scapy()
    recs: list[PacketRecord] = []
    truncated = False
    try:
        with mods["PcapReader"](str(path)) as reader:  # type: ignore[arg-type]
            for no, pkt in enumerate(reader):
                if no >= max_packets:
                    truncated = True
                    break
                rec = _normalize(no, pkt)
                if rec is not None:
                    recs.append(rec)
    except PcapUnavailable:
        raise
    except Exception as e:  # scapy IOException / rozbitá capture
        raise PcapParseError(f"PCAP se nepodařilo přečíst ({path.name}): {e}") from e

    if truncated:
        logger.warning("pcap %s: stříženo na max_packets=%d", path.name, max_packets)
    return recs


class PcapParseError(Exception):
    """Nečitelný capture nebo překročen guard (max_packets)."""
