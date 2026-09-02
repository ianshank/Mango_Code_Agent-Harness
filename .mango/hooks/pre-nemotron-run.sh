#!/bin/bash
# Pre-Nemotron Run Hook
# Ensures that all governance invariants are satisfied before allowing the orchestrator to mutate code.

set -e

echo "[.mango hook] Running pre-nemotron-run validation..."

# Check if the validator exists
VALIDATOR="harness/shared/validate_invariants.py"
if [ ! -f "$VALIDATOR" ]; then
    echo "[.mango hook] ERROR: Validator script $VALIDATOR not found."
    exit 1
fi

# Run the Python validator
python3 "$VALIDATOR"

echo "[.mango hook] Validation passed. Proceeding with Nemotron Orchestrator execution."
exit 0
