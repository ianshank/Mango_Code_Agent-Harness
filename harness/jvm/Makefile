SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
GRADLE ?= $(ROOT)/gradlew
GRADLE_FLAGS ?=
GITLEAKS ?= gitleaks
GITLEAKS_VERSION ?= v8.28.0
OSV ?= osv-scanner
OSV_VERSION ?= v2.2.3
# Both `*-install` targets run `go install`, which puts the binary in
# `$(go env GOPATH)/bin` -- not on PATH by default -- so `secrets` and `audit`
# failed closed right after their own install step. Resolve each tool as it was
# installed: PATH first, then GOPATH/bin; a name found in neither stays as
# written so the `command -v` guards still fail closed (root Makefile, same note).
GO_BIN_DIR := $(shell go env GOPATH 2>/dev/null)/bin
GITLEAKS := $(shell command -v $(GITLEAKS) 2>/dev/null || { test -x $(GO_BIN_DIR)/$(GITLEAKS) && echo $(GO_BIN_DIR)/$(GITLEAKS); } || echo $(GITLEAKS))
OSV := $(shell command -v $(OSV) 2>/dev/null || { test -x $(GO_BIN_DIR)/$(OSV) && echo $(GO_BIN_DIR)/$(OSV); } || echo $(OSV))
.PHONY: help install lockfiles format lint types test cov secrets specs audit remotes projections traceability governance guard-probe pre-pr clean secrets-install audit-install
help:
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-18s %s\n", $$1, $$2}'
install: ## Resolve locked, verified dependencies and install hook
	@test -x $(GRADLE) || { echo 'gradlew missing; generate/commit the Gradle wrapper'; exit 1; }
	@test -f $(ROOT)/gradle.lockfile || { echo 'gradle.lockfile missing; run make lockfiles in a reviewed bootstrap'; exit 1; }
	@test -f $(ROOT)/gradle/verification-metadata.xml || { echo 'gradle/verification-metadata.xml missing; run make lockfiles and review checksums'; exit 1; }
	$(GRADLE) $(GRADLE_FLAGS) classes testClasses
	bash $(ROOT)/scripts/install_hooks.sh
lockfiles: ## Deliberately regenerate lock state and dependency verification metadata
	@test -x $(GRADLE) || { echo 'gradlew missing'; exit 1; }
	$(GRADLE) $(GRADLE_FLAGS) dependencies --write-locks
	$(GRADLE) $(GRADLE_FLAGS) --write-verification-metadata sha256 help
format: ## Apply formatting
	$(GRADLE) $(GRADLE_FLAGS) spotlessApply
lint: ## Formatting, static analysis, dependency analysis
	$(GRADLE) $(GRADLE_FLAGS) spotlessCheck detekt buildHealth
types: ## Compiler/type gate
	$(GRADLE) $(GRADLE_FLAGS) typesCheck
test: ## Tests followed by build-failing zero-skip verification
	$(GRADLE) $(GRADLE_FLAGS) verifyNoSkippedTests
cov: ## Coverage and zero-skip verification
	$(GRADLE) $(GRADLE_FLAGS) verifyNoSkippedTests jacocoTestReport jacocoTestCoverageVerification
secrets: ## Working-tree and full-history secret scans
	@command -v $(GITLEAKS) >/dev/null || { echo 'gitleaks missing; failing closed'; exit 1; }
	@test -f $(ROOT)/.gitleaks.toml || { echo '.gitleaks.toml missing'; exit 1; }
	$(GITLEAKS) dir $(ROOT) --config $(ROOT)/.gitleaks.toml --redact --no-banner
	$(GITLEAKS) git $(ROOT) --config $(ROOT)/.gitleaks.toml --redact --no-banner --log-opts="HEAD"
secrets-install:
	go install github.com/zricethezav/gitleaks/v8@$(GITLEAKS_VERSION)
specs: ## Spec validation
	bash $(ROOT)/scripts/validate_specs.sh
audit: ## Locked dependency vulnerability scan
	@command -v $(OSV) >/dev/null || { echo 'osv-scanner missing; failing closed'; exit 1; }
	@test -f $(ROOT)/gradle.lockfile || { echo 'gradle.lockfile missing; refusing vacuous audit'; exit 1; }
	$(OSV) scan --lockfile=$(ROOT)/gradle.lockfile --config=$(ROOT)/osv-scanner.toml
audit-install:
	go install github.com/google/osv-scanner/v2/cmd/osv-scanner@$(OSV_VERSION)
remotes: ## Verify every configured Git push URL against the allowlist
	PYTHONPATH=$(ROOT)/../.. python3 $(ROOT)/scripts/remotes.py --check-current-remotes --repo $(ROOT) --allowlist $(ROOT)/.governance/allowed-remotes.txt
projections: ## Projection applicability/drift gate
	cd $(ROOT) && PYTHONPATH=../.. python3 scripts/check_projections.py
traceability: ## Requirement traceability gate
	cd $(ROOT) && PYTHONPATH=../.. python3 scripts/check_traceability.py
governance: ## Policy and agent/sub-agent governance conformance
	cd $(ROOT) && PYTHONPATH=../.. python3 scripts/validate_policy.py && PYTHONPATH=../.. python3 scripts/validate_agent_policy.py && PYTHONPATH=../.. python3 scripts/validate_governance_docs.py && PYTHONPATH=../.. python3 scripts/validate_adoption.py
guard-probe: ## Probe PreToolUse decision; CMD is required
	@test -n "$(CMD)" || { echo 'usage: make guard-probe CMD="<command>"'; exit 2; }
	@set +e; printf '%s' "$(CMD)" | python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.stdin.read()}}))' | CLAUDE_PROJECT_DIR=$(ROOT) bash $(ROOT)/scripts/pretooluse_guard.sh; rc=$$?; set -e; if [ $$rc -eq 0 ]; then echo 'verdict: ALLOW'; elif [ $$rc -eq 2 ]; then echo 'verdict: BLOCK'; exit 2; else echo "verdict: ERROR (rc=$$rc)"; exit $$rc; fi
pre-pr: install lint types cov secrets specs audit remotes projections traceability governance ## Same gate vocabulary as CI
	@echo 'pre-PR validation complete'
clean:
	$(GRADLE) $(GRADLE_FLAGS) clean
	rm -f build/governance/runtime-skips.tsv
