# syntax=docker/dockerfile:1
# =============================================================================
# STOPA — unifikovaná forenzní workbench (R0.2 Distributivní balíčky)
# Multi-stage build: nativní knihovny z oficiálních zdrojů → slim runtime.
# AK: image < 1.5 GB, `stopa serve` hotové k použití, EWF/TSK funkční offline.
# =============================================================================

# -----------------------------------------------------------------------------
# STAGE 1 — builder: autotools stack + libcommon/libafflib/libewf (ctypes)
#   STOPA načítá libewf.so + libafflib.so přes ctypes z STOPA_EWF_LIB.
#   Buildujeme do /opt/native, aby file name odpovídal očekávání _load()
#   ({name}.so → libewf.so / libafflib.so). Zdroje: github.com/libyal (master,
#   --depth 1 = vždy buildable stav bez nutnosti poznat přesný release tag).
# -----------------------------------------------------------------------------
FROM python:3.11-bookworm AS native-builder

ENV DEBIAN_FRONTEND=noninteractive \
    PREFIX=/opt/native

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential autoconf automake libtool pkg-config git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Závislostní řetězec: libcommon → (libafflib, libewf). Každá do PREFIX.
WORKDIR /build

RUN set -eux; \
    git clone --depth 1 https://github.com/libyal/libcommon.git; \
    cd libcommon; ./autogen.sh; \
    ./configure --prefix=$PREFIX; make -j"$(nproc)"; make install; ldconfig

RUN set -eux; \
    export PKG_CONFIG_PATH=$PREFIX/lib/pkgconfig \
           CPPFLAGS=-I$PREFIX/include LDFLAGS="-L$PREFIX/lib -Wl,-rpath,$PREFIX/lib"; \
    git clone --depth 1 https://github.com/libyal/libafflib.git; \
    cd libafflib; ./autogen.sh; \
    ./configure --prefix=$PREFIX; make -j"$(nproc)"; make install; ldconfig

RUN set -eux; \
    export PKG_CONFIG_PATH=$PREFIX/lib/pkgconfig \
           CPPFLAGS=-I$PREFIX/include LDFLAGS="-L$PREFIX/lib -Wl,-rpath,$PREFIX/lib"; \
    git clone --depth 1 https://github.com/libyal/libewf.git; \
    cd libewf; ./autogen.sh; \
    ./configure --prefix=$PREFIX; make -j"$(nproc)"; make install; ldconfig

# Zkontroluj, že oba .so existují (jinak by runtime tichounce spadl na fallback).
RUN test -e $PREFIX/lib/libewf.so && test -e $PREFIX/lib/libafflib.so \
    || { echo "CHYBI libewf.so nebo libafflib.so v $PREFIX/lib"; ls -la $PREFIX/lib | head; exit 1; }

# -----------------------------------------------------------------------------
# STAGE 2 — runtime: python slim + stopa[web] + sleuthkit (TSK CLI fallback)
#   pytsk3 wheel se neinstaluje (build risk); STOPA má explicitní fallback na
#   tsk_cli binárky z apt balíčku `sleuthkit`. EWF běží přes ctypes ze STAGE 1.
# -----------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    STOPA_EWF_LIB=/opt/native/lib \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        sleuthkit ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Nativní knihovny z builderu.
COPY --from=native-builder /opt/native/ /opt/native/
RUN ldconfig /opt/native/lib || true

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/

# web extra = FastAPI/uvicorn (nutné pro `stopa serve`). Editovatelná instalace.
RUN pip install --no-cache-dir ".[web]"

# STOPA data mimo image (volume v produkci).
ENV STOPA_DATA=/data
VOLUME ["/data"]

EXPOSE 8473
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8473/', timeout=4).status==200 else 1)"]

CMD ["stopa", "serve", "--host", "0.0.0.0", "--port", "8473"]
