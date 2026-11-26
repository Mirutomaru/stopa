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

Komparační engine (§4–5) a CLI ``stopa differential`` (vlna 28 / STP-072):
:class:`Difference`, :func:`compare_records`, :class:`DifferentialReport`,
:func:`build_report`, adjudikace (:func:`adjudicate`) a exit kódy (§6).
"""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
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


# ════════════════════════════════════════════════════════════════
# Komparační engine (design §4–5) — vlna 28 / STP-072
# ════════════════════════════════════════════════════════════════

#: Kind rozdílu (§4). Třídí se podle sémantiky, ne podle toho „kdo má víc".
KIND_MISSING_IN_REF = "missing_in_ref"  # záznam má reference, chybí ve STOPA (STOPA podává méně dat)
KIND_EXTRA_IN_STOPA = "extra_in_stopa"  # záznam má STOPA, nemá ho reference
KIND_FIELD_DIFFERS = "field_differs"  # shoda join keyu, liší se obsah (pole nebo ts_epoch)

#: Stavy adjudikace (§5) — každý rozdíl má stav rozhodnutí + zdůvodnění.
STATUS_UNADJUDICATED = "UNADJUDICATED"  # default: čeká na člověka
STATUS_STOPA_WRONG = "STOPA_WRONG"  # bug parseru STOPA → ticket
STATUS_REF_WRONG = "REF_WRONG"  # chyba referenčního nástroje
STATUS_SEMANTIC_DIFF = "SEMANTIC_DIFF"  # obojí „pravdivé", jiná reprezentace
STATUS_AMBIGUOUS = "AMBIGUOUS"  # otevřené rozhodnutí (dokumentováno)

#: Validní stavy adjudikace (ověření vstupů :func:`adjudicate`).
ADJUDICATION_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_UNADJUDICATED,
        STATUS_STOPA_WRONG,
        STATUS_REF_WRONG,
        STATUS_SEMANTIC_DIFF,
        STATUS_AMBIGUOUS,
    }
)


def join_key_display(record: CanonicalRecord, spec: JoinKeySpec) -> str:
    """Čitelný tvar join keyu pro report a adjudikace (vzor designu §4).

    ``type:value`` pro jedno pole, ``type:v1:v2…`` pro více polí; :data:`TS_KEY`
    se vykresluje jako epoch. Vstup musí být záznam validní dle ``spec``
    (tj. prošlý přes :func:`make_join_key`, který zajistí přítomnost polí).

    Returns:
        Deterministický str — stejný záznam → vždy stejný tvar.
    """
    parts = [
        str(record.ts_epoch if name == TS_KEY else record.fields[name]) for name in spec
    ]
    return f"{record.type}:{':'.join(parts)}"


@dataclass(frozen=True)
class Difference:
    """Jeden rozdíl mezi výstupem STOPA a reference (design §4 + stavy §5).

    Jednostranné rozdíly (``missing_in_ref`` / ``extra_in_stopa``) agregují
    kopie se stejným join keyem do jednoho záznamu s polem ``count`` (přítomné
    jen když > 1 — běžný případ odpovídá tvaru vzoru v designu). ``field_differs``
    má vždy konkrétní pole a hodnoty obou stran.

    Attributes:
        kind: :data:`KIND_MISSING_IN_REF` / :data:`KIND_EXTRA_IN_STOPA` /
            :data:`KIND_FIELD_DIFFERS`.
        join_key: čitelný tvar dle :func:`join_key_display`.
        field: jméno pole (``ts_epoch`` nebo field) — jen pro ``field_differs``.
        stopa_value / ref_value: hodnoty obou stran — jen pro ``field_differs``.
        count: počet kopii se stejným join keyem na jedné straně (None/1 = jedna).
        status: stav adjudikace (§5), default :data:`STATUS_UNADJUDICATED`.
        reason: zdůvodnění verdiktu (jen po adjudikaci).
    """

    kind: str
    join_key: str
    field: str | None = None
    stopa_value: Any | None = None
    ref_value: Any | None = None
    count: int | None = None
    status: str = STATUS_UNADJUDICATED
    reason: str | None = None

    @property
    def id(self) -> str:
        """Deterministická identita pro adjudikace (unikační v rámci reportu)."""
        base = f"{self.kind}:{self.join_key}"
        return f"{base}:{self.field}" if self.field is not None else base

    def to_dict(self) -> dict[str, Any]:
        """JSON tvar dle designu §4 (+ stavy adjudikace §5)."""
        out: dict[str, Any] = {"kind": self.kind, "join_key": self.join_key}
        if self.count is not None and self.count != 1:
            out["count"] = self.count
        if self.field is not None:
            out["field"] = self.field
            out["stopa_value"] = self.stopa_value
            out["ref_value"] = self.ref_value
        out["status"] = self.status
        if self.reason is not None:
            out["reason"] = self.reason
        return out


@dataclass(frozen=True)
class ComparisonResult:
    """Výsledek komparace dvou sad canonical records (design §4).

    Attributes:
        differences: deterministicky seřazené rozdíly (kind → join key → field).
        identical_pairs: počet spárovaných záznamů bez jediného rozdílu.
        union_size: velikost sjednocení multisadu záznamů (max po klíči).
    """

    differences: tuple[Difference, ...]
    identical_pairs: int
    union_size: int

    @property
    def identical_pct(self) -> float:
        """Podíl identických párových záznamů na sjednocení (% za 1 desetinné místo).

        Prázdná obě strany → 100.0 (triviální shoda). Zaokrouhlení ``round`` —
        deterministické (banker's rounding je konzistentní mezi běhy i platformami).
        """
        if self.union_size == 0:
            return 100.0
        return round(100.0 * self.identical_pairs / self.union_size, 1)


def _index_by_join_key(
    records: Sequence[CanonicalRecord], join_keys: Mapping[str, JoinKeySpec]
) -> dict[str, list[CanonicalRecord]]:
    """Interní index: join key (repr kódování) → deterministicky seřazená kopie.

    Raises:
        TypeError: záznam není :class:`CanonicalRecord`.
        ValueError: typ bez deklarovaného join keyu (§3.4 fail-fast), chybějící
            klíčové pole (:func:`make_join_key`).
    """
    out: dict[str, list[CanonicalRecord]] = {}
    for record in records:
        if not isinstance(record, CanonicalRecord):
            raise TypeError(
                f"záznam: očekáváno CanonicalRecord, dostalo {type(record).__name__}"
            )
        spec = join_keys.get(record.type)
        if spec is None:
            raise ValueError(
                f"join key: typ {record.type!r} nemá deklarovaný join key — "
                "komparace se nespustí (design §3.4)"
            )
        out.setdefault(make_join_key(record, spec), []).append(record)
    return out


def _compare_values(stopa_rec: CanonicalRecord, ref_rec: CanonicalRecord) -> list[tuple[str, Any, Any]]:
    """Rozdílné položky spárovaných záznamů (ts_epoch + sjednocení field klíčů).

    Chybějící klíč se hodnotově ekvivalentní ``None`` (value-level equivalence —
    explicitní None a absentní pole jsou v canonical tvaru to samé); srovnání je
    Python rovností skalárů. Seřazeno podle jména pole → deterministické.
    """
    out: list[tuple[str, Any, Any]] = []
    if stopa_rec.ts_epoch != ref_rec.ts_epoch:
        out.append(("ts_epoch", stopa_rec.ts_epoch, ref_rec.ts_epoch))
    for name in sorted(set(stopa_rec.fields) | set(ref_rec.fields)):
        stopa_value = stopa_rec.fields.get(name)
        ref_value = ref_rec.fields.get(name)
        if stopa_value != ref_value:
            out.append((name, stopa_value, ref_value))
    return out


def compare_records(
    stopa: Iterable[CanonicalRecord],
    ref: Iterable[CanonicalRecord],
    join_keys: Mapping[str, JoinKeySpec],
) -> ComparisonResult:
    """Deterministická komparace dvou sad canonical records (design §4).

    Postup dle designu: obě strany se (re-)seřadí deterministicky (§3.2),
    záznamy se spárují podle deklarovaného join keyu; pořadí surového výstupu
    se nepočítá jako rozdíl. Pro každý klíč se páruje pozicí (min(count) párů —
    řazení maximalizuje počet identických párů), nespárované kopie tvoří
    jednostranné rozdíly, spárované záznamy se porovnávají po polích.

    Args:
        stopa: normalizované záznamy parseru STOPA (§3).
        ref: normalizované záznamy referenčního nástroje (§3).
        join_keys: deklarace join klíčů dle typu — musí pokrývat každý typ
            přítomný v datech, jinak ValueError (fail-fast, §3.4).

    Returns:
        :class:`ComparisonResult` s deterministicky seřazenými rozdíly
        (kind → join key → field) a statistikou shody.

    Raises:
        TypeError: záznam není :class:`CanonicalRecord`.
        ValueError: typ bez deklarovaného join keyu, chybějící klíčové pole.
    """
    stopa_list = list(stopa)
    ref_list = list(ref)
    # typová validace PŘED řazením (sort_records předpokládá CanonicalRecord)
    for record in [*stopa_list, *ref_list]:
        if not isinstance(record, CanonicalRecord):
            raise TypeError(
                f"záznam: očekáváno CanonicalRecord, dostalo {type(record).__name__}"
            )
    stopa_sorted = sort_records(stopa_list)
    ref_sorted = sort_records(ref_list)
    stopa_by_key = _index_by_join_key(stopa_sorted, join_keys)
    ref_by_key = _index_by_join_key(ref_sorted, join_keys)

    differences: list[Difference] = []
    identical_pairs = 0
    union_size = 0
    for key in sorted(set(stopa_by_key) | set(ref_by_key)):
        stopa_list = stopa_by_key.get(key, [])
        ref_list = ref_by_key.get(key, [])
        union_size += max(len(stopa_list), len(ref_list))
        paired = min(len(stopa_list), len(ref_list))

        for i in range(paired):
            stopa_rec = stopa_list[i]
            ref_rec = ref_list[i]
            diffs = _compare_values(stopa_rec, ref_rec)
            if not diffs:
                identical_pairs += 1
                continue
            spec = join_keys[stopa_rec.type]
            display = join_key_display(stopa_rec, spec)
            for field_name, stopa_value, ref_value in diffs:
                differences.append(
                    Difference(
                        kind=KIND_FIELD_DIFFERS,
                        join_key=display,
                        field=field_name,
                        stopa_value=stopa_value,
                        ref_value=ref_value,
                    )
                )

        extra_stopa = len(stopa_list) - paired
        if extra_stopa:
            spec = join_keys[stopa_list[0].type]
            display = join_key_display(stopa_list[0], spec)
            differences.append(
                Difference(kind=KIND_EXTRA_IN_STOPA, join_key=display, count=_maybe_count(extra_stopa))
            )
        extra_ref = len(ref_list) - paired
        if extra_ref:
            spec = join_keys[ref_list[0].type]
            display = join_key_display(ref_list[0], spec)
            differences.append(
                Difference(kind=KIND_MISSING_IN_REF, join_key=display, count=_maybe_count(extra_ref))
            )

    differences.sort(key=lambda d: (d.kind, d.join_key, d.field or ""))
    return ComparisonResult(
        differences=tuple(differences), identical_pairs=identical_pairs, union_size=union_size
    )


def _maybe_count(n: int) -> int | None:
    """Počet kopii pro report — 1 se do JSON nepíše (tvar vzoru designu §4)."""
    return n if n > 1 else None


@dataclass(frozen=True)
class DifferentialReport:
    """Nezměnitelný, deterministický komparační report (design §4).

    Tvar odpovídá vzoru v ``docs/DIFFERENTIAL_TESTING.md`` §4 (+ stavy a
    zdůvodnění adjudikace §5 u každého rozdílu, + deklarovaný ``run_id`` —
    jediný povolený nestabilní prvek; bez něj je report bit-po-bit reprodukovatelný).
    """

    parser: str
    input_sha256: str | None
    reference_tool: str | None
    stopa_records: int
    ref_records: int
    differences: tuple[Difference, ...]
    identical_pct: float
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Strukturovaný tvar reportu (klíčové jména dle designu §4)."""
        return {
            "parser": self.parser,
            "input_sha256": self.input_sha256,
            "reference_tool": self.reference_tool,
            "stopa_records": self.stopa_records,
            "ref_records": self.ref_records,
            "differences": [d.to_dict() for d in self.differences],
            "identical_pct": self.identical_pct,
            "run_id": self.run_id,
        }

    def to_json(self) -> str:
        """Kanonical JSON — deterministický (seřazené klíče, kompaktní separátory)."""
        return json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )


def build_report(
    *,
    parser: str,
    stopa_records: Iterable[CanonicalRecord],
    ref_records: Iterable[CanonicalRecord],
    join_keys: Mapping[str, JoinKeySpec],
    input_sha256: str | None = None,
    reference_tool: str | None = None,
    run_id: str | None = None,
) -> DifferentialReport:
    """Komparace + metadata → nezměnitelný report (design §4).

    Args:
        parser: identifikátor parseru STOPA (neprázný str — report metadata).
        stopa_records / ref_records: normalizované sady (§3) obou stran.
        join_keys: deklarace join klíčů dle typu (pokrýt každý typ v datech).
        input_sha256: SHA-256 vstupního artefaktu STOPA (pro stopu do reportu).
        reference_tool: identifikátor referenčního nástroje (návrh designu §10.2).
        run_id: deklarovaný run ID (jediný povolený nestabilní prvek, §4).

    Raises:
        TypeError: ``parser`` není str.
        ValueError: prázdný ``parser``, nebo chyba komparace (join keys atd.).
    """
    if not isinstance(parser, str):
        raise TypeError(f"parser: očekáváno str, dostalo {type(parser).__name__}")
    if not parser:
        raise ValueError("parser: identifikátor parseru nesmí být prázdný")
    stopa_list = list(stopa_records)
    ref_list = list(ref_records)
    result = compare_records(stopa_list, ref_list, join_keys)
    return DifferentialReport(
        parser=parser,
        input_sha256=input_sha256,
        reference_tool=reference_tool,
        stopa_records=len(stopa_list),
        ref_records=len(ref_list),
        differences=result.differences,
        identical_pct=result.identical_pct,
        run_id=run_id,
    )


def adjudicate(
    differences: Sequence[Difference],
    decisions: Mapping[str, str | Mapping[str, Any]],
) -> list[Difference]:
    """Aplikace verdiktů adjudikace (§5) — vrací novou listu, vstup se nemění.

    ``decisions`` je mapa ID rozdílu (:attr:`Difference.id`) na stav rozhodnutí
    nebo mapping ``{"status": …, "reason": …}`. Každý rozdíl má stav +
    zdůvodnění; default :data:`STATUS_UNADJUDICATED` zůstává u nerozhodnutých.

    Raises:
        ValueError: neznámé ID rozdílu (fail-fast — žádné tiché opomenutí),
            nevalidní stav, ne-klíč string reason, prázdný status.
    """
    known_ids = {d.id for d in differences}
    unknown = set(decisions) - known_ids
    if unknown:
        raise ValueError(
            f"adjudikace: neznámé ID rozdílu {min(unknown)!r} "
            "(fail-fast — žádné tiché opomenutí)"
        )
    out: list[Difference] = []
    for difference in differences:
        if difference.id not in decisions:
            out.append(difference)
            continue
        decision = decisions[difference.id]
        reason: str | None = None
        if isinstance(decision, Mapping):
            status = decision.get("status")
            reason = decision.get("reason")
        else:
            status = decision
        if not isinstance(status, str) or not status:
            raise ValueError(f"adjudikace {difference.id}: stav musí být neprázdný str")
        if status not in ADJUDICATION_STATUSES:
            raise ValueError(
                f"adjudikace {difference.id}: neznámý stav {status!r} "
                f"(validní: {sorted(ADJUDICATION_STATUSES)})"
            )
        if reason is not None and not isinstance(reason, str):
            raise ValueError(f"adjudikace {difference.id}: reason musí být str nebo None")
        out.append(replace(difference, status=status, reason=reason))
    return out


def exit_code_for(differences: Sequence[Difference]) -> int:
    """Exit kód CLI ``stopa differential`` (design §6).

    - **0** — shoda: žádné rozdíly vůbec.
    - **3** — existují jen rozdíly adjudikované jako :data:`STATUS_SEMANTIC_DIFF`
      (obočí „pravdivé", jiná reprezentace — ne-regrese).
    - **1** — ostatní případy: jakýkoli neadjudikovaný rozdíl, nebo adjudikovaný
      jako STOPA_WRONG / REF_WRONG / AMBIGUOUS (konzervativní volba: dokud se
      nezavře verdikt, exit zůstává 1).
    """
    if not differences:
        return 0
    if all(d.status == STATUS_SEMANTIC_DIFF for d in differences):
        return 3
    return 1
