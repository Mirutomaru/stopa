# syntax=docker/dockerfile:1
# =============================================================================
# STOPA — unifikovaná forenzní workbench (R0.2 Distributivní balíčky)
# python:3.11-bookworm + nativní libewf/libafflib pro carving (ctypes).
# AK: image < 1.5 GB, `stopa serve` hotové k použití, EWF/TSK funkční offline.
# =============================================================================

# Release 2.4 CI fix: knihovny z Debian balíčků (libewf2, libafflib0v5) místo
# source buildu — upstream github.com/libyal rozštěpil závislostní řetězec
# (libcommon → libcfile/libcdata/...) a master už není spolehlivě buildable.
# apt na bookworm vyřeší všechny tranzitivní závislosti; -dev balíčky dodávají
# neversionované symlinky, které _load() očekává ({name}.so → libewf.so /
# libafflib.so) — stejné knihovny, jaké STOPA installer používá v apt instalacích.
FROM python:3.11-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    # STOPA_EWF_LIB = adresář s libewf.so / libafflib.so (ctypes _load())
    STOPA_EWF_LIB=/opt/native/lib \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Runtime deps: sleuthkit (TSK CLI fallback), ca-certificates + nativní EWF/AFFLIB.
# --no-install-recommends drží image malý; -dev = neversionované symlinky pro _load().
RUN apt-get update && apt-get install -y --no-install-recommends \
        sleuthkit ca-certificates libewf2 libafflib0v5 libewf-dev libafflib-dev \
    # arch-safe multiarch dir (x86_64: x86_64-linux-gnu, arm64: aarch64-linux-gnu)
    && LIBDIR=$(dpkg-architecture -qDEB_HOST_MULTIARCH) \
    && mkdir -p /opt/native/lib \
    && ln -sf "/usr/lib/${LIBDIR}/libewf.so" /opt/native/lib/ \
    && ln -sf "/usr/lib/${LIBDIR}/libafflib.so" /opt/native/lib/ \
    # kontrola, že oba .so existují (jinak by runtime ticho spadl na fallback)
    && test -e /opt/native/lib/libewf.so && test -e /opt/native/lib/libafflib.so \
    || { echo "CHYBI libewf.so nebo libafflib.so v /opt/native/lib"; ls -la /opt/native/lib; exit 1; } \
    && ldconfig \
    && rm -rf /var/lib/apt/lists/*

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
