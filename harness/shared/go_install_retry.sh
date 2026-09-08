#!/usr/bin/env bash
# Retry `go install` on transient proxy.golang.org / sum.golang.org failures.
# GOPROXY HTTP/2 stream errors are not a finding; a required check that fails
# on them is not a check. Override GO_INSTALL_ATTEMPTS / GO_INSTALL_RETRY_SECONDS
# in the environment; do not restated those ceilings in the Makefiles.
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: go_install_retry.sh <module>@<version> ..." >&2
  exit 2
fi

max="${GO_INSTALL_ATTEMPTS:-4}"
delay="${GO_INSTALL_RETRY_SECONDS:-4}"
n=1
while true; do
  if go install "$@"; then
    exit 0
  fi
  if [ "$n" -ge "$max" ]; then
    echo "go install failed after ${n} attempt(s)" >&2
    exit 1
  fi
  echo "go install failed (attempt ${n}/${max}); retrying in ${delay}s" >&2
  sleep "$delay"
  n=$((n + 1))
  delay=$((delay * 2))
done
