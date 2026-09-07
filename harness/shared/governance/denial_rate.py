"""Measure how often the command allowlist denies work a role legitimately does.

``command_actions.classify`` is an allowlist whose unmodelled default is an
action no role holds. That is the right failure direction, and it has a cost
nothing measured: every command the table does not model denies, whether or not
anyone intended it to. The cost was real. Before DEC-066, 13 of the 36 commands
in ``command-corpus.json`` resolved to an action no role holds -- including
``python -m ruff check .`` and ``python -m mypy harness``, the two forms
``CLAUDE.md`` mandates under DEC-013. The allowlist was denying the contributor
guide.

This gate turns that from an anecdote into a ratchet. It reports the share of the
corpus resolving to an unheld action and fails above a policy-declared ceiling,
so a change that narrows the classifier has to show what it costs.

Two vacuity guards, because a rate over an empty population is zero:

* the corpus must hold at least ``min_corpus_commands`` entries, so the rate
  cannot be driven down by deleting the denied ones; and
* the corpus file is a protected path, so lowering that population is a reviewed
  change rather than an agent edit.

Thresholds are read from ``governance-policy.json`` and fail closed when absent,
matching ``coverage_gate.load_thresholds``: a repository that wires this gate has
declared the governance, and running it against a silently invented ceiling would
be the inversion the gate exists to prevent.

Spec: ``docs/specs/attested-execution-isolation.md`` (R-AEI-2, AC-3).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import typing
from collections.abc import Sequence
from pathlib import Path

from harness.shared.governance.command_actions import classify

logger = logging.getLogger(__name__)

__all__ = ["Report", "held_actions", "load_corpus", "load_thresholds", "main", "measure"]

#: Resolved next to this package so the gate travels with the installed harness
#: rather than being read out of the agent's workspace, matching ``broker.py``.
_HERE: typing.Final[Path] = Path(__file__).resolve().parent
DEFAULT_CORPUS_PATH: typing.Final[Path] = _HERE / "command-corpus.json"
DEFAULT_POLICY_PATH: typing.Final[Path] = _HERE.parent / "governance-policy.json"
DEFAULT_AGENT_POLICY_PATH: typing.Final[Path] = _HERE.parent / "agent-policy.json"

#: The policy block this gate reads. A block of its own rather than a key inside
#: an existing one: DEC-043 makes an absent key in an adopted block a hard error
#: for every adopter policy that predates it, so a new block is the only additive
#: place to put one.
POLICY_BLOCK: typing.Final[str] = "denial_rate"


class Thresholds(typing.NamedTuple):
    """What the gate enforces, both read from policy."""

    max_denial_rate: float
    min_corpus_commands: int


class Denial(typing.NamedTuple):
    """One corpus entry the classifier grades to an action no role holds."""

    command: str
    action: str
    reason: str


class Report(typing.NamedTuple):
    """The measurement, separable from the decision made about it."""

    total: int
    denials: tuple[Denial, ...]

    @property
    def rate(self) -> float:
        """Share of the corpus denied. Zero for an empty corpus, which is why the
        population floor exists rather than this returning something clever."""
        return len(self.denials) / self.total if self.total else 0.0


def _load_json_object(path: Path, what: str) -> dict[str, typing.Any]:
    """Read ``path`` as a JSON object, failing closed on anything else."""
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error("[FAIL] %s not found at %s", what, path)
        raise SystemExit(1) from None
    except (OSError, ValueError) as exc:
        logger.error("[FAIL] %s at %s is unreadable or malformed: %s", what, path, exc)
        raise SystemExit(1) from None
    if not isinstance(loaded, dict):
        logger.error("[FAIL] %s at %s is not a JSON object", what, path)
        raise SystemExit(1)
    return loaded


def load_thresholds(policy_path: Path) -> Thresholds:
    """Return the enforced thresholds. An absent block or key fails closed."""
    block = _load_json_object(policy_path, "governance policy").get(POLICY_BLOCK)
    if not isinstance(block, dict):
        logger.error("[FAIL] governance policy %s has no %s block", policy_path, POLICY_BLOCK)
        raise SystemExit(1)
    rate = block.get("max_denial_rate")
    floor = block.get("min_corpus_commands")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        logger.error("[FAIL] %s.max_denial_rate is missing or non-numeric", POLICY_BLOCK)
        raise SystemExit(1)
    if not isinstance(floor, int) or isinstance(floor, bool):
        logger.error("[FAIL] %s.min_corpus_commands is missing or not an integer", POLICY_BLOCK)
        raise SystemExit(1)
    return Thresholds(float(rate), floor)


def load_corpus(corpus_path: Path) -> tuple[str, ...]:
    """Return the commands to measure. An entry without a command is a defect in
    the corpus, not an entry to skip: skipping one would shrink the population
    the floor is meant to hold."""
    entries = _load_json_object(corpus_path, "command corpus").get("commands")
    if not isinstance(entries, list):
        logger.error("[FAIL] command corpus %s has no commands list", corpus_path)
        raise SystemExit(1)
    commands: list[str] = []
    for index, entry in enumerate(entries):
        command = entry.get("command") if isinstance(entry, dict) else None
        if not isinstance(command, str) or not command.strip():
            logger.error("[FAIL] command corpus entry %d has no command string", index)
            raise SystemExit(1)
        commands.append(command)
    return tuple(commands)


def held_actions(agent_policy_path: Path) -> frozenset[str]:
    """Every action some role holds, read from the authority model rather than
    restated. A role that gains or loses an action moves this set with it."""
    agents = _load_json_object(agent_policy_path, "authority model").get("agents")
    if not isinstance(agents, list) or not agents:
        logger.error("[FAIL] authority model %s declares no agents", agent_policy_path)
        raise SystemExit(1)
    return frozenset(
        action
        for agent in agents
        if isinstance(agent, dict)
        for action in agent.get("allowed_actions", [])
        if isinstance(action, str)
    )


def measure(commands: Sequence[str], held: frozenset[str]) -> Report:
    """Classify each command and collect the ones no role could run."""
    denials: list[Denial] = []
    for command in commands:
        verdict = classify(command)
        if verdict.action not in held:
            logger.debug("denial_rate: %r -> %s (%s)", command, verdict.action, verdict.reason)
            denials.append(Denial(command, verdict.action, verdict.reason))
    return Report(len(commands), tuple(denials))


def _decide(report: Report, thresholds: Thresholds) -> int:
    """Exit code for ``report``, and the log lines explaining it."""
    failed = False
    if report.total < thresholds.min_corpus_commands:
        logger.error(
            "[FAIL] command corpus holds %d command(s), below the floor of %d "
            "(governance-policy.json -> %s.min_corpus_commands). A rate over a "
            "shrunken corpus measures nothing.",
            report.total,
            thresholds.min_corpus_commands,
            POLICY_BLOCK,
        )
        failed = True
    if report.rate > thresholds.max_denial_rate:
        logger.error(
            "[FAIL] %d of %d corpus command(s) resolve to an action no role holds "
            "(%.1f%%), above the ceiling of %.1f%% (governance-policy.json -> "
            "%s.max_denial_rate). The ceiling may be lowered as denials are "
            "closed, never raised.",
            len(report.denials),
            report.total,
            report.rate * 100,
            thresholds.max_denial_rate * 100,
            POLICY_BLOCK,
        )
        for denial in report.denials:
            logger.error("  %s -> %s: %s", denial.command, denial.action, denial.reason)
        failed = True
    if failed:
        return 1
    logger.info(
        "[PASS] denial rate %.1f%% over %d command(s), at or below the ceiling of %.1f%%",
        report.rate * 100,
        report.total,
        thresholds.max_denial_rate * 100,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the exit code rather than raising, so a caller
    can drive the gate in-process the way the tests do."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--agent-policy", type=Path, default=DEFAULT_AGENT_POLICY_PATH)
    parser.add_argument("--json", action="store_true", help="print the measurement as JSON")
    args = parser.parse_args(argv)

    thresholds = load_thresholds(args.policy)
    report = measure(load_corpus(args.corpus), held_actions(args.agent_policy))
    if args.json:
        print(
            json.dumps(
                {
                    "total": report.total,
                    "denied": len(report.denials),
                    "rate": round(report.rate, 6),
                    "max_denial_rate": thresholds.max_denial_rate,
                    "min_corpus_commands": thresholds.min_corpus_commands,
                    "denials": [d._asdict() for d in report.denials],
                },
                indent=2,
                sort_keys=True,
            )
        )
    return _decide(report, thresholds)


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
