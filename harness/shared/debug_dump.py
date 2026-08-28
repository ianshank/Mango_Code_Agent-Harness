"""Conversation-history redaction and debug dumping.

Extracted from ``MangoMASOrchestrator._dump_debug_history`` for two reasons.

First, correctness: the in-place version redacted only when
``self.api_key`` was truthy, but the orchestrator normally leaves that
``None`` and lets ``nemotron_bridge.complete_chat`` resolve the credential
downstream. In that (normal) configuration the redaction loop never ran, and
``MANGO_DEBUG_DUMP=1`` wrote an **unredacted** history to a predictably named
file in the shared temp directory. Redaction here does not depend on the
caller having remembered to pass a key: an explicit key is used when given,
the environment is consulted when it is not, and a provider-shaped token is
scrubbed by pattern regardless.

Second, reuse: ``harness/api_server`` returns the same history over HTTP and
needs the same guarantee. One redactor, two consumers.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REDACTED = "<REDACTED_API_KEY>"

# Environment variables that may hold a credential worth scrubbing. Keeping
# this a module constant (rather than a literal at the call site) means adding
# a provider is a one-line change that both consumers pick up.
CREDENTIAL_ENV_VARS = ("NVIDIA_API_KEY",)

# NVIDIA-issued keys are `nvapi-` followed by a long opaque token. Matching the
# shape catches a key that reached the history by a route we do not control --
# echoed by a tool, pasted into a prompt, or resolved inside the bridge -- which
# is exactly the case the old value-equality check could not cover.
CREDENTIAL_PATTERN = re.compile(r"nvapi-[A-Za-z0-9_\-]{8,}")

# Dump files can contain prompts and tool output. The directory is created
# owner-only; the previous code took the default 0o777 & ~umask, which on a
# shared host left the history world-readable.
DUMP_DIR_MODE = 0o700
DUMP_ENV_FLAG = "MANGO_DEBUG_DUMP"


def resolve_credentials(explicit: str | None = None, env: Mapping[str, str] | None = None) -> list[str]:
    """Every literal credential worth scrubbing, most specific first.

    ``explicit`` is the caller's key when it has one. The environment is read
    regardless, because the common orchestrator path passes ``None`` and lets
    the bridge resolve the key later -- the exact case the old guard missed.
    """
    source = os.environ if env is None else env
    found: list[str] = []
    for candidate in (explicit, *(source.get(var, "") for var in CREDENTIAL_ENV_VARS)):
        if candidate and candidate not in found:
            found.append(candidate)
    return found


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Replace known literals and any provider-shaped token in ``text``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return CREDENTIAL_PATTERN.sub(REDACTED, text)


def redact_history(
    history: Sequence[Mapping[str, Any]],
    api_key: str | None = None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Deep-copy ``history`` with every string value redacted.

    Every string in each message is scrubbed, not just ``content``: tool
    results, names and ids are model-influenced too, and a redactor that
    covers one key is a redactor that can be routed around.
    """
    secrets = resolve_credentials(api_key, env)
    redacted = copy.deepcopy(list(history))
    return [{key: _redact_value(value, secrets) for key, value in message.items()} for message in redacted]


def _redact_value(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item, secrets) for key, item in value.items()}
    return value


def dump_enabled(env: Mapping[str, str] | None = None) -> bool:
    """True when MANGO_DEBUG_DUMP opts this process into writing dumps."""
    source = os.environ if env is None else env
    return source.get(DUMP_ENV_FLAG) == "1"


def write_dump(
    history: Sequence[Mapping[str, Any]],
    agent_name: str,
    api_key: str | None = None,
    dump_root: Path | None = None,
) -> Path | None:
    """Write a redacted history dump; return the path, or None when disabled.

    Failures are logged and swallowed: a debugging aid must never be the reason
    an agent run dies.
    """
    if not dump_enabled():
        return None
    root = Path(tempfile.gettempdir()) / "mango_debug" if dump_root is None else dump_root
    try:
        root.mkdir(parents=True, exist_ok=True)
        # mkdir's mode is ignored when the directory already exists, so set it
        # explicitly -- a dump directory left over from an earlier, laxer run
        # would otherwise keep its permissions.
        root.chmod(DUMP_DIR_MODE)
        target = root / f"debug_{agent_name}_{int(time.time() * 1000)}.json"
        payload = json.dumps(redact_history(history, api_key), indent=2)
        target.write_text(payload, encoding="utf-8")
    except OSError:
        logger.warning("Could not write debug dump for agent %s", agent_name, exc_info=True)
        return None
    return target
