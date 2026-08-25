#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SPEC_DIR="${SPEC_DIR:-$ROOT/docs/specs}"
VALIDATOR="${SPEC_VALIDATOR:-openspec}"
REQUIRE_STRICT="${REQUIRE_STRICT_SPEC_VALIDATOR:-0}"
[ -d "$SPEC_DIR" ] || { echo "specs: $SPEC_DIR does not exist" >&2; exit 1; }
if command -v "$VALIDATOR" >/dev/null 2>&1; then
  "$VALIDATOR" validate "$SPEC_DIR"
elif [ "$REQUIRE_STRICT" = "1" ]; then
  echo "specs: strict validator '$VALIDATOR' is required in this environment; failing closed" >&2
  exit 1
else
  echo "specs: WARNING strict validator '$VALIDATOR' unavailable; structural tier remains mandatory" >&2
fi
python3 - "$SPEC_DIR" <<'PY2'
import pathlib,re,sys
root=pathlib.Path(sys.argv[1]); files=sorted(root.rglob('*.md')); fail=[]; req=re.compile(r'\b([CR]-[A-Za-z0-9_-]+)\b')
if not files: raise SystemExit('specs: no markdown specs found')
for p in files:
 t=p.read_text(); rel=p.relative_to(root)
 for s in ('## Requirements','## Acceptance criteria'):
  if s not in t: fail.append(f"{rel}: missing {s}")
 for ln in t.splitlines():
  if ln.lstrip().startswith(('- ','* ')) and 'MUST' in ln and not req.search(ln): fail.append(f'{rel}: normative MUST has no requirement ID: {ln[:80]}')
 for x in ('works correctly','as expected','appropriately'):
  if x in t.lower(): fail.append(f"{rel}: unfalsifiable acceptance language '{x}'")
if fail: raise SystemExit('specs: FAILED\n  - '+'\n  - '.join(fail))
print(f'specs: structural validation passed ({len(files)} documents)')
PY2
