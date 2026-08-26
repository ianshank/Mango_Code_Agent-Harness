import shutil
import pathlib

files = [
    "remotes.py",
    "pretooluse_guard.py",
    "pretooluse_guard.sh",
    "pre_push_scan.sh",
    "install_hooks.sh",
    "verify_zero_skips.py",
    "check_projections.py",
    "check_traceability.py",
    "validate_agent_policy.py",
    "validate_policy.py",
    "validate_governance_docs.py",
    "validate_adoption.py",
    "validate_specs.sh",
]

shared = pathlib.Path('harness/shared')
stacks = ['node', 'jvm', 'python']

for stack in stacks:
    for f in files:
        src = shared / f
        dest = pathlib.Path('harness') / stack / 'scripts' / f
        if src.exists() and dest.exists():
            shutil.copy2(src, dest)
            print(f"Copied {f} to {stack}/scripts")
