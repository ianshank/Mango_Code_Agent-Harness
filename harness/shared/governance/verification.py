"""The check the harness runs itself, to earn a verdict it did not ask a model for.

Spec: ``docs/specs/verdict-propagation.md`` (R-VP-2 … R-VP-7).

The agent selects the commands in its own turn, so the only way a verdict can be
about the change rather than about the model's choices is for the harness to pick
and run a command of its own. That command goes through the same
``ExecutionBroker`` as everything else, under the verifier's canonical identity,
so this adds a caller -- not an authority.

Three details are load-bearing rather than defensive:

* ``-f Makefile`` is not decoration. GNU Make searches ``GNUmakefile``, then
  ``makefile``, then ``Makefile``. ``Makefile`` is a protected path; the first two
  are not, so an agent holding ``write`` can add a ``GNUmakefile`` whose target is
  a no-op and the check exits 0. Naming the file removes the search.
* The probe runs ``make -n`` and a ``command -v`` census rather than testing that
  a Makefile exists. A workspace whose Makefile lacks the target exits 2 with no
  broker reason, which is indistinguishable from a failing suite; the probe is
  what makes that distinction possible.
* ``-n`` is also why the probe cannot invoke what it probes. A probe that runs the
  target to find out whether the target runs would recurse here, because the
  configured target runs the suite that contains this module.
"""
from __future__ import annotations

import logging
import os
import shlex
import time
import typing
from pathlib import Path

from harness.shared.governance.verdict import HarnessCheck

logger = logging.getLogger(__name__)

#: Set in the child environment so a check cannot run inside its own execution.
#: Deliberately not credential-shaped: ``debug_dump.credential_env_names`` strips
#: names ending in KEY/TOKEN/SECRET/PASSWORD/CREDENTIALS from spawned processes,
#: and a sentinel that got stripped would not survive to be seen.
REENTRANCY_ENV = "MANGO_VERIFICATION_ACTIVE"

#: This repository's own verification target. A default, not a policy value: a
#: policy key would oblige rebuilding the committed policy artifact, and this
#: module is itself a protected path, so the constant is reviewed either way.
#: Callers configure their own; an adopter that configures none is told so rather
#: than handed a failure (see ``verdict.not_configured``).
#:
#: `test-python` and not `test`: the latter depends on the Node stack, so a
#: container without it would report a toolchain condition as a failing change.
#: The cost is that a pass here does not imply lint, types, coverage or the
#: governance validators -- which is why the verdict carries the command.
DEFAULT_TARGET = "test-python"
DEFAULT_MAKEFILE = "Makefile"


class VerificationRunner:
    """Runs one policy-governed command and reports what happened.

    The broker, the command and the timeout are all injected. Nothing here reads
    the environment or the filesystem at import time.
    """

    def __init__(
        self,
        broker: typing.Any,
        agent_id: str,
        *,
        target: str | None = DEFAULT_TARGET,
        makefile: str = DEFAULT_MAKEFILE,
        timeout: int = 300,
    ) -> None:
        self._broker = broker
        self._agent_id = agent_id
        self._target = target
        self._makefile = makefile
        self._timeout = timeout

    @property
    def target(self) -> str | None:
        return self._target

    @property
    def command(self) -> str:
        """The command that earns a verdict, with the makefile named explicitly."""
        return f"make -f {shlex.quote(self._makefile)} {shlex.quote(str(self._target))}"

    def _probe_command(self) -> str:
        """A dry run. ``-n`` prints the recipe and executes none of it."""
        return f"make -f {shlex.quote(self._makefile)} -n {shlex.quote(str(self._target))}"

    def is_reentrant(self, environ: typing.Mapping[str, str] | None = None) -> bool:
        env = os.environ if environ is None else environ
        return bool(env.get(REENTRANCY_ENV))

    def probe(self, cwd: Path) -> tuple[bool, str]:
        """Establish that the target exists and the programs it names are present.

        Returns ``(ok, detail)``. Two failures are distinguished in the detail so
        an operator is told which one to fix, though both mean the same thing to
        the verdict: no signal is obtainable here.
        """
        dry = self._broker.execute_command(
            self._probe_command(), {"agent_id": self._agent_id}, cwd=cwd, timeout=self._timeout
        )
        if dry.status != "SUCCESS" or dry.exit_code != 0:
            return False, f"{self._target} is not a target of {self._makefile}"

        missing = self._missing_programs(dry.stdout, cwd)
        if missing:
            return False, "not on PATH: " + ", ".join(sorted(missing))
        return True, ""

    def _missing_programs(self, recipe: str, cwd: Path) -> set[str]:
        """Programs the recipe names that are not runnable.

        A recipe naming a program that is absent exits non-zero with no broker
        reason, which would otherwise grade as a failing change. Only the leading
        word of each line is censused: that is the program, and anything further
        in is an argument this has no business interpreting.
        """
        programs: set[str] = set()
        for line in recipe.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                tokens = shlex.split(stripped)
            except ValueError:
                # An unbalanced quote in a recipe line is not this module's
                # problem to diagnose; the line is skipped rather than guessed at.
                continue
            if tokens and "=" not in tokens[0] and "/" not in tokens[0]:
                programs.add(tokens[0])

        missing = set()
        for program in programs:
            probe = self._broker.execute_command(
                f"command -v {shlex.quote(program)}", {"agent_id": self._agent_id}, cwd=cwd, timeout=self._timeout
            )
            if probe.status != "SUCCESS" or probe.exit_code != 0:
                missing.add(program)
        return missing

    def run(self, cwd: Path, environ: typing.Mapping[str, str] | None = None) -> HarnessCheck:
        """Probe, then run, and report. The only constructor of ``HarnessCheck``."""
        target = str(self._target)
        started = time.monotonic()

        probe_ok, detail = self.probe(cwd)
        if not probe_ok:
            logger.warning("verification: %s is not runnable: %s", target, detail)
            return HarnessCheck(
                target=target,
                status="BLOCKED",
                exit_code=-1,
                reason=detail,
                probe_ok=False,
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        previous = os.environ.get(REENTRANCY_ENV)
        os.environ[REENTRANCY_ENV] = "1"
        try:
            result = self._broker.execute_command(
                self.command, {"agent_id": self._agent_id}, cwd=cwd, timeout=self._timeout
            )
        finally:
            if previous is None:
                os.environ.pop(REENTRANCY_ENV, None)
            else:
                os.environ[REENTRANCY_ENV] = previous

        elapsed = int((time.monotonic() - started) * 1000)
        logger.info(
            "verification: %s status=%s exit=%s in %dms", target, result.status, result.exit_code, elapsed
        )
        return HarnessCheck(
            target=target,
            status=result.status,
            exit_code=result.exit_code,
            reason=result.reason,
            probe_ok=True,
            latency_ms=elapsed,
        )
