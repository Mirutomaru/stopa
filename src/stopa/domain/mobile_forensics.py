"""STOPA F1.5 — Mobilní extrakce: doménová vrstva (čistá, stdlib).

Cellebrite UFDR ``report.xml`` parser + VCF kontakty + normalizace pro
korelaci entit s existujícími kontakty případu. Žádné file I/O — CLI čte
ZIP/složku a předává sem bajty/text; IO i DB zápis zůstávají v `data/`+CLI.

Zdroj struktury report.xml: Cellebrite UFED evidence export (viz ufedlib-py).
Modelové elementy ``<model type="...">`` nesou skalární ``<field name=X>``,
``<multiField>`` a vnořená ``<multiModelField>`` s dcerinými ``<model>``.

Konvence sdílené s ostatními doménovými moduly:
- čisté funkce, deterministický výstup (řazení tam, kde záleží na pořadí),
- chyby parsu → explicitní `UfedParseError` / prázdný výsledek, ne výjimka nahoru.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.etree import ElementTree

from stopa.domain.xml_bounded import XmlLimitError, bounded_xml_parse

logger = logging.getLogger(__name__)

# E1: verze parseru — eviduje se v audit logu (reprodukovatelnost analýzy)
PARSER_VERSION = "1.0"


class UfedParseError(ValueError):
    """report.xml neprošlo parsem (nevalidní XML / chybějící kořen)."""


# ── časové formáty UFED reportu ────────────────────────────────

def _parse_ts(value: str | None) -> datetime | None:
    """ISO 8601 z report.xml → aware UTC datetime; nečitelné → None."""
    if not value:
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # bez offsetu = UTC (doložit v limitacích)
    return dt.astimezone(timezone.utc)


# ── modelové elementy report.xml ───────────────────────────────

@dataclass(frozen=True)
class ModelSpec:
    """Jeden vyprocesovaný ``<model>`` — typ + skalární pole + dceřiné modely."""

    model_type: str
    fields: dict[str, str] = field(default_factory=dict)
    nested: tuple[ModelSpec, ...] = ()


def _localname(tag: object) -> str:
    """Tag bez XML namespaceu (``{ns}field`` → ``field``)."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _collect_parts(elem: ElementTree.Element) -> tuple[dict[str, str], list[ElementTree.Element]]:
    """Skalární pole + vnořené ``<model>`` elementy (bez namespaceu)."""
    fields: dict[str, str] = {}
    nested_elems: list[ElementTree.Element] = []
    for child in list(elem):
        tag = _localname(child.tag)
        if tag == "field":
            name = child.get("name") or ""
            value = (child.text or "").strip()
            if not value:  # tvar <field name="X"><value>...</value></field>
                for sub in list(child):
                    if _localname(sub.tag) == "value":
                        value = (sub.text or "").strip()
                        break
            if name and value:
                fields[name] = value
        elif tag == "multiField":
            # seznam skalárů — spojíme do jednoho pole (| odděleně, strop 8 položek)
            values = [(sub.text or "").strip() for sub in list(child)]
            values = [v for v in values if v]
            name = child.get("name") or ""
            if name and values:
                fields[name] = " | ".join(values[:8])
        elif tag == "multiModelField":
            nested_elems.extend(
                sub for sub in list(child) if _localname(sub.tag) == "model"
            )
    return fields, nested_elems


def _process_model(elem: ElementTree.Element, unsupported: set[str]) -> ModelSpec | None:
    """Rekurzivně vyprocesuje model včetně dceřiných (dceriny se spotřebují)."""
    mtype = elem.get("type") or ""
    if not mtype:
        return None
    fields, nested_elems = _collect_parts(elem)
    nested: list[ModelSpec] = []
    for sub in nested_elems:
        spec = _process_model(sub, unsupported)
        if spec is not None:
            nested.append(spec)
    if mtype not in KNOWN_MODEL_TYPES:
        unsupported.add(mtype)
    return ModelSpec(model_type=mtype, fields=fields, nested=tuple(nested))


def parse_ufdr_xml(xml_text: str | bytes) -> tuple[list[ModelSpec], list[str]]:
    """Parsovaní report.xml → (top-level modely, neznámé typy).

    Top-level = modely přímo pod kořenem extrakce; dceřiné modely jsou už
    spotřebované u rodiče (žádné dvojité počítání). Nevalidní XML → `UfedParseError`.
    """
    try:
        # P1 security — report.xml je nedůvěryhodný (billion laughs / hloubka)
        root = bounded_xml_parse(xml_text if isinstance(xml_text, str) else xml_text.decode("utf-8"))
    except (ElementTree.ParseError, UnicodeDecodeError, XmlLimitError) as e:
        raise UfedParseError(f"report.xml nevalidní XML: {e}") from e

    unsupported: set[str] = set()
    top: list[ModelSpec] = []
    # rekurzivní průchod — model se vyprocesuje celý (dceřiny spotřebovají)
    def walk(elem: ElementTree.Element, in_model: bool) -> None:
        if in_model:
            return  # dceriny už patří rodiči
        for child in list(elem):
            tag = _localname(child.tag)
            if tag == "model" and child.get("type"):
                spec = _process_model(child, unsupported)
                if spec is not None and not in_model:
                    top.append(spec)
            else:
                walk(child, False)

    walk(root, False)
    return top, sorted(unsupported)


# ── mapování modelů → artefakty ────────────────────────────────

#: typy report.xml, které umíme promapovat na kanonické artifact types
KNOWN_MODEL_TYPES: frozenset[str] = frozenset({
    "ApplicationUsage", "AppsUsageLog", "Call", "CalendarEntry", "Chat",
    "Contact", "Email", "InstantMessage", "Location", "Party", "Voicemail",
})

#: strop textových polí v detailu (PII zásada — DB nese shrnutí, ne celá tělesa)
_MAX_TEXT = 500


def _title(fields: dict[str, str], *keys: str) -> str | None:
    for k in keys:
        v = fields.get(k)
        if v and v.strip():
            return v.strip()[:300]
    return None


# Android/iOS konvence — entities.py u "contact" artifactu čte jen title +
# mimetype, proto musí být každá hodnota (jméno/telefon/mail) vlastní artifact.
_MIME_PHONE = "vnd.android.cursor.item/phone_v2"
_MIME_EMAIL = "vnd.android.cursor.item/email_v2"


def _split_multi(value: str | None) -> list[str]:
    """multiField pole je spojeno ' | ' → rozbalí na části."""
    if not value:
        return []
    return [p.strip() for p in value.split("|") if p and p.strip()]


def contact_value_specs(
    *, name: str | None = None, phones: Sequence[str] = (), emails: Sequence[str] = (),
    engine: str = "ufdr", person_name: str | None = None,
) -> list[ArtifactSpec]:
    """Jedna karta kontaktu → N per-value contact artifactů (jméno + telefony + maile).

    Telefony/maile se validují normalizací (hodnota jako 'Mobile' v poli PhoneType
    nevytvoří falešný kontakt). Deduplikace s zachováním pořadí.
    """
    specs: list[ArtifactSpec] = []
    if name and name.strip():
        nm = person_name or name.strip()[:200]
        specs.append(ArtifactSpec("contact", nm, None, {"engine": engine}))
    seen_p: set[str] = set()
    for p in phones:
        parts = _split_multi(p) if "|" in (p or "") else [p or ""]
        for part in parts:
            raw = part.strip()[:200]
            if not raw or raw in seen_p:
                continue
            n = normalize_phone(raw)
            if n is None:  # ne telefonní číslo → přeskočit (PhoneType apod.)
                continue
            seen_p.add(raw)
            specs.append(ArtifactSpec("contact", raw, None, {
                "engine": engine, "mimetype": _MIME_PHONE,
                **({"person_name": person_name[:200]} if person_name else {}),
            }))
    seen_e: set[str] = set()
    for e in emails:
        parts = _split_multi(e) if "|" in (e or "") else [e or ""]
        for part in parts:
            raw = part.strip()[:200]
            if not raw or raw.lower() in seen_e:
                continue
            n = normalize_email(raw)
            if n is None:  # ne e-mail → přeskočit
                continue
            seen_e.add(raw.lower())
            specs.append(ArtifactSpec("contact", raw, None, {
                "engine": engine, "mimetype": _MIME_EMAIL,
                **({"person_name": person_name[:200]} if person_name else {}),
            }))
    return specs


def contact_specs_from_card(card: dict[str, object], *, engine: str) -> list[ArtifactSpec]:
    """VCF karta {name, phones[], emails[]} → per-value contact artifacty."""
    raw_name = card.get("name")
    name = raw_name if isinstance(raw_name, str) else None
    phones = [p for p in _cast_list(card.get("phones"))]
    emails = [e for e in _cast_list(card.get("emails"))]
    return contact_value_specs(
        name=name, phones=phones, emails=emails, engine=engine, person_name=name,
    )


@dataclass(frozen=True)
class ArtifactSpec:
    """Popis artefaktu pro CLI zápis (čistý — bez Pydantic modelů)."""

    artifact_type: str
    title: str | None
    timestamp: datetime | None
    details: dict[str, object] = field(default_factory=dict)


def _chat_party_names(parties: Sequence[ModelSpec]) -> list[str]:
    names: list[str] = []
    for p in parties:
        n = (p.fields.get("Name") or "").strip()
        if n and n not in names:
            names.append(n)
    return names


def _map_one(model: ModelSpec, chat_ctx: str | None = None) -> list[ArtifactSpec]:
    """Jeden model → 1..N speců. `chat_ctx` = název konverzace (pro vnořené IM)."""
    f = model.fields
    ts_key = {"Call": "TimeStamp", "Email": "TimeStamp", "Location": "StartTime",
              "CalendarEntry": "StartTime"}.get(model.model_type, "TimeStamp")
    ts = _parse_ts(f.get(ts_key))

    if model.model_type == "Contact":
        name = _title(f, "Name", "Account")
        # pole s čísly — multiField je spojeno ' | ', scalar pole jednorázově
        phone_fields: list[str] = []
        email_fields: list[str] = []
        for k in sorted(f.keys()):
            kl = k.lower()
            if any(s in kl for s in ("phone", "tel", "mobile")) and "type" not in kl:
                phone_fields.append(f[k])
            elif "email" in kl or "mail" in kl:
                email_fields.append(f[k])
        return contact_value_specs(
            name=name, phones=phone_fields, emails=email_fields, engine="ufdr",
        )

    if model.model_type == "Call":
        parties = [p for p in model.nested if p.model_type == "Party"]
        party_names = _chat_party_names(parties[:4])
        title = ", ".join(party_names) or _title(f, "NetworkName") or "(neznámá strana)"
        return [ArtifactSpec("call_log", title, ts, {
            "engine": "ufdr",
            "direction": f.get("Direction"),
            "duration": f.get("Duration"),
            "status": f.get("Status"),
            "parties": party_names,
        })]

    if model.model_type == "InstantMessage":
        body = (f.get("Body") or "").strip()[:_MAX_TEXT]
        atype = "chat_message" if chat_ctx else "sms_message"
        details: dict[str, object] = {"engine": "ufdr"}
        if f.get("FromIsOwner"):
            details["from_is_owner"] = f["FromIsOwner"]
        for k in ("Platform", "SourceApplication", "ServiceIdentifier"):
            if f.get(k):
                details[k.lower()] = f[k][:100]
        if chat_ctx:
            details["conversation"] = chat_ctx[:200]
        return [ArtifactSpec(atype, body or "(prázdná zpráva)", ts, details)]

    if model.model_type == "Chat":
        parties = _chat_party_names([p for p in model.nested if p.model_type == "Party"][:8])
        msgs = [m for m in model.nested if m.model_type == "InstantMessage"]
        specs: list[ArtifactSpec] = [ArtifactSpec(
            "chat_conversation", _title(f, "Name") or "(bez názvu)", ts, {
                "engine": "ufdr",
                "participants": parties,
                "message_count": len(msgs),
            },
        )]
        ctx = (f.get("Name") or "").strip()[:200] or None
        for m in msgs:
            specs.extend(_map_one(m, chat_ctx=ctx))
        return specs

    if model.model_type == "Email":
        frm = _title(f, "From", "Account")
        fallback = f"Email od {frm}" if frm else None
        title = _title(f, "Subject") or fallback
        details: dict[str, object] = {"engine": "ufdr"}
        for k in ("From", "To", "Folder", "Status", "Priority"):
            if f.get(k):
                details[k.lower()] = f[k][:200]
        body = (f.get("Body") or f.get("Snippet") or "").strip()[:_MAX_TEXT]
        if body:
            details["snippet"] = body
        return [ArtifactSpec("email_message", title, ts, details)]

    if model.model_type == "Location":
        details: dict[str, object] = {"engine": "ufdr"}
        for k in ("PositionAddress", "Name", "Origin", "Category"):
            if f.get(k):
                details[k.lower().replace("positionaddress", "address")] = f[k][:200]
        for k in ("Latitude", "Longitude", "GpsHorizontalAccuracy"):
            if f.get(k) is not None:
                try:
                    details["lat" if k == "Latitude" else "lon" if k == "Longitude" else "accuracy"] = float(f[k])
                except ValueError:
                    pass
        return [ArtifactSpec("location", _title(f, "Name", "PositionAddress") or "(poloha)", ts, details)]

    if model.model_type == "CalendarEntry":
        return [ArtifactSpec(
            "calendar_event", _title(f, "Subject", "Name") or "(událost)", ts,
            {"engine": "ufdr"},
        )]

    if model.model_type in ("ApplicationUsage", "AppsUsageLog"):
        details: dict[str, object] = {"engine": "ufdr"}
        for k in ("LaunchCount", "ActivationCount", "LastLaunch", "ActiveTime"):
            if f.get(k) is not None:
                try:
                    details[k.lower()] = float(f[k])
                except ValueError:
                    details[k.lower()] = f[k][:100]
        return [ArtifactSpec(
            "app_execution", _title(f, "Name", "Identifier") or "(aplikace)", ts, details,
        )]

    if model.model_type == "Voicemail":
        return [ArtifactSpec(
            "voicemail", _title(f, "From", "Subject") or "(hovorna)", ts, {"engine": "ufdr"},
        )]

    # Party a ostatní — bez samostatného artefaktu (žijí v detailu rodiče)
    return []


def models_to_artifact_specs(models: list[ModelSpec]) -> list[ArtifactSpec]:
    """Top-level modely → specy artefaktů (deterministické pořadí = pořadí reportu)."""
    specs: list[ArtifactSpec] = []
    for m in models:
        try:
            specs.extend(_map_one(m))
        except Exception:  # jeden zlomený model ≠ pád celého importu
            logger.warning("model '%s' se nepodařilo promapovat", m.model_type, exc_info=True)
    return specs


# ── VCF kontakty (MSAB / ADB logical) ─────────────────────────

_VCARD_RE = re.compile(r"BEGIN:VCARD", re.IGNORECASE)


def parse_vcf(text: str) -> list[dict[str, object]]:
    """VCard text → kontakty ``{name, phones[], emails[]}`` (strop 500 karet).

    Obsahuje standardní VCF chování, které nás zajímá: FN/TEL/EMAIL, typy
    v TEL[:CELL;...], skládání dlouhých řádků (počáteční mezikráj). Žádné I/O.
    """
    # rozbalení složených řádků (continuation = nová řádka začínající mezí/tabem)
    lines: list[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw.lstrip()
        else:
            lines.append(raw.strip())

    out: list[dict[str, object]] = []
    cur: dict[str, object] | None = None
    for line in lines[:20_000]:  # strop proti patologickému souboru
        if _VCARD_RE.search(line):
            if cur is not None and (cur.get("name") or cur.get("phones")):
                out.append(cur)
            cur = {"name": None, "phones": [], "emails": []}
            continue
        if line.upper().startswith("END:"):
            if cur is not None and (cur.get("name") or cur.get("phones")):
                out.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().upper()
        value = value.strip()
        if key == "FN" and not cur["name"]:  # type: ignore[union-attr]
            cur["name"] = value[:200] or None  # type: ignore[index]
        elif key.startswith("TEL"):
            phones = _cast_list(cur.get("phones"))
            if value and value not in phones:
                phones.append(value)
        elif key == "EMAIL":
            emails = _cast_list(cur.get("emails"))
            if value and value not in emails:
                emails.append(value[:200])
    # poslední karta bez END:VCARD (časté u exportů) — flush na konci
    if cur is not None and (cur.get("name") or cur.get("phones")):
        out.append(cur)
    return out[:500]


def _cast_list(v: object) -> list[str]:
    """Interní invariant — VCF karty začínají s `[]`; jinak nová lista."""
    return v if isinstance(v, list) else []  # type: ignore[return-value]


# ── normalizace pro korelaci entit s kontakty ─────────────────

_PHONE_STRIP_RE = re.compile(r"[^0-9+]")


def normalize_phone(value: str | None) -> str | None:
    """Telefon do kanonické podoby (pouze číslice + vedoucí '+')."""
    if not value:
        return None
    v = _PHONE_STRIP_RE.sub("", value.strip())
    if len(v) < 4 or "+" in v[1:]:
        return None
    if v.startswith("+"):
        return v
    return f"+{v}"


def normalize_email(value: str | None) -> str | None:
    """E-mail do lower-case podoby; nevalidní → None."""
    if not value:
        return None
    v = value.strip().lower()
    if "@" not in v or "." not in v.split("@", 1)[-1]:
        return None
    return v[:200]
