# ============================================================================
# Agentic SSD v2.1.4 — Root Makefile
# Unified entry point for validation, testing, and CI gates.
# ============================================================================
SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON   ?= python
PYTEST   ?= $(PYTHON) -m pytest
RUFF     ?= $(PYTHON) -m ruff
MYPY     ?= $(PYTHON) -m mypy
COV_MIN  ?= 80

SHARED_SRC   := harness/shared
SHARED_TESTS := harness/shared/tests

# --- Help ---
.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- Linting ---
.PHONY: lint
lint: ## Run ruff check + mypy on Python sources and tests
	$(RUFF) check $(SHARED_TESTS)/
	$(MYPY) $(SHARED_SRC) --explicit-package-bases

# --- Testing ---
.PHONY: test
test: ## Run full pytest suite (excludes live tests)
	$(PYTEST) $(SHARED_TESTS)/ -m "not live" -v

.PHONY: coverage
coverage: ## Run pytest with coverage gate (default: 80%)
	$(PYTEST) $(SHARED_TESTS)/ -m "not live" --cov=$(SHARED_SRC) --cov-report=term-missing --cov-fail-under=$(COV_MIN)

# --- Governance Validators ---
.PHONY: validate
validate: ## Run all governance validation scripts
	@echo "--- Running governance validators ---"
	@for script in validate_governance_docs validate_policy validate_adoption validate_agent_policy check_projections check_traceability; do \
		echo "  → $$script.py"; \
		(cd harness/node && $(PYTHON) ../shared/$$script.py) || exit 1; \
	done
	@echo "--- All governance validators passed ---"

# --- Composite Targets ---
.PHONY: ci
ci: lint coverage validate ## Full CI pipeline: lint → coverage → validate

.PHONY: pre-pr
pre-pr: lint coverage ## Pre-PR checks: lint → coverage

.PHONY: clean
clean: ## Remove build/test artifacts
	rm -rf .coverage .pytest_cache .mypy_cache .ruff_cache htmlcov __pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
