#!/bin/bash
# post-nemotron-reasoner-run - orchestrator post-turn recorder (NS-21).
# Presence enables the hook; body lives in lib/record_post_run.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib/record_post_run.sh
source "${SCRIPT_DIR}/lib/record_post_run.sh"
