#!/usr/bin/env python3
import glob, json, re
from pathlib import Path
REQ=re.compile(r'\b([CR]-[A-Za-z0-9_-]+)\b')
cfg=json.loads(Path('.governance/traceability.json').read_text())
def files(patterns):
    out=[]
    for p in patterns: out += [Path(x) for x in glob.glob(p,recursive=True) if Path(x).is_file()]
    return out
specs=files(cfg['spec_globs']); impl=files(cfg['implementation_globs']); tests=files(cfg['test_globs'])
if not specs: raise SystemExit('traceability: no spec files matched')
ids=set();
for p in specs: ids.update(REQ.findall(p.read_text(errors='replace')))
if not ids: raise SystemExit('traceability: specs contain no requirement IDs')
impl_text='\n'.join(p.read_text(errors='replace') for p in impl); test_text='\n'.join(p.read_text(errors='replace') for p in tests)
missing=[r for r in sorted(ids) if r not in impl_text or r not in test_text]
if missing: raise SystemExit('traceability: requirement IDs missing implementation and/or test citation: '+', '.join(missing))
print(f'traceability: passed ({len(ids)} requirements)')
