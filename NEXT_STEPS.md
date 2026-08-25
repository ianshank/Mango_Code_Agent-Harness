# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.1.3  
**Status:** In Progress / Strategic Roadmap

---

## 0. Completed Milestones

### ✅ v2.1.2 — Nemotron Model Migration & Live Smoke Tests
- [x] Migrated to `nvidia/llama-3.3-nemotron-super-49b-v1` (from deprecated `nvidia/llama-3.1-nemotron-70b-instruct`).
- [x] Added live smoke test tier (`tests/ai/smoke/`) with shared fixtures and cost-conscious client factory.
- [x] Added Python bridge live validation with wire parity contract test.

### ✅ v2.1.3 — Python AQA Framework & Code Hygiene
- [x] Implemented full Python AQA suite: 133 tests, 98.44% coverage across `harness/shared`.
- [x] Created root `Makefile` with `lint`, `test`, `coverage`, `validate`, `ci` targets.
- [x] Resolved all ruff/mypy violations in test code. Added `pyproject.toml` tooling config.
- [x] Updated `.gitignore`, `.dockerignore`, `.gitleaks.toml`, C4 architecture, and CHANGELOG.

---

## 1. Near-Term Milestones (v2.2.0)

### 1.1 NVIDIA NIM Multi-Model Routing & Token Budgeting
- [ ] **Dynamic Model Fallback:** Implement multi-tier routing (e.g. fast reasoning → deep synthesis).
- [ ] **Prompt Cache & Cost Tracking:** Add local disk/memory prompt-cache adapter to minimize repeated token costs on invariant verification prompts.
- [ ] **Model Context Protocol (MCP) Server:** Package `NemotronClient` as an independent standard STDIO/SSE MCP server for seamless integration with external AI IDEs and clients.

### 1.2 Pong Engine Enhancements
- [ ] **WebSocket Multiplayer Protocol:** Add real-time deterministic rollback netcode (GGPO-style) for client-to-client PvP over WebSockets.
- [ ] **Audio Customization:** Expose interactive sound effect waveform customization (sine/square/triangle/sawtooth) in the Web UI.
- [ ] **Game State Recording & Replay:** Implement binary snapshot encoding to record full matches for automated test regression playback.

### 1.3 CI/CD Hardening
- [ ] **GitHub Actions CI Workflow:** Create `.github/workflows/ci.yml` with pinned full commit SHAs (`PIN_FULL_COMMIT_SHA`).
- [ ] **Pre-Push Git Hook:** Wire `make pre-pr` into local Git hooks for developer-local validation.

---

## 2. Infrastructure & DevSecOps Milestones (v2.3.0)

### 2.1 Container & Cloud Orchestration
- [ ] **Kubernetes Deployment Manifests:** Provide Helm charts for hosting containerized Pong tournament servers and Nemotron proxy relays.

### 2.2 Advanced Agentic Governance
- [ ] **Dynamic Policy Synthesis:** Enable `nemotron-reasoner` subagent to generate formal TLA+ state machine invariants for new harness modules.
- [ ] **Telemetry Dashboard:** Build a Grafana/OpenTelemetry export bridge tracking token counts, API latency percentiles (p50/p95/p99), and circuit breaker health.

### 2.3 Reusable Agent Skills
- [ ] **Validation Runner Skill:** Package the governance validation pipeline as an autonomous agent skill for cross-project reuse.
- [ ] **Coverage Gate Skill:** Create a reusable skill that enforces coverage thresholds and reports gaps.
