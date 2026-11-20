"""P3-3 — pravidlový klasifikátor souborů/artefaktů do kategorií (čistá doména).

Offline determinismus (v 3.x žádné ML/síť): kategorie vznikne kombinací
parser signatury + typové heuristiky + entity. Vstupy = pouze stav DB
(artifact_type hodnoty, extenze/signatura souboru, druhy entit) → stejné
vstupy dávají stejný výstup (AK1).

Výstup nese neprázdné ``reasons[]`` (forenzní vysvětlitelnost, AK2) a flag
``needs_review``, když je důvěra pod prahem. Rizikové signály (hash_set_hit,
bad_extension) jdou do ``risk_flags`` a do reasons.

Pravidla jsou limitována na rodiny z ``PARSER_VALIDATIONS`` rejstříku
(74 hodnot artifact_type — viz testy), aby nedošlo k rule creepu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Uzavřená množina kategorií (forenzně auditovatelná taxonomie).
CATEGORIES: tuple[str, ...] = (
    "browser",
    "chat_messaging",
    "email",
    "contact_identity",
    "cloud_sync",
    "location_tracking",
    "system_logs",
    "memory_capture",
    "crypto_assets",
    "documents_media",
    "unknown",
)

#: Kategorie pro neparsované/neznámé obsahy.
UNKNOWN_CATEGORY = "unknown"

#: Výchozí prahová důvěra; ``confidence < threshold`` → needs_review (design).
DEFAULT_THRESHOLD = 0.6

#: Slabý signál — parser selhal / typ není v rejstříku.
_UNKNOWN_WEIGHT = 0.4

#: Důvěrový bonus za potvrzení příslušnými entitami (E4).
_ENTITY_BOOST = 0.1

# ── Pravidla: artifact_type → (kategorie, váha) ──────────────────────────────
# Silný signál = 1.0; smíšené signály (např. autofill, wifi profile) = 0.6.


def _rules(*pairs: tuple[str, str, float]) -> dict[str, tuple[str, float]]:
    """Kompaktní konstruktorem pravidel (typ → (kategorie, váha))."""
    out: dict[str, tuple[str, float]] = {}
    for name, category, weight in pairs:
        if name in out:  # duplicitní pravidlo = chybná taxonomie
            raise ValueError(f"duplicitní artifact_type pravidlo: {name}")
        out[name] = (category, weight)
    return out


ARTIFACT_TYPE_RULES: dict[str, tuple[str, float]] = _rules(
    # browser
    ("browser_bookmark", "browser", 1.0),
    ("browser_cookie", "browser", 1.0),
    ("browser_history", "browser", 1.0),
    ("browser_search", "browser", 1.0),
    ("browser_setting", "browser", 1.0),
    ("browser_tab", "browser", 1.0),
    ("web_page", "browser", 1.0),
    ("google_search", "browser", 1.0),
    # chat / messaging / telefony
    ("chat_message", "chat_messaging", 1.0),
    ("messenger_message", "chat_messaging", 1.0),
    ("imessage", "chat_messaging", 1.0),
    ("sms_message", "chat_messaging", 1.0),
    ("whatsapp_message", "chat_messaging", 1.0),
    ("sns_post", "chat_messaging", 1.0),
    ("sns_comment", "chat_messaging", 1.0),
    ("skype_account", "chat_messaging", 1.0),
    ("voice_recording", "chat_messaging", 1.0),
    ("voicemail", "chat_messaging", 1.0),
    ("call_log", "chat_messaging", 1.0),
    ("call_record", "chat_messaging", 1.0),
    # e-mail
    ("email_message", "email", 1.0),
    ("email_attachment", "email", 1.0),
    ("google_mail_info", "email", 1.0),
    # identity / osobní data
    ("contact", "contact_identity", 1.0),
    ("credential", "contact_identity", 1.0),
    ("autofill_entry", "contact_identity", 0.6),
    ("google_identity_session", "contact_identity", 1.0),
    ("user_sid", "contact_identity", 1.0),
    ("google_login", "contact_identity", 1.0),
    ("calendar_event", "contact_identity", 1.0),
    # cloud exporty / účty
    ("cloud_file", "cloud_sync", 1.0),
    ("cloud_instance", "cloud_sync", 1.0),
    ("drive_activity", "cloud_sync", 1.0),
    ("google_account", "cloud_sync", 1.0),
    ("google_account_event", "cloud_sync", 1.0),
    ("google_activity", "cloud_sync", 1.0),
    ("google_device", "cloud_sync", 1.0),
    ("google_export_summary", "cloud_sync", 1.0),
    ("google_photo", "cloud_sync", 1.0),
    # lokalizace
    ("location", "location_tracking", 1.0),
    ("location_data", "location_tracking", 1.0),
    ("google_location", "location_tracking", 1.0),
    ("google_maps_activity", "location_tracking", 1.0),
    ("wifi_profile", "location_tracking", 0.6),
    # systémové logy / OS artefakty
    ("event_log_entry", "system_logs", 1.0),
    ("app_execution", "system_logs", 1.0),
    ("shell_link", "system_logs", 1.0),
    ("win_jumplist", "system_logs", 1.0),
    ("win_prefetch", "system_logs", 1.0),
    ("usn_record", "system_logs", 1.0),
    ("scheduled_task", "system_logs", 1.0),
    ("registry_hive", "system_logs", 1.0),
    ("plist_date", "system_logs", 1.0),
    ("property_list", "system_logs", 1.0),
    ("sqlite_database", "system_logs", 1.0),
    ("sqlite_deleted_row", "system_logs", 1.0),
    ("win_driver", "system_logs", 1.0),
    ("network_connection", "system_logs", 1.0),
    ("clipboard_entry", "system_logs", 1.0),
    # paměť a blokové záchyty
    ("mem_connection", "memory_capture", 1.0),
    ("mem_handle", "memory_capture", 1.0),
    ("mem_hook", "memory_capture", 1.0),
    ("mem_module", "memory_capture", 1.0),
    ("mem_process", "memory_capture", 1.0),
    ("memory_file", "memory_capture", 1.0),
    ("memory_process", "memory_capture", 1.0),
    ("disk_image", "memory_capture", 1.0),
    # kryptoměny
    ("crypto_detection", "crypto_assets", 1.0),
    ("crypto_exchange_record", "crypto_assets", 1.0),
    ("crypto_wallet", "crypto_assets", 1.0),
    # dokumenty / metadata (obsah neanalyzovaný)
    ("document_metadata", "documents_media", 1.0),
    ("file_metadata", "documents_media", 1.0),
    # parser selhal → obsah neznámý (slabý signál)
    ("parser_error", UNKNOWN_CATEGORY, _UNKNOWN_WEIGHT),
)

# ── Heuristika souboru (pouze když chybí artifact_type signály) ──────────────

#: Binární signatura (files.signature_type) → (kategorie, váha).
# Váhy pod výchozím prahem 0.6 — neparsovaný soubor vždy jde do revize.
SIGNATURE_RULES: dict[str, tuple[str, float]] = {
    "evtx": ("system_logs", 0.5),
    "registry_hive": ("system_logs", 0.5),
    "win_prefetch": ("system_logs", 0.4),
    "plist": ("system_logs", 0.35),
    "lnk": ("system_logs", 0.35),
    "sqlite": (UNKNOWN_CATEGORY, 0.3),
}

#: Extenze → (kategorie, váha). Pouze když parser nic neextrahoval.
_DOCUMENT_EXTS = frozenset(
    {"docx", "doc", "pdf", "xls", "xlsx", "pptx", "txt", "md"}
)
_MEDIA_EXTS = frozenset(
    {
        "jpg",
        "jpeg",
        "png",
        "gif",
        "bmp",
        "webp",
        "mp4",
        "mov",
        "avi",
        "wmv",
        "mp3",
        "wav",
        "m4a",
    }
)

#: Kategorie, které potvrzují příslušné druhy entit (E4 corroboration).
_ENTITY_CONFIRM: dict[str, tuple[str, ...]] = {
    "chat_messaging": ("phone", "email"),
    "email": ("email",),
    "contact_identity": ("phone", "email"),
}


@dataclass(frozen=True)
class ClassificationInput:
    """Vstup klasifikátoru — pouze stav DB, žádné I/O (čistá doména)."""

    file_name: str = ""  # basename pro reason texty
    file_extension: str = ""  # bez tečky, malá písmena
    signature_type: str | None = None  # files.signature_type (6 binárních typů)
    bad_extension: bool = False
    hash_set_hit: bool = False
    artifact_types: tuple[str, ...] = ()  # distinct artifact_type pro soubor
    entity_kinds: tuple[str, ...] = ()  # distinct druhy entit ze souboru

    def extension_key(self) -> str:
        """Klíč heuristiky: binární signatura má přednost před extenzí."""
        if self.signature_type:
            return f"_sig_{self.signature_type}"
        return (self.file_extension or "").lower()


@dataclass(frozen=True)
class Classification:
    """Výsledek klasifikace — deterministický a vysvětlitelný."""

    category: str
    confidence: float  # 0..1, zaokrouhleno na 2 desetinná místa
    reasons: tuple[str, ...]  # vždy neprázdné (AK2)
    needs_review: bool
    risk_flags: tuple[str, ...] = field(default=())


def _score_artifact_buckets(artifact_types: tuple[str, ...]) -> dict[str, float]:
    """Vážené součty signálů per kategorie (kap 1.0 na kategorii)."""
    buckets: dict[str, float] = {}
    for art_type in artifact_types:
        category, weight = ARTIFACT_TYPE_RULES.get(
            art_type, (UNKNOWN_CATEGORY, _UNKNOWN_WEIGHT)
        )
        current = buckets.get(category, 0.0)
        buckets[category] = min(1.0, current + weight)
    return buckets


def classify(
    input: ClassificationInput, threshold: float = DEFAULT_THRESHOLD
) -> Classification:
    """Pravidlová klasifikace jednoho souboru (deterministická, bez I/O).

    :param threshold: prahová důvěra; ``confidence < threshold`` → needs_review.
        Musí ležet v intervalu ``(0; 1]``, jinak ``ValueError``.
    """
    if not (0 < threshold <= 1):
        raise ValueError(f"threshold musí být v intervalu (0; 1], je {threshold!r}")

    reasons: list[str] = []
    risk_flags: list[str] = []
    if input.hash_set_hit:
        risk_flags.append("hash_set_hit")
        reasons.append("hash nalezen ve známém hash setu (riziko)")
    if input.bad_extension:
        risk_flags.append("bad_extension")
        reasons.append("nesouhlasí extenze s detekovaným typem souboru")

    buckets = _score_artifact_buckets(input.artifact_types)
    heuristic_only = False

    if buckets:
        winner = max(buckets.items(), key=lambda kv: (kv[1], CATEGORIES.index(kv[0])))
        category, raw_score = winner
        total = sum(buckets.values())
        confidence = round(raw_score / total, 2) if total > 0 else 0.0
        matched = [t for t in input.artifact_types if ARTIFACT_TYPE_RULES.get(t)]
        unmatched = [
            t for t in input.artifact_types if t not in ARTIFACT_TYPE_RULES
        ]
        prefix = f"{input.file_name}: " if input.file_name else ""
        reasons.append(
            f"{prefix}artifact_type signály → kategorie {category} "
            f"(score {raw_score:.2f}/{total:.2f})"
        )
        if matched:
            sample = ", ".join(sorted(set(matched))[:3])
            suffix = " …" if len(set(matched)) > 3 else ""
            reasons.append(f"typy artefaktů: {sample}{suffix}")
        if unmatched:
            reasons.append(
                f"neznámé artifact_type (slabý signál): {', '.join(sorted(set(unmatched)))}"
            )
        if category == UNKNOWN_CATEGORY and len(buckets) == 1:
            # jen parser_error / neznámé typy → nízka důvěra i když "vyhrává"
            confidence = min(confidence, _UNKNOWN_WEIGHT)
            reasons.append("obsah neprošel parsováním — nízká důvěra")

    else:
        # žádné parser artefakty → heuristika extenze/signatury (kap 0.5)
        heuristic_only = True
        category, weight = _heuristic_score(input.extension_key())
        confidence = round(weight, 2) if weight else 0.2
        if category is None:
            category = UNKNOWN_CATEGORY  # žádný signál → explicitně unknown
            reasons.append(
                "žádné artefakty ani rozpoznaná extenze/signatura — neznámý obsah"
            )
        elif input.signature_type == "sqlite":
            # signatura rozeznána, ale obecný kontejner → obsah neurčen
            reasons.append(
                f"bez parser artefaktů — {input.signature_type} je obecný kontejner,"
                " obsah neurčen"
            )
        else:
            reasons.append(
                f"bez parser artefaktů — klasifikace podle heuristiky souboru → {category}"
            )

    # corroboration entitami (pouze u komunikacích kategorií)
    confirm = _ENTITY_CONFIRM.get(category, ())
    if not heuristic_only and confirm:
        present = [k for k in input.entity_kinds if k in confirm]
        if present:
            confidence = round(min(1.0, confidence + _ENTITY_BOOST), 2)
            reasons.append(f"potvrzeno entitami ({', '.join(sorted(present))})")

    needs_review = confidence < threshold
    if needs_review:
        reasons.append(
            f"důvěra {confidence:.2f} pod prahem {threshold:.2f} — k revizi"
        )

    return Classification(
        category=category,
        confidence=confidence,
        reasons=tuple(reasons),
        needs_review=needs_review,
        risk_flags=tuple(risk_flags),
    )


def _heuristic_score(extension_key: str) -> tuple[str | None, float]:
    """Heuristika pouze pro soubory bez parser artefaktů (kap 0.5).

    ``extension_key`` je buď ``_sig_<signature_type>`` nebo holá extenze —
    signatura má přednost (binární ověření > jméno souboru).
    """
    if extension_key.startswith("_sig_"):
        category, weight = SIGNATURE_RULES.get(
            extension_key[len("_sig_") :], (None, 0.2)
        )
    elif extension_key in _DOCUMENT_EXTS:
        return "documents_media", 0.5
    elif extension_key in _MEDIA_EXTS:
        return "documents_media", 0.4
    else:
        category, weight = None, 0.2
    # heuristika nikdy nedosáhne plné důvěry — obsah nebyl parsován
    if category is not None and weight > 0.5:
        weight = 0.5
    return category, min(weight, 0.5)


def classification_to_dict(c: Classification) -> dict:
    """Serializace pro CLI/Web (aditivní povrch P3-3 W2)."""
    return {
        "category": c.category,
        "confidence": c.confidence,
        "reasons": list(c.reasons),
        "needs_review": c.needs_review,
        "risk_flags": list(c.risk_flags),
    }

