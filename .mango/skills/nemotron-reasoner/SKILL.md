---
name: nemotron-reasoner
Reviewed: 2026-08-28
description: Invoke NVIDIA Nemotron Ultra API for deep reasoning, architectural audits, and spec verification.
---

# NVIDIA Nemotron Ultra AI Skill

Use this skill when you need high-capacity chain-of-thought reasoning, multi-turn architectural audits, or formal verification via the NVIDIA Nemotron Ultra API.

## Available Invocation Channels

### 1. TypeScript CLI Runner (Node)

```bash
# Basic reasoning query
npx tsx harness/node/src/ai/nemotron/cli.ts --prompt "Analyze the deterministic collision system in src/pong/core/physics.ts"

# Query with specific model and temperature
npx tsx harness/node/src/ai/nemotron/cli.ts \
  --prompt "Review state machine transitions for race conditions" \
  --model "nvidia/llama-3.1-nemotron-70b-instruct" \
  --temperature 0.2 \
  --stream
```

### 2. Python Bridge (Shared Tools & Hooks)

```bash
# Python CLI execution
python harness/shared/nemotron_bridge.py --prompt "Audit INV-1 secret scan rules in test_harness.py"
```

### 3. Programmatic Node API

```typescript
import { NemotronClient } from './src/ai/nemotron/nemotron-client.js';

const client = new NemotronClient();
const response = await client.complete({
  messages: [
    { role: 'system', content: 'You are an adversarial security architect.' },
    { role: 'user', content: 'Verify secret redaction in logging pipelines.' }
  ],
  temperature: 0.1
});
console.log(response.content);
```

## Security & Credential Rules

- The API key is loaded dynamically from `NVIDIA_API_KEY` (or `.env`).
- Never pass raw API keys as CLI parameters or log them in trace files.
