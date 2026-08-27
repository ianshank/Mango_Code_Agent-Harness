#!/bin/bash
# SessionStart hook — prepare a remote/web Claude Code session to run the gates.
#
# Without this, `make lint`, `make coverage-python` and `make validate` fail on a
# fresh container with "No module named ruff/mypy/pytest", and the api_server
# tests fail on a missing fastapi. Installing synchronously (not backgrounded)
# is deliberate: an agent may run `make ci` on its very first turn, and a race
# between that and the install is exactly the failure this prevents.
#
# Python only. `make test-node` / `verify-zero-skips` additionally need:
#   cd harness/node && pnpm install --frozen-lockfile
# That install is slow against the committed lockfile and most sessions never
# touch the Node stack, so it stays a deliberate, opt-in step.
set -euo pipefail

# Local workstations manage their own virtualenvs; only prepare managed remotes.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
    exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

if [ ! -f requirements-dev.txt ]; then
    echo "session-start: requirements-dev.txt not found; skipping dependency install" >&2
    exit 0
fi

echo "session-start: installing Python dev dependencies (pinned)"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements-dev.txt
python -m pip install --quiet -e .
echo "session-start: ready — 'make lint' and 'make coverage-python' can now run"
