"""STOPA CLI — spuštění jako ``python -m stopa.cli`` (P1-4: modul → balíček)."""
from __future__ import annotations

import sys

from . import main

if __name__ == "__main__":
    sys.exit(main())
