import re

content = open('harness/shared/tests/test_harness.py').read()

# For test_guard_fail_closed_and_allows_safe
# Replace env = {**os.environ, "CLAUDE_PROJECT_DIR": str(r)}
content = content.replace(
    'env = {**os.environ, "CLAUDE_PROJECT_DIR": str(r)}',
    'env = {**os.environ, "CLAUDE_PROJECT_DIR": str(r), "PYTHONPATH": str(HARNESS.parent) + os.pathsep + os.environ.get("PYTHONPATH", "")}'
)

# For test_zero_skip_exact_decision_backed_waivers
# Replace self.assertEqual(subprocess.run([*base, "--vitest-json", str(r / "vitest.json")]).returncode, 0)
# and the other two runs
content = content.replace(
    'subprocess.run([*base, "--vitest-json", str(r / "vitest.json")])',
    'subprocess.run([*base, "--vitest-json", str(r / "vitest.json")], env={**os.environ, "PYTHONPATH": str(HARNESS.parent) + os.pathsep + os.environ.get("PYTHONPATH", "")})'
)
content = content.replace(
    'subprocess.run([*base, "--junit-events", str(r / "junit.tsv")])',
    'subprocess.run([*base, "--junit-events", str(r / "junit.tsv")], env={**os.environ, "PYTHONPATH": str(HARNESS.parent) + os.pathsep + os.environ.get("PYTHONPATH", "")})'
)

# Fix test_shared_kernel_byte_identical since they are now shims:
# Wait, the node/scripts and jvm/scripts probably have the old code, they need to be replaced with the shims!
# It's better to just copy the shims into those directories. We can do that via terminal.

open('harness/shared/tests/test_harness.py', 'w').write(content)
print("Updated test_harness.py")
