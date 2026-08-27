# ============================================================================
# Agentic SSD v2.1.9 — Root Makefile
# Unified entry point for validation, testing, and CI gates.
# ============================================================================
SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON   ?= python
PYTEST   ?= $(PYTHON) -m pytest
RUFF     ?= $(PYTHON) -m ruff
MYPY     ?= $(PYTHON) -m mypy
PM       ?= pnpm
GITLEAKS ?= gitleaks
# Pinned to match the per-stack adopter workflows; bump both together.
GITLEAKS_VERSION ?= v8.28.0
# Coverage threshold is sourced from the governance policy (single source of truth)
# so the gate and the policy can never silently drift. Falls back to 80 if unreadable.
COV_MIN  ?= $(shell $(PYTHON) -c "import json,sys; p=json.load(open('harness/shared/governance-policy.json')); print(p.get('coverage',{}).get('lines',80))" 2>/dev/null || echo 80)

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
lint-python: ## Run ruff check + mypy across all first-party Python (sources, tools, and tests)
	$(RUFF) check .
	$(MYPY) $(SHARED_SRC) harness/api_server --explicit-package-bases

.PHONY: check-compat
check-compat: ## Fail if any module uses syntax newer than the oldest Python in the CI matrix
	$(PYTHON) $(SHARED_SRC)/check_py_compat.py --repo-root .

.PHONY: lint-node
lint-node: ## Run ESLint, Prettier, and Knip on Node stack
	(cd $(NODE_DIR) && $(PM) exec eslint . --max-warnings=0 && $(PM) exec prettier --check . && $(PM) exec knip)

.PHONY: lint
lint: lint-python check-compat ## Run code style, static analysis, and runtime-compatibility gates

# --- Python Testing & Coverage ---
.PHONY: test-python
test-python: ## Run full pytest suite (excludes live tests)
	$(PYTEST) $(SHARED_TESTS)/ $(API_TESTS)/ -m "not live" -v

.PHONY: coverage-python
coverage-python: ## Run pytest with the coverage gate (threshold from governance-policy.json)
	$(PYTEST) $(SHARED_TESTS)/ $(API_TESTS)/ -m "not live" --cov=$(SHARED_SRC) --cov=harness/api_server --cov=harness/control-plane --cov-report=term-missing --cov-fail-under=$(COV_MIN)

# --- Node Testing & Zero-Skip Verification ---
.PHONY: test-node
test-node: ## Run Vitest test suite and generate test results JSON
	(cd $(NODE_DIR) && $(PM) exec vitest run --reporter=default --reporter=json --outputFile.json=.governance/vitest-results.json)

.PHONY: verify-zero-skips
verify-zero-skips: ## Verify zero unapproved test skips (Invariant INV-2)
	$(PYTHON) $(SHARED_SRC)/governance/verify_zero_skips.py \
		--vitest-json $(NODE_DIR)/.governance/vitest-results.json \
		--decision-log $(NODE_DIR)/.governance/decision-log.md \
		--waivers $(NODE_DIR)/.governance/skip-waivers.json

# --- Governance Validators ---
.PHONY: validate
validate: ## Run all governance validation scripts
	@echo "--- Running governance validators ---"
	@for script in validate_governance_docs validate_policy validate_adoption validate_agent_policy check_projections; do \
		echo "  → $$script.py"; \
		(cd $(NODE_DIR) && $(PYTHON) ../shared/$$script.py) || exit 1; \
	done
	@echo "  → governance/check_traceability.py"
	@(cd $(NODE_DIR) && $(PYTHON) ../shared/governance/check_traceability.py) || exit 1
	@echo "  → validate_invariants.py"
	@(cd $(NODE_DIR) && $(PYTHON) ../shared/validate_invariants.py) || exit 1
	@echo "--- All governance validators passed ---"

# --- Secret Scan Gate (INV-1) ---
# Kept out of `ci` deliberately: the scan is interpreter-independent, so running it
# on every leg of the Python matrix would repeat identical work. The root workflow
# invokes it once in a dedicated job. INV-1 requires failing closed when the tool
# or config is absent, so neither is treated as "nothing to scan".
.PHONY: secrets
secrets: ## Working-tree and full-history secret scans (INV-1; fails closed if gitleaks is absent)
	@command -v $(GITLEAKS) >/dev/null || { echo 'gitleaks missing; failing closed (run: make secrets-install)'; exit 1; }
	@test -f .gitleaks.toml || { echo '.gitleaks.toml missing; failing closed'; exit 1; }
	$(GITLEAKS) dir . --config .gitleaks.toml --redact --no-banner
	$(GITLEAKS) git . --config .gitleaks.toml --redact --no-banner

.PHONY: secrets-install
secrets-install: ## Install the pinned gitleaks used by the secrets gate
	go install github.com/zricethezav/gitleaks/v8@$(GITLEAKS_VERSION)

# --- Remote Allowlist Gate ---
.PHONY: remotes
remotes: ## Verify every configured Git push URL against the governance allowlist
	$(PYTHON) $(SHARED_SRC)/remotes.py --check-current-remotes --allowlist $(NODE_DIR)/.governance/allowed-remotes.txt

# --- Spec Gate ---
# Invoked via `bash`: validate_specs.sh is mode 644, so a bare ./ invocation is a
# guaranteed "Permission denied". Both per-stack Makefiles already call it this way.
.PHONY: specs
specs: ## Validate spec documents (structural tier always; openspec strict tier when available)
	bash $(SHARED_SRC)/validate_specs.sh

# --- Drift Detection ---
.PHONY: check-dedup
check-dedup: ## Fail if any per-stack governance script is a copy instead of a shim delegating to harness/shared
	$(PYTHON) $(SHARED_SRC)/check_dedup.py --repo-root .

# --- Digest Regeneration ---
.PHONY: digest-regen
digest-regen: ## Regenerate protected-file digests in the control-plane policy bundle
	$(PYTHON) harness/control-plane/regenerate_bundle_digests.py
	git diff --exit-code -- harness/control-plane/policy-bundle.example.json

# --- Governance-specific test target ---
.PHONY: test-governance
test-governance: ## Run governance module tests in isolation (broker, evidence, invariants)
	$(PYTEST) $(SHARED_TESTS)/test_governance_broker.py \
	          $(SHARED_TESTS)/test_evidence_manifest.py \
	          $(SHARED_TESTS)/test_validate_invariants.py \
	          -m "not live" -v --tb=short

# --- Neuro-symbolic synthesis test target ---
.PHONY: test-neurosym
test-neurosym: ## Run neurosym synthesis tests (strategies, critique, evaluation, execution profiles)
	$(PYTEST) $(SHARED_TESTS)/ -m "neurosym and not live" -v --tb=short

# --- Composite Targets ---
.PHONY: test
test: test-python test-node verify-zero-skips ## Run all Python and Node tests + zero-skips

.PHONY: coverage
coverage: coverage-python ## Run coverage validation

.PHONY: ci
ci: lint coverage test-node verify-zero-skips specs remotes validate check-dedup digest-regen ## Full CI pipeline: lint → coverage → test-node → zero-skips → specs → remotes → validate → drift-check → digest-regen

.PHONY: spec
spec: ## Scaffold a new spec from docs/specs/SPEC_TEMPLATE.md (usage: make spec NAME=my-feature)
	@test -n "$(NAME)" || { echo 'Usage: make spec NAME=<feature-name>'; exit 1; }
	@mkdir -p docs/specs
	@test -f docs/specs/SPEC_TEMPLATE.md || { echo 'ERROR: docs/specs/SPEC_TEMPLATE.md missing'; exit 1; }
	@cp docs/specs/SPEC_TEMPLATE.md docs/specs/$(NAME).md
	@echo "Scaffolded docs/specs/$(NAME).md — fill in the required sections."

.PHONY: review
review: validate ## Mechanical pre-PR review gate (invariants + governance validators)
	@echo "--- Pre-PR review checklist ---"
	@echo "1. Mechanical invariants: PASSED (validate target)"
	@echo "2. Run the 'openspec-peer-review' skill on the change/plan (Architecture, SDLC, QA, Product)."
	@echo "3. Run the 'repo-invariant-review' skill to predict concrete CI failures."
	@echo "4. For spec-driven work, confirm docs/specs/<feature>.md exists and acceptance criteria map to checks."

.PHONY: pre-pr
pre-pr: ci review ## Pre-PR validation gate (full CI + mechanical review checklist)

.PHONY: clean
clean: ## Remove build/test artifacts
	rm -rf .coverage .pytest_cache .mypy_cache .ruff_cache htmlcov __pycache__
	rm -rf $(NODE_DIR)/coverage $(NODE_DIR)/.governance/vitest-results.json
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
