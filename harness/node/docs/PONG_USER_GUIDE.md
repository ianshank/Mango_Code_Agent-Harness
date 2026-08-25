# Pong Engine User & Developer Guide

**Module:** `harness/node/src/pong`  
**Standard:** 2026 Modular Engine  

---

## 1. Quick Start

### Running in Node Terminal (CLI Mode)

To launch the interactive ANSI terminal game or autonomous bot tournament:

```bash
# Autonomous AI vs AI Tournament (Headless / Fast)
npx tsx src/pong/cli/pong-cli.ts --autoplay --ticks 1000

# Interactive Terminal Gameplay (Player vs AI)
npx tsx src/pong/cli/pong-cli.ts --mode pve --difficulty medium

# Head-to-Head Terminal (Player 1 vs Player 2)
npx tsx src/pong/cli/pong-cli.ts --mode pvp
```

### Running in Browser (Web UI Mode)

Open `src/pong/web/index.html` in any modern web browser or serve it locally with Vite/live-server to enjoy hardware-accelerated 60-144fps Canvas 2D graphics with procedural sound effects.

---

## 2. Controls

| Action | Player 1 (Left Paddle) | Player 2 (Right Paddle) |
| :--- | :--- | :--- |
| Move Up | `W` or `ArrowUp` (in Single Player) | `ArrowUp` (in 2P mode) |
| Move Down | `S` or `ArrowDown` (in Single Player) | `ArrowDown` (in 2P mode) |
| Serve / Start | `Space` / `Enter` | `Space` / `Enter` |
| Pause / Resume | `P` / `Escape` | `P` / `Escape` |
| Reset Match | `R` | `R` |

---

## 3. Configuration Profiles

The game engine accepts dynamic configuration overrides:

```typescript
import { createGameConfig, GameEngine, CanvasRenderer, AudioManager } from './src/pong/index.js';

// Load preset profile or customize parameters
const config = createGameConfig('fast', {
  maxScore: 11,
  ball: {
    baseSpeed: 450,
    speedMultiplier: 1.08,
    maxSpeed: 1000,
  },
  ai: {
    difficulty: 'expert',
    reactionDelayTicks: 2,
    predictionAccuracy: 0.98,
  }
});
```

---

## 4. Test Suite Execution

Run the complete 7-tier test matrix:

```bash
# Run all tests with coverage report & zero-skip check
pnpm run test:coverage

# Run specific test suites
pnpm vitest run tests/pong/unit/
pnpm vitest run tests/pong/integration/
pnpm vitest run tests/pong/functional/
pnpm vitest run tests/pong/e2e/
pnpm vitest run tests/pong/journey/
pnpm vitest run tests/pong/security/
pnpm vitest run tests/pong/sanity/
```
