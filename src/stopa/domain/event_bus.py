"""P4-7 — DB event bus: čistá doména (bez I/O).

Kanonický tvar LiveEvent události pro cross-process distribuci přes instance DB
(tabulka ``events``, viz :data:`stopa.data.schema.EVENT_BUS_DDL`). Pořadí
událostí je dáno monotónním ``id`` řádku — ne časem (bez clock driftu napříč
procesy); ``ts_utc`` slouží jen diagnostice a pruningu.

Sémantika chyb (STOPA konvence): typová chyba = ``TypeError``, semantická =
``ValueError``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime


def make_event(etype: str, case_id: str | None, *, ts: str, **payload) -> dict:
    """Kanonická událost pro DB bus (tvar LiveEvent z F4.2).

    :param etype: Typ události (např. ``artifact_extracted``); prázdný → ValueError.
    :param case_id: ID případu nebo ``None`` (globální událost).
    :param ts: ISO UTC čas (diagnostika; pořadí = id řádku, ne čas).
    :param payload: Další pole (libovolné JSON-safe hodnoty).
    :raises ValueError: Prázdný typ / ne-ISO ``ts``.
    """
    if not isinstance(etype, str) or not etype:
        raise ValueError(f"typ události musí být neprázdný string (dostalo {etype!r})")
    if not isinstance(ts, str) or not ts:
        raise ValueError("ts musí být ISO UTC string")
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError as exc:  # syntakticky neplatné → semantická chyba tvaru
        raise ValueError(f"ts není validní ISO (dostalo {ts!r})") from exc
    ev = {"type": etype, "case_id": case_id, "ts": ts}
    ev.update(payload)
    return ev


def canonical_json(event: Mapping) -> str:
    """Deterministická JSON serializace (sort_keys, bez mezer).

    Stejná událost → stejný string v každém procesu (parity testů/diffů).
    :raises TypeError: Ne-JSON-safe hodnota (např. bytes).
    """
    return json.dumps(dict(event), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_event(payload_json: str) -> dict:
    """Řádek z DB → plain dict události.

    :raises ValueError: Neplatná JSON syntaxe.
    :raises TypeError: Platné JSON, ale ne objekt (typová chyba tvaru katalogu).
    """
    try:
        data = json.loads(payload_json)
    except json.JSONDecodeError as exc:  # syntaktická → semantická
        raise ValueError(f"payload není validní JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError("událost musí být JSON objekt (dostalo " f"{type(data).__name__})")
    return data


def validate_topic(topic: str) -> str:
    """Kontrola tématu busu; vrací nezměněné.

    :param topic: Očekává se kanonický tvar ``case:{case_id}``
        (:func:`stopa.domain.events.case_topic`).
    :raises ValueError: Prázdné / ne-string / bez prefixu ``case:``.
    """
    if not isinstance(topic, str) or not topic.startswith("case:") or len(topic) < 6:
        raise ValueError(f"téma busu musí mít tvar case:<id> (dostalo {topic!r})")
    return topic
