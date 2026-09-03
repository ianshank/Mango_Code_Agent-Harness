"""Shadow-mode planner comparison channel.

Observation-only: with the flag enabled, the incumbent plan and one shadow
plan are recorded as CognitiveSignals for offline comparison. The shadow pass
holds zero authority — it runs with an empty tool schema, receives only a
frozen value object (never the orchestrator), and its failures are contained.

Requirement Citations (docs/specs/mangomas-integration-core.md):
- R-MMI-5: incumbent + shadow signals with shared run_id and lineage
- R-MMI-6: shadow payload carries elapsed_ms and the provider usage object
- R-MMI-7: existing planner prompt reuse; bounded shadow timeout
- C-MMI-3: empty tool schema, no tool_choice, no orchestrator references
- C-MMI-5: no failure in this module may affect the incumbent result
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import typing
import uuid
from dataclasses import dataclass
from pathlib import Path

from harness.shared.cognitive_signal import CognitiveSignal, CognitiveSignalSink
from harness.shared.nemotron_bridge import complete_chat

logger = logging.getLogger(__name__)

SHADOW_PLANNER_ENV = "MANGO_SHADOW_PLANNER"
SHADOW_MODEL_ENV = "MANGO_SHADOW_MODEL"
SHADOW_TIMEOUT_ENV = "MANGO_SHADOW_TIMEOUT_SEC"
DEFAULT_SHADOW_TIMEOUT_SEC = 60

INCUMBENT_PRODUCER_ID = "planner.incumbent"
SHADOW_PRODUCER_ID = "planner.shadow"
SIGNAL_TYPE_INCUMBENT_PLAN = "plan.incumbent"
SIGNAL_TYPE_SHADOW_PLAN = "plan.shadow"
# Terminal signal for a run whose shadow half failed (R-MMI-5): without this,
# a run_id with only an incumbent signal is indistinguishable from "still in
# flight" to an offline consumer (see .mango/skills/shadow-channel-analysis).
SIGNAL_TYPE_SHADOW_ERROR = "plan.shadow_error"
UNKNOWN_POLICY_IDENTITY = "unknown"

TASK_ID_HEX_LEN = 16
POLICY_VERSION_HEX_LEN = 16
POLICY_RELPATH = Path("harness") / "shared" / "governance-policy.json"


@dataclass(frozen=True)
class ShadowContext:
    """Everything the shadow pass may see. Deliberately a value object:
    handing this module a live orchestrator would hand it tool authority."""

    workspace_dir: Path
    api_key: str | None
    model: str | None
    api_timeout: int
    planner_system_prompt: str
    planner_user_prompt: str
    task: str
    incumbent_plan: str
    incumbent_elapsed_ms: int


def shadow_planner_enabled(environ: typing.Mapping[str, str] | None = None) -> bool:
    """True only when the flag is exactly "1" (same idiom as MANGO_DEBUG_DUMP)."""
    env = os.environ if environ is None else environ
    return env.get(SHADOW_PLANNER_ENV) == "1"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _policy_identity(workspace_dir: Path) -> tuple[str, str]:
    """Read-only (policy_id, content-digest policy_version) for signal metadata.

    The policy file's own schema_version is a format version, not a content
    version, so the version recorded here is a digest of the bytes in effect.
    Metadata only — any failure, including a policy file that parses but
    carries an empty/null/non-string ``policy_id``, degrades to
    ``(UNKNOWN_POLICY_IDENTITY, UNKNOWN_POLICY_IDENTITY)`` rather than passing
    a value through that ``validate_signal_dict`` would reject — that
    rejection would otherwise happen on the very first ``sink.append`` in
    ``_run``, silently discarding the incumbent signal along with it.
    """
    policy_path = Path(workspace_dir) / POLICY_RELPATH
    try:
        raw = policy_path.read_bytes()
        raw_id = json.loads(raw.decode("utf-8")).get("policy_id")
        digest = hashlib.sha256(raw).hexdigest()[:POLICY_VERSION_HEX_LEN]
        policy_id = raw_id if isinstance(raw_id, str) and raw_id else UNKNOWN_POLICY_IDENTITY
        return policy_id, digest
    except Exception:  # noqa: BLE001 - containment boundary, read failure must not break run
        # read it must never break the run that was going to happen anyway.
        logger.warning(
            "shadow_planner: could not read policy identity from %s", policy_path, exc_info=True
        )
        return (UNKNOWN_POLICY_IDENTITY, UNKNOWN_POLICY_IDENTITY)


def _shadow_timeout_sec(context: ShadowContext, environ: typing.Mapping[str, str] | None = None) -> int:
    """Bounded shadow timeout: env override, capped by the orchestrator timeout."""
    env = os.environ if environ is None else environ
    raw = env.get(SHADOW_TIMEOUT_ENV, "")
    try:
        value = int(raw) if raw else DEFAULT_SHADOW_TIMEOUT_SEC
    except ValueError:
        logger.warning("shadow_planner: invalid %s=%r; using default", SHADOW_TIMEOUT_ENV, raw)
        value = DEFAULT_SHADOW_TIMEOUT_SEC
    return max(1, min(value, context.api_timeout))


def run_shadow_comparison(
    context: ShadowContext, environ: typing.Mapping[str, str] | None = None
) -> None:
    """Record the incumbent plan and one shadow plan. Never raises (C-MMI-5).

    On any failure, best-effort records a ``plan.shadow_error`` terminal
    signal (see ``_run``) before this — the channel's own containment layer,
    distinct from the orchestrator's outer guard around this call — swallows
    it. The two layers log different messages so a test (or an operator
    reading logs) can tell which one actually caught a given failure.
    """
    try:
        _run(context, environ=environ)
    except Exception:  # noqa: BLE001 - channel containment layer (C-MMI-5)
        # the shadow channel must never be able to affect the primary path, so
        # every failure class is absorbed here by design.
        logger.warning(
            "shadow_planner: channel-level containment caught a failure; "
            "incumbent plan is unaffected",
            exc_info=True,
        )


def _extract_shadow_plan_text(response: dict) -> str:
    """Defensively pull the plan text out of a provider response. A hostile
    or malformed response (``choices=[None]``, a non-dict ``message``, or
    ``content`` shaped as an Anthropic-style content-block list rather than a
    plain string) degrades to ``""`` instead of raising ``AttributeError``
    deep in the happy path."""
    choices = response.get("choices") or [{}]
    first = choices[0] if choices else {}
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, str) else ""


def _run(
    context: ShadowContext, environ: typing.Mapping[str, str] | None = None
) -> None:
    env = os.environ if environ is None else environ
    sink = CognitiveSignalSink.for_workspace(context.workspace_dir, environ=env)
    run_id = str(uuid.uuid4())
    task_id = _sha256_text(context.task)[:TASK_ID_HEX_LEN]
    policy_id, policy_version = _policy_identity(context.workspace_dir)
    logger.debug(
        "shadow_planner: run %s starting; sink=%s policy=%s/%s",
        run_id,
        sink.path,
        policy_id,
        policy_version,
    )

    incumbent = CognitiveSignal.create(
        run_id=run_id,
        task_id=task_id,
        producer_id=INCUMBENT_PRODUCER_ID,
        signal_type=SIGNAL_TYPE_INCUMBENT_PLAN,
        payload={
            "plan_sha256": _sha256_text(context.incumbent_plan),
            "plan": context.incumbent_plan,
            "elapsed_ms": context.incumbent_elapsed_ms,
        },
        policy_id=policy_id,
        policy_version=policy_version,
        producer_version=context.model,
    )
    sink.append(incumbent)

    shadow_model = env.get(SHADOW_MODEL_ENV) or context.model
    shadow_timeout = _shadow_timeout_sec(context, environ=env)
    logger.debug(
        "shadow_planner: run %s calling shadow model=%s timeout_s=%s",
        run_id,
        shadow_model or "(orchestrator default)",
        shadow_timeout,
    )
    call_kwargs: dict = {
        "messages": [
            {"role": "system", "content": context.planner_system_prompt},
            {"role": "user", "content": context.planner_user_prompt},
        ],
        # Zero authority (C-MMI-3): the shadow pass is never offered a tool.
        "tools": [],
        "timeout_sec": shadow_timeout,
    }
    if context.api_key is not None:
        call_kwargs["api_key"] = context.api_key
    if shadow_model:
        call_kwargs["model"] = shadow_model

    try:
        started = time.monotonic()
        response = complete_chat(**call_kwargs)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        shadow_plan = _extract_shadow_plan_text(response)
        usage = response.get("usage")
        usage = usage if isinstance(usage, dict) else {}
    except Exception as exc:
        # R-MMI-5: a run_id with only an incumbent signal reads as "still in
        # flight" to an offline consumer. Emit a terminal error signal so a
        # failed shadow pass is distinguishable from one that never ran,
        # then let the outer guard's warning-and-swallow contract (C-MMI-5)
        # take over — this signal is best-effort, not a substitute for it.
        try:
            sink.append(
                CognitiveSignal.create(
                    run_id=run_id,
                    task_id=task_id,
                    producer_id=SHADOW_PRODUCER_ID,
                    signal_type=SIGNAL_TYPE_SHADOW_ERROR,
                    payload={"error_type": type(exc).__name__, "error": str(exc)},
                    policy_id=policy_id,
                    policy_version=policy_version,
                    parent_signal_id=incumbent.signal_id,
                )
            )
        except Exception:  # noqa: BLE001 - best-effort signal recording
            # path; the original failure is re-raised below and must not be masked
            # by a failure to record it.
            logger.warning("shadow_planner: run %s could not record shadow_error signal", run_id, exc_info=True)
        raise

    shadow = CognitiveSignal.create(
        run_id=run_id,
        task_id=task_id,
        producer_id=SHADOW_PRODUCER_ID,
        signal_type=SIGNAL_TYPE_SHADOW_PLAN,
        payload={
            "plan_sha256": _sha256_text(shadow_plan),
            "plan": shadow_plan,
            "elapsed_ms": elapsed_ms,
            "usage": usage,
        },
        policy_id=policy_id,
        policy_version=policy_version,
        producer_version=shadow_model,
        parent_signal_id=incumbent.signal_id,
    )
    sink.append(shadow)
    logger.info(
        "shadow_planner: recorded comparison run %s (incumbent %s, shadow %s)",
        run_id,
        incumbent.signal_id,
        shadow.signal_id,
    )
