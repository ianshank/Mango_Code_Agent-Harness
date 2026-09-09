#!/usr/bin/env bash
# guard-forbidden-paths.sh — Forbidden-path guard shim
# Called PreToolUse by .mango/agents/hooks.json
#
# Claude Code PreToolUse hook receives JSON on stdin describing the tool call.
# We parse stdin, extract file-path arguments, and check each against the
# protected-path predicate exported by validate_invariants.py.
#
# Fails closed (exit 1) if:
#   - A path matches any protected pattern
#   - validate_invariants.py cannot be found
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo "$(cd "$(dirname "$0")/.." && pwd)")"
cd "${REPO_ROOT}"

VALIDATOR="${REPO_ROOT}/harness/shared/validate_invariants.py"
if [[ ! -f "${VALIDATOR}" ]]; then
    echo "guard-forbidden-paths: validate_invariants.py not found; failing closed" >&2
    exit 1
fi

# Resolve the venv Python if available, fall back to system python3
VENV_PY="${REPO_ROOT}/.venv/Scripts/python.exe"
if [[ -x "${VENV_PY}" ]]; then
    PYTHON="${VENV_PY}"
elif [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
    PYTHON="${REPO_ROOT}/.venv/bin/python"
else
    PYTHON="$(command -v python3 || command -v python)"
fi

# Read hook payload (may be empty when fired without stdin)
INPUT="$(cat -)"

"${PYTHON}" - "${REPO_ROOT}" "${INPUT}" <<'PYEOF'
import json, sys
from pathlib import Path

repo_root = Path(sys.argv[1])
raw_input = sys.argv[2] if len(sys.argv) > 2 else ""

try:
    payload = json.loads(raw_input) if raw_input.strip() else {}
except json.JSONDecodeError:
    sys.exit(0)

tool_input = payload.get("tool_input", payload.get("input", {}))

paths_to_check: list[str] = []
if isinstance(tool_input, dict):
    for key, val in tool_input.items():
        if isinstance(val, str) and (
            "path" in key.lower() or "file" in key.lower() or key in ("target", "destination")
        ):
            paths_to_check.append(val)

if not paths_to_check:
    sys.exit(0)

sys.path.insert(0, str(repo_root))
from harness.shared.validate_invariants import is_protected, load_protected_patterns

policy_path = repo_root / "harness" / "shared" / "governance-policy.json"
patterns = load_protected_patterns(policy_path)

for p in paths_to_check:
    try:
        rel = Path(p).resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        rel = p

    if is_protected(rel, patterns):
        print(f"guard-forbidden-paths: DENIED write to protected path: {rel}", file=sys.stderr)
        sys.exit(1)

sys.exit(0)
PYEOF
