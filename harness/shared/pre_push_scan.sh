#!/usr/bin/env bash
# Native execution-time Git push control. Git supplies the actual remote URL.
set -euo pipefail
block(){ echo "BLOCKED: $1" >&2; echo "Remediation: $2" >&2; exit 1; }
[ "$#" -ge 2 ] || block "expected <remote-name> <remote-url>" "invoke through git push"
REMOTE_NAME="$1"; REMOTE_URL="$2"; REFS="$(cat || true)"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || block "cannot resolve repository root" "run inside a git work tree"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$SCRIPT_DIR/remotes.py" ] || block "shared remote normalizer missing" "restore remotes.py"
GOV_DIR="$(dirname "$SCRIPT_DIR")/.governance"
[ -d "$GOV_DIR" ] || block "governance directory missing" "restore $GOV_DIR"
[ -f "$GOV_DIR/allowed-remotes.txt" ] || block "remote allowlist missing" "restore/configure $GOV_DIR/allowed-remotes.txt"
python3 "$SCRIPT_DIR/remotes.py" --check-url "$REMOTE_URL" --allowlist "$GOV_DIR/allowed-remotes.txt" || block "remote '$REMOTE_NAME' is not approved" "use an approved destination or independently approve a policy change"
G="$GOV_DIR/governed-paths.txt"
report(){ echo "pre-push report: $*" >&2; }
if [ ! -f "$G" ]; then report "WARNING: $G absent; governed-path intelligence unavailable"; exit 0; fi
while IFS= read -r glob || [ -n "$glob" ]; do
  glob="${glob%$'\r'}"; case "$glob" in ''|\#*) continue;; esac
  while read -r local_ref local_sha remote_ref remote_sha; do
    [ -n "${local_sha:-}" ] || continue
    case "$local_sha" in 0000000000000000000000000000000000000000) continue;; esac
    if [ "$remote_sha" = "0000000000000000000000000000000000000000" ]; then
      if ! HITS="$(git -C "$ROOT" ls-tree -r --name-only "$local_sha" -- "$glob" 2>&1)"; then report "WARNING: governed-path scan failed for initial push: $HITS"; continue; fi
    else
      if ! HITS="$(git -C "$ROOT" diff --name-only "$remote_sha..$local_sha" -- "$glob" 2>&1)"; then report "WARNING: governed-path diff failed: $HITS"; continue; fi
    fi
    [ -n "$HITS" ] && report "governed path '$glob': $(printf '%s' "$HITS" | tr '\n' ' ')"
  done <<<"$REFS"
done < "$G"
