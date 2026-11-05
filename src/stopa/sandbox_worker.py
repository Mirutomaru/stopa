"""STOPA — Sandbox worker (ETAPA E vlna 1, STP-046).

Dceřiný proces pro izolovaný běh jednoho artifact extraktoru. Spouští se:

    python -m stopa.sandbox_worker <module_name> <func_name> <path>

Kontrakt (viz ``domain/sandbox.py``):
- stdout = POUZE JSON array artifactů (``model_dump(mode="json")``) — nic jiného.
- stderr = logy a traceback (konzument čte jen při crashi).
- exit 0 = úspěch; exit 1 = parser selhal (jakákoli výjimka → crash kategorie).

Backstop: na POSIX se aplikuje ``RLIMIT_CPU`` z env ``STOPA_SANDBOX_TIMEOUT`` —
i kdyby externí timeout selhal, proces zemře po N CPU sekundách. Na platformě
bez ``resource`` modulu (Windows) backstop chybí a spoléháme jen na timeout.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
from pathlib import Path


def _apply_cpu_rlimit() -> None:
    """RLIMIT_CPU backstop (POSIX) — CPU limit = 2× wall-clock timeout."""
    raw = os.environ.get("STOPA_SANDBOX_TIMEOUT")
    if not raw:
        return
    try:
        import resource

        seconds = int(float(raw)) * 2 or 1
        # soft+hard: SIGXCPU po soft limitu; hard brání parseru, který by ho zvedl
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    except Exception as e:  # noqa: BLE001 — backstop je best-effort, nikdy neblokuj start
        logging.getLogger("stopa.sandbox_worker").debug("RLIMIT_CPU nepoužit: %s", e)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint workeru. Vrací exit code (0 úspěch / 1 selhání)."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        print("usage: python -m stopa.sandbox_worker <module> <func> <path>", file=sys.stderr)
        return 1
    module_name, func_name, path_str = args

    _apply_cpu_rlimit()
    log = logging.getLogger("stopa.sandbox_worker")
    try:
        module = importlib.import_module(module_name)
        fn = getattr(module, func_name)
        artifacts = fn(Path(path_str))
    except Exception as e:
        log.exception("parser %s.%s selhal", module_name, func_name)
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    payload = [a.model_dump(mode="json") for a in artifacts]
    json.dump(payload, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
