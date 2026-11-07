"""STP-059 — Timesketch push (oblast Q, interop): case data → Timesketch sketch.

ČISTÁ logika bez IO a bez HTTP — transport řeší injektovatelný klient
(``TimesketchClient`` z ``stopa.data.timesketch_client``, ale funkce přijme
jakoukoli implementaci se stejným rozhraním: ``create_sketch()`` +
``upload_timeline()``). To umožňuje plně offline testy s mockem.

Reuse STP-054/STP-058: timeline push = **l2tcsv** přes ``to_l2tcsv`` —
stejný deterministický formát, který Timesketch importuje nativně
(log2timeline parser). Žádné nové serializační schéma.

Workflow (dvě volání API):
1. ``create_sketch(name)`` → sketch ID,
2. ``upload_timeline(sketch_id, name, l2tcsv_bytes)`` → timeline + task ID.

Výsledek = souhrn pro audit log (bez přístupových údajů).
"""

from __future__ import annotations

from typing import Any, Protocol

from stopa.domain.export import to_l2tcsv


class TimesketchPushClient(Protocol):
    """Rozhraní push klienta — implementuje ``TimesketchClient`` i testy."""

    def create_sketch(self, name: str, description: str = "") -> int: ...

    def upload_timeline(
        self, sketch_id: int, name: str, file_bytes: bytes, filename: str = "..."
    ) -> dict[str, object]: ...


def build_l2tcsv_payload(records: list[dict[str, Any]], dataset: str) -> tuple[bytes, str]:
    """Záznamy → (l2tcsv bytů, název souboru).

    Deterministický výstup ``to_l2tcsv`` (STP-054); název souboru nese
    dataset pro čitelnost v Timesketch timeline.
    """
    text = to_l2tcsv(records, dataset=dataset)
    filename = f"stopa_{dataset}.l2t.csv"
    return text.encode("utf-8"), filename


def push_to_timesketch(
    client: TimesketchPushClient,
    case_name: str,
    what: str,
    records: list[dict[str, Any]],
) -> dict[str, object]:
    """Push datasetu případu do nového Timesketch sketchu.

    - ``what`` = dataset (artifacts / timeline / correlations),
    - vytvoří sketch s názvem ``STOPA <case_name> — <what>``,
    - nahraje l2tcsv payload jako timeline,
    - vrací souhrn pro audit: ``{"sketch_id", "timeline_id", "task_id",
      "records"}`` (žádné přístupové údaje).

    Hází výjimky klienta (``TimesketchError`` a podtřídy) — volající vrstva
    je mapuje na HTTP 502/503 nebo CLI exit code.
    """
    if not records:
        raise ValueError("prázdný dataset — není co pushovat")

    sketch_name = f"STOPA {case_name} — {what}"
    description = (
        "Vytvořeno STOPA (forenzní workbench) — l2tcsv export, "
        f"{len(records)} záznamů."
    )
    sketch_id = client.create_sketch(sketch_name, description=description)

    payload_bytes, filename = build_l2tcsv_payload(records, what)
    upload = client.upload_timeline(
        sketch_id, name=f"stopa_{what}", file_bytes=payload_bytes, filename=filename
    )
    return {
        "sketch_id": sketch_id,
        "timeline_id": upload.get("timeline_id"),
        "task_id": upload.get("task_id"),
        "records": len(records),
    }
