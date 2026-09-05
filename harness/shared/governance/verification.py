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
* ``-f Makefile`` protects against a *second* makefile, not against the first
  being rewritten. ``Makefile`` is a protected path and ``write_file`` refuses
  it, but a script the agent wrote and ran through ``run_command`` -- graded
  ``test_execute``, which every role holds -- rewrote it, and the next check
  returned ``VERIFIED`` on a failing suite (2026 standards audit, B4). The
  runner therefore records the digest of every protected file in the workspace
  when the loop starts (``snapshot_enforcement``) and refuses to run the check
  if any of them changed, appeared or vanished since: ``BLOCKED`` with
  ``enforcement_tampered`` naming the files. Containment, not isolation -- the
  script still ran; what it cannot do is have its rewrite graded.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import time
import typing
from pathlib import Path

from harness.shared.governance.enforcement_digest import (
    EnforcementDigestError,
    enforcement_digests,
    tampered_files,
)
from harness.shared.governance.indirect_exec import CANONICAL_MAKEFILE
from harness.shared.governance.verdict import BLOCKED, BROKER_SUCCESS, HarnessCheck
from harness.shared.policy_loader import orchestrator_defaults

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
#: The same name the command classifier accepts for ``make -f``: any other file
#: grades as a program the agent chose, so the runner's own command must name
#: this one or it would be denied by the broker it runs through.
DEFAULT_MAKEFILE = CANONICAL_MAKEFILE


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
        timeout: int | None = None,
    ) -> None:
        self._broker = broker
        self._agent_id = agent_id
        self._target = target
        self._makefile = makefile
        # Resolved from policy, not a literal. The default was a bare `300`,
        # which is `orchestrator.api_timeout_sec` written down a second time --
        # the same unlinked-literal shape R-CQ-7 removed from `HookRunner`, and
        # the same failure mode: raising the policy value would have left this
        # caller on the old number silently. `MangoMASOrchestrator` already
        # passes the policy value explicitly, so the literal was only reachable
        # from direct construction (every test here), which is exactly where a
        # drift would go unnoticed.
        #
        # The key is `verification_timeout_sec`, not `api_timeout_sec`: the
        # latter bounds one model round-trip, and this bounds a test suite. A
        # `TimeoutExpired` here is graded BROKER_FAILED and the verdict becomes
        # BLOCKED/harness_fault, so a runner slower than the one the model
        # latency was tuned for reported a passing change as a harness fault
        # (2026 standards audit H16).
        self._timeout = orchestrator_defaults()["verification_timeout_sec"] if timeout is None else timeout
        #: `(workspace, digests)` recorded by `snapshot_enforcement`. `None`
        #: until a caller records one; `run` then records its own and warns,
        #: because a check with no baseline can only compare the tree to itself.
        self._baseline: tuple[Path, dict[str, str]] | None = None
        #: Why the loop-start snapshot failed, if it was attempted and failed.
        #: A run on such a runner is refused: recording the post-agent tree as
        #: the reference would trust exactly the state the snapshot exists to
        #: distrust (Copilot review on PR #86).
        self._baseline_failed: str | None = None

    @property
    def target(self) -> str | None:
        return self._target

    @property
    def baseline(self) -> dict[str, str] | None:
        """The digests recorded at loop start, or ``None`` if none were."""
        return None if self._baseline is None else dict(self._baseline[1])

    def snapshot_enforcement(self, cwd: Path) -> dict[str, str]:
        """Record the digest of every protected file under ``cwd``.

        Called by the loop before its first agent turn. Anything an agent
        changes in that set afterwards -- by any door -- makes ``run`` refuse
        to grade. Raises ``EnforcementDigestError`` rather than recording a
        partial baseline; the loop treats that as the same fault ``run`` would.
        """
        try:
            digests = enforcement_digests(cwd)
        except Exception as exc:
            # Remembered, not swallowed: `run` refuses until a snapshot succeeds.
            self._baseline = None
            self._baseline_failed = str(exc)
            raise
        self._baseline = (cwd.resolve(), digests)
        self._baseline_failed = None
        logger.info("verification: enforcement baseline recorded, %d protected file(s)", len(digests))
        return dict(digests)

    def _tampered_since_baseline(self, cwd: Path) -> list[str]:
        """Protected files that differ from the baseline, recording one if absent."""
        if self._baseline_failed is not None:
            raise EnforcementDigestError(
                "the enforcement baseline could not be recorded at loop start "
                f"({self._baseline_failed}); a verdict earned against an unknown tree is refused"
            )
        current = enforcement_digests(cwd)
        if self._baseline is None or self._baseline[0] != cwd.resolve():
            logger.warning(
                "verification: no enforcement baseline was recorded for %s before this run; "
                "recording one now, so a change made before this point is not detectable",
                cwd,
            )
            self._baseline = (cwd.resolve(), current)
            return []
        return tampered_files(self._baseline[1], current)

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
        # Pre-flight: `make` itself must be on PATH. On Windows dev machines
        # without GNU Make, the broker subprocess would fail with an OS-level
        # CommandNotFound that produces the misleading diagnostic "test-python
        # is not a target of Makefile". This gives a specific, actionable
        # message instead. CI runs Linux where `make` is always present, so
        # this branch is exercised only in local development.
        if shutil.which("make") is None:
            return False, "make is not installed; install GNU Make or add it to PATH"

        dry = self._broker.execute_command(
            self._probe_command(), {"agent_id": self._agent_id}, cwd=cwd, timeout=self._timeout
        )
        if dry.status != BROKER_SUCCESS or dry.exit_code != 0:
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
            if probe.status != BROKER_SUCCESS or probe.exit_code != 0:
                missing.add(program)
        return missing

    def run(self, cwd: Path) -> HarnessCheck:
        """Probe, then run, and report. The only constructor of ``HarnessCheck``."""
        target = str(self._target)
        started = time.monotonic()

        # Before the probe. The probe reads the makefile, and a probe result
        # obtained against a rewritten one describes the forgery, not the change.
        try:
            tampered = self._tampered_since_baseline(cwd)
        except EnforcementDigestError as exc:
            logger.warning("verification: enforcement set could not be established: %s", exc)
            return HarnessCheck(
                target=target,
                command=self.command,
                status=BLOCKED,
                exit_code=-1,
                reason=f"the enforcement set could not be established: {exc}",
                probe_ok=False,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        if tampered:
            logger.warning("verification: refusing to grade %s, enforcement files changed: %s", target, tampered)
            return HarnessCheck(
                target=target,
                command=self.command,
                status=BLOCKED,
                exit_code=-1,
                reason="protected files changed since the loop started: " + ", ".join(tampered),
                probe_ok=False,
                latency_ms=int((time.monotonic() - started) * 1000),
                tampered_files=tuple(tampered),
            )

        probe_ok, detail = self.probe(cwd)
        if not probe_ok:
            logger.warning("verification: %s is not runnable: %s", target, detail)
            return HarnessCheck(
                target=target,
                command=self.command,
                status=BLOCKED,
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

        # After the run as well as before it. A script an agent was allowed to
        # start can leave a process behind that rewrites the makefile between
        # the check above and `make` reading it; a change that persists is
        # caught here. A swap-and-restore inside that window is not -- that
        # needs an immutable snapshot or OS isolation of the backend, which is
        # Phase F of the remediation plan (Copilot review on PR #86).
        try:
            tampered_after = self._tampered_since_baseline(cwd)
        except EnforcementDigestError as exc:
            logger.warning("verification: enforcement set could not be re-read after the run: %s", exc)
            return HarnessCheck(
                target=target,
                command=self.command,
                status=BLOCKED,
                exit_code=-1,
                reason=f"the enforcement set could not be re-read after the run: {exc}",
                probe_ok=True,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        if tampered_after:
            logger.warning(
                "verification: refusing %s, enforcement files changed during the run: %s", target, tampered_after
            )
            return HarnessCheck(
                target=target,
                command=self.command,
                status=BLOCKED,
                exit_code=-1,
                reason="protected files changed while the verdict was being earned: " + ", ".join(tampered_after),
                probe_ok=True,
                latency_ms=int((time.monotonic() - started) * 1000),
                tampered_files=tuple(tampered_after),
            )

        elapsed = int((time.monotonic() - started) * 1000)
        logger.info("verification: %s status=%s exit=%s in %dms", target, result.status, result.exit_code, elapsed)
        return HarnessCheck(
            target=target,
            command=self.command,
            status=result.status,
            exit_code=result.exit_code,
            reason=result.reason,
            probe_ok=True,
            latency_ms=elapsed,
        )
