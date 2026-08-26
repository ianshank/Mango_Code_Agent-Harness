---
name: nemotron-reasoner
description: Executes NVIDIA Nemotron models for structural reasoning tasks via the Python Bridge.
---

# Nemotron Reasoner

This skill enables agents to invoke the `nemotron_bridge.py` script to perform advanced reasoning or generation tasks using NVIDIA NIM models.

## Usage

Use the `run_command` tool to execute the bridge. Pass the prompt and an optional system instruction.

```bash
python harness/shared/nemotron_bridge.py --prompt "Your reasoning task here" --json
```

## Flags

- `--prompt`: The user prompt (required).
- `--system`: The system instruction (defaults to architect/reasoning assistant).
- `--model`: The target model ID (overrides NEMOTRON_DEFAULT_MODEL).
- `--temperature`: The sampling temperature (default: 0.2).
- `--json`: Output raw JSON response instead of text formatting.
- `--debug`: Enable verbose debug logging.

## Requirements

The `NVIDIA_API_KEY` and `NEMOTRON_DEFAULT_MODEL` environment variables must be configured in the workspace `.env` file.
