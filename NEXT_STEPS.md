# Roadmap & Next Steps: Agentic SSD & Nemotron AI Platform

**Version:** 2.1.0  
**Status:** In Progress / Strategic Roadmap

---

## 1. Near-Term Milestones (v2.2.0)

### 1.1 NVIDIA NIM Multi-Model Routing & Token Budgeting
- [ ] **Dynamic Model Fallback:** Implement multi-tier routing (e.g. `nvidia/llama-3.1-nemotron-70b-instruct` for fast reasoning, `nvidia/nemotron-4-340b-instruct` for deep synthesis).
- [ ] **Prompt Cache & Cost Tracking:** Add local disk/memory prompt-cache adapter to minimize repeated token costs on invariant verification prompts.
- [ ] **Model Context Protocol (MCP) Server:** Package `NemotronClient` as an independent standard STDIO/SSE MCP server for seamless integration with external AI IDEs and clients.

### 1.2 Pong Engine Enhancements
- [ ] **WebSocket Multiplayer Protocol:** Add real-time deterministic rollback netcode (GGPO-style) for client-to-client PvP over WebSockets.
- [ ] **Audio Customization:** Expose interactive sound effect waveform customization (sine/square/triangle/sawtooth) in the Web UI.
- [ ] **Game State Recording & Replay:** Implement binary snapshot encoding to record full matches for automated test regression playback.

---

## 2. Infrastructure & DevSecOps Milestones (v2.3.0)

### 2.1 Container & Cloud Orchestration
- [ ] **Kubernetes Deployment Manifests:** Provide Helm charts for hosting containerized Pong tournament servers and Nemotron proxy relays.
- [ ] **Automated GitHub Actions CI Hardening:** Pin full commit SHAs for all external actions in `.github/workflows/ci.yml`.

### 2.2 Advanced Agentic Governance
- [ ] **Dynamic Policy Synthesis:** Enable `nemotron-reasoner` subagent to generate formal TLA+ state machine invariants for new harness modules.
- [ ] **Telemetry Dashboard:** Build a Grafana/OpenTelemetry export bridge tracking token counts, API latency percentiles (p50/p95/p99), and circuit breaker health.
