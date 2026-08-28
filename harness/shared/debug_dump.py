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
#
# This list covered only NVIDIA_API_KEY while `main.py` returned the conversation
# history over HTTP through `redact_history`, so API_SERVER_KEY and
# AGENT_EVIDENCE_KEY left the process in clear text whenever a tool echoed them.
# The second is the HMAC key EvidenceBuilder signs with: disclosing it does not
# just leak, it lets an attacker forge the manifests INV-7 and INV-13 rest on.
CREDENTIAL_ENV_VARS = (
    "NVIDIA_API_KEY",
    "API_SERVER_KEY",
    "AGENT_EVIDENCE_KEY",
    "CONTEXT7_API_KEY",
)

# Any variable whose *name* marks it as a credential is scrubbed by value too, so
# a provider added to .env later is covered without editing this module. The
# named list above stays because it is the reviewed set; this is the safety net.
CREDENTIAL_NAME_PATTERN = re.compile(r"(?:^|_)(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS?)$")

# Floor for a value discovered in the environment. `redact_text` replaces by
# substring, so a variable set to "x" would rewrite every "x" in the history and
# destroy it. Caller-supplied secrets are exempt: the caller knows what it passed.
MIN_ENV_CREDENTIAL_LENGTH = 8

# NVIDIA-issued keys are `nvapi-` followed by a long opaque token. Matching the
# shape catches a key that reached the history by a route we do not control --
# echoed by a tool, pasted into a prompt, or resolved inside the bridge -- which
# is exactly the case the old value-equality check could not cover.
CREDENTIAL_PATTERN = re.compile(r"nvapi-[A-Za-z0-9_\-]{8,}")

# The full shape set. `.gitleaks.toml` carries only an allowlist over gitleaks'
# built-in rules, so there is no rule table here to source these from and no
# drift to guard against; this tuple is the single definition, and
# CREDENTIAL_PATTERN above is retained as the NVIDIA member for existing callers.
CREDENTIAL_PATTERNS = (
    CREDENTIAL_PATTERN,
    re.compile(r"ctx7sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)authorization:\s*bearer\s+\S+"),
)

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
    if explicit and explicit not in found:
        found.append(explicit)

    # The reviewed list carries no length floor: these names are known credentials,
    # and applying one would silently stop scrubbing a short key. The floor applies
    # only to names discovered by pattern, where a false positive on a short value
    # ("DEBUG_TOKEN=1") would rewrite every "1" in the history.
    for name in CREDENTIAL_ENV_VARS:
        candidate = source.get(name, "")
        if candidate and candidate not in found:
            found.append(candidate)

    for name in source:
        if name in CREDENTIAL_ENV_VARS or not CREDENTIAL_NAME_PATTERN.search(name):
            continue
        candidate = source.get(name, "")
        if len(candidate) >= MIN_ENV_CREDENTIAL_LENGTH and candidate not in found:
            found.append(candidate)

    # Longest first, and this ordering is load-bearing rather than cosmetic.
    # `redact_text` replaces by substring in list order, so when one credential is
    # a prefix of another -- two keys sharing an issuer prefix, or a truncated
    # copy of the same key -- replacing the shorter one first consumes its head
    # and leaves the remainder of the longer one in clear text. `sorted` is
    # stable, so equal-length values keep their declared order.
    return sorted(found, key=len, reverse=True)


def credential_env_names(env: Mapping[str, str] | None = None) -> list[str]:
    """Names in ``env`` that hold a credential, by review or by shape of the name.

    ``agent-policy.json`` declares ``secrets_may_not_be_propagated_to_subagents``
    and nothing enforced it: the orchestrator handed every hook the full
    ``os.environ``. This is the list a child process must not inherit.
    """
    source = os.environ if env is None else env
    return [
        name
        for name in source
        if name in CREDENTIAL_ENV_VARS or CREDENTIAL_NAME_PATTERN.search(name)
    ]


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    """Replace known literals and any provider-shaped token in ``text``."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    for pattern in CREDENTIAL_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


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
