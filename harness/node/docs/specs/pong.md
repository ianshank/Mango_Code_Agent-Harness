# Pong Game Specification

**Specification Version:** 1.0.0  
**Target Module:** `harness/node/src/pong`  
**Governance Conformance:** Agentic SSD Governance Harness v2.0

---

## 1. Overview & System Requirements

This specification defines the functional, structural, performance, and governance requirements for the modular Pong game engine.

### Requirements & Constraints

- **R-PONG-CONFIG-1 — Dynamic Configuration & Presets:**  
  The system MUST NOT contain hardcoded game constants. All dimensions (canvas, paddles, ball), physics velocities, acceleration multipliers, max bounce angles, spin friction coefficients, winning score thresholds, keybindings, audio frequencies, and render color palettes MUST be dynamically injected and validated via typed configuration schemas with pre-built profiles (e.g. `classic`, `fast`, `arcade`, `tournament`).

- **R-PONG-CORE-2 — Pure 2D Vector Math & Physics Simulation:**  
  The physics engine MUST use deterministic, pure functional 2D vector mathematics. It MUST implement continuous collision detection (CCD) and Axis-Aligned Bounding Box (AABB) collision resolution between the ball and top/bottom boundaries, as well as paddle surfaces with segmented reflection angles, spin acceleration, and velocity scaling.

- **R-PONG-STATE-3 — Deterministic Finite State Machine:**  
  The game lifecycle MUST be managed through an explicit Finite State Machine with defined states: `MENU`, `SERVE`, `PLAYING`, `PAUSED`, `ROUND_OVER`, and `GAME_OVER`. The engine MUST maintain deterministic score state, track rally metrics, and support state snapshots for replay and rollback.

- **R-PONG-INPUT-4 — Decoupled Pluggable Input Subsystem:**  
  The input subsystem MUST decouple physical input hardware from game actions. It MUST support DOM Keyboard events, Touch coordinates, virtual gamepads, and automated AI driver actions through a unified action polling and event listener interface.

- **R-PONG-AI-5 — Multi-Tier Predictive AI Controllers:**  
  The AI system MUST support multiple selectable difficulty tiers:
  1. _Easy (Reactive Tracker):_ Direct ball tracking with simulated human reaction latency and positional jitter.
  2. _Medium (Trajectory Estimator):_ Raycasted trajectory projection calculating wall bounces to arrive at the predicted intercept point.
  3. _Hard/Expert (Adaptive Interceptor):_ Trajectory calculation combined with paddle-edge targeting to return aggressive angular deflection shots.

- **R-PONG-AUDIO-6 — Procedural Sound Synthesis Abstraction:**  
  The audio subsystem MUST provide an abstract synthesizer interface with concrete drivers:
  1. `WebAudioDriver`: Procedurally synthesizes sound effects (paddle hit, wall bounce, score point, match victory) using Web Audio API oscillators without external audio assets.
  2. `NullAudioDriver`: A headless mock driver for CLI and test environments ensuring zero browser-dependency in automated tests.

- **R-PONG-RENDER-7 — Multi-Target Rendering Subsystem:**  
  The render subsystem MUST decouple the game state from output display targets, providing:
  1. `CanvasRenderer`: High-DPI HTML5 Canvas 2D renderer with glowing CRT retro aesthetics, particle effects, and dynamic scoreboard.
  2. `TerminalRenderer`: ANSI 2D terminal renderer supporting direct text-mode CLI gameplay in Node.js/PowerShell/bash.
  3. `NullRenderer`: Fast headless renderer for automated benchmarking and testing.

- **R-PONG-LOOP-8 — Frame-Rate Independent Accumulator Loop:**  
  The game loop MUST use a fixed-timestep physics accumulator pattern (`delta` accumulation with spiral-of-death clamp) decoupled from rendering refresh rates (supporting 60Hz, 120Hz, 144Hz, 240Hz monitors), providing fractional state interpolation for fluid rendering.

- **C-PONG-GOV-9 — Governance, Quality & Traceability Conformance:**  
  All code MUST adhere to strict TypeScript 2026 standards, achieve **>80% test coverage** across Unit, Integration, Functional, E2E, User Journey, Security, and Sanity dimensions, maintain zero test skips without approved waivers, and maintain 100% requirement traceability.

---

## 2. Acceptance Criteria Matrix

| Requirement ID    | Implementation Citation                                                      | Verification Suite                                                                               |
| :---------------- | :--------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------- |
| `R-PONG-CONFIG-1` | `src/pong/core/config.ts`                                                    | `tests/pong/unit/config.test.ts`                                                                 |
| `R-PONG-CORE-2`   | `src/pong/core/physics.ts`, `src/pong/core/vector.ts`                        | `tests/pong/unit/physics.test.ts`, `tests/pong/unit/vector.test.ts`                              |
| `R-PONG-STATE-3`  | `src/pong/core/state-machine.ts`                                             | `tests/pong/unit/state-machine.test.ts`, `tests/pong/functional/pause-resume-reset.test.ts`      |
| `R-PONG-INPUT-4`  | `src/pong/input/input-manager.ts`                                            | `tests/pong/integration/input-ai-interaction.test.ts`                                            |
| `R-PONG-AI-5`     | `src/pong/ai/ai-opponent.ts`                                                 | `tests/pong/unit/ai.test.ts`, `tests/pong/e2e/bot-tournament-e2e.test.ts`                        |
| `R-PONG-AUDIO-6`  | `src/pong/audio/audio-manager.ts`                                            | `tests/pong/integration/audio-render-events.test.ts`                                             |
| `R-PONG-RENDER-7` | `src/pong/render/canvas-renderer.ts`, `src/pong/render/terminal-renderer.ts` | `tests/pong/integration/audio-render-events.test.ts`                                             |
| `R-PONG-LOOP-8`   | `src/pong/loop/game-loop.ts`                                                 | `tests/pong/sanity/loop-sanity.test.ts`                                                          |
| `C-PONG-GOV-9`    | `src/pong/core/game-engine.ts`                                               | `tests/pong/journey/player-journey.test.ts`, `tests/pong/security/security-sanitization.test.ts` |
