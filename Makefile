# R0.2 — STOPA distributivní balíčky: lokální buildy (zrcadlí .github/workflows/release.yml)
# Použití: make <target>. Vše nejlepší-effort; chybějící nástroje = jasná chyba, ne ticho.

PY      ?= python3
VENV    ?= .venv
TAG     ?= $(shell v=$$(git describe --tags --abbrev=0 2>/dev/null); if [ -n "$$v" ]; then echo $${v#v}; else echo 0.1.0; fi)
PKGDIR  := dist/pkg

.DEFAULT_GOAL := help

.PHONY: help venv lint test wheel sdist wheels deb rpm appimage docker install clean

help: ## Seznam targetů
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

$(VENV)/bin/activate:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip

venv: ## Vytvořit/aktualizovat dev venv
	test -d $(VENV) || $(PY) -m venv $(VENV); $(VENV)/bin/pip install --quiet ".[dev,web]"

lint: ## Ruff check (src + tests)
	$(VENV)/bin/ruff check src tests

test: ## Offline test suite
	$(VENV)/bin/python -m pytest -q

wheel: ## Build wheel (dist/*.whl)
	$(PY) -m pip install --quiet build; $(PY) -m build --wheel --outdir dist/

sdist: ## Build sdist (dist/*.tar.gz)
	$(PY) -m pip install --quiet build; $(PY) -m build --sdist --outdir dist/

# --- R0.2: offline wheels (installační set pro .deb postinst) -----------------
# Síť vyžaduje; regenerovat před release tagem. Cíle: cp310–cp313 + py3-none-any.
WHEELS := dist/wheels

wheels: ## Stáhnout offline wheel set (stopa[web] + volitelné extenze, síť!)
	$(VENV)/bin/pip install --quiet build
	rm -rf $(WHEELS); mkdir -p $(WHEELS)
	$(PY) -m build --wheel --outdir $(WHEELS) .
	$(VENV)/bin/pip download --only-binary=:all: -d $(WHEELS) "pydantic>=2.5" "regipy>=6" "rich>=13"
	$(VENV)/bin/pip download --only-binary=:all: -d $(WHEELS) "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27" "python-multipart>=0.0.9" python-dotenv websockets pyyaml
	$(VENV)/bin/pip download --only-binary=:all: -d $(WHEELS) cryptography openpyxl Pillow
	for pv in 310 311 312 313; do \
	  $(VENV)/bin/pip download --only-binary=:all: --python-version $${pv:0:1}.$${pv:1} -d $(WHEELS) pydantic-core pillow httptools uvloop websockets pyyaml cffi || true; \
	done
	@echo "→ $(WHEELS)/ ($(ls $(WHEELS) | wc -l) wheels, $$(du -sh $(WHEELS) | cut -f1))"

# --- instalační strom pro .deb -------------------------------------------------
# Layout: /usr/lib/stopa/wheels/*.whl + DEBIAN/postinst (venv offline z wheels).
# ŽÁDNÉ bundlované site-packages — cp3xx extenze by nešly cross-verze; postinst
# vybere správné wheels podle pythonu cílového systému. Recept kopíruje vždy
# čerstvě (file target by po 1. buildu nesledoval změny v dist/wheels).
deb: ## .deb (wheels + postinst venv; fpm fallback dpkg-deb)
	@command -v fpm >/dev/null && { \
	fpm -s dir -t deb --name stopa --version $(TAG) --architecture amd64 \
		--depends python3 --depends python3-venv --depends sleuthkit \
		--after-install packaging/postinst.sh \
		--description "STOPA — unifikovaná forenzní workbench" \
		dist/pkg=/ --force -p dist/stopa_$(TAG)_amd64.deb; exit 0; } || true
	rm -rf $(PKGDIR); mkdir -p $(PKGDIR)/usr/lib/stopa/wheels $(PKGDIR)/DEBIAN
	cp $(WHEELS)/*.whl $(PKGDIR)/usr/lib/stopa/wheels/
	printf 'Package: stopa\nVersion: $(TAG)\nArchitecture: amd64\nMaintainer: Miroslav Matúš <mirdamatus@gmail.com>\nDepends: python3, python3-venv, sleuthkit\nDescription: STOPA — unifikovaná forenzní workbench\n' > $(PKGDIR)/DEBIAN/control
	install -m 0755 packaging/postinst.sh $(PKGDIR)/DEBIAN/postinst
	dpkg-deb --build --root-owner-group -Zgzip $(PKGDIR) dist/stopa_$(TAG)_amd64.deb
	@echo "→ dist/stopa_$(TAG)_amd64.deb"

rpm: $(PKGDIR) ## .rpm přes fpm (vyžaduje ruby + gem fpm)
	@command -v fpm >/dev/null || { echo "Chybí 'fpm' → sudo apt install ruby && gem install --no-document fpm"; exit 1; }
	fpm -s dir -t rpm --name stopa --version $(TAG) --architecture x86_64 \
		--depends python3 --requires sleuthkit \
		--description "STOPA — unifikovaná forenzní workbench" \
		dist/pkg=/ --force -p dist/stopa-$(TAG)-x86_64.rpm

appimage: ## AppImage (PyInstaller onedir + appimagetool)
	@command -v pyinstaller >/dev/null || $(VENV)/bin/pip install --quiet pyinstaller
	$(VENV)/bin/pyinstaller --name stopa --onedir --noconfirm --collect-all stopa src/stopa/__main__.py

docker: ## Docker image → dist/stopa-docker.tar (vyžaduje docker)
	@command -v docker >/dev/null || { echo "Chybí 'docker'"; exit 1; }
	docker build --tag stopa:$(TAG) .
	docker save stopa:$(TAG) -o dist/stopa-docker.tar

install: ## Bootstrap installer (detekce OS + systémové závislosti)
	$(VENV)/bin/python -m stopa.cli install

clean: ## Smazat build artefakty
	rm -rf dist build AppDir *.AppImage .venv 2>/dev/null || true
	find . -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
