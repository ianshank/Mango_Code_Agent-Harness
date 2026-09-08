"""Single source of truth for operational values in governance-policy.json.

This module resolves: explicit argument > policy file > built-in default.
Environment-variable overrides are deliberately NOT read here — they are the
caller's layer where one exists (nemotron_bridge reads NEMOTRON_TIMEOUT_MS /
NEMOTRON_MAX_RETRIES before falling back to these policy values, completing
the full arg > env > policy > builtin chain for those knobs; orchestrator
limits define no env override). Fail-closed semantics match
coverage_gate.load_thresholds: an *absent* policy file is the adopter path
and yields built-in defaults; a *present but malformed* policy raises,
because silently falling back would let a corrupted policy weaken a gate or
a runtime limit.

Spec: docs/specs/policy-single-source.md.
"""

from __future__ import annotations

import json
import logging
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

POLICY_PATH = Path(__file__).resolve().parent / "governance-policy.json"

logger = logging.getLogger("harness.shared.policy_loader")


def _live_policy_path() -> Path:
    """The path tests monkeypatch on the ``policy_loader`` facade.

    Accessors moved here in the size-budget split; looking up ``POLICY_PATH``
    on this module would ignore ``monkeypatch.setattr(policy_loader, "POLICY_PATH", ...)``.
    """
    try:
        from harness.shared import policy_loader as facade
    except ImportError:
        return POLICY_PATH
    return facade.POLICY_PATH


def resolve_policy_path(policy_path: Path | None = None) -> Path:
    """Explicit path, else the live facade path."""
    return policy_path if policy_path is not None else _live_policy_path()


class OrchestratorLimits(TypedDict):
    """The `orchestrator` block, typed so an unknown key is a static error.

    Every threshold in the system resolves through this module, and the
    accessors used to return a bare ``dict`` -- so ``limits["max_iteration"]``
    was a runtime ``KeyError`` in whatever code path happened to reach it
    first. DEC-032 fixed one instance of exactly that shape by hand, in
    ``_session_hooks``. A ``TypedDict`` is a plain ``dict`` at runtime, so no
    caller changes and adopters reading the block dynamically are unaffected;
    what changes is that ``python -m mypy`` now reports the typo (R-GT-5).
    """

    max_iterations: int
    api_timeout_sec: int
    verification_timeout_sec: int
    tool_timeout_sec: int
    max_command_bytes: int
    max_healing_retries: int
    max_output_bytes: int
    context_budget_tokens: int
    context_chars_per_token: float


class NemotronDefaults(TypedDict):
    """The `nemotron` block. See :class:`OrchestratorLimits` for the rationale."""

    temperature: float
    top_p: float
    max_tokens: int
    timeout_ms: int
    max_retries: int


class LangGraphDefaults(TypedDict):
    """The `langgraph` block. See :class:`OrchestratorLimits` for the rationale."""

    recursion_limit: int
    max_concurrency: int
    plan_divergence_threshold: float


class CoverageThresholds(TypedDict):
    """The `coverage` block. See :class:`OrchestratorLimits` for the rationale."""

    lines: int
    branches: int


class AgentMemoryLimits(TypedDict):
    """The `agent_memory` block. See :class:`OrchestratorLimits` for the rationale."""

    max_gaps: int
    max_hypotheses: int
    planner_gap_limit: int
    reasoner_hypothesis_limit: int
    reasoner_hypothesis_budget_tokens: int


class GateFloors(TypedDict):
    """The `gates` block. See :class:`OrchestratorLimits` for the rationale."""

    dedup_min_scripts: int
    py_compat_min_files: int


def _log_resolution(block: str, values: Mapping[str, object], policy_path: Path | None) -> None:
    """Record what a policy block resolved to, and which file it came from.

    Nothing recorded which policy a run actually read, so under
    ``LOG_LEVEL=DEBUG`` the question "which thresholds is this run enforcing,
    and from where" had no answer -- while every gate in the repository depends
    on the answer. ``ExecutionLoop`` already logs its own resolution this way;
    this is the same pattern applied at the source (R-GT-4).

    Guarded on ``isEnabledFor`` so the formatting cost is not paid on the
    default path, and emitted at DEBUG so nothing changes for existing callers.
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return
    resolved = resolve_policy_path(policy_path)
    origin = resolved if resolved.exists() else f"{resolved} (absent; built-in defaults)"
    logger.debug(
        "policy %s resolved from %s: %s",
        block,
        origin,
        ", ".join(f"{key}={value!r}" for key, value in sorted(values.items())),
    )


class PolicyError(ValueError):
    """A policy file exists but cannot be used. Never swallowed."""


def policy_file_is_absent(path: Path) -> bool:
    """True when nothing exists at ``path`` -- the adopter path.

    Raises PolicyError for anything else: a directory, a dangling symlink, a
    FIFO, a device node, a path whose parent component is not a directory, an
    unreadable parent, a symlink loop.

    Deliberately probes with ``stat``/``lstat`` rather than the ``Path``
    predicates. ``is_file()``, ``exists()`` and ``is_symlink()`` all swallow
    OSError and answer False, so each of them reports "absent" for a policy
    that is present and merely inaccessible -- a parent directory without
    execute permission, or a path component that turned out to be a file. The
    predicates cannot express the question; only the errno can.

    That distinction is the whole point of this function. "This adopter has not
    adopted the policy yet" is supported and yields built-in defaults. "The
    policy that governs this run cannot be read" must stop the run. Collapse
    them and a bad volume mount or a half-extracted archive drops every
    threshold to its default while every gate still reports success.
    """
    try:
        info = path.stat()
    except FileNotFoundError:
        # Either nothing is here at all, or a symlink whose target is gone --
        # stat() follows the link and cannot tell them apart. lstat() does not
        # follow it, so it answers the question stat() just lost.
        try:
            path.lstat()
        except FileNotFoundError:
            return True
        except OSError as exc:
            raise PolicyError(f"governance policy path {path} is not readable: {exc}") from exc
        raise PolicyError(
            f"governance policy path {path} is a symlink whose target does not exist; "
            "refusing to fall back to built-in defaults"
        ) from None
    except OSError as exc:
        raise PolicyError(f"governance policy path {path} is not readable: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise PolicyError(
            f"governance policy path {path} exists but is not a regular file; "
            "refusing to fall back to built-in defaults"
        )
    return False


def load_policy(policy_path: Path | None = None) -> dict:
    """Return the parsed policy, or {} when no policy file exists (adopter path).

    A present-but-unparseable policy raises PolicyError (fail-closed), and so
    does a policy path that exists without being a regular file.
    """
    path = resolve_policy_path(policy_path)
    if policy_file_is_absent(path):
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicyError(f"unreadable governance policy at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PolicyError(f"governance policy at {path} is not a JSON object")
    return data


class _Section:
    """One policy block, and whether a policy file backs it.

    That second fact is the whole of R-CQ-8. The previous helpers took
    ``section.get(key, default)``, which cannot tell *this adopter has no policy
    file, so use the built-in default* from *the policy governing this run has
    lost a key*. It answered the literal for both. The first is a supported
    path -- ``policy_file_is_absent`` exists to keep it working. The second is a
    policy that no longer says what every reader believes it says, and the Node
    reader has always thrown for it (``policy.ts:58-69``): one stack failed
    closed while the other quietly substituted a number nobody reviewed.

    A dropped key is not hypothetical in the direction that matters. Deleting
    ``orchestrator.max_iterations`` returned 10 and the loop kept running;
    deleting ``coverage.lines`` returned 90 while the policy on disk was the
    document a reviewer had been pointed at. The failure is silent by
    construction, because the substituted value is a *plausible* one.

    Carrying ``backed`` next to the data is what lets one call site express both
    outcomes, so every accessor below gets the behaviour without restating it.
    """

    #: The path is carried so the error can name it. The first version said
    #: "missing from a present policy at this path" and then named no path,
    #: which is the least useful shape an error can take: it tells the reader a
    #: file is at fault and withholds which one. Every accessor takes an
    #: optional `policy_path`, and the tests use `tmp_path` fixtures, so "which
    #: policy?" is a real question at the moment the error is read. Reported by
    #: a review bot on this PR.
    __slots__ = ("_data", "_name", "_backed", "_path", "_declared")

    def __init__(self, data: dict, name: str, backed: bool, path: Path, declared: bool | None = None) -> None:
        self._data = data
        self._name = name
        self._backed = backed
        self._path = path
        # `None` infers, for a direct caller. `_section` always states it:
        # only it can see whether the block was a key in the policy.
        self._declared = bool(data) if declared is None else declared

    def _value(self, key: str, default: object) -> object:
        if key in self._data:
            return self._data[key]
        if self._backed:
            raise PolicyError(
                f"policy {self._name}.{key} is missing from the policy at {self._path}; "
                "refusing to substitute the built-in default, which would let a gate "
                "report success against a threshold the policy no longer states"
            )
        return default

    def int(self, key: str, default: int) -> int:
        value = self._value(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise PolicyError(f"policy {self._name}.{key} must be an integer, got {value!r}")
        return int(value)

    def float(self, key: str, default: float) -> float:
        value = self._value(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PolicyError(f"policy {self._name}.{key} must be a number, got {value!r}")
        return float(value)

    def declared(self) -> bool:
        """Whether this deployment states the block at all.

        Distinct from ``backed``, which is about the policy *file*. A file
        predating a newly added block is supported: the block is absent, so the
        deployment declares nothing and an accessor may use its built-in
        defaults. A block that is *present* still owes every key it reads, which
        ``_value`` enforces.

        The test is presence *as a key*, never whether the block resolved to
        something non-empty: ``"gates": {}`` has adopted the block and stated
        none of it, so reading it as "undeclared" would have returned defaults
        (reported by a review bot on PR #122).
        """
        return self._declared

    def optional(self, key: str, default: object) -> object:
        """A key whose *absence* is part of the schema, not a hole in it.

        Only for keys documented as optional at their accessor. Missing here
        means "this deployment declares none", which is a statement; missing in
        ``_value`` means the policy stopped saying something it used to say.
        """
        return self._data.get(key, default)


def _section(name: str, policy_path: Path | None = None) -> _Section:
    path = resolve_policy_path(policy_path)
    backed = not policy_file_is_absent(path)
    policy = load_policy(path) if backed else {}
    data = policy.get(name, {})
    if not isinstance(data, dict):
        raise PolicyError(f"policy section {name!r} is not an object")
    return _Section(data, name, backed, path, declared=name in policy)
