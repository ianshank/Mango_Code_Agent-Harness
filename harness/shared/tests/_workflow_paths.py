"""Paths and line-readers shared by the workflow and dependency-lock contracts.

Extracted when `test_workflow_contracts.py` reached 653/700 and the lock
concern needed its own module (DEC-035, DEC-041's precedent): both suites read
the same two workflow files and the same lock, and a second copy of these
constants is a second thing to update when a path moves.

Textual parsing, per job, matching how `test_ci_gate_coverage.py` reads the same
files: PyYAML is not a declared dependency of this repository and a gate must
not depend on a transitive one.
"""

from __future__ import annotations

import re

from harness.shared.tests._helpers import REPO

WORKFLOW_DIR = REPO / ".github" / "workflows"
WORKFLOW = WORKFLOW_DIR / "python-package.yml"
DRIFT_WORKFLOW = WORKFLOW_DIR / "scheduled-drift.yml"
DEPENDABOT = REPO / ".github" / "dependabot.yml"
RULESET = REPO / ".github" / "rulesets" / "main.json"
LOCK = REPO / "requirements-lock.txt"
LOCK_NAME = LOCK.name
#: The two range files the lock compiles from, transitively: `requirements-dev.txt`
#: opens with `-r requirements.txt`, and `requirements-langgraph.txt` is the
#: second compile input. DEC-047 turns on the lock subsuming both.
RANGE_FILES = (REPO / "requirements.txt", REPO / "requirements-langgraph.txt", REPO / "requirements-dev.txt")
# The oldest interpreter in the matrix; langgraph declares Requires-Python >=3.10.
UNSUPPORTED_LEG = "3.9"


def pip_install_lines(workflow_text: str) -> list[str]:
    """Every `python -m pip install …` line in a workflow, stripped."""
    return [line.strip() for line in workflow_text.splitlines() if re.match(r"^\s*python -m pip install ", line)]


def distribution_names(requirements_text: str) -> set[str]:
    """The distributions a requirements file names, normalised for comparison.

    `-r` includes are skipped rather than followed: each included file is read
    on its own, so following them would double-count and hide a file that the
    caller forgot to pass.
    """
    names = set()
    for raw in requirements_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"^([A-Za-z0-9._-]+)", line)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def lock_pins(lock_text: str) -> set[str]:
    """The distributions the lock pins with `==`, normalised the same way."""
    return {match.group(1).lower().replace("_", "-") for match in re.finditer(r"^([A-Za-z0-9._-]+)==", lock_text, re.M)}
