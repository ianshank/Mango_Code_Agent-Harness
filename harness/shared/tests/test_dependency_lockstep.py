"""`requirements.txt` and `pyproject.toml` must declare the same runtime dependencies.

`requirements.txt`'s own header comment says this explicitly: it is split out
so `pip install -e .` (which reads `pyproject.toml`'s `[project.dependencies]`)
"declares its own real dependencies instead of relying on a dev file", and
`pyproject.toml` in turn says it "mirrors requirements.txt... keep both in
lockstep". Nothing mechanical checked that until this file: a PR that adds a
package to one and not the other passes every other gate silently -- exactly
what happened when `mcp` was added to `requirements.txt` alone, missed across
four rounds of human review, and caught only by chance because Python 3.9 CI
happened to also be red for an unrelated reason on the same run.

Only package identity is compared (normalized per PEP 503: case-insensitive,
`.`/`_`/`-` treated as equivalent), not version constraints or environment
markers -- the two files are free to spell a constraint differently (an exact
pin in one, a range in the other) as long as neither forgets a package the
other declares.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on the 3.9/3.10 matrix legs
    import tomli as tomllib

import pytest

from harness.shared.tests._helpers import REPO

pytestmark = pytest.mark.governance

REQUIREMENTS_TXT = REPO / "requirements.txt"
PYPROJECT = REPO / "pyproject.toml"

# A PEP 508 requirement string starts with a package name: letters/digits,
# then letters/digits/./_/- , stopping at the first extras bracket, version
# comparator, or environment-marker semicolon.
_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalize(name: str) -> str:
    """PEP 503 normalization: case-insensitive, `.`/`_`/`-` are equivalent."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _names_from_requirements_txt(path: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _NAME_RE.match(line)
        if match is None:  # pragma: no cover - defensive; every real spec matches
            continue
        names.add(_normalize(match.group(1)))
    return names


def _names_from_pyproject_dependencies(path: Path) -> set[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    specs = data.get("project", {}).get("dependencies", [])
    names: set[str] = set()
    for spec in specs:
        match = _NAME_RE.match(spec.strip())
        if match is None:  # pragma: no cover - defensive; every real spec matches
            continue
        names.add(_normalize(match.group(1)))
    return names


class TestRequirementsTxtAndPyprojectStayInLockstep:
    def test_same_package_set(self) -> None:
        from_requirements = _names_from_requirements_txt(REQUIREMENTS_TXT)
        from_pyproject = _names_from_pyproject_dependencies(PYPROJECT)

        only_in_requirements = from_requirements - from_pyproject
        only_in_pyproject = from_pyproject - from_requirements

        assert not only_in_requirements, (
            f"requirements.txt declares {sorted(only_in_requirements)} that "
            "pyproject.toml's [project.dependencies] is missing -- pip install -e . "
            "would silently not install it. Mirror it into pyproject.toml."
        )
        assert not only_in_pyproject, (
            f"pyproject.toml's [project.dependencies] declares {sorted(only_in_pyproject)} "
            "that requirements.txt is missing -- a plain `pip install -r requirements.txt` "
            "would silently not install it. Mirror it into requirements.txt."
        )

    def test_neither_file_is_accidentally_empty(self) -> None:
        # A parsing regression that silently matched zero requirements would make
        # the equality check above vacuously pass -- this is the floor.
        assert len(_names_from_requirements_txt(REQUIREMENTS_TXT)) >= 4
        assert len(_names_from_pyproject_dependencies(PYPROJECT)) >= 4
