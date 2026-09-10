#!/bin/bash
# Shared body for post-{role}-run orchestrator hooks (NS-21).
# Thin entrypoints under .mango/hooks/ source this file; their presence on disk
# is the enablement switch. Appends one JSONL record of turn outcome + spend.
set -euo pipefail

STATUS="${MANGO_HOOK_STATUS:-}"
RUN_ID="${MANGO_HOOK_RUN_ID:-}"
AGENT="${MANGO_HOOK_AGENT:-}"
USED="${MANGO_HOOK_TOOL_CALLS_USED:-}"
LIMIT="${MANGO_HOOK_TOOL_CALLS_LIMIT:-}"

RECORD_PATH="${MANGO_HOOK_RECORD_PATH:-.mango/.state/post-run.jsonl}"
RECORD_DIR="$(dirname "$RECORD_PATH")"
mkdir -p "$RECORD_DIR"

# Encode via python so values cannot break the JSON line.
python3 - "$RECORD_PATH" "$STATUS" "$RUN_ID" "$AGENT" "$USED" "$LIMIT" <<'PY'
import json
import sys

path, status, run_id, agent, used, limit = sys.argv[1:7]

def _int_or_none(raw: str):
    if raw == "":
        return None
    return int(raw)

record = {
    "status": status,
    "run_id": run_id,
    "agent": agent,
    "tool_calls_used": _int_or_none(used),
    "tool_calls_limit": _int_or_none(limit),
}
with open(path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record, separators=(",", ":")) + "\n")
PY

echo "[.mango hook] recorded post-run status=${STATUS} agent=${AGENT} used=${USED}/${LIMIT} run_id=${RUN_ID}"
exit 0
