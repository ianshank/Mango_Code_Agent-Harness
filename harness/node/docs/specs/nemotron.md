# NVIDIA Nemotron Ultra AI Client Specification

**Specification Version:** 1.0.0  
**Target Module:** `harness/node/src/ai/nemotron`  
**Governance Conformance:** Agentic SSD Governance Harness v2.0

---

## 1. Overview & System Requirements

This specification defines the functional, architectural, resilience, and security requirements for the NVIDIA Nemotron Ultra integration.

### Requirements & Constraints

- **R-AI-NEMO-1 — OpenAI-Compatible Wire Protocol & Provider Abstraction:**  
  The AI client MUST conform to the standard OpenAI `/chat/completions` REST wire protocol. The client MUST support target models (e.g. `nvidia/llama-3.1-nemotron-70b-instruct`), custom base URLs (`https://integrate.api.nvidia.com/v1`), configurable timeouts, and dynamic endpoint injection.

- **R-AI-NEMO-2 — Strict Streaming, Typing & Token Telemetry:**  
  The module MUST expose typed interfaces for chat messages, non-streaming completions, and Server-Sent Events (SSE) streaming yielding async iterable chunks. The response MUST capture execution latency and token usage metrics (`prompt_tokens`, `completion_tokens`, `total_tokens`).

- **R-AI-RES-3 — Exponential Backoff with Jitter & Circuit Breaker:**  
  The client MUST implement automatic exponential backoff with full jitter for retryable HTTP status codes (HTTP 429 Rate Limit, 500, 502, 503, 504). The client MUST incorporate a 3-state Circuit Breaker (`CLOSED`, `OPEN`, `HALF_OPEN`) to prevent cascading outages during upstream network failures.

- **C-AI-SEC-1 — Secret Sanitization & Fail-Closed Credential Governance:**  
  Raw API keys (`nvapi-...`) MUST NEVER be hardcoded in source files or exposed in stdout, logs, error traces, or test artifacts. The client MUST sanitize errors before re-throwing and fail closed when credentials are missing.

---

## 2. Acceptance Criteria Matrix

| Requirement ID | Implementation Citation | Verification Suite |
| :--- | :--- | :--- |
| `R-AI-NEMO-1` | `src/ai/nemotron/nemotron-client.ts` | `tests/ai/unit/nemotron-client.test.ts`, `tests/ai/e2e/nemotron-e2e.test.ts` |
| `R-AI-NEMO-2` | `src/ai/nemotron/types.ts`, `src/ai/nemotron/nemotron-client.ts` | `tests/ai/integration/nemotron-streaming.test.ts`, `tests/ai/functional/prompt-completion.test.ts` |
| `R-AI-RES-3` | `src/ai/nemotron/circuit-breaker.ts`, `src/ai/nemotron/nemotron-client.ts` | `tests/ai/sanity/resilience-stress.test.ts` |
| `C-AI-SEC-1` | `src/ai/nemotron/secret-masker.ts`, `src/ai/nemotron/nemotron-client.ts` | `tests/ai/security/secret-safety.test.ts` |
