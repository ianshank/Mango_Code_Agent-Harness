"""Regression: the traceability gate measured a corpus that was not its own.

Spec: docs/specs/graph-engineering-adoption.md (R-GEA-1, R-GEA-4, AC-GEA-1).
Decision: docs/decisions/DEC-065.md.

Two defects reached `main` here, and both are the same failure wearing two
faces: the number the gate printed was not a number about the corpus it claimed
to check.

**1. The gate read the corpus under the process CWD.**
`check_traceability.py` resolved `.governance/traceability.json` and every glob
against `Path.cwd()`, and `make validate` runs it from `harness/node`. It read 6
requirement IDs while `docs/specs/` held 412 sharing not one member with them,
and printed `traceability: passed (6 requirements)` with exit 0. Its two
emptiness guards -- `no spec files matched` and `specs contain no requirement
IDs` -- both passed, because the failure mode is not "found nothing", it is
"found the wrong two files", which no emptiness check can catch. The fix is a
floor on the discovered count that applies to any config declaring
`scope: repository`. What would regress: dropping `--workspace`, or dropping
`traceability.min_discovered_requirement_ids`, restores a gate that reports
success for a tree it was never aimed at.

**2. `SPEC_TEMPLATE.md` inflated every count the gate reported.**
The scaffold `make spec` copies declares placeholder requirement IDs, and the
gate counted them while `validate_specs.py` and `validate_plan.py` both skip the
file by name -- so the three gates read three different corpora and every number
this one reported, including the ones the policy is set against, was two too
high. What would regress: removing the name filter, which reads as a
simplification and silently moves the floor and the ratchet off the corpus they
were measured against.

Every threshold is read from `governance-policy.json` -> `traceability`; none is
restated here, which is what keeps this file from pinning the numbers the fix
exists to let move.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pytest

from harness.shared.governance.check_traceability import (
    REPOSITORY_SCOPE,
    REQ,
    SPEC_TEMPLATE_NAME,
    TRACEABILITY_CONFIG,
    _traceability_policy,
    analyse_traceability,
    check_traceability,
)
from harness.shared.tests._helpers import REPO
from harness.shared.validate_plan import TEMPLATE_NAME

pytestmark = pytest.mark.governance

logger = logging.getLogger(__name__)

SPEC_TEMPLATE = REPO / "docs" / "specs" / SPEC_TEMPLATE_NAME
VALIDATE_SPECS = REPO / "harness" / "shared" / "validate_specs.py"

#: How `validate_specs.py` spells its own skip. Matched as a comparison rather
#: than as a bare mention so a comment naming the scaffold does not satisfy it.
_TEMPLATE_COMPARISON = re.compile(rf'[!=]=\s*"{re.escape(SPEC_TEMPLATE_NAME)}"')


@pytest.fixture(scope="module")
def policy() -> dict[str, Any]:
    """The `traceability` section of `governance-policy.json`, read once."""
    section: dict[str, Any] = _traceability_policy()
    return section


@pytest.fixture(scope="module")
def template_ids() -> list[str]:
    """The requirement IDs the shipped scaffold declares.

    Read from the real `SPEC_TEMPLATE.md` rather than restated, so a scaffold
    that stops carrying placeholders fails the guard below instead of quietly
    making every assertion about the exclusion true of nothing.
    """
    found = sorted(set(REQ.findall(SPEC_TEMPLATE.read_text(encoding="utf-8"))))
    assert found, (
        f"{SPEC_TEMPLATE} declares no requirement IDs, so the exclusion under test has nothing "
        "to exclude and every assertion about it is vacuous"
    )
    return found


def _ids(count: int, prefix: str) -> str:
    """A document body declaring ``count`` distinct requirement IDs."""
    return "\n".join(f"- {prefix}-{index}: fixture requirement" for index in range(count))


def _stack(root: Path, *, specs: dict[str, str], cited: str, scope: str | None) -> Path:
    """Build one self-contained workspace and return its root.

    ``scope`` is omitted from the config entirely when ``None``, which is the
    shape every per-stack `.governance/traceability.json` in this repository
    has and therefore the shape the pre-fix gate always saw.
    """
    (root / "docs" / "specs").mkdir(parents=True, exist_ok=True)
    for name, body in specs.items():
        (root / "docs" / "specs" / name).write_text(body, encoding="utf-8")
    for directory, leaf in (("src", "impl.py"), ("tests", "test_impl.py")):
        (root / directory).mkdir(parents=True, exist_ok=True)
        (root / directory / leaf).write_text(cited, encoding="utf-8")

    config: dict[str, Any] = {
        "spec_globs": ["docs/specs/**/*.md"],
        "implementation_globs": ["src/**/*.py"],
        "test_globs": ["tests/**/*.py"],
    }
    if scope is not None:
        config["scope"] = scope
    config_path = root / TRACEABILITY_CONFIG
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return root


def _wrong_corpus(tmp_path: Path, floor: int, *, scope: str | None) -> tuple[Path, Path]:
    """A repository whose real corpus is at the root and whose CWD is a stack.

    The two spec trees share no requirement ID, which is the measured shape of
    the shipped defect: not an empty read, a read of somebody else's corpus.
    """
    repository = tmp_path / "repository"
    real = _ids(floor + 1, "R-REPO")
    _stack(repository, specs={"contract.md": real}, cited=real, scope=REPOSITORY_SCOPE)

    stack = repository / "stack"
    small = _ids(2, "R-STACK")
    _stack(stack, specs={"stack.md": small}, cited=small, scope=scope)
    return repository, stack


class TestTheGateReadTheCorpusUnderTheProcessCwd:
    """Same tree, two configs, two verdicts: the fix is the floor, not the globs.

    The pre-fix code path is still present verbatim -- `--workspace` defaults to
    the CWD and a config declaring no `scope` is exempt from the floor, both
    deliberately, so the per-stack shims keep working during the DEC-056 shim
    window. That is what lets this reproduce the shipped behaviour live rather
    than by mutating source: the legacy reading of the wrong tree still reports
    a pass, and only the repository-scoped reading refuses it.
    """

    def test_the_pre_fix_reading_of_the_wrong_tree_still_reports_a_pass(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        policy: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The defect as it shipped: two files, a green verdict, exit 0.

        Both emptiness guards are asserted to pass here, because that is the
        whole point -- an emptiness check cannot see a corpus that is populated
        and wrong, and the two guards the gate already carried are exactly the
        checks a reader would assume had covered this.
        """
        floor = int(policy["min_discovered_requirement_ids"])
        repository, stack = _wrong_corpus(tmp_path, floor, scope=None)

        stack_result = analyse_traceability(stack, policy)
        repository_result = analyse_traceability(repository, policy)
        logger.debug(
            "stack discovered %d ID(s); repository discovered %d ID(s)",
            len(stack_result.discovered),
            len(repository_result.discovered),
        )

        assert stack_result.discovered, "the wrong-corpus premise needs a *populated* wrong tree"
        assert repository_result.discovered, "the real corpus is empty; the disjointness below proves nothing"
        assert not (stack_result.discovered & repository_result.discovered), (
            "the two corpora share a requirement ID, so this fixture no longer models the defect: "
            "the gate read 6 IDs while docs/specs held 412 sharing not one member with them"
        )

        # No `--workspace`, so the config and every glob resolve against the CWD
        # -- byte for byte the pre-fix behaviour, on a tree that is not the one
        # the run claims to cover.
        monkeypatch.chdir(stack)
        check_traceability()
        printed = capsys.readouterr().out
        assert f"traceability: passed ({len(stack_result.discovered)} requirements)" in printed, printed
        assert len(stack_result.discovered) < floor, (
            "the wrong corpus is already above the policy floor, so the fix below could not have "
            "changed this verdict and the reproduction is vacuous"
        )

    def test_the_repository_floor_refuses_the_same_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy: dict[str, Any]
    ) -> None:
        """The fix: a config claiming repository scope must clear the floor.

        Run from the same wrong directory, with no `--workspace` either -- the
        floor has to catch a run that is pointed at the wrong tree *by the CWD*,
        because that is how `make validate` invoked it.
        """
        floor = int(policy["min_discovered_requirement_ids"])
        _repository, stack = _wrong_corpus(tmp_path, floor, scope=REPOSITORY_SCOPE)

        monkeypatch.chdir(stack)
        with pytest.raises(SystemExit) as excinfo:
            check_traceability()
        message = str(excinfo.value)
        assert f"below the floor of {floor}" in message, message
        assert "min_discovered_requirement_ids" in message, "the failure must name the policy key that decided it"
        assert str(stack.resolve()) in message, "the failure must name the workspace it actually read"

    def test_the_floor_passes_the_corpus_it_was_measured_against(
        self, tmp_path: Path, policy: dict[str, Any], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The positive control. A floor that refused everything would satisfy
        the test above while making the gate useless, and a gate that fails on
        correct input is a gate that gets switched off."""
        floor = int(policy["min_discovered_requirement_ids"])
        repository, _stack = _wrong_corpus(tmp_path, floor, scope=REPOSITORY_SCOPE)

        check_traceability(repository)
        assert f"traceability: passed ({floor + 1} requirements;" in capsys.readouterr().out


class TestTheScaffoldInflatedEveryReportedCount:
    """`SPEC_TEMPLATE.md`'s placeholders were requirement IDs to this gate alone.

    `validate_specs.py` and `validate_plan.py` skip the scaffold by name. This
    gate counted it, so the three read three corpora and this one's numbers --
    the floor and the ratchet included -- were two too high. A glob cannot
    express the exclusion, so it lives in the traversal beside the two siblings'
    copies of the same rule.
    """

    def test_a_workspace_holding_only_the_scaffold_fails_closed(self, tmp_path: Path, template_ids: list[str]) -> None:
        """Counted the placeholders before; now refuses to report anything.

        The implementation and test files cite every placeholder, so the pre-fix
        gate found them all cited and printed `traceability: passed (2
        requirements)` -- measured, on a green verdict whose entire corpus was a
        scaffold nobody wrote. With the scaffold excluded the spec set is empty
        and the run raises instead.
        """
        root = _stack(
            tmp_path,
            specs={SPEC_TEMPLATE_NAME: SPEC_TEMPLATE.read_text(encoding="utf-8")},
            cited="\n".join(template_ids),
            scope=None,
        )
        with pytest.raises(SystemExit) as excinfo:
            check_traceability(root)
        assert "no spec files matched" in str(excinfo.value), (
            "a workspace whose only spec is the scaffold must fail closed rather than reporting "
            f"the scaffold's {len(template_ids)} placeholder ID(s) as a satisfied corpus"
        )

    def test_the_scaffold_does_not_inflate_a_real_corpus(
        self, tmp_path: Path, policy: dict[str, Any], template_ids: list[str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Adding the scaffold beside real specs must change no number at all."""
        body = _ids(3, "R-SAMPLE")
        root = _stack(
            tmp_path,
            specs={"contract.md": body, SPEC_TEMPLATE_NAME: SPEC_TEMPLATE.read_text(encoding="utf-8")},
            cited=body,
            scope=None,
        )
        result = analyse_traceability(root, policy)
        assert result.discovered == set(REQ.findall(body)), (
            f"the scaffold's IDs leaked into the corpus: {sorted(result.discovered)}"
        )
        assert not (result.discovered & set(template_ids))
        check_traceability(root)
        assert f"traceability: passed ({len(result.discovered)} requirements)" in capsys.readouterr().out

    def test_the_live_corpus_carries_none_of_the_scaffold_ids(
        self, policy: dict[str, Any], template_ids: list[str]
    ) -> None:
        """The fix on the real tree, not on a fixture.

        The floor and the ratchet in `governance-policy.json` were measured
        against a corpus with the scaffold excluded; a run that counted it would
        be grading a different set against those numbers.
        """
        discovered = analyse_traceability(REPO, policy).discovered
        assert discovered, "the repository-scoped run discovered nothing; this assertion would be vacuous"
        leaked = sorted(set(template_ids) & discovered)
        assert not leaked, (
            f"the repository-scoped run counted the scaffold's placeholder ID(s) {leaked}. Every count it "
            "reports -- and the policy floor and ratchet set against those counts -- is inflated by them."
        )

    def test_all_three_gates_skip_the_same_scaffold(self) -> None:
        """One corpus, three readers. Nothing else holds the three names equal."""
        assert SPEC_TEMPLATE_NAME == TEMPLATE_NAME, (
            "check_traceability.py and validate_plan.py name different scaffolds, so the two gates "
            "grade different corpora again"
        )
        source = VALIDATE_SPECS.read_text(encoding="utf-8")
        assert _TEMPLATE_COMPARISON.search(source), (
            f"{VALIDATE_SPECS.name} no longer compares a spec name against {SPEC_TEMPLATE_NAME!r}; "
            "the structural gate and the traceability gate have drifted onto different corpora"
        )
