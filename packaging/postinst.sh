#!/bin/sh
# STOPA .deb postinst — vytvoří /opt/stopa/venv z vendored wheels (offline).
# Idempotentní: pokud už je venv s funkčním stopa, přeskočí.

set -e

VENV=/opt/stopa/venv
WHEELS=/usr/lib/stopa/wheels

if [ -x "$VENV/bin/stopa" ]; then
    exit 0
fi

# python3-venv je v Depends; přesto ověř (jinak venv bez pipu = tichá porucha).
PY=$(command -v python3 || echo /usr/bin/python3)
"$PY" -m venv --help >/dev/null 2>&1 || {
    echo "ERROR: python3-venv nedostupné (apt install python3-venv)" >&2
    exit 1
}

mkdir -p /opt/stopa
rm -rf "$VENV"
"$PY" -m venv "$VENV"

# Offline instalace z vendored wheels (--no-index = žádné síťové volání).
# pydantic-core se vybere automaticky podle verze pythonu (wheels cp310–cp313).
"$VENV/bin/pip" install --quiet --no-index \
    --find-links "$WHEELS" "stopa[web]" || {
    echo "ERROR: offline pip install stopa[web] selhalo (chybí wheel?)" >&2
    exit 1
}

# Volitelné extenze — best-effort, není blokující. TSK běží přes sleuthkit CLI
# fallback; pytsk3 v balíčku není (sdist vyžaduje build na cíli).
"$VENV/bin/pip" install --quiet --no-index \
    --find-links "$WHEELS" cryptography openpyxl Pillow 2>/dev/null || \
    echo "WARNING: volitelné extenze se neinstalovaly (FDE/XLSX/EXIF omezeno)" >&2

ln -sf "$VENV/bin/stopa" /usr/local/bin/stopa
echo "[stopa] instalace hotova → /usr/local/bin/stopa (venv: $VENV)"
