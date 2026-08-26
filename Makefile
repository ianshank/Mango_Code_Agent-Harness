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
PM       ?= pnpm
COV_MIN  ?= 80

SHARED_SRC   := harness/shared
SHARED_TESTS := harness/shared/tests
API_TESTS    := harness/api_server/tests
NODE_DIR     := harness/node

# --- Help ---
.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- Linting & Static Analysis ---
.PHONY: lint-python
lint-python: ## Run ruff check + mypy on Python sources and tests
	$(RUFF) check $(SHARED_TESTS)/ $(API_TESTS)/
	$(MYPY) $(SHARED_SRC) harness/api_server --explicit-package-bases

.PHONY: lint-node
lint-node: ## Run ESLint, Prettier, and Knip on Node stack
	(cd $(NODE_DIR) && $(PM) exec eslint . --max-warnings=0 && $(PM) exec prettier --check . && $(PM) exec knip)

.PHONY: lint
lint: lint-python ## Run code style & static analysis gates

# --- Python Testing & Coverage ---
.PHONY: test-python
test-python: ## Run full pytest suite (excludes live tests)
	$(PYTEST) $(SHARED_TESTS)/ $(API_TESTS)/ -m "not live" -v

.PHONY: coverage-python
coverage-python: ## Run pytest with coverage gate (default: 80%)
	$(PYTEST) $(SHARED_TESTS)/ $(API_TESTS)/ -m "not live" --cov=$(SHARED_SRC) --cov=harness/api_server --cov-report=term-missing --cov-fail-under=$(COV_MIN)

# --- Node Testing & Zero-Skip Verification ---
.PHONY: test-node
test-node: ## Run Vitest test suite and generate test results JSON
	(cd $(NODE_DIR) && $(PM) exec vitest run --reporter=default --reporter=json --outputFile.json=.governance/vitest-results.json)

.PHONY: verify-zero-skips
verify-zero-skips: ## Verify zero unapproved test skips (Invariant INV-2)
	$(PYTHON) $(SHARED_SRC)/verify_zero_skips.py \
		--vitest-json $(NODE_DIR)/.governance/vitest-results.json \
		--decision-log $(NODE_DIR)/.governance/decision-log.md \
		--waivers $(NODE_DIR)/.governance/skip-waivers.json

# --- Governance Validators ---
.PHONY: validate
validate: ## Run all governance validation scripts
	@echo "--- Running governance validators ---"
	@for script in validate_governance_docs validate_policy validate_adoption validate_agent_policy validate_invariants check_projections check_traceability; do \
		echo "  → $$script.py"; \
		(cd $(NODE_DIR) && $(PYTHON) ../shared/$$script.py) || exit 1; \
	done
	@echo "--- All governance validators passed ---"

# --- Drift Detection ---
.PHONY: check-dedup
check-dedup: ## Fail if node/jvm governance script copies drift from harness/shared (single source of truth)
	@echo "--- Checking governance script parity (shared == node == jvm) ---"
	@for script in check_projections check_traceability pretooluse_guard remotes validate_adoption validate_agent_policy validate_governance_docs validate_policy verify_zero_skips; do \
		if ! diff -q $(SHARED_SRC)/$$script.py $(NODE_DIR)/scripts/$$script.py >/dev/null 2>&1; then \
			echo "[FAIL] $$script.py drifted: $(NODE_DIR)/scripts differs from $(SHARED_SRC)"; exit 1; \
		fi; \
		if ! diff -q $(SHARED_SRC)/$$script.py harness/jvm/scripts/$$script.py >/dev/null 2>&1; then \
			echo "[FAIL] $$script.py drifted: harness/jvm/scripts differs from $(SHARED_SRC)"; exit 1; \
		fi; \
	done
	@echo "[PASS] All governance script copies match harness/shared (single source of truth)."

# --- Composite Targets ---
.PHONY: test
test: test-python test-node verify-zero-skips ## Run all Python and Node tests + zero-skips

.PHONY: coverage
coverage: coverage-python ## Run coverage validation

.PHONY: ci
ci: lint coverage test-node verify-zero-skips validate check-dedup ## Full CI pipeline: lint → coverage → test-node → zero-skips → validate → drift-check

.PHONY: pre-pr
pre-pr: ci ## Pre-PR validation gate (identical to CI)

.PHONY: clean
clean: ## Remove build/test artifacts
	rm -rf .coverage .pytest_cache .mypy_cache .ruff_cache htmlcov __pycache__
	rm -rf $(NODE_DIR)/coverage $(NODE_DIR)/.governance/vitest-results.json
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
