.PHONY: help dev test lint typecheck web web-check i18n-check vendor e2e check

PY ?= python
REGISTRATION ?= open

help: ## list targets
	@grep -E '^[a-z0-9-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

dev: web ## run the app locally with reload (http://127.0.0.1:8978, data in ./data)
	REGISTRATION=$(REGISTRATION) $(PY) -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8978

test: ## backend tests
	$(PY) -m pytest -q

lint: ## ruff
	$(PY) -m ruff check backend/ scripts/ tests/ e2e/

typecheck: ## mypy
	$(PY) -m mypy backend/ scripts/ tests/ e2e/

web: ## build index.html from web/
	$(PY) web/build.py

web-check: ## fail if index.html is out of date
	$(PY) web/build.py --check

i18n-check: ## fail if i18n keys are missing or strings hardcoded
	$(PY) web/check_i18n.py

vendor: ## download pinned CDN assets into vendor/ (needs network)
	$(PY) scripts/vendor.py

e2e: ## browser smoke tests (needs: pip install -r requirements-e2e.txt && playwright install chromium)
	$(PY) -m pytest e2e -q

check: lint typecheck web-check i18n-check test ## everything CI runs for Python + frontend build
