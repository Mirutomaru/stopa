"""STP-071 — Normalizační vrstva diferenciálního testování parserů (oblast P).

První celek schváleného designu ``docs/DIFFERENTIAL_TESTING.md`` (§3) pro
release 2.8: čistá doménová funkce **bez IO**, která převádí surové záznamy
parseru STOPA i referenčního nástroje na jediný **canonical record** tvar —
jediný tvar, který vidí komparační engine (§4).

Pravidla dle designu §3:

1. **Čas:** vše → Unix epoch sekundy UTC; zdrojové epochy (CFAbsoluteTime,
   Windows FILETIME) se přepočítávají deklarovanou konverzí — tabulku epoch
   zná parser, normalizace validuje typ a aplikuje offset.
2. **Řazení:** soubory záznamů se řadí deterministicky (typ → ts → stabilní
   klíč); pořadí v surovém výstupu se nepočítá jako rozdíl.
3. **Kódování/locale:** textová pole → NFKC; ``None`` ≠ ``""``
   (chybějící pole ≠ prázdné pole).
4. **Join key:** každý typ artefaktu má deklarovaný join key; bez něj se
   komparace nespustí — lépe selže explicitně než srovná řádky po sobě.

Komparační engine (§4–5) a CLI ``stopa differential`` = další celek (vlna 28).
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

# ── Zdrojové epochy (design §3.1) ────────────────────────────────────────
# unix:        Unix epoch sekundy (výchozí; STOPA interně pracuje v UTC)
# cfabsolute:  CFAbsoluteTime — sekundy od 2001-01-01T00:00:00Z
# windows_filetime: FILETIME — 100 ns intervaly od 1601-01-01T00:00:00Z

EPOCH_UNIX = "unix"
EPOCH_CFABSOLUTE = "cfabsolute"
EPOCH_WINDOWS_FILETIME = "windows_filetime"

#: unix − CFAbsoluteTime (2001-01-01T00:00:00Z v Unix epoch sekundách)
_CFABSOLUTE_OFFSET_S = 9_783_072_00.0
#: Windows FILETIME epoch offset: 1601→1970 v sekundách (int — přesná celočíselná cesta)
_FILETIME_EPOCH_S = 11_644_473_600
#: FILETIME jednotka: 100 ns interval → dělit na sekundy
_FILETIME_SCALE = 1e-7

#: Zvláštní token pro join key — odkazuje na ``ts_epoch`` záznamu (ne field)
TS_KEY = "ts"

#: Deklarace join klíčů: typ artefaktu → pořadová n-tice jmen polí (token TS_KEY povolen)
JoinKeySpec = tuple[str, ...]


def _as_finite_float(value: Any, what: str) -> float:
    """Value → konečné float; typová chyba ≠ semantická chyba.

    Raises:
        TypeError: value není číslo ani číselný string (bool se počítá jako
            typová chyba — ``isinstance(True, int)`` je v Pythonu True).
        ValueError: číselný string se nedá parsovat, nebo NaN/±inf.
    """
    if isinstance(value, bool):
        raise TypeError(f"{what}: bool není epoch hodnota (překážka isinstance(True, int))")
    if isinstance(value, (int, float)):
        number = value
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{what}: číselný string se nedaří parsovat: {value!r}") from exc
    else:
        raise TypeError(f"{what}: očekáváno číslo/číselný string, dostalo {type(value).__name__}")
    if not math.isfinite(number):
        raise ValueError(f"{what}: hodnota musí být konečná, dostalo {number!r}")
    return number


def normalize_ts(value: Any, epoch: str = EPOCH_UNIX) -> int:
    """Surová hodnota → Unix epoch sekundy UTC (int; podsekundová část se zaokrouhluje dolů).

    Args:
        value: číselná hodnota v deklarované zdrojové epoše (int/float/číselný string).
        epoch: jedna z ``EPOCH_UNIX`` / ``EPOCH_CFABSOLUTE`` / ``EPOCH_WINDOWS_FILETIME``.

    Raises:
        TypeError: nečíslný typ (včetně bool).
        ValueError: neznámá epocha, NaN/±inf, neparsovatelný string.
    """
    number = _as_finite_float(value, "ts")
    if epoch == EPOCH_UNIX:
        seconds = number
    elif epoch == EPOCH_CFABSOLUTE:
        seconds = number + _CFABSOLUTE_OFFSET_S
    elif epoch == EPOCH_WINDOWS_FILETIME:
        # int vstup (případně celočíselný string) → přesná celočíselná aritmetika
        # (float64 by u FILETIME hodnot ~1.3e17 — nad 2^53 — mohl zaokrouhlit pod
        # celosekundovou hranici a vrátit s-1)
        text = str(value).strip() if isinstance(value, str) else None
        if isinstance(value, int):
            return value // 10_000_000 - _FILETIME_EPOCH_S
        if text is not None and text.isdigit():
            return int(text) // 10_000_000 - _FILETIME_EPOCH_S
        seconds = number * _FILETIME_SCALE - _FILETIME_EPOCH_S
    else:
        raise ValueError(f"ts: neznámá zdrojová epocha {epoch!r}")
    return math.floor(seconds)


def normalize_field_value(value: Any) -> Any:
    """Normalizace jednoho pole canonical recordu (design §3.3).

    str → NFKC normalizace; int/float/bool → beze změny; ``None`` → ``None``
    (chybějící pole ≠ prázdný string — explicitní rozlišení); ostatní typy
    (dict/list/tuple…) → TypeError, canonical fields jsou ploché.

    Raises:
        TypeError: složitý/normální nestrukturovaný typ.
        ValueError: nekonečné float pole (porušuje determinismus sérializace).
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFKC", value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"field: nekonečné float {value!r}")
        return value
    raise TypeError(f"canonical field: očekáváno str/int/float/bool/None, dostalo {type(value).__name__}")


@dataclass(frozen=True)
class CanonicalRecord:
    """Normalizovaný záznam — jediný tvar, který vidí komparační engine (design §3.5).

    Tvar ``{type, ts_epoch, fields}`` nezávislý na formátu vstupního nástroje.
    ``fields`` je neměnné mapping (záznam je immutable artefakt).
    """

    type: str
    ts_epoch: int | None  # None = záznam bez času (nechává se, engine to vidí explicitně)
    fields: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.fields, MappingProxyType):
            object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))


def canonicalize(
    artifact_type: str,
    ts_value: Any | None,
    fields_raw: Mapping[str, Any],
    *,
    epoch: str = EPOCH_UNIX,
) -> CanonicalRecord:
    """Surový záznam parseru/reference → :class:`CanonicalRecord` (design §3.5).

    Args:
        artifact_type: typ artefaktu (neprázný str).
        ts_value: čas v deklarované epoše, nebo None (záznam bez času).
        fields_raw: surová pole; hodnoty se normalizují (NFKC atd.), klíče musí být str.
        epoch: zdrojová epocha ``ts_value`` (výchozí unix).

    Raises:
        TypeError: ne-klíč string, nečíslný ts, složitá field hodnota.
        ValueError: prázdný typ, neznámá epocha, nekonečné float pole.
    """
    if not isinstance(artifact_type, str):
        raise TypeError(f"type: očekáváno str, dostalo {type(artifact_type).__name__}")
    if not artifact_type:
        raise ValueError("type: typ artefaktu nesmí být prázdný")
    ts_epoch = None if ts_value is None else normalize_ts(ts_value, epoch)
    fields: dict[str, Any] = {}
    for key, value in fields_raw.items():
        if not isinstance(key, str):
            raise TypeError(f"fields: klíč musí být str, dostalo {type(key).__name__}")
        fields[key] = normalize_field_value(value)
    return CanonicalRecord(type=artifact_type, ts_epoch=ts_epoch, fields=fields)


def make_join_key(record: CanonicalRecord, spec: JoinKeySpec) -> str:
    """Deterministický join key z deklarovaných polí (design §3.4).

    Spec je pořadová n-tice jmen polí canonical recordu; token :data:`TS_KEY`
    odkazuje na ``ts_epoch``. Hodnoty se kódují ``repr()`` a spojovají ASCII
    unit separator (\\x1f) — deterministické i pro hodnoty obsahující běžné
    oddělovače.

    Chybějící pole (klíč neexistuje nebo hodnota je None) → ValueError: bez
    join key se komparace nespustí, lépe explicitní selhání než srovnání
    řádků po sobě.

    Raises:
        ValueError: prázdný spec, nebo chybějící/None join klíčové pole.
    """
    if not spec:
        raise ValueError("join key: spec nesmí být prázdný")
    parts: list[str] = []
    for name in spec:
        if name == TS_KEY:
            value: Any = record.ts_epoch
        else:
            value = record.fields.get(name)
        if value is None:
            raise ValueError(f"join key: chybějící pole {name!r} (typ {record.type!r})")
        parts.append(repr(value))
    return "\x1f".join(parts)


def _sort_key(record: CanonicalRecord) -> tuple[str, int, int, str]:
    """Deterministické řazení dle designu §3.2: typ → ts → stabilní klíč.

    Záznamy bez času se řadí za záznamy s časem uvnitř stejného typu (flag 1).
    Stabilní klíč = pole seřazená podle jména v repr formě — pořadí ve field
    mappingu a pořadí surového výstupu se nepočítá jako rozdíl.
    """
    stable = "\x1f".join(f"{k}={v!r}" for k, v in sorted(record.fields.items()))
    ts_part = (0, record.ts_epoch) if record.ts_epoch is not None else (1, 0)
    return (record.type, ts_part[0], ts_part[1], stable)


def sort_records(records: Iterable[CanonicalRecord]) -> list[CanonicalRecord]:
    """Deterministicky seřazená kopie souboru záznamů (design §3.2)."""
    return sorted(records, key=_sort_key)


def normalize_dataset(
    entries: Iterable[Mapping[str, Any]],
    join_keys: Mapping[str, JoinKeySpec] | None = None,
) -> list[CanonicalRecord]:
    """Batch normalizace surových záznamů + deterministické řazení (design §3.1–3.2).

    Každý vstupní záznam je mapping s klíči ``type`` (str), ``fields``
    (mapping) a volitelně ``ts`` (epoch hodnota, výchozí None) a ``epoch``
    (zdrojová epocha, výchozí unix). Pokud typ má deklarovaný join key spec,
    validuje se přítomnost všech klíčových polí (chybějící → ValueError).

    Args:
        entries: surové záznamy parseru STOPA i referenčního nástroje.
        join_keys: deklarace join klíčů dle typu artefaktu (None = bez validace).

    Returns:
        Seřazená lista :class:`CanonicalRecord` (typ → ts → stabilní klíč).

    Raises:
        TypeError: vstup není mapping, ``type`` chybí/nebo není str, ne-klíč string v fields.
        ValueError: chybějící ``fields``, prázdný typ, chybějící join key pole.
    """
    records: list[CanonicalRecord] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise TypeError(f"dataset entry: očekáváno mapping, dostalo {type(entry).__name__}")
        artifact_type = entry.get("type")
        if "fields" not in entry:
            raise ValueError(f"dataset entry: chybějící klíč 'fields' (typ={artifact_type!r})")
        if not isinstance(artifact_type, str):
            raise TypeError(
                f"dataset entry: 'type' musí být str, dostalo {type(artifact_type).__name__}"
            )
        record = canonicalize(
            artifact_type,
            entry.get("ts"),
            entry["fields"],
            epoch=entry.get("epoch", EPOCH_UNIX),
        )
        spec = join_keys.get(record.type) if join_keys else None
        if spec:
            make_join_key(record, spec)  # validace přítomnosti klíčových polí
        records.append(record)
    return sort_records(records)
