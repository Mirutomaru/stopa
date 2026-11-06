"""STP-049 — AI Copilot grounding: detekce rozporů mezi odpovědí LLM a artifacty v DB.

Design (Clean Architecture):
- **bez IO** — vstupem je text odpovědi + citovaná ID + dict artifactů
  (``model_dump(mode="json")``); výstup = deterministický report, který se dá
  testovat bez spuštěného LM Studio i bez case DB
- tři kategorie rozporu:
  - ``mismatch_date``   — odpověď uvádí datum, které neodpovídá timestampu citovaného artifactu
  - ``mismatch_type``   — odpověď zmiňuje typ artifactu (ze slovníku), který se liší od reálného typu
  - ``unverified_claim``— odpověď cituje artifact, ale v textu není žádný ověřitelný
                         kotva (žádné shodné datum, správný typ ani hodnota z details)

Atribuce tvrdění: každé tvrzení (datum/zmiňovaný typ) se přiřadí k **nejbližší**
citaci podle vzdálenosti znaků; při rovnocenné vzdálenosti vyhrává citace s
menším indexem. Deterministické — stejný vstup → stejný report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ── konstanty ────────────────────────────────────────────────────────────────

#: Slovník typů artifactů STOPA — zrcadlí reálný výstup parserů
#: (``grep -rhoE 'artifact_type="[^"]+"' src/stopa/artifacts/*.py``).
#: Zmiňování jiného typu než reálný = mismatch_type. Seřazeno deterministicky.
KNOWN_ARTIFACT_TYPES: tuple[str, ...] = (
    "app_execution",
    "autofill_entry",
    "browser_bookmark",
    "browser_cookie",
    "browser_history",
    "browser_search",
    "browser_setting",
    "browser_tab",
    "calendar_event",
    "call_log",
    "call_record",
    "chat_message",
    "clipboard_entry",
    "cloud_file",
    "cloud_instance",
    "contact",
    "credential",
    "document_metadata",
    "drive_activity",
    "email_attachment",
    "email_message",
    "event_log_entry",
    "file_metadata",
    "google_account",
    "google_account_event",
    "google_activity",
    "google_device",
    "google_export_summary",
    "google_identity_session",
    "google_location",
    "google_login",
    "google_mail_info",
    "google_maps_activity",
    "google_photo",
    "google_search",
    "imessage",
    "location",
    "location_data",
    "mem_connection",
    "mem_handle",
    "mem_hook",
    "mem_module",
    "mem_process",
    "memory_file",
    "memory_process",
    "messenger_message",
    "network_connection",
    "plist_date",
    "property_list",
    "registry_hive",
    "scheduled_task",
    "shell_link",
    "sms_message",
    "sns_comment",
    "sns_post",
    "sqlite_database",
    "user_sid",
    "usn_record",
    "voice_recording",
    "voicemail",
    "web_page",
    "whatsapp_message",
    "wifi_profile",
    "win_driver",
    "win_jumplist",
    "win_prefetch",
)

#: ISO datum (volitelně s časem) — ``2026-03-10`` / ``2026-03-10T12:05`` / ``2026-03-10 12:05``
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b")

#: české datum s měsícem — ``10. března 2026`` / ``10. březen 2026``
_CS_MONTHS: dict[str, int] = {
    "leden": 1, "únor": 2,
    "březen": 3, "března": 3,
    "duben": 4, "dubna": 4,
    "květen": 5, "května": 5,
    "červen": 6, "června": 6,
    "červenec": 7, "července": 7,
    "srpen": 8, "srpna": 8,
    "září": 9,
    "říjen": 10, "října": 10,
    "listopad": 11, "listopadu": 11,
    "prosinec": 12, "prosince": 12,
}
_CS_DATE_RE = re.compile(
    r"\b(\d{1,2})\.\s*(" + "|".join(sorted(_CS_MONTHS, key=len, reverse=True)) + r")\s+(\d{4})\b"
)

#: minimální délka hodnoty z details, aby se počítala jako ověřitelná kotva
_MIN_VALUE_ANCHOR_LEN = 4


# ── datové typy ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Claim:
    """Jedno extrahované tvrzení v textu odpovědi."""

    kind: str  # "date" | "type"
    value: str  # normalizovaná hodnota (datum YYYY-MM-DD / typ artifactu)
    raw: str  # přesný úryvek z textu
    start: int
    end: int


@dataclass(frozen=True)
class GroundingFinding:
    """Jeden rozpor mezi odpovědí a daty citovaného artifactu."""

    category: str  # mismatch_date | mismatch_type | unverified_claim
    citation_id: str
    claim: str | None  # co odpověď tvrdí (datum / typ / úryvek textu)
    actual: str | None  # co je v DB (None = neověřitelné)


@dataclass(frozen=True)
class GroundingReport:
    """Výsledek grounding analýzy jedné odpovědi."""

    findings: tuple[GroundingFinding, ...] = ()
    verified_citations: tuple[str, ...] = ()  # citace bez jediného rozporu

    @property
    def has_contradictions(self) -> bool:
        return bool(self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": list(self.verified_citations),
            "findings": [
                {"category": f.category, "citation_id": f.citation_id,
                 "claim": f.claim, "actual": f.actual}
                for f in self.findings
            ],
        }


# ── extrakce tvrdění (čistá logika) ─────────────────────────────────────────

def _valid_date(y: int, m: int, d: int) -> bool:
    return 1 <= m <= 12 and 1 <= d <= 31


def extract_claims(text: str, known_types: tuple[str, ...] = KNOWN_ARTIFACT_TYPES) -> list[_Claim]:
    """Extrahuje tvrdění z odpovědi LLM: data (ISO + česká) a zmiňované typy artifactů.

    Výsledek je seřazený podle pozice v textu (deterministické).
    """
    claims: list[_Claim] = []
    for m in _ISO_DATE_RE.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not _valid_date(y, mo, d):
            continue
        claims.append(_Claim("date", f"{y:04d}-{mo:02d}-{d:02d}", m.group(0), m.start(), m.end()))
    for m in _CS_DATE_RE.finditer(text):
        day, month_name, year = int(m.group(1)), _CS_MONTHS[m.group(2)], int(m.group(3))
        if not _valid_date(year, month_name, day):
            continue
        claims.append(_Claim("date", f"{year:04d}-{month_name:02d}-{day:02d}", m.group(0), m.start(), m.end()))
    lowered = text.lower()
    # jeden kombinovaný pattern — alternativy seřazené délkou (delší vyhraje),
    # jinak by `location` matchovala uvnitř `location_data` atd.
    if known_types:
        alt = "|".join(sorted((re.escape(t) for t in known_types), key=len, reverse=True))
        type_re = re.compile(r"(?<![a-z0-9])(" + alt + r")(?![a-z0-9])")
        for m in type_re.finditer(lowered):
            claims.append(_Claim("type", m.group(1), text[m.start():m.end()], m.start(), m.end()))
    return sorted(claims, key=lambda c: (c.start, c.kind))


def _artifact_date(artifact: dict[str, Any]) -> str | None:
    """Datum z timestampu artifactu (``YYYY-MM-DD``) nebo ``None``."""
    ts = artifact.get("timestamp")
    if not ts:
        return None
    s = str(ts)
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


def _detail_strings(details: Any, out: list[str]) -> None:
    """Rekurzivně sbere všechny listové hodnoty z details (libovolná hloubka)."""
    if isinstance(details, dict):
        for v in details.values():
            _detail_strings(v, out)
    elif isinstance(details, (list, tuple)):
        for v in details:
            _detail_strings(v, out)
    elif isinstance(details, str) and len(details) >= _MIN_VALUE_ANCHOR_LEN:
        out.append(details.lower())


def _nearest_citation(claim: _Claim, citations: list[tuple[int, int, str]]) -> str | None:
    """ID citace nejbližší tvrzení (vzdálenost znaků; tie → menší index)."""
    best_id: str | None = None
    best_dist = -1
    best_idx = 0
    for idx, (start, end, cid) in enumerate(citations):
        if claim.start >= end:  # citace před tvrzením
            dist = claim.start - end
        elif claim.end <= start:  # citace za tvrzením
            dist = start - claim.end
        else:  # překryv (nemá se stát, ale deterministicky)
            dist = 0
        if best_dist < 0 or dist < best_dist or (dist == best_dist and idx < best_idx):
            best_dist, best_id, best_idx = dist, cid, idx
    return best_id


# ── hlavní vstupní bod ───────────────────────────────────────────────────────

def ground_answer(
    text: str,
    citations: list[str],
    artifacts_by_id: dict[str, dict[str, Any]],
    known_types: tuple[str, ...] = KNOWN_ARTIFACT_TYPES,
) -> GroundingReport:
    """Porovná tvrdění v odpovědi s daty citovaných artifactů.

    :param text: **původní** text odpovědi LLM — včetně tokenů ``[art:<id>]``
        (ne clean text z ``extract_citations``, který je už odstranil;
        pozice citací jsou potřeba pro atribuci tvrdění)
    :param citations: validovaná ID citací v pořadí výskytu
    :param artifacts_by_id: id → artifact dict (``model_dump(mode="json")``)
    :return: deterministický report s rozpornými i ověřenými citacemi
    """
    from stopa.domain.ai_assistant import CITATION_RE

    spans = [(m.start(), m.end(), m.group(1)) for m in CITATION_RE.finditer(text)]
    claims = extract_claims(text, known_types)

    # atribuce tvrzení → citace (nejbližší)
    attributed: dict[str, list[_Claim]] = {cid: [] for cid in citations}
    for c in claims:
        if not spans:
            break
        target = _nearest_citation(c, spans)
        if target is not None and target in attributed:
            attributed[target].append(c)

    # okno textu PŘED každou citací (pro unverified_claim kontrolu)
    prose_before: dict[str, str] = {}
    for i, (start, _end, cid) in enumerate(spans):
        prev_end = spans[i - 1][1] if i > 0 else 0
        prose_before[cid] = text[prev_end:start]

    findings: list[GroundingFinding] = []
    for cid in citations:
        art = artifacts_by_id.get(cid)
        if art is None:
            continue  # nevalidní ID už vyřadila extract_citations; defenzivně skip
        actual_date = _artifact_date(art)
        actual_type = str(art.get("artifact_type") or "").lower()

        anchors: set[str] = set()
        for c in attributed[cid]:
            if c.kind == "date":
                if actual_date is None:
                    continue  # artifact bez timestampu — datum neověřitelné, ale ani rozpor
                if c.value == actual_date:
                    anchors.add("date")
                else:
                    findings.append(GroundingFinding(
                        "mismatch_date", cid, claim=c.raw, actual=actual_date))
            elif c.kind == "type":
                if c.value == actual_type:
                    anchors.add("type")
                else:
                    findings.append(GroundingFinding(
                        "mismatch_type", cid, claim=c.raw, actual=art.get("artifact_type")))

        # kotvy z hodnot details — hodnota se objeví kdekoliv v odpovědi
        values: list[str] = []
        _detail_strings(art.get("details") or {}, values)
        lowered_text = text.lower()
        if any(v in lowered_text for v in values):
            anchors.add("value")

        # unverified_claim — citace bez atributovaného tvrzení i ověřitelné kotvy,
        # s podstatným textem (konkrétní mismatchy už rozpor vysvětlují)
        prose = (prose_before.get(cid) or "").strip()
        if not anchors and not attributed[cid] and len(prose) >= 20:
            findings.append(GroundingFinding(
                "unverified_claim", cid, claim=prose[:120], actual=None))

    verified = tuple(cid for cid in citations if all(f.citation_id != cid for f in findings))
    return GroundingReport(findings=tuple(findings), verified_citations=verified)


__all__ = [
    "KNOWN_ARTIFACT_TYPES",
    "GroundingFinding",
    "GroundingReport",
    "extract_claims",
    "ground_answer",
]
