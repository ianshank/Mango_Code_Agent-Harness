"""Protected-path portability: how two policies combine, and what pins the second.

Spec: ``openspec/changes/fix-protected-path-portability`` (R-PPP-1..5, C-PPP-1,
C-PPP-2).

The defect these tests close is not that the write gate is wrong here. Against
this repository it is correct and well-guarded. It is that
``write_denial_reason`` resolved its pattern set next to its own module and
matched it against whatever workspace it was handed, so against any other layout
every pattern missed and the gate permitted everything -- silently, which
``harness/CONTRACT.md`` names directly.

The obvious repair is worse than the defect: reading the policy out of the tree
being governed lets a tree an agent can write to widen the policy that governs
writes to it, which is the INV-6 inversion. So the repair has a direction. A
supplied policy is *unioned* with the harness policy, never substituted for it,
and it is denied outright unless a digest record held outside the tree it
governs pins it.

``ALWAYS_DENIED_SEGMENTS`` and the read-side denials are decided before any
policy is read and are outside the merge entirely; the tests below check that by
probing, not by reading the source.
"""

from __future__ import annotations

import ast
import inspect
import json
import logging
from pathlib import Path

import pytest

from harness.shared.read_policy import read_denial_reason
from harness.shared.tests._helpers import CONTROL_PLANE, SHARED
from harness.shared.tests.test_write_policy import CONTROL_SURFACE, ORDINARY_WORK
from harness.shared.validate_invariants import load_protected_patterns
from harness.shared.write_policy import (
    ALWAYS_DENIED_SEGMENTS,
    DEFAULT_PIN_RECORD_PATH,
    DEFAULT_POLICY_PATH,
    POLICY_PIN_RECORD_ENV,
    WRITE_POLICY_PATH_ENV,
    active_policy_path,
    merge_protected_patterns,
    pin_key,
    pin_record_path,
    policy_digest,
    write_denial_reason,
)

pytestmark = pytest.mark.governance

#: The two modules whose bare calls made ``policy_path`` unreachable outside
#: tests. Named so the static check below cannot pass by finding no call sites
#: at all.
KNOWN_CALL_SITES = (SHARED / "tool_executors.py", SHARED / "governance" / "broker.py")

#: A path no pattern in the harness policy matches, used as the thing a supplied
#: policy adds. If a harness pattern ever grows to cover it, the "adds a denial"
#: test would pass for the wrong reason -- so it is asserted, not assumed.
ADDED_TARGET = "config/deploy.yaml"


@pytest.fixture
def harness_patterns() -> list[str]:
    return load_protected_patterns(DEFAULT_POLICY_PATH)


@pytest.fixture
def supplied(tmp_path: Path):
    """Build a supplied policy in one tree and its digest record in another.

    The two directories are siblings on purpose: a record inside the tree it
    governs is the arrangement R-PPP-3 rejects, and a fixture that produced one
    by default would make every test below agree with a design the spec refuses.
    """

    made: list[Path] = []

    def _make(policy: dict, *, digest: str | None = None, record: bool = True) -> tuple[Path, Path]:
        # A fresh pair of trees per call: two supplied policies in one test must
        # not share a record, or "no record" would silently read the previous
        # test case's pin and the missing-record branch would never be taken.
        root = tmp_path / f"case-{len(made)}"
        made.append(root)
        target = root / "target-repo"
        target.mkdir(parents=True)
        policy_path = target / "governance-policy.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")

        anchor = root / "anchor"
        anchor.mkdir()
        pin_path = anchor / "supplied-policy-pins.json"
        if record:
            pinned = digest if digest is not None else policy_digest(policy_path.read_bytes())
            pin_path.write_text(
                json.dumps({"pinned_policies": {pin_key(policy_path): pinned}}), encoding="utf-8"
            )
        return policy_path, pin_path

    return _make


def _bare_calls(path: Path) -> list[int]:
    """Line numbers of ``write_denial_reason`` calls that supply no policy path.

    AST rather than a text search: ``grep`` cannot tell a call from a mention in
    a docstring, and three of the four mentions in this repository are prose.
    """
    bare: list[int] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "write_denial_reason":
            continue
        supplies = len(node.args) >= 2 or any(kw.arg == "policy_path" for kw in node.keywords)
        if not supplies:
            bare.append(node.lineno)
    return bare


def _imported_modules(path: Path) -> set[str]:
    """Every module name ``path`` imports, so "depends on the hook layer" is
    measured on the import graph rather than on whether the word appears in a
    comment."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _production_modules() -> list[Path]:
    found: list[Path] = []
    for root in (SHARED, CONTROL_PLANE):
        for path in sorted(root.rglob("*.py")):
            if "tests" in path.parts or path.name.startswith("test_"):
                continue
            found.append(path)
    return found


class TestMergeDirection:
    """Harness denials are a floor; a supplied policy may only add to it."""

    def test_supplied_policy_cannot_remove_a_harness_denial(
        self, supplied, harness_patterns, caplog
    ) -> None:
        """AC-PPP-1. Three shapes of removal, none of which takes effect, all reported."""
        attacker = {
            "protected_paths": ["!CLAUDE.md", ADDED_TARGET],
            "protected_paths_removed": ["harness/shared/governance-policy.json"],
            "protected_paths_disabled": [".mango/hooks/**"],
        }
        policy_path, pin_path = supplied(attacker)

        with caplog.at_level(logging.WARNING, logger="harness.shared.write_policy"):
            for target in (
                "CLAUDE.md",
                "harness/shared/governance-policy.json",
                ".mango/hooks/pre-nemotron-run.sh",
            ):
                assert (
                    write_denial_reason(target, policy_path=policy_path, pin_path=pin_path)
                    is not None
                ), f"{target} lost its harness denial to a supplied policy"

        reported = caplog.text
        for named in ("CLAUDE.md", "harness/shared/governance-policy.json", ".mango/hooks/**"):
            assert named in reported, f"the attempt on {named} was honoured or dropped, not reported"

        merged, findings = merge_protected_patterns(harness_patterns, attacker)
        assert set(harness_patterns).issubset(set(merged)), "the union lost a harness pattern"
        assert len(findings) >= 3, f"removal attempts must be reported, got {findings}"

    def test_the_union_direction_is_what_holds_the_denial(self, harness_patterns) -> None:
        """Inverting the direction -- supplied as the floor -- drops the denial.

        Without this the test above could pass because ``CLAUDE.md`` happens to
        be absent from the attacker's set rather than because the merge refuses
        to remove it.
        """
        attacker = {"protected_paths": [ADDED_TARGET]}
        merged, _ = merge_protected_patterns(harness_patterns, attacker)
        inverted = list(attacker["protected_paths"])
        assert "CLAUDE.md" in merged
        assert "CLAUDE.md" not in inverted

    def test_supplied_policy_adds_a_denial(self, supplied, harness_patterns) -> None:
        """AC-PPP-2."""
        assert write_denial_reason(ADDED_TARGET) is None, (
            f"{ADDED_TARGET} is already denied by the harness policy; this test would "
            "pass without the supplied policy doing anything"
        )
        policy_path, pin_path = supplied({"protected_paths": [ADDED_TARGET]})
        assert (
            write_denial_reason(ADDED_TARGET, policy_path=policy_path, pin_path=pin_path) is not None
        )
        assert (
            write_denial_reason("config/other.yaml", policy_path=policy_path, pin_path=pin_path)
            is None
        ), "the added pattern widened past what it names"

    def test_a_narrower_twin_of_a_harness_pattern_is_reported(self, harness_patterns) -> None:
        """Narrowing is inoperative because of the union; it is reported anyway,
        because a supplied policy restating a harness pattern more tightly is a
        statement of intent worth surfacing."""
        merged, findings = merge_protected_patterns(
            harness_patterns, {"protected_paths": ["harness/shared/governance/broker.py"]}
        )
        assert "harness/shared/governance/**" in merged
        assert any("reaches inside" in f for f in findings), findings

    def test_a_non_string_pattern_entry_is_reported_and_dropped(self, harness_patterns) -> None:
        merged, findings = merge_protected_patterns(harness_patterns, {"protected_paths": [17]})
        assert merged == harness_patterns
        assert any("not a string" in f for f in findings), findings


class TestUnconditionalDenialsAreOutsideTheMerge:
    def test_always_denied_segments_ignore_supplied_policy(self, supplied) -> None:
        """AC-PPP-3. Decided before any policy is read, so no policy can reach them."""
        assert ".git" in ALWAYS_DENIED_SEGMENTS
        policy_path, pin_path = supplied(
            {"protected_paths": ["!.git/**"], "protected_paths_removed": [".git/**"]}
        )
        for target in (".git/config", "sub/.git/hooks/pre-commit"):
            reason = write_denial_reason(target, policy_path=policy_path, pin_path=pin_path)
            assert reason is not None and "git directory" in reason

        # Even an entirely untrusted policy cannot reach them: the segment check
        # runs before the pin is consulted, so the denial does not depend on the
        # policy being readable, pinned, or present.
        unpinned, absent = supplied({"protected_paths": []}, record=False)
        reason = write_denial_reason(".git/config", policy_path=unpinned, pin_path=absent)
        assert reason is not None and "git directory" in reason

    def test_the_read_side_takes_no_policy_and_is_unaffected(self) -> None:
        """R-PPP-2. The read denials are static patterns; there is nothing to merge."""
        assert list(inspect.signature(read_denial_reason).parameters) == ["relpath"]
        assert read_denial_reason(".env") is not None
        assert read_denial_reason(".git/config") is not None
        assert read_denial_reason("src/feature.py") is None


class TestDigestPinning:
    def test_digest_mismatch_and_missing_record_both_deny(self, supplied, tmp_path) -> None:
        """AC-PPP-4."""
        policy_path, pin_path = supplied({"protected_paths": [ADDED_TARGET]}, digest="0" * 64)
        reason = write_denial_reason("docs/notes.md", policy_path=policy_path, pin_path=pin_path)
        assert reason is not None and "digest mismatch" in reason, reason

        unpinned, absent = supplied({"protected_paths": [ADDED_TARGET]}, record=False)
        reason = write_denial_reason("docs/notes.md", policy_path=unpinned, pin_path=absent)
        assert reason is not None and "no digest record" in reason, reason
        assert "docs/notes.md" not in (reason or ""), (
            "a missing record must deny the write, not fall back to the harness set"
        )

    def test_a_policy_mutated_after_pinning_is_denied(self, supplied) -> None:
        """The pin is over bytes, so widening the file after it was recorded is caught."""
        policy_path, pin_path = supplied({"protected_paths": [ADDED_TARGET]})
        assert write_denial_reason("docs/notes.md", policy_path=policy_path, pin_path=pin_path) is None

        policy_path.write_text(json.dumps({"protected_paths": []}), encoding="utf-8")
        reason = write_denial_reason("docs/notes.md", policy_path=policy_path, pin_path=pin_path)
        assert reason is not None and "digest mismatch" in reason

    def test_a_record_inside_the_governed_tree_is_refused(self, tmp_path) -> None:
        """INV-6: a tree may not be its own root of trust."""
        target = tmp_path / "target-repo"
        target.mkdir()
        policy_path = target / "governance-policy.json"
        policy_path.write_text(json.dumps({"protected_paths": []}), encoding="utf-8")
        inside = target / "pins.json"
        inside.write_text(
            json.dumps({"pinned_policies": {pin_key(policy_path): policy_digest(policy_path.read_bytes())}}),
            encoding="utf-8",
        )
        reason = write_denial_reason("docs/notes.md", policy_path=policy_path, pin_path=inside)
        assert reason is not None and "own root of trust" in reason

    def test_an_unreadable_or_shapeless_record_denies(self, supplied, tmp_path) -> None:
        policy_path, pin_path = supplied({"protected_paths": []})
        pin_path.write_text("{ not json", encoding="utf-8")
        reason = write_denial_reason("docs/notes.md", policy_path=policy_path, pin_path=pin_path)
        assert reason is not None and "could not be read" in reason

        pin_path.write_text(json.dumps({"pinned_policies": ["not a mapping"]}), encoding="utf-8")
        reason = write_denial_reason("docs/notes.md", policy_path=policy_path, pin_path=pin_path)
        assert reason is not None and "pins no digest" in reason

    def test_the_default_record_is_held_next_to_the_harness(self) -> None:
        """Not in the governed tree, and not somewhere the governed tree can name."""
        assert DEFAULT_PIN_RECORD_PATH.parent == DEFAULT_POLICY_PATH.parent


class TestPolicyPathResolution:
    def test_active_policy_path_defaults_to_the_harness_policy(self, monkeypatch) -> None:
        monkeypatch.delenv(WRITE_POLICY_PATH_ENV, raising=False)
        assert active_policy_path() == DEFAULT_POLICY_PATH

    def test_active_policy_path_honours_the_override(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv(WRITE_POLICY_PATH_ENV, str(tmp_path / "supplied.json"))
        assert active_policy_path() == tmp_path / "supplied.json"

    def test_pin_record_path_prefers_the_argument_then_the_env_then_the_default(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setenv(POLICY_PIN_RECORD_ENV, str(tmp_path / "from-env.json"))
        assert pin_record_path(tmp_path / "explicit.json") == tmp_path / "explicit.json"
        assert pin_record_path() == tmp_path / "from-env.json"
        monkeypatch.delenv(POLICY_PIN_RECORD_ENV, raising=False)
        assert pin_record_path() == DEFAULT_PIN_RECORD_PATH


class TestEveryCallSiteSuppliesThePolicy:
    def test_no_bare_write_denial_reason_call_remains(self) -> None:
        """AC-PPP-5. Static, so the defect cannot reappear by omission."""
        called_in = [p for p in _production_modules() if "write_denial_reason(" in p.read_text(encoding="utf-8")]
        for known in KNOWN_CALL_SITES:
            assert known in called_in, f"{known} no longer calls the write gate; this check is vacuous"

        bare = {str(p): _bare_calls(p) for p in called_in if _bare_calls(p)}
        assert not bare, (
            "write_denial_reason is called without a policy path, so the parameter is "
            f"unreachable outside tests and the gate matches this repository's patterns "
            f"against whatever tree it is given: {bare}"
        )

    def test_the_static_check_detects_a_reintroduced_bare_call(self, tmp_path) -> None:
        """Otherwise an empty finding list would prove only that the scan found nothing."""
        probe = tmp_path / "probe.py"
        probe.write_text("write_denial_reason('x')\nwrite_denial_reason('y', policy_path=p)\n", encoding="utf-8")
        assert _bare_calls(probe) == [1]


class TestNoDenialIsRelaxed:
    def test_existing_denial_corpus_is_unchanged(self, supplied, harness_patterns) -> None:
        """AC-PPP-7. The corpus is imported from the pre-change suite, not restated."""
        policy_path, pin_path = supplied({"protected_paths": [ADDED_TARGET]})
        for relpath in CONTROL_SURFACE:
            assert write_denial_reason(relpath) is not None, relpath
            assert write_denial_reason(relpath, policy_path=DEFAULT_POLICY_PATH) is not None, relpath
            assert (
                write_denial_reason(relpath, policy_path=policy_path, pin_path=pin_path) is not None
            ), f"{relpath} lost its denial once a policy was supplied"
        for relpath in ORDINARY_WORK:
            assert write_denial_reason(relpath, policy_path=DEFAULT_POLICY_PATH) is None, relpath
            assert (
                write_denial_reason(relpath, policy_path=policy_path, pin_path=pin_path) is None
            ), f"{relpath} became denied; the merge widened past what the supplied policy names"

        merged, _ = merge_protected_patterns(harness_patterns, {"protected_paths": []})
        assert merged == harness_patterns, "an empty supplied policy changed the pattern set"


class TestNoHookDependency:
    def test_controls_do_not_depend_on_the_hook_layer(self, monkeypatch, supplied) -> None:
        """AC-PPP-8. DEC-003 declares the hooks dormant and deliberately unmirrored
        into the file Claude Code reads, so a control that resolved through one
        would not run at all. Two halves: the gate names no hook, and every
        criterion above still holds with the hook layer's environment removed."""
        imported = _imported_modules(SHARED / "write_policy.py")
        assert not [m for m in imported if "hook" in m], (
            f"the write gate imports a hook module: {sorted(imported)}"
        )
        assert "subprocess" not in imported and "os.system" not in imported, (
            "the write gate can spawn a process, so a control here could route through "
            f"a hook script rather than the in-process broker path: {sorted(imported)}"
        )

        for var in ("CLAUDE_PROJECT_DIR", WRITE_POLICY_PATH_ENV, POLICY_PIN_RECORD_ENV):
            monkeypatch.delenv(var, raising=False)

        policy_path, pin_path = supplied(
            {"protected_paths": [ADDED_TARGET], "protected_paths_removed": ["CLAUDE.md"]}
        )
        assert write_denial_reason("CLAUDE.md", policy_path=policy_path, pin_path=pin_path) is not None
        assert write_denial_reason(ADDED_TARGET, policy_path=policy_path, pin_path=pin_path) is not None
        assert write_denial_reason(".git/config", policy_path=policy_path, pin_path=pin_path) is not None

        unpinned, absent = supplied({"protected_paths": []}, record=False)
        assert write_denial_reason("docs/notes.md", policy_path=unpinned, pin_path=absent) is not None
        assert not _bare_calls(SHARED / "governance" / "broker.py")
