"""What a run's verdict is, and the only value it may be derived from.

Spec: ``docs/specs/verdict-propagation.md`` (R-VP-1, R-VP-8, R-VP-9, R-VP-10,
C-VP-2).

The orchestration loop used to end by returning the verifier agent's prose, which
no code read. Deriving a verdict from the *agent's* command results instead would
not fix that: the model chooses which commands to run, so a verifier that runs
``true`` produces a SUCCESS/exit-0 result and a passing verdict. That is model
authorship at one remove, and worse than prose, because the result would carry
mechanical authority.

So the verdict is derived from a check the **harness** selected and ran, and
``derive_verdict`` accepts only a :class:`HarnessCheck`. That type is constructed
in ``harness.shared.governance.verification`` and nowhere else, which makes
"whose command was this?" a property of the type rather than of the call site --
a refactor that starts reading the agent's results cannot typecheck, where a
positional convention would have silently survived it.

This module imports no first-party module (C-VP-2). ``derive_verdict`` needs four
scalars off a check, so it declares the shape it needs rather than importing the
broker to get it; that keeps the vocabulary at the bottom of the import graph and
stops ``api_server.main`` pulling the whole governance package in to name a field.
"""
from __future__ import annotations

import logging
import typing

logger = logging.getLogger(__name__)

#: The check ran and exited zero.
VERIFIED = "VERIFIED"
#: The check ran and did not exit zero.
FAILED = "FAILED"
#: No verdict was obtained. Never conflated with FAILED: "we could not check"
#: and "it failed" are different facts, and reporting the first as the second is
#: the dishonesty this change exists to remove.
BLOCKED = "BLOCKED"

#: Why a run ended where it did. Empty string on a pass.
NOT_CONFIGURED = "verification_not_configured"
REENTRANT = "verification_reentrant"
UNAVAILABLE = "verification_unavailable"
HARNESS_FAULT = "harness_fault"
DENIED = "verification_denied"
FAILED_CHECK = "verification_failed"
UNRECOGNISED = "unrecognised_status"

#: Broker (``ExecutionResult``) statuses this module models. Anything else is
#: not a pass -- an allowlist, so a backend inventing a status cannot invent a
#: success. Public so the broker, the process backend and every consumer name
#: the same strings instead of restating them (tech-debt-hardening-plan
#: R-TDH-14; ``test_verdict_literals.py`` fails on a raw literal elsewhere).
BROKER_SUCCESS = "SUCCESS"
BROKER_FAILED = "FAILED"
BROKER_BLOCKED = "BLOCKED"
_SUCCESS = BROKER_SUCCESS
_FAILED = BROKER_FAILED
_BLOCKED = BROKER_BLOCKED


class HarnessCheck(typing.NamedTuple):
    """The outcome of the verification command the harness itself ran.

    Constructed by ``verification.run`` and by nothing else. ``probe_ok`` records
    whether the target was established to be runnable *before* it ran: without
    it, a missing build target or absent interpreter exits non-zero with no
    broker reason and is indistinguishable from a failing test suite, so a
    toolchain condition would be reported as a failure of the change and, in a
    later milestone, would drive a repair loop against code that never ran.

    ``target`` is the bare Make target (``test-python``); ``command`` is what was
    actually invoked (``make -f Makefile test-python``). They are carried
    separately because R-VP-3's ``-f Makefile`` pin is the whole point of the
    fix it verifies -- a verdict naming the target and silently dropping how it
    was run would lose the provenance the invocation exists to guarantee.
    """

    target: str
    command: str
    status: str
    exit_code: int
    reason: str
    probe_ok: bool
    latency_ms: int


class Verdict(typing.NamedTuple):
    """A verdict, why it was reached, and what was run to reach it.

    ``command`` and ``exit_code`` are carried rather than derived on demand
    because the verdict word alone overstates what was checked: the configured
    target is one gate, not the repository's full matrix. A reader is given what
    ran so they can judge what it is worth.
    """

    status: str
    reason: str
    termination_reason: str
    command: str
    exit_code: int

    @property
    def is_pass(self) -> bool:
        """True only for VERIFIED. Never ``not failed`` -- BLOCKED is not a pass."""
        return self.status == VERIFIED


class LoopOutcome(typing.NamedTuple):
    """Everything one orchestration produced.

    ``verifier_message`` is the verifier agent's own text, and is advisory: it is
    what ``execute_sequential_thinking_loop`` has always returned and continues to
    return, and no control path reads it. The load-bearing half is ``verdict``.
    Named for what it holds rather than ``verification_text``, which would read as
    the authoritative thing while sitting beside the field that actually is.
    """

    verdict: Verdict
    verifier_message: str
    plan: str
    code_output: str


def _emit(verdict: Verdict) -> Verdict:
    """Log every verdict at the one point all three constructors share.

    Message-string fields, not ``extra=``: ``JSONFormatter.format()``
    (``json_logging.py``) reads four fixed record attributes and drops ``extra``
    kwargs today, so anything meant to survive into the emitted JSON line has to
    be in the message itself. ``Verdict.reason`` never carries captured
    stdout/stderr (see ``derive_verdict``), so nothing here needs redaction.

    ``exit_code`` is normalised to ``"-"`` when negative: ``not_configured()``,
    ``reentrant()``, and the unrunnable-probe branch of ``derive_verdict`` all use
    ``-1`` as a sentinel for "no command ever ran", not a real process exit status.
    Logged verbatim, ``-1`` reads exactly like a command that ran and exited -1 --
    a real subprocess's own returncode is never negative on the paths that reach
    this function, so there is no ambiguity to lose by normalising it away.
    """
    exit_code: object = verdict.exit_code if verdict.exit_code >= 0 else "-"
    logger.info(
        "verdict status=%s termination_reason=%s command=%r exit_code=%s",
        verdict.status, verdict.termination_reason or "-", verdict.command, exit_code,
    )
    return verdict


def derive_verdict(check: typing.Any) -> Verdict:
    """Grade a harness-run check.

    Accepts only a :class:`HarnessCheck`. An ``ExecutionResult`` -- the agent's
    own command outcome -- is refused rather than graded, because the two are
    otherwise structurally similar enough to substitute for one another silently.

    Ordered; the first matching condition wins. Every condition under which a
    verdict could not be obtained resolves to ``BLOCKED``, so a missing toolchain
    is never reported as a failing change.
    """
    if not isinstance(check, HarnessCheck):
        raise TypeError(
            "derive_verdict grades a HarnessCheck, which only "
            "harness.shared.governance.verification constructs; "
            f"refusing a {type(check).__name__}. A verdict derived from a command the "
            "model chose is model authorship at one remove (spec R-VP-8)."
        )

    def _v(status: str, reason: str, termination: str) -> Verdict:
        return _emit(Verdict(status, reason, termination, check.command, check.exit_code))

    if not check.probe_ok:
        return _v(BLOCKED, f"{check.target} could not be established as runnable", UNAVAILABLE)
    if check.status == _BLOCKED:
        return _v(BLOCKED, check.reason or f"{check.target} was denied by policy", DENIED)
    if check.status == _FAILED and check.reason:
        # A reason on a FAILED result is set only for a timeout or a failure to
        # start; an ordinary non-zero exit leaves it empty. So the reason is what
        # separates "the harness could not run this" from "this ran and failed".
        return _v(BLOCKED, check.reason, HARNESS_FAULT)
    if check.status == _SUCCESS and check.exit_code == 0:
        return _v(VERIFIED, f"{check.target} exited 0", "")
    if check.status in (_SUCCESS, _FAILED):
        # Both fields are tested, not just one. The broker takes an injected
        # backend, and a verdict trusting a single field that a foreign backend
        # fills in is the fail-open shape this repository has been removing.
        return _v(FAILED, f"{check.target} exited {check.exit_code}", FAILED_CHECK)
    return _v(BLOCKED, f"unrecognised check status {check.status!r}", UNRECOGNISED)


def not_configured(target: str = "") -> Verdict:
    """The verdict for a harness with no verification command.

    An adopter that configures none must be told so, not handed a failure for a
    check that was never attempted. ``validate_adoption`` does not require a
    Makefile, so this is a real deployment, not a hypothetical one.
    """
    return _emit(Verdict(BLOCKED, "no verification command is configured", NOT_CONFIGURED, target, -1))


def reentrant(target: str) -> Verdict:
    """The verdict for a check that would run inside its own execution."""
    return _emit(Verdict(BLOCKED, f"{target} is already running", REENTRANT, target, -1))
