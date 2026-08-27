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
    Metadata only — any failure degrades to ("unknown", "unknown").
    """
    policy_path = Path(workspace_dir) / POLICY_RELPATH
    try:
        raw = policy_path.read_bytes()
        policy_id = json.loads(raw.decode("utf-8")).get("policy_id", "unknown")
        digest = hashlib.sha256(raw).hexdigest()[:POLICY_VERSION_HEX_LEN]
        return str(policy_id), digest
    except Exception:
        logger.warning("shadow_planner: could not read policy identity from %s", policy_path)
        return ("unknown", "unknown")


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


def run_shadow_comparison(context: ShadowContext) -> None:
    """Record the incumbent plan and one shadow plan. Never raises (C-MMI-5)."""
    try:
        _run(context)
    except Exception:
        logger.warning(
            "shadow_planner: comparison failed; incumbent plan is unaffected", exc_info=True
        )


def _run(context: ShadowContext) -> None:
    sink = CognitiveSignalSink.for_workspace(context.workspace_dir)
    run_id = str(uuid.uuid4())
    task_id = _sha256_text(context.task)[:TASK_ID_HEX_LEN]
    policy_id, policy_version = _policy_identity(context.workspace_dir)

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

    shadow_model = os.environ.get(SHADOW_MODEL_ENV) or context.model
    call_kwargs: dict = {
        "messages": [
            {"role": "system", "content": context.planner_system_prompt},
            {"role": "user", "content": context.planner_user_prompt},
        ],
        # Zero authority (C-MMI-3): the shadow pass is never offered a tool.
        "tools": [],
        "timeout_sec": _shadow_timeout_sec(context),
    }
    if context.api_key is not None:
        call_kwargs["api_key"] = context.api_key
    if shadow_model:
        call_kwargs["model"] = shadow_model

    started = time.monotonic()
    response = complete_chat(**call_kwargs)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    message = (response.get("choices") or [{}])[0].get("message", {})
    shadow_plan = message.get("content") or ""

    shadow = CognitiveSignal.create(
        run_id=run_id,
        task_id=task_id,
        producer_id=SHADOW_PRODUCER_ID,
        signal_type=SIGNAL_TYPE_SHADOW_PLAN,
        payload={
            "plan_sha256": _sha256_text(shadow_plan),
            "plan": shadow_plan,
            "elapsed_ms": elapsed_ms,
            "usage": response.get("usage") or {},
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
