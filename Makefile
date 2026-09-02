# ============================================================================
# Agentic SSD v2.4.0 — Root Makefile
# Unified entry point for validation, testing, and CI gates.
# ============================================================================
SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON   ?= python
PYTEST   ?= $(PYTHON) -m pytest
RUFF     ?= $(PYTHON) -m ruff
MYPY     ?= $(PYTHON) -m mypy
# --check-untyped-defs checks the *bodies* of unannotated functions, which is
# where latent test bugs live (a re.search(...).group() that starts returning
# None raises AttributeError instead of failing with a message). Measured at 14
# findings across the tree, all fixed in the same change that enabled it.
# Deliberately NOT --strict (604) or --disallow-untyped-defs (533): both are
# dominated by no-untyped-def on test functions, which buys annotations rather
# than correctness. See test_deferred_rigor.py.
MYPY_FLAGS ?= --check-untyped-defs
PM       ?= pnpm
GITLEAKS ?= gitleaks
# Pinned to match the per-stack adopter workflows; bump both together.
GITLEAKS_VERSION ?= v8.28.0
# Pinned so the audit gate cannot change or break on an unreviewed upstream
# release; CI installs this exact version via `audit-install`, never `--upgrade`
# with no pin. Mirrors GITLEAKS_VERSION/OSV_VERSION (harness/node/Makefile).
# Capped at 2.9.0, not the newer 2.10.x: pip-audit 2.10.0 raised its own floor to
# Requires-Python >=3.10, which cannot install at all on the 3.9 leg of the
# `audit-matrix` job below -- confirmed by that job's first real CI run. 2.9.0 is
# the newest release still declaring >=3.9, matching this project's own floor.
PIP_AUDIT_VERSION ?= 2.9.0
# Coverage thresholds are sourced from the governance policy (single source of
# truth) and applied by coverage_gate.py as TWO separate numbers: coverage.lines
# against line coverage and coverage.branches against branch coverage. With
# `branch = true` in pyproject, pytest-cov's single "total" is a blended
# statements+branches percentage, so gating that blend with --cov-fail-under
# would mislabel what the lines floor applies to — the same "gate that lowers
# itself" inversion the old hard-coded COV_MIN=80 fallback had. The gate script
# fails closed on a missing or malformed report or policy.

SHARED_SRC   := harness/shared
SHARED_TESTS := harness/shared/tests
API_TESTS    := harness/api_server/tests
NODE_DIR     := harness/node

# --- Help ---
.PHONY: help
help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- Install ---
.PHONY: install
install: ## Install the pre-push remote-allowlist hook (a root-only workflow otherwise never gets it)
	bash harness/shared/install_hooks.sh

# --- Linting & Static Analysis ---
# harness/control-plane is hyphenated (not an importable package) but mypy
# checks it fine as a directory of top-level modules; it is in the coverage
# source set, so it must not be type-unchecked.
MYPY_TARGETS := $(SHARED_SRC) harness/api_server harness/control-plane

# Dead-code gate. Tests are excluded (pytest discovers them by name), the
# whitelist carries framework-registered symbols, and the confidence floor is
# vulture's "certainly unused" tier so an unused import or unreferenced module
# function fails lint without heuristic noise (tech-debt-hardening-plan R-TDH-17).
VULTURE       ?= $(PYTHON) -m vulture
VULTURE_MIN_CONFIDENCE ?= 80

.PHONY: lint-python
lint-python: ## Run ruff check + mypy + vulture across all first-party Python (sources, tools, and tests)
	$(RUFF) check .
	$(MYPY) $(MYPY_TARGETS) --explicit-package-bases $(MYPY_FLAGS)
	$(VULTURE) $(MYPY_TARGETS) vulture_whitelist.py --min-confidence $(VULTURE_MIN_CONFIDENCE) --exclude '*/tests/*'

.PHONY: lint-cold
lint-cold: ## Typecheck with no mypy cache — CI always runs cold, the inner loop does not
	$(MYPY) $(MYPY_TARGETS) --explicit-package-bases $(MYPY_FLAGS) --no-incremental

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

.PHONY: test-regression
test-regression: ## Run the regression/AQA tier on its own (one reproduction per fixed defect)
	$(PYTEST) $(SHARED_TESTS)/regression/ -m "not live" -v

.PHONY: test-langgraph
test-langgraph: ## Run LangGraph StateGraph suite (state, nodes, graph, policy, regression)
	$(PYTEST) $(SHARED_TESTS)/test_langgraph_*.py $(SHARED_TESTS)/regression/test_langgraph_regression.py -m "not live" -v

.PHONY: test-mcp
test-mcp: ## Run Model Context Protocol (MCP) server tests
	$(PYTEST) $(SHARED_TESTS)/test_mcp_server.py -m "not live" -v

.PHONY: test-lats
test-lats: ## Run LATS Optimizer and Ablation state forking tests
	$(PYTEST) $(SHARED_TESTS)/test_lats_optimizer.py $(SHARED_TESTS)/test_ablation.py -m "not live" -v

.PHONY: test-aqa
test-aqa: ## Run AQA smoke tests and coverage-gap regression suite
	$(PYTEST) $(SHARED_TESTS)/regression/test_coverage_gap_regression.py $(SHARED_TESTS)/regression/test_nemotron_api_aqa.py -m "not live" -v

.PHONY: coverage-python
coverage-python: ## Run pytest, then enforce lines and branches floors from governance-policy.json
	$(PYTEST) $(SHARED_TESTS)/ $(API_TESTS)/ -m "not live" --cov=$(SHARED_SRC) --cov=harness/api_server --cov=harness/control-plane --cov-report=term-missing --cov-report=json
	$(PYTHON) $(SHARED_SRC)/coverage_gate.py

# --- Node Testing & Zero-Skip Verification ---
.PHONY: node-deps
node-deps: ## Install pinned Node dependencies (shared by CI, the session hook, and local runs)
	(cd $(NODE_DIR) && $(PM) install --frozen-lockfile)

.PHONY: test-node
test-node: ## Run Vitest with coverage (thresholds from the governance policy via vitest.config.ts) and generate test results JSON
	(cd $(NODE_DIR) && $(PM) exec vitest run --coverage --reporter=default --reporter=json --outputFile.json=.governance/vitest-results.json)

.PHONY: verify-zero-skips
verify-zero-skips: ## Verify zero unapproved test skips (Invariant INV-2)
	$(PYTHON) $(SHARED_SRC)/governance/verify_zero_skips.py \
		--vitest-json $(NODE_DIR)/.governance/vitest-results.json \
		--decision-log $(NODE_DIR)/.governance/decision-log.md \
		--waivers $(NODE_DIR)/.governance/skip-waivers.json

# The Python half of INV-2. The pytest run under `coverage-python` writes every
# skip it produced to PYTEST_SKIP_EVENTS (harness/shared/tests/conftest.py); this
# reads that file through the same gate the Node stack uses, against a waiver
# registry that lives beside the suite (the root .governance/ is dormant,
# DEC-005). A skip whose reason does not carry its waiver's DEC id is unapproved.
PYTEST_SKIP_EVENTS ?= $(SHARED_TESTS)/.artifacts/pytest-skips.tsv

.PHONY: verify-zero-skips-python
verify-zero-skips-python: ## Verify zero unapproved pytest skips from the last coverage-python run (INV-2, Python)
	@test -f $(PYTEST_SKIP_EVENTS) || { echo 'zero-skip: $(PYTEST_SKIP_EVENTS) missing; run make coverage-python first'; exit 1; }
	$(PYTHON) $(SHARED_SRC)/governance/verify_zero_skips.py \
		--junit-events $(PYTEST_SKIP_EVENTS) \
		--decision-log $(NODE_DIR)/.governance/decision-log.md \
		--waivers $(SHARED_TESTS)/skip-waivers.json

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
	$(GITLEAKS) git . --config .gitleaks.toml --redact --no-banner --log-opts="HEAD"

.PHONY: secrets-install
secrets-install: ## Install the pinned gitleaks used by the secrets gate
	go install github.com/zricethezav/gitleaks/v8@$(GITLEAKS_VERSION)

# --- Dependency Vulnerability Scan ---
# Kept out of `ci`/`ci-python` deliberately, mirroring `secrets`: interpreter-independent,
# so running it on every Python matrix leg would repeat identical work. Dedicated
# workflow jobs run it instead (see the `audit`/`audit-matrix` jobs in
# .github/workflows/python-package.yml).
#
# Split from `audit` so CI can resolve dependency markers and transitive constraints
# under each supported interpreter (3.9/3.10/3.12), not only the one `audit`
# happens to run on: `pip-audit`'s resolution is interpreter-specific, so a
# single-version scan can miss a vulnerability that only a differently-pinned
# transitive dependency under another supported version would pull in.
.PHONY: audit-python
audit-python: ## Dependency vulnerability scan for the Python interpreter running this invocation
	@command -v pip-audit >/dev/null || { echo 'pip-audit missing; failing closed (run: make audit-install)'; exit 1; }
	@test -f requirements.txt || { echo 'requirements.txt missing; refusing a vacuous audit'; exit 1; }
	@test -f requirements-langgraph.txt || { echo 'requirements-langgraph.txt missing; refusing a partial audit'; exit 1; }
	@test -f requirements-lock.txt || { echo 'requirements-lock.txt missing; refusing a partial audit'; exit 1; }
	pip-audit --requirement requirements.txt --requirement requirements-langgraph.txt --requirement requirements-lock.txt

# --- Dependency Lock ---
# One universal lock serves every interpreter in the CI matrix: `uv pip compile
# --universal` keeps environment markers instead of evaluating them for the
# running interpreter, which is why a plain pip-compile output could not be
# shared across 3.9/3.10/3.12 (mcp is >=3.10 only, tomli <3.11 only). The floor
# is read from pyproject's requires-python so there is one declaration of it.
# `lock-check` recompiles against the committed lock (uv keeps existing pins as
# preferences, so it only changes when an input changed) and fails on any diff;
# `lock-upgrade-check` ignores those preferences to report how far behind PyPI the
# lock is, which the weekly drift job turns into an issue rather than a red PR.
PYTHON_FLOOR := $(shell $(PYTHON) -c "import re,pathlib;print(re.search(r'requires-python\s*=\s*\">=([0-9.]+)\"', pathlib.Path('pyproject.toml').read_text()).group(1))")
LOCK_INPUTS  := requirements-dev.txt requirements-langgraph.txt
LOCK_FILE    := requirements-lock.txt
UV           ?= $(PYTHON) -m uv

.PHONY: lock
lock: ## Regenerate requirements-lock.txt from the requirements files (universal, floor from pyproject)
	$(UV) pip compile --universal --python-version $(PYTHON_FLOOR) -o $(LOCK_FILE) $(LOCK_INPUTS)

# Both checks compare pins only (`grep -v '^#'`): uv writes the compile command,
# output path included, into the header, so a byte comparison against a temp
# output would always differ. The committed header is still pinned by
# test_workflow_contracts.py (it must show `--universal`).
.PHONY: lock-check
lock-check: ## Fail if requirements-lock.txt is not what the requirements files compile to
	@test -f $(LOCK_FILE) || { echo '$(LOCK_FILE) missing; run make lock'; exit 1; }
	@tmp=$$(mktemp) && cp $(LOCK_FILE) $$tmp && \
	  $(UV) pip compile --quiet --universal --python-version $(PYTHON_FLOOR) -o $$tmp $(LOCK_INPUTS) && \
	  if diff -u <(grep -v '^#' $(LOCK_FILE)) <(grep -v '^#' $$tmp); then echo 'lock-check: passed'; rm -f $$tmp; \
	  else echo 'lock-check: FAILED ($(LOCK_FILE) is stale; run make lock)'; rm -f $$tmp; exit 1; fi

.PHONY: lock-upgrade-check
lock-upgrade-check: ## Report (exit 1) when newer releases than the lock pins are available
	@tmp=$$(mktemp) && \
	  $(UV) pip compile --quiet --universal --upgrade --python-version $(PYTHON_FLOOR) -o $$tmp $(LOCK_INPUTS) && \
	  if diff -u <(grep -v '^#' $(LOCK_FILE)) <(grep -v '^#' $$tmp); then echo 'lock-upgrade-check: lock is current'; rm -f $$tmp; \
	  else echo 'lock-upgrade-check: newer releases available (run make lock-upgrade)'; rm -f $$tmp; exit 1; fi

.PHONY: lock-upgrade
lock-upgrade: ## Regenerate the lock taking the newest releases the requirements files allow
	$(UV) pip compile --universal --upgrade --python-version $(PYTHON_FLOOR) -o $(LOCK_FILE) $(LOCK_INPUTS)

.PHONY: audit
audit: audit-python ## Dependency vulnerability scan: pip-audit (Python) + delegates to the Node stack's osv-scanner
	$(MAKE) -C $(NODE_DIR) audit

.PHONY: audit-install-python
audit-install-python: ## Install the pinned pip-audit used by the audit gate
	python -m pip install --upgrade "pip-audit==$(PIP_AUDIT_VERSION)"

.PHONY: audit-install
audit-install: audit-install-python ## Install pip-audit and the Node stack's pinned osv-scanner
	$(MAKE) -C $(NODE_DIR) audit-install

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
digest-regen: ## Regenerate the control-plane policy bundle (per-file digests + top-level policy digests)
	$(PYTHON) harness/control-plane/regenerate_bundle_digests.py
	$(PYTHON) harness/control-plane/build_policy_bundle.py --node harness/node --jvm harness/jvm --output harness/control-plane/policy-bundle.example.json
	git diff --exit-code -- harness/control-plane/policy-bundle.example.json

# --- Governance-specific test target ---
.PHONY: test-governance
test-governance: ## Run every governance-marked gate in isolation (selected by marker, cannot go stale)
	$(PYTEST) $(SHARED_TESTS)/ $(API_TESTS)/ -m "governance and not live" -v --tb=short

# --- Neuro-symbolic synthesis test target ---
.PHONY: test-neurosym
test-neurosym: ## Run neurosym synthesis tests (strategies, critique, evaluation, execution profiles)
	$(PYTEST) $(SHARED_TESTS)/ -m "neurosym and not live" -v --tb=short

# --- Live Model & MAS integration test targets ---
.PHONY: test-live
test-live: ## Run live API integration tests against NVIDIA Nemotron NIM
	$(PYTEST) $(SHARED_TESTS)/ -m "live" -v

.PHONY: test-live-mas
test-live-mas: ## Run live multi-agent sequential thinking and synthesis loops against Nemotron
	$(PYTEST) $(SHARED_TESTS)/test_mango_mas_live.py -m "live" -v

# --- Composite Targets ---
.PHONY: test
test: test-python test-node verify-zero-skips ## Run all Python and Node tests + zero-skips

.PHONY: coverage
coverage: coverage-python ## Run coverage validation

.PHONY: ci
ci: lint lock-check coverage verify-zero-skips-python test-node verify-zero-skips specs remotes validate check-dedup digest-regen ## Full CI pipeline: lint → lock-check → coverage → python zero-skips → test-node → zero-skips → specs → remotes → validate → drift-check → digest-regen

# The Node suite's result is Python-version-independent, so the CI matrix runs
# the full `ci` on one leg only and this Python-scoped pipeline on the others.
# Every gate stays enforced by Make target (INV-5); nothing is skipped, the
# Node gates just run once per PR instead of once per interpreter.
.PHONY: ci-python
ci-python: lint lock-check coverage verify-zero-skips-python specs remotes validate check-dedup digest-regen ## Python-scoped CI pipeline for secondary matrix legs (Node gates run once, on the primary leg)

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
	@echo "4. Run the 'validation-runner' skill for a structured PASS/FAIL with evidence."
	@echo "5. For spec-driven work, confirm docs/specs/<feature>.md exists and acceptance criteria map to checks."
	@echo "6. For protected-path changes, run the 'protected-path-attestation' skill and paste the block into the PR."

.PHONY: pre-pr
pre-pr: ci review lint-cold audit secrets ## Pre-PR validation gate (full CI + mechanical review checklist + cold typecheck + dependency audit + secret scan)

.PHONY: clean
clean: ## Remove build/test artifacts
	rm -rf .coverage .pytest_cache .mypy_cache .ruff_cache htmlcov __pycache__
	rm -rf $(NODE_DIR)/coverage $(NODE_DIR)/.governance/vitest-results.json
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
