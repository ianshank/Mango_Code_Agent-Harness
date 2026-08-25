SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
PM ?= pnpm
RUN ?= $(PM) exec --
GITLEAKS ?= gitleaks
GITLEAKS_VERSION ?= v8.28.0
OSV ?= osv-scanner
OSV_VERSION ?= v2.2.3
.PHONY: help install format lint types test cov secrets specs audit remotes projections traceability governance guard-probe pre-pr clean secrets-install audit-install
help:
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-18s %s\n", $$1, $$2}'
install: ## Frozen install and hook installation
	@test -f $(ROOT)/pnpm-lock.yaml || { echo 'pnpm-lock.yaml missing; generate and review it before install'; exit 1; }
	$(PM) install --frozen-lockfile
	bash $(ROOT)/scripts/install_hooks.sh
format: ## Apply formatting
	$(RUN) prettier --write .
lint: ## ESLint, Prettier, dead-code/dependency analysis
	$(RUN) eslint . --max-warnings=0
	$(RUN) prettier --check .
	$(RUN) knip
types: ## Whole-project static types
	$(RUN) tsc --noEmit -p $(ROOT)/tsconfig.json
test: ## Tests plus post-run zero-skip verification
	bash $(ROOT)/scripts/run_vitest.sh
cov: ## Coverage plus post-run zero-skip verification
	bash $(ROOT)/scripts/run_vitest.sh --coverage
secrets: ## Working-tree and full-history secret scans
	@command -v $(GITLEAKS) >/dev/null || { echo 'gitleaks missing; failing closed'; exit 1; }
	@test -f $(ROOT)/.gitleaks.toml || { echo '.gitleaks.toml missing'; exit 1; }
	$(GITLEAKS) dir $(ROOT) --config $(ROOT)/.gitleaks.toml --redact --no-banner
	$(GITLEAKS) git $(ROOT) --config $(ROOT)/.gitleaks.toml --redact --no-banner
secrets-install: ## Install pinned gitleaks
	go install github.com/zricethezav/gitleaks/v8@$(GITLEAKS_VERSION)
specs: ## Spec validation
	bash $(ROOT)/scripts/validate_specs.sh
audit: ## Dependency vulnerability scan
	@command -v $(OSV) >/dev/null || { echo 'osv-scanner missing; failing closed'; exit 1; }
	@test -f $(ROOT)/pnpm-lock.yaml || { echo 'pnpm-lock.yaml missing; refusing a vacuous audit'; exit 1; }
	$(OSV) scan --lockfile=$(ROOT)/pnpm-lock.yaml --config=$(ROOT)/osv-scanner.toml
audit-install: ## Install pinned osv-scanner
	go install github.com/google/osv-scanner/v2/cmd/osv-scanner@$(OSV_VERSION)
remotes: ## Verify every configured Git push URL against the allowlist
	python3 $(ROOT)/scripts/remotes.py --check-current-remotes --repo $(ROOT) --allowlist $(ROOT)/.governance/allowed-remotes.txt
projections: ## Projection applicability/drift gate
	cd $(ROOT) && python3 scripts/check_projections.py
traceability: ## Requirement traceability gate
	cd $(ROOT) && python3 scripts/check_traceability.py
governance: ## Policy and agent/sub-agent governance conformance
	cd $(ROOT) && python3 scripts/validate_policy.py && python3 scripts/validate_agent_policy.py && python3 scripts/validate_governance_docs.py && python3 scripts/validate_adoption.py
guard-probe: ## Probe PreToolUse decision; CMD is required
	@test -n "$(CMD)" || { echo 'usage: make guard-probe CMD="<command>"'; exit 2; }
	@set +e; printf '%s' "$(CMD)" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>process.stdout.write(JSON.stringify({tool_name:"Bash",tool_input:{command:s}})))' | CLAUDE_PROJECT_DIR=$(ROOT) bash $(ROOT)/scripts/pretooluse_guard.sh; rc=$$?; set -e; if [ $$rc -eq 0 ]; then echo 'verdict: ALLOW'; elif [ $$rc -eq 2 ]; then echo 'verdict: BLOCK'; exit 2; else echo "verdict: ERROR (rc=$$rc)"; exit $$rc; fi
pre-pr: install lint types cov secrets specs audit remotes projections traceability governance ## Same gate vocabulary as CI
	@echo 'pre-PR validation complete'
clean: ## Remove generated state
	rm -rf coverage .vitest .tsbuildinfo dist node_modules/.cache .governance/vitest-results.json
