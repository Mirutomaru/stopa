"""ETAPA B vlna 15 — SIM TPDU phonebook extrakce (AT+CPBR export).

AXIOM ekvivalent: ``TpduDataExtractor``.

SIM telefonní book je na logických dumpůch dostupný jako **textový export**
AT příkazů (``AT+CPBR`` / ``AT+CPMS``) nebo jednoduchý CSV/TSV výpis z
forenzního nástroje. Tento parser je tolerantní — zvládne běžné varianty:

- ``AT+CPBR: "Jmeno",+420777123456,129``  (index, číslo, typ)
- ``"Jmeno","+420777123456"``              (CSV/TSV pár)
- ``Jmeno; +420777123456``                 (volně oddělené)

Bez platných záznamů → prázdný výsledek. Číslo se normalizuje a deduplikuje
podle normalizovaného čísla (stejná konvence jako mobile_extract kontakty).

Artifact type: ``contact`` — jeden kontakt = jeden artifact, source=sim_tpdu.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stopa.models import Artifact

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0"

MAX_CONTACTS_PER_DUMP = 2000

# Soubory, které obsahují SIM phonebook dump (name-based detekce).
_TPDU_EXTS = {".tpdu", ".cpbr", ".simdump", ".sim"}

# AT+CPBR: <index>, "name", +420..., type  (index je volitelný)
_CPBR_RE = re.compile(
    r'AT\+CPBR\s*:\s*(?:(?:\d+)\s*,\s*)?'
    r'(?:"(?P<q>[^"]*)"|(?P<u>\S+))\s*,\s*'
    r"(?P<num>[\d+\-() .]{4,20})\s*(?:,\s*\d+)?"
)

# Volně oddělený pár: jméno + číslo (CSV/TSV/volný text). Číslo musí být
# rozpoznatelné jako telefonní (začíná + nebo má ≥6 číslic).
_PAIR_RE = re.compile(
    r'"?(?P<name>[^",;\t][^",;\n]{0,80})"?\s*[;,]\s*"?(?P<num>\+?[\d()\- .]{4,20})"?'
)


def _printable_ratio(s: str) -> float:
    if not s:
        return 0.0
    sample = s[:64]
    return sum(c.isprintable() or c.isspace() for c in sample) / len(sample)


@dataclass
class TpduContact:
    """Jeden SIM kontakt — jméno + normalizované číslo."""

    name: str = ""
    number: str = ""  # surové (z dumpu)
    normalized: str = ""  # jen číslice (pro dedupe)


def normalize_phone_number(raw: str) -> str:
    """ČISTÁ funkce: telefonní číslo → jen číslice (E.164-lite)."""
    return re.sub(r"\D", "", raw or "")


def is_sim_tpdu_file(name: str) -> bool:
    """Name-based detekce — SIM phonebook dump podle přípony / názvu."""
    n = name.lower()
    stem = Path(n).stem.lower()
    if Path(n).suffix in _TPDU_EXTS:
        return True
    # známé exportní jména bez přípony (forenzní nástroje)
    return bool(any(k in stem for k in ("phonebook", "simdump", "cpbr")))


def parse_tpdu_text(text: str) -> list[TpduContact]:
    """ČISTÁ funkce: textový SIM dump → kontakty (tolerantní, dedupe).

    Nejdřív přesný AT+CPBR formát; zbytek řádků projde volným párováním.
    Deduplikace podle normalizovaného čísla — první výskyt vítězí.
    """
    if not text:
        return []
    contacts: list[TpduContact] = []
    seen: set[str] = set()

    def _add(name: str, num: str) -> None:
        name = (name or "").strip().strip('"').strip()
        num = (num or "").strip()
        norm = normalize_phone_number(num)
        if not norm or len(norm) < 4:
            return
        if _printable_ratio(name) < 0.9 and name:
            name = ""
        if norm in seen:
            return
        seen.add(norm)
        contacts.append(TpduContact(name=name, number=num, normalized=norm))

    for m in _CPBR_RE.finditer(text):
        # jméno může být v uvozovkách (q) nebo bez (u)
        name = m.group("q") if m.group("q") is not None else (m.group("u") or "")
        _add(name, m.group("num"))

    # volné páry jen na řádcích, které neobsahují AT+CPBR (ty už CPBR zpracoval)
    for line in text.splitlines():
        if "cpbr" in line.lower() or "at+" in line.lower():
            continue
        m = _PAIR_RE.search(line)
        if not m:
            continue
        _add(m.group("name") or "", m.group("num") or "")

    return contacts[:MAX_CONTACTS_PER_DUMP]


def build_tpdu_artifacts(entries: list[TpduContact]) -> list[Artifact]:
    """ČISTÁ funkce: ze SIM kontaktů vytvoří contact artifacty."""
    artifacts: list[Artifact] = []
    for e in entries:
        if not e.normalized:
            continue
        details: dict[str, Any] = {
            "engine": "sim_tpdu",
            "source": "sim_tpdu",
            "mimetype": "phone",
            "number": e.number,
        }
        artifacts.append(
            Artifact(
                artifact_type="contact",
                timestamp=None,  # SIM dump nemá spolehlivý čas
                title=e.name if e.name else f"SIM: {e.number}",
                details=details,
                confidence=0.8,
                parser_version=PARSER_VERSION,
            )
        )
    return artifacts


def extract_tpdu_artifacts(path) -> list[Artifact]:
    """Pipeline entrypoint — textový SIM dump → contact artifacty."""
    p = Path(str(path))
    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        logger.warning("SIM TPDU soubor nenalezen: %s", path)
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error("Chyba při čtení SIM TPDU %s: %s", path, exc)
        return []

    text = ""
    for enc in ("utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue

    entries = parse_tpdu_text(text)
    logger.debug("SIM TPDU %s: %d kontaktů", path, len(entries))
    return build_tpdu_artifacts(entries)
