# C4 Architecture Model: Agentic SSD & NVIDIA Nemotron AI Platform

**System:** Agentic SSD & NVIDIA Nemotron AI Platform (Mango Ecosystem)  
**Version:** 2.1.8 (2026 Standards)  
**Governance:** `harness/CONTRACT.md` / Agentic SSD Governance Harness v2.1 (INV-1..INV-16)

---

## 1. System Context Diagram (Level 1)

The System Context diagram illustrates the high-level actors, the Autonomous Mango Multi-Agent Ecosystem, and external cloud infrastructure.

```mermaid
graph TD
    User([Developer / Player]) -->|Commands, Gameplay & Prompts| Platform[Agentic SSD & Nemotron Platform]
    
    subgraph "External Cloud Services & PDP"
        NIM[NVIDIA NIM Cloud API<br/>integrate.api.nvidia.com]
        ExtPDP[External Tool Broker / PDP<br/>Policy Decision Point]
        GitServer[Remote Git Server<br/>GitHub / GitLab]
        Context7[Upstash Context7 MCP<br/>Real-Time Documentation Engine]
    end

    Platform -->|HTTPS /v1/chat/completions| NIM
    Platform -->|Action Authorization Request| ExtPDP
    Platform -->|Verified Push / Audit| GitServer
    Platform -->|Documentation & Context Sync| Context7
```

---

## 2. Container Diagram (Level 2)

The Container diagram shows the runtime environments, repositories, tools, and execution processes.

```mermaid
graph TD
    User([Developer / Engineer]) --> CLI[Terminal CLI / PowerShell / Bash]
    User --> Browser[Web Browser<br/>HTML5 Canvas 2D UI]

    subgraph "Repository Runtime Containers"
        subgraph ".agents Skill Registry"
            AgentSkills[Skills: nemotron-reasoner<br/>Native Antigravity Skill Definition]
        end

        subgraph ".mango Agent Runtime"
            MA[Mango Agent Core]
            SubAgents[Subagents: nemotron-reasoner, planner, verifier]
            Personas[Persona Topology: Web Presenter, Node Bridge]
            Hooks[Lifecycle Hooks: PreToolUse, Stop, SessionStart, PreNemotron]
            Skills[Skills: repo-invariant-review, openspec-peer-review, nemotron-reasoner]
            MetaTools[Continuous Learning & MCPs: knowledge_gap_log, query_docs (Context7) [Planned]]
            Memory[(Local JSON Memory: gaps.json, hypotheses.json)]
            MA --> SubAgents
            SubAgents --> Personas
            MA --> Hooks
            MA --> Skills
            MA --> MetaTools
            MetaTools --> Memory
        end

        subgraph "Node.js Container - harness/node"
            TSClient[NemotronClient<br/>TypeScript Adapter & Circuit Breaker]
            PongEngine[Pong Game Engine<br/>Physics, FSM, Renderers]
            VitestRunner[Vitest Test Runner<br/>95 Tests / 7 Tiers]
            PongCli[Pong CLI Runner<br/>Autoplay & Tournament]
        end

        subgraph "Python Shared Runtime - harness/shared"
            PyBridge[nemotron_bridge.py<br/>Python Adapter]
            Orchestrator[mango_mas_orchestrator.py<br/>MAS Orchestrator]
            MetaTools[meta_tools.py<br/>Meta-Learning Tools + file_lock]
            subgraph "Cognitive Boundary — INV-16 (one-directional)"
                Signal[cognitive_signal.py<br/>CognitiveSignal envelope + JSONL sink]
                Shadow[shadow_planner.py<br/>Shadow-mode comparison channel<br/>MANGO_SHADOW_PLANNER, off by default]
                Shadow -->|emits, zero tool authority| Signal
            end
            subgraph "governance/"
                GovGuards[pretooluse_guard.py<br/>Policy Guards]
                Validators["Governance Validators<br/>traceability, zero-skips, remotes"]
                Evidence[evidence_manifest.py<br/>EvidenceBuilder — HMAC attestation]
            end
            RootValidators["Root Validators<br/>policy, adoption, agent-policy"]
            Orchestrator -.->|guarded, observation-only| Shadow
        end

        subgraph "Control Plane - harness/control-plane"
            Publisher[publish_policy_artifact.py<br/>Versioned, digest-pinned policy artifact]
            Artifact[(policy-artifact.json<br/>committed, drift-gated)]
            Verifier[verify_repository.py<br/>External root-of-trust verifier]
            Publisher -->|attest, optional| Evidence
            Publisher --> Artifact
        end

        subgraph "Python AQA Engine - harness/shared/tests"
            AQA["Pytest AQA Suite<br/>490+ Tests / >=90% Coverage (per policy)"]
            RunpyExec["runpy.run_path() Executor<br/>In-Process CLI Coverage"]
            AQA --> RunpyExec
            RunpyExec -->|executes in-process| Validators
            RunpyExec -->|executes in-process| PyBridge
            RunpyExec -->|executes in-process| GovGuards
            AQA -->|drift gate| Artifact
        end
    end

    CLI --> PongCli
    CLI --> TSClient
    CLI --> PyBridge
    Browser --> PongEngine

    SubAgents --> TSClient
    SubAgents --> PyBridge
    Hooks --> GovGuards

    TSClient -->|HTTPS POST| NIM[NVIDIA Nemotron Ultra API]
    PyBridge -->|HTTPS POST| NIM
```

---

## 3. Component Diagram (Level 3)

### 3.1 NVIDIA Nemotron AI Subsystem (`harness/node/src/ai/nemotron/`)

```mermaid
graph TD
    Caller[Mango Subagent / CLI / App] --> Client[NemotronClient]
    
    subgraph "Nemotron Module Components"
        Client --> Config[Config & Secret Resolver]
        Client --> Masker[SecretMasker Utility]
        Client --> Backoff[Exponential Backoff & Jitter Engine]
        Client --> CB[3-State Circuit Breaker]
        Client --> SSE[SSE Streaming Parser]
        Client --> Telemetry[Token & Latency Accounting]
    end
    
    Config -.-> EnvVar[(.env / Process Env<br/>NVIDIA_API_KEY)]
    Client -->|Authorized HTTPS POST| Cloud[NVIDIA NIM Endpoint]
```

### 3.2 Deterministic Pong Engine Subsystem (`harness/node/src/pong/`)

```mermaid
graph TD
    GL[Fixed-Timestep GameLoop<br/>60Hz Accumulator] --> GE[GameEngine Orchestrator]
    Input[InputManager & KeyboardDriver] --> GE
    AI[AIOpponent<br/>Predictive Raycaster] --> GE

    subgraph "Deterministic Core"
        GE --> Vec[Pure 2D Vector Math]
        GE --> Phys[Continuous Collision Detection]
        GE --> FSM[6-State Finite State Machine]
    end

    GE --> Audio[AudioManager -> WebAudioDriver / NullAudioDriver]
    GE --> Render[RenderManager -> CanvasRenderer / TerminalRenderer / NullRenderer]
```

---

## 4. Code & Governance Diagram (Level 4)

### 4.1 Fail-Closed Invariants & Governance Gates

```mermaid
flowchart TD
    Commit[Pre-PR Git Commit] --> Secrets[INV-1: Full Working Tree & History Secret Scan]
    Secrets --> ZeroSkip[INV-2: Zero-Skip Test Verification]
    ZeroSkip --> Remotes[INV-3: Canonical Remote URL Normalizer & Allowlist]
    Remotes --> Hooks[INV-4: Non-Destructive Effective Git Hook Installer]
    Hooks --> SpecTrace[Traceability: Bidirectional Requirements]
    SpecTrace --> Policy[INV-6: External Root of Trust Digest Verification]
    Policy --> ArtifactDrift["Policy Artifact Drift Gate<br/>(publish_policy_artifact --check, via pytest)"]
    ArtifactDrift --> Delegation[INV-7: Bounded Agent Authority & Trace Logging]
    Delegation --> Boundary["INV-16: Cognitive/Execution Boundary<br/>(no CognitiveSignal field reaches a control path)"]
    Boundary --> Pass[PR Approved for Merge]
```

### 4.2 Cognitive/Execution Boundary (INV-16)

The shadow planner channel is one-directional and off by default. It is
included at Level 4, not Level 2/3, because its defining property is a
constraint on data flow rather than a runtime container: no field of a
`CognitiveSignal` may reach a control path, select a tool, or alter tool
exposure, and observation-mode code never receives the live orchestrator.

```mermaid
flowchart LR
    subgraph "Incumbent path (always runs)"
        Planner[planner role] --> Plan[incumbent plan]
        Plan --> Reasoner[nemotron-reasoner]
        Reasoner --> Verifier[verifier]
    end

    subgraph "Shadow channel (MANGO_SHADOW_PLANNER=1 only)"
        Plan -.->|value object, zero tool authority| ShadowCall[shadow_planner.run_shadow_comparison]
        ShadowCall -->|tools=[], bounded timeout| ShadowModel[shadow model call]
        ShadowModel --> Signals[(cognitive-signals.jsonl<br/>.mango/memory/signals, gitignored)]
        ShadowCall -.->|never raises; caller swallows and logs| Verifier
    end

    Signals -.->|read-only, offline| Analysis["shadow-channel-analysis skill<br/>(UC-4 kill-criteria reporting)"]
```

Enforced by `pytest -m governance` (byte-identity when disabled,
zero-authority, envelope invariance, containment) and the static boundary
scan in `test_shadow_planner.py`. See `docs/specs/mangomas-integration-core.md`
and `.mango/skills/boundary-invariant-review/SKILL.md`.
