#!/bin/bash
# SessionStart hook — prepare a remote/web Claude Code session to run the gates.
#
# Without this, `make lint`, `make coverage-python` and `make validate` fail on a
# fresh container with "No module named ruff/mypy/pytest", and the api_server
# tests fail on a missing fastapi. Installing synchronously (not backgrounded)
# is deliberate: an agent may run `make ci` on its very first turn, and a race
# between that and the install is exactly the failure this prevents.
#
# Node dependencies are installed too, through `make node-deps` -- the same
# recipe CI uses, so the three environments cannot drift into installing
# different things. Previously this hook was Python-only, which meant CLAUDE.md
# called `make pre-pr` non-negotiable while `make ci` could not complete in a
# web session at all: test-node and verify-zero-skips have no node_modules.
# Set MANGO_SKIP_NODE_DEPS=1 to opt out when a session will not touch the Node
# stack and the extra install time is not wanted.
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
if [ "${MANGO_SKIP_NODE_DEPS:-}" = "1" ]; then
    echo "session-start: MANGO_SKIP_NODE_DEPS=1 — skipping Node deps; 'make ci' will fail at test-node"
    exit 0
fi

if ! command -v pnpm >/dev/null 2>&1; then
    # Not fatal: the Python gates are already usable, and failing the hook would
    # leave the session worse off than a partial install.
    echo "session-start: pnpm not on PATH; skipping Node deps ('make ci' will fail at test-node)" >&2
    exit 0
fi

echo "session-start: installing Node dependencies (make node-deps)"
if make node-deps >/dev/null 2>&1; then
    echo "session-start: ready — 'make ci' can now run end to end"
else
    echo "session-start: Node dependency install failed; Python gates are still usable" >&2
fi
