import json
import hashlib
from pathlib import Path

bundle_path = Path("harness/control-plane/policy-bundle.example.json")
bundle = json.loads(bundle_path.read_text("utf-8"))

def get_hash(path_str):
    return hashlib.sha256(Path(path_str).read_bytes()).hexdigest()

for stack in ["node", "jvm"]:
    protected_files = bundle["profiles"][stack]["protected_files"]
    for file_path in protected_files:
        if file_path.startswith("scripts/"):
            # They should match the ones in harness/shared
            shared_file = Path("harness/shared") / Path(file_path).name
            if shared_file.exists():
                protected_files[file_path] = get_hash(shared_file)
            else:
                raise FileNotFoundError(f"Cannot resolve hash for {file_path}: {shared_file} not found")

# If agent_policy_sha256 is unresolved or empty in the bundle, we should abort
if not bundle.get("agent_policy_sha256"):
    raise ValueError("agent_policy_sha256 is unresolved in the bundle.")

bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", "utf-8")
print("Updated policy-bundle.example.json")
