# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.1.5  
**Status:** In Progress / Strategic Roadmap

---

## 0. Completed Milestones

### ✅ v2.1.4 — Governance Kernel Extraction & MAS Orchestrator
- [x] Extracted policy evaluation mechanisms into `harness/shared/governance/`.
- [x] Implemented `mango_mas_orchestrator.py` with fail-closed PreToolUse guards.
- [x] Implemented `meta_tools.py` for meta-learning and knowledge gaps tracking.
- [x] Updated C4 architecture, documentation, and root Makefile to align with governance boundaries.

### ✅ v2.1.3 — Python AQA Framework & Code Hygiene
- [x] Implemented full Python AQA suite: 133 tests, 98.44% coverage across `harness/shared`.
- [x] Created root `Makefile` with `lint`, `test`, `coverage`, `validate`, `ci` targets.

---

## 1. Near-Term Milestones (v2.2.0)

### 1.1 Optimize Language Agent Tree Search (LATS)
- [ ] **MCTS Refinement:** Refine the Monte Carlo Tree Search components in the reasoning layer.
- [ ] **Ablation Studies:** Measure the efficacy of LATS implementations against standard chain-of-thought methods.
- [ ] **Trace Logging:** Formalize the trace logging formats for LATS pathways.

### 1.2 Autonomous Healing Integration
- [ ] **Merge Experimental Branch:** Merge and stabilize the experimental Autonomous Healing branch.
- [ ] **Test-Driven Healing:** Wire the healing routines to automatically trigger upon test suite failures (`vitest` and `pytest`).
- [ ] **Policy Enforcement:** Gate autonomous healing behind the `.governance/` policy invariants to prevent out-of-bounds structural modifications.

### 1.3 Multi-Agent Memory Maturation
- [ ] **Persistent Storage:** Extend `meta_tools.py` for persistent JSON/Markdown storage for knowledge gap logs.
- [ ] **Retention Policies:** Establish retention policies and periodic context summarization protocols for the agent `memory/` directory.

---

## 2. Infrastructure & DevSecOps Milestones (v2.3.0)

### 2.1 NVIDIA NIM Multi-Model Routing & Token Budgeting
- [ ] **Dynamic Model Fallback:** Implement multi-tier routing (e.g. fast reasoning → deep synthesis).
- [ ] **Prompt Cache & Cost Tracking:** Add local disk/memory prompt-cache adapter to minimize repeated token costs on invariant verification prompts.
- [ ] **Model Context Protocol (MCP) Server:** Package `NemotronClient` as an independent standard STDIO/SSE MCP server for seamless integration with external AI IDEs and clients.

### 2.2 Pong Engine Enhancements
- [ ] **WebSocket Multiplayer Protocol:** Add real-time deterministic rollback netcode (GGPO-style) for client-to-client PvP over WebSockets.
- [ ] **Audio Customization:** Expose interactive sound effect waveform customization (sine/square/triangle/sawtooth) in the Web UI.
- [ ] **Game State Recording & Replay:** Implement binary snapshot encoding to record full matches for automated test regression playback.
