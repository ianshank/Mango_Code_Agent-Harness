"""The agent and skill surface as a function: same inputs, same answer, no gaps.

`test_agent_surface_liveness.py` asserts that the surface is *present and true*
-- skills carry a `Reviewed:` date, hook commands go through `bash`, every
canonical role has a contract and every contract has a role. This file asserts
the properties that survive all of that being true:

* **Determinism.** The tool set a role receives is a pure function of
  `agent-policy.json` and the mappings in `agent_authority.py`. Nothing pinned
  that it is *only* a function of those: the derivation walks a `frozenset` of
  actions, and a filter that iterated the grants instead of the tool list would
  return a set-ordered surface that differs run to run under a different
  `PYTHONHASHSEED`. A non-deterministic authority surface is a bug you cannot
  reproduce, so it is proved across two interpreter hash seeds rather than
  argued.
* **Closure of the persona graph in both directions.** `agent-policy.json`
  <-> `harness/shared/agents/` is already closed both ways
  (`TestAgentContractsMatchThePolicy`), and `EXECUTION_IDENTITY` <->
  `ACTIVE_TO_CANONICAL` share a key set by `test_agent_authority.py`. Persona
  files against `ACTIVE_TO_CANONICAL` is stated directly here; today it is also
  *implied*, by two separate literal role sets in two test files, and saying it
  once against the mapping itself is what removes the indirection. The gap with
  teeth is the next one: whether an active role's execution identity is one of the
  contracts that role actually maps to. `test_execution_identity_is_no_wider_
  than_the_role` compares *action sets*, and today no canonical role's effective
  actions are a subset of a different active role's union, so that comparison
  happens to reject every out-of-tuple identity. It happens to: that is a fact
  about the current `agent-policy.json`, not a property of it. Granting
  `implementer` one more action the reasoner already holds elsewhere is enough
  to make `nemotron-reasoner` -> `test-eval` pass on actions while executing as
  a contract the role does not map to -- and the role would keep being *offered*
  the tools its union grants and denied them by the broker on every call, which
  is a silent authority gap rather than a loud one.
* **Hook commands resolve to files that exist, in both settings files.**
  `test_declared_hooks_exist_on_disk` scans `.mango/settings.json` only, by a
  regex anchored on `.mango/hooks/`. A hook added to `.claude/settings.json` --
  the file Claude Code actually reads -- naming a script that does not exist is
  seen by nothing.
* **The skill review horizon has one source.** `skill_max_age_days` is declared
  once in policy and then restated as a literal fallback in two consumers and in
  one skill's own frontmatter, with nothing holding the four equal. That is the
  shape `test_constant_triage.py` calls state (a) applied where it was missing.

Two things are deliberately absent, because adding them would contradict
decisions already recorded:

* **No blocking age assertion.** `test_agent_surface_liveness.py` records that
  age is a notification and not a gate, since a clock-dependent assertion turns
  unrelated PRs red at a date boundary. What is asserted here is that the
  horizon a consumer applies is the policy's, which needs no clock.
* **No executable-bit assertion on hook scripts.** Every tracked `.sh` here is
  mode 644 by convention and every command is routed through `bash`; both halves
  are already pinned in the liveness file, and asserting the bit would demand
  the opposite of the convention.

Every check that discovers its own input set fails closed when that set comes
back empty, in the style of `test_constant_triage.py::test_discovery_is_not_
vacuous`: a scan that finds no skills, no personas or no hooks is a broken scan,
not a satisfied property (DEC-065, R-GEA-4).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from harness.shared.agent_authority import (
    ACTIVE_TO_CANONICAL,
    EXECUTION_IDENTITY,
    allowed_actions,
    load_agent_policy,
    tools_for_role,
)
from harness.shared.tests._helpers import REPO
from harness.shared.tool_schemas import NEMOTRON_TOOLS

pytestmark = pytest.mark.governance

logger = logging.getLogger(__name__)

ACTIVE_AGENTS = REPO / ".mango" / "agents"
SKILLS_DIR = REPO / ".mango" / "skills"
GOVERNANCE_POLICY = REPO / "harness" / "shared" / "governance-policy.json"
SETTINGS_FILES = (REPO / ".mango" / "settings.json", REPO / ".claude" / "settings.json")

#: Consumers that read the review horizon and declare a literal fallback for it.
#: Both are outside this file's reach; what is asserted is that their fallbacks
#: still agree with the policy, not that they exist.
HORIZON_KEY = "skill_max_age_days"
#: The scheduled workflow is the *only* thing that applies the horizon to the
#: `.mango/skills/` corpus, since `validate_governance_docs.py` applies it to
#: `governance_skill_path` alone. Named separately because the two are checked
#: for different things.
STALENESS_WORKFLOW = REPO / ".github" / "workflows" / "scheduled-drift.yml"
HORIZON_CONSUMERS = (REPO / "harness" / "shared" / "validate_governance_docs.py", STALENESS_WORKFLOW)
_HORIZON_FALLBACK = re.compile(rf'\.get\(\s*"{HORIZON_KEY}"\s*,\s*(\d+)\s*\)')
_HORIZON_IN_FRONTMATTER = re.compile(rf"^{HORIZON_KEY}:\s*(\d+)\s*$", re.M)

#: `$CLAUDE_PROJECT_DIR` and `${CLAUDE_PROJECT_DIR}` both appear; Claude Code
#: expands them to the repository root, so this test resolves them the same way.
_PROJECT_DIR = re.compile(r"\$\{?CLAUDE_PROJECT_DIR\}?")
_SCRIPT_TOKEN = re.compile(r"[^\s\"']+\.sh")

#: Two seeds, because `PYTHONHASHSEED` is what makes `set` iteration order vary
#: between interpreters. Strings, since that is what the environment takes.
HASH_SEEDS = ("0", "1")

#: Printed by the probe below as sorted JSON, so a difference between two runs is
#: a difference in the surface rather than in how it was serialised.
_SURFACE_PROBE = """
import json
import sys

from harness.shared.agent_authority import ACTIVE_TO_CANONICAL, allowed_actions, tools_for_role
from harness.shared.tool_schemas import NEMOTRON_TOOLS

json.dump(
    {
        role: {
            "actions": sorted(allowed_actions(role)),
            "tools": [tool["function"]["name"] for tool in tools_for_role(role, NEMOTRON_TOOLS)],
        }
        for role in sorted(ACTIVE_TO_CANONICAL)
    },
    sys.stdout,
    sort_keys=True,
)
"""


def _tool_names(role: str, tools: list[dict[str, Any]] | None = None) -> list[str]:
    """The tool names ``role`` is granted, in the order the filter returned them."""
    catalogue: list[dict[str, Any]] = NEMOTRON_TOOLS if tools is None else tools
    return [tool["function"]["name"] for tool in tools_for_role(role, catalogue)]


def _probe_surface(seed: str) -> dict[str, Any]:
    """Derive the whole role surface in a fresh interpreter under ``seed``."""
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = seed
    result = subprocess.run(
        [sys.executable, "-c", _SURFACE_PROBE],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env=environment,
        timeout=300,
    )
    assert result.returncode == 0, f"the surface probe failed under PYTHONHASHSEED={seed}:\n{result.stderr}"
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def _persona_names() -> set[str]:
    """Active-role personas on disk, which is what the orchestrator loads."""
    return {path.stem for path in ACTIVE_AGENTS.glob("*.md")} - {"README"}


def _skill_documents() -> list[Path]:
    return sorted(path / "SKILL.md" for path in SKILLS_DIR.iterdir() if (path / "SKILL.md").is_file())


def _frontmatter(document: Path) -> str:
    """The leading `---` block, or the empty string when there is none."""
    text = document.read_text(encoding="utf-8")
    return text.split("---", 2)[1] if text.startswith("---") else ""


def _hook_commands(settings: Path) -> list[str]:
    data = json.loads(settings.read_text(encoding="utf-8"))
    return [
        hook["command"] for event in data.get("hooks", {}).values() for matcher in event for hook in matcher["hooks"]
    ]


def _hook_script(command: str) -> Path | None:
    """The script a hook command runs, with the project-dir variable expanded."""
    match = _SCRIPT_TOKEN.search(command)
    if match is None:
        return None
    return Path(_PROJECT_DIR.sub(str(REPO), match.group(0)))


@pytest.fixture(scope="module")
def horizon() -> int:
    """`skill_max_age_days`, the one place the review window is declared."""
    policy = json.loads(GOVERNANCE_POLICY.read_text(encoding="utf-8"))
    assert HORIZON_KEY in policy, f"governance-policy.json no longer declares {HORIZON_KEY}"
    return int(policy[HORIZON_KEY])


class TestTheRoleSurfaceIsDeterministic:
    """Same policy, same mappings, same answer -- on any interpreter, every time."""

    def test_the_surface_is_identical_across_interpreter_hash_seeds(self) -> None:
        """The derivation walks a `frozenset`; set order is seed-dependent.

        Two fresh interpreters rather than two in-process calls, because
        `PYTHONHASHSEED` is fixed at startup: an in-process repeat cannot see
        this class of defect at all.
        """
        surfaces = {seed: _probe_surface(seed) for seed in HASH_SEEDS}
        first, *rest = HASH_SEEDS
        for seed in rest:
            assert surfaces[seed] == surfaces[first], (
                f"the derived role surface differs between PYTHONHASHSEED={first} and PYTHONHASHSEED={seed}. "
                "Something in the derivation iterates a set, so which tools a role is offered depends on the "
                "interpreter's hash randomisation rather than on the policy."
            )
        logger.debug("role surface stable across seeds %s: %s", list(HASH_SEEDS), surfaces[first])

    def test_the_probe_measured_a_real_surface(self) -> None:
        """The positive control: two empty answers would agree perfectly."""
        surface = _probe_surface(HASH_SEEDS[0])
        assert set(surface) == set(ACTIVE_TO_CANONICAL), (
            f"the probe reported roles {sorted(surface)}, not the active roles {sorted(ACTIVE_TO_CANONICAL)}"
        )
        for role, derived in surface.items():
            assert derived["actions"], f"{role} was derived with no actions; the comparison above proves nothing"
            assert derived["tools"], f"{role} was derived with no tools; the comparison above proves nothing"

    def test_repeated_derivations_agree_in_one_process(self) -> None:
        """Purity: no cache, no accumulated state, no dependence on call order."""
        for role in sorted(ACTIVE_TO_CANONICAL):
            first, second = _tool_names(role), _tool_names(role)
            assert first == second, f"{role} received {first} then {second} from the same inputs"
            assert allowed_actions(role) == allowed_actions(role)

    def test_the_order_of_the_result_is_the_callers_not_a_sets(self) -> None:
        """A reversed catalogue must produce a reversed result, not a reshuffled one.

        This is what says the filter walks the tools it was handed. A filter
        that walked the granted actions instead would return a set-ordered list
        that no caller could predict -- and the model is shown that order.
        """
        catalogue: list[dict[str, Any]] = NEMOTRON_TOOLS
        for role in sorted(ACTIVE_TO_CANONICAL):
            forward = _tool_names(role, list(catalogue))
            backward = _tool_names(role, list(reversed(catalogue)))
            assert backward == list(reversed(forward)), (
                f"{role}: reversing the tool catalogue gave {backward}, not {list(reversed(forward))}. "
                "The result order is not the caller's, so it is somebody's set order."
            )

    def test_the_derived_grant_cannot_be_mutated_by_its_caller(self) -> None:
        """`frozenset`, so a caller cannot widen a grant it was only shown."""
        for role in sorted(ACTIVE_TO_CANONICAL):
            granted = allowed_actions(role)
            assert isinstance(granted, frozenset), f"{role} yields a mutable {type(granted).__name__}"

    def test_a_different_policy_yields_a_different_surface(self, tmp_path: Path) -> None:
        """The other positive control: the derivation really does read the policy.

        Without it, a `tools_for_role` that ignored its policy argument and
        returned a constant would satisfy every determinism assertion above --
        perfectly reproducible, and wrong.
        """
        narrowed = tmp_path / "agent-policy.json"
        narrowed.write_text(
            json.dumps({"agents": [{"id": "implementer", "allowed_actions": ["read"]}]}), encoding="utf-8"
        )
        shipped = _tool_names("nemotron-reasoner")
        restricted = [
            tool["function"]["name"] for tool in tools_for_role("nemotron-reasoner", NEMOTRON_TOOLS, narrowed)
        ]
        assert restricted != shipped, "narrowing the policy changed nothing; the surface is not derived from it"
        assert set(restricted) < set(shipped), f"the narrowed policy widened the surface: {restricted}"


class TestThePersonaAndIdentityGraphIsClosed:
    """Every active role has a persona, every persona is an active role, and the
    identity each role executes as is one of the contracts it maps to."""

    def test_every_active_role_has_a_persona_file(self) -> None:
        missing = sorted(set(ACTIVE_TO_CANONICAL) - _persona_names())
        assert not missing, (
            f"agent_authority.ACTIVE_TO_CANONICAL declares roles with no persona in .mango/agents/: {missing}. "
            "The orchestrator loads the persona by name, so a role in the mapping with no file on disk holds "
            "a derived tool grant it can never be asked to use."
        )

    def test_every_persona_file_is_a_declared_active_role(self) -> None:
        extra = sorted(_persona_names() - set(ACTIVE_TO_CANONICAL))
        assert not extra, (
            f"personas exist for roles agent_authority.ACTIVE_TO_CANONICAL does not declare: {extra}. "
            "An undeclared role receives the empty grant, so the persona reads as authoritative and confers nothing."
        )

    def test_every_execution_identity_is_one_of_the_roles_own_contracts(self) -> None:
        """The structural rule the action-subset check only stands in for.

        `test_execution_identity_is_no_wider_than_the_role` compares action
        sets. Against today's `agent-policy.json` that rejects every out-of-tuple
        identity too -- but only because no canonical role's effective actions
        happen to be a subset of a different active role's union. Add
        `evidence_write` to `implementer` and `nemotron-reasoner` -> `test-eval`
        clears the action check while executing as a contract the reasoner does
        not map to; verified by mutation, with the action check staying green.
        The reasoner would keep being offered `write_file` from `implementer`'s
        grant and denied it by the broker on every call, which fails at run time
        and in no gate. This rule does not move when the action sets do.
        """
        stray = {
            active: identity
            for active, identity in EXECUTION_IDENTITY.items()
            if identity not in ACTIVE_TO_CANONICAL.get(active, ())
        }
        assert not stray, (
            f"these active roles execute as a canonical role they do not map to: {stray}. "
            "Tool exposure is the union over ACTIVE_TO_CANONICAL and the broker's verdict is about "
            "EXECUTION_IDENTITY, so an identity outside the tuple offers tools that are then denied on every call."
        )

    def test_every_execution_identity_is_declared_in_the_policy(self) -> None:
        declared = {role["id"] for role in load_agent_policy()["agents"]}
        assert declared, "agent-policy.json declares no agents; the check below would be vacuous"
        undeclared = sorted(set(EXECUTION_IDENTITY.values()) - declared)
        assert not undeclared, f"execution identities absent from agent-policy.json: {undeclared}"

    def test_the_persona_scan_is_not_vacuous(self) -> None:
        """Two empty sets are equal in both directions."""
        personas = _persona_names()
        assert personas, ".mango/agents/ contributed no personas; the closure checks above prove nothing"
        assert ACTIVE_TO_CANONICAL, "ACTIVE_TO_CANONICAL is empty; the closure checks above prove nothing"
        assert EXECUTION_IDENTITY, "EXECUTION_IDENTITY is empty; the membership check above proves nothing"


class TestDeclaredHooksResolveToRealScripts:
    """Both settings files, not just the one a `.mango/hooks/` regex reaches.

    `test_declared_hooks_exist_on_disk` matches `\\.mango/hooks/([\\w.\\-]+)`, so a
    hook registered in `.claude/settings.json` -- the file Claude Code actually
    reads -- is outside its scan entirely. `.claude/hooks/session-start.sh` is
    reached today only because one test happens to read it; a second entry there
    naming a missing script would be caught by nothing.
    """

    def test_every_declared_hook_names_a_script_that_exists(self) -> None:
        missing = []
        for settings in SETTINGS_FILES:
            for command in _hook_commands(settings):
                script = _hook_script(command)
                if script is None or not script.is_file():
                    missing.append(f"{settings.relative_to(REPO)}: {command}")
        assert not missing, (
            f"hook commands naming scripts that do not exist: {missing}. A hook that is wrong while dormant "
            "is a hook that fails the day someone wakes it."
        )

    def test_the_hook_scan_is_not_vacuous(self) -> None:
        """A settings file that parses to no commands would satisfy the check above."""
        for settings in SETTINGS_FILES:
            commands = _hook_commands(settings)
            assert commands, f"{settings.relative_to(REPO)} contributed no hook commands to the scan"
            unreadable = [command for command in commands if _hook_script(command) is None]
            assert not unreadable, (
                f"{settings.relative_to(REPO)}: the extractor found no script path in {unreadable}. "
                "A command shape this cannot read is a broken scan, not a hook that needs no file."
            )


class TestTheSkillReviewHorizonComesFromThePolicy:
    """`skill_max_age_days` is declared once and restated three times.

    Two consumers carry it as a literal `.get(..., N)` fallback and one skill
    declares it in its own frontmatter, where nothing reads it. None of the four
    copies is held equal to the policy by anything, so the horizon can be raised
    in one place and left alone in the others -- and a reader of the skill would
    take its number as the one in force.
    """

    def test_every_consumer_fallback_equals_the_policy(self, horizon: int) -> None:
        drifted = {}
        found = 0
        for consumer in HORIZON_CONSUMERS:
            for declared in _HORIZON_FALLBACK.findall(consumer.read_text(encoding="utf-8")):
                found += 1
                if int(declared) != horizon:
                    drifted[consumer.relative_to(REPO).as_posix()] = int(declared)
        assert found, (
            f"no consumer of {HORIZON_KEY} declares a literal fallback any more. If the fallbacks were removed "
            "this check has nothing left to hold equal and should be deleted with them; if the scan stopped "
            "matching, it is passing on nothing."
        )
        assert not drifted, (
            f"these fallbacks disagree with governance-policy.json -> {HORIZON_KEY} ({horizon}): {drifted}. "
            "A fallback that outlives its policy value silently enforces a different horizon wherever the "
            "policy read fails."
        )

    def test_the_staleness_surface_reads_the_policy_and_scans_the_skills(self) -> None:
        """The age check has to be a policy read over the real skill corpus.

        Age is a notification here rather than a gate, by the decision recorded
        in `test_agent_surface_liveness.py`. That makes *this* the only thing
        standing between the policy key and no enforcement at all: a workflow
        that stopped reading the policy, or stopped scanning `.mango/skills`,
        would leave `skill_max_age_days` inert with nothing red.
        """
        text = STALENESS_WORKFLOW.read_text(encoding="utf-8")
        for needle in ("harness/shared/governance-policy.json", HORIZON_KEY, ".mango/skills"):
            assert needle in text, (
                f"{STALENESS_WORKFLOW.relative_to(REPO)} no longer names {needle!r}, so the skill review horizon is "
                "declared in policy and applied by nothing."
            )

    def test_no_skill_declares_a_horizon_that_disagrees_with_the_policy(self, horizon: int) -> None:
        """Nothing honours a per-skill override, so a divergent one is a false claim."""
        drifted = {}
        for document in _skill_documents():
            match = _HORIZON_IN_FRONTMATTER.search(_frontmatter(document))
            if match is not None and int(match.group(1)) != horizon:
                drifted[document.parent.name] = int(match.group(1))
        assert not drifted, (
            f"these skills declare {HORIZON_KEY} values the policy does not ({horizon}): {drifted}. "
            "No consumer reads a per-skill horizon, so the number reads as authoritative and is not; "
            "remove it, or move the exception into governance-policy.json where something applies it."
        )

    def test_the_skill_scan_is_not_vacuous(self) -> None:
        """Guards this file's own frontmatter reader, which the check above relies on."""
        documents = _skill_documents()
        assert documents, f"{SKILLS_DIR.relative_to(REPO)} contributed no SKILL.md files to the scan"
        unparsed = [
            document.parent.name
            for document in documents
            if f"name: {document.parent.name}" not in _frontmatter(document)
        ]
        assert not unparsed, (
            f"the frontmatter reader recovered no `name:` line for {unparsed}; it has stopped parsing these "
            "documents, so a divergent horizon in them would go unseen."
        )
