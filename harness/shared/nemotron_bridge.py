#!/usr/bin/env python3
"""
NVIDIA Nemotron Ultra Shared Python Bridge.
Provides zero-dependency Python invocation for git hooks, governance scripts, and CLI tasks.

Requirement Citations:
- R-AI-NEMO-1: OpenAI-compatible wire protocol with endpoint abstraction
- C-AI-SEC-1: Secret sanitization and prevention of sensitive key leakage in stdout/logs
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import warnings
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Optional, cast

from harness.shared import retry_policy
from harness.shared.json_logging import setup_json_logging
from harness.shared.policy_loader import nemotron_defaults
from harness.shared.retry_policy import RetryPolicy, is_retryable_connection_error, parse_retry_after

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"

#: The real ``urlopen`` as it existed at import.
#:
#: The egress floor (R-EGF-5) must refuse the *vendor network path* without
#: breaking a caller or test that supplied its own transport. A double
#: monkeypatched over ``urllib.request.urlopen`` is a declared transport; this
#: pristine reference is how the two are told apart. Mirrors the TypeScript
#: client's PRISTINE_FETCH check so both runtimes behave identically (R-EGF-3).
_PRISTINE_URLOPEN = urllib.request.urlopen


class NemotronEgressRefused(RuntimeError):
    """Raised when a run would reach the network without an explicit declaration."""


def resolve_nemotron_mode(env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Return the declared transport mode, or None when nothing was declared."""
    source = os.environ if env is None else env
    raw = source.get("NEMOTRON_MODE")
    return raw if raw in ("online", "offline") else None


def _assert_egress_permitted(url: str) -> None:
    """Fail closed unless egress was explicitly declared (R-EGF-5, DEC-EGF-003).

    A monkeypatched ``urlopen`` is a declared transport and passes through, so
    the offline test suite and any injected double keep working. Only the
    genuine vendor path requires ``NEMOTRON_MODE=online``.
    """
    if urllib.request.urlopen is not _PRISTINE_URLOPEN:
        return
    mode = resolve_nemotron_mode()
    if mode == "online":
        return
    if mode == "offline":
        raise NemotronEgressRefused(
            f"NEMOTRON_MODE=offline: refusing to open a network transport to {url}. Inject a transport to run offline."
        )
    raise NemotronEgressRefused(
        f"no transport mode declared: refusing to reach {url}. Set "
        "NEMOTRON_MODE=online to permit network egress, NEMOTRON_MODE=offline "
        "to forbid it, or inject a transport."
    )


# Timeout and retry fallbacks now come from governance-policy.json via
# policy_loader.nemotron_defaults(); this module no longer carries its own.
# Backoff between retry attempts. The arithmetic (exponential growth, cap and
# jitter) lives in retry_policy.RetryPolicy. The old alias RETRY_BACKOFF_BASE_SEC
# has no first-party caller left; it is served through ``__getattr__`` below
# with a DeprecationWarning for one minor release (tech-debt-hardening-plan
# R-TDH-17, C-TDH-2) and removed after that.
_DEPRECATED_NAMES = {
    "RETRY_BACKOFF_BASE_SEC": (
        retry_policy.DEFAULT_BASE_SEC,
        "RETRY_BACKOFF_BASE_SEC is deprecated; use retry_policy.DEFAULT_BASE_SEC",
    ),
}


def __getattr__(name: str) -> object:
    """PEP 562: deprecated module names warn on first use instead of vanishing."""
    if name in _DEPRECATED_NAMES:
        value, message = _DEPRECATED_NAMES[name]
        warnings.warn(message, DeprecationWarning, stacklevel=2)
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Transient HTTP statuses worth retrying; everything else fails immediately.
RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})


def mask_secret(secret: str) -> str:
    """Mask sensitive tokens showing prefix and suffix."""
    if not secret:
        return "<UNSET>"
    s = secret.strip()
    if len(s) <= 10:
        return "****"
    return f"{s[:10]}...{s[-4:]}"


# Environment variables the bridge honors, mapped to resolve_environment keys.
_ENV_VAR_KEYS = {
    "NVIDIA_API_KEY": "api_key",
    "NVIDIA_BASE_URL": "base_url",
    "NEMOTRON_DEFAULT_MODEL": "default_model",
    "NEMOTRON_TIMEOUT_MS": "timeout_ms",
    "NEMOTRON_MAX_RETRIES": "max_retries",
}


def resolve_environment() -> dict[str, str]:
    """Resolve API key, base URL, model, timeout, and retries from environment
    or a local .env file (process environment wins)."""
    env_vars = {key: os.environ.get(var, "") for var, key in _ENV_VAR_KEYS.items()}
    # Short-circuit only when *every* key is already supplied by the process
    # environment. The previous guard returned as soon as api_key and
    # default_model were present, which made NEMOTRON_TIMEOUT_MS and
    # NEMOTRON_MAX_RETRIES unreachable from .env in the normal case -- the
    # .env file was only ever consulted when credentials were missing.
    if all(env_vars.values()):
        return env_vars

    # Check candidate .env files
    current = Path(__file__).resolve()
    for parent in [current.parent, current.parent.parent, current.parent.parent.parent]:
        env_path = parent / ".env"
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        key_name = _ENV_VAR_KEYS.get(k.strip())
                        if key_name and not env_vars[key_name]:
                            stripped = v.strip()
                            # Strip matching surrounding quotes (KEY="val" or KEY='val')
                            if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in ('"', "'"):
                                stripped = stripped[1:-1]
                            env_vars[key_name] = stripped
            except (OSError, UnicodeDecodeError):
                # A malformed or unreadable .env must not crash the bridge, but
                # it must not fail invisibly either.
                logger.debug("Skipping unreadable .env file at %s", env_path, exc_info=True)
    return env_vars


def _int_from_env(raw: str, default: int, name: str) -> int:
    """Parse an integer env value, warning (not raising) on garbage."""
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Ignoring non-integer %s=%r; using %d", name, raw, default)
        return default


def resolve_api_key() -> str:
    """Resolve API key from environment variable or local .env file."""
    return resolve_environment()["api_key"]


def complete_chat(
    messages: list[dict[str, Any]],
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout_sec: Optional[int] = None,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    max_retries: Optional[int] = None,
) -> dict[str, Any]:
    """Execute a chat completion request against NVIDIA Nemotron API.

    Request defaults resolve with the precedence: explicit argument >
    environment variable (NEMOTRON_TIMEOUT_MS / NEMOTRON_MAX_RETRIES) >
    governance-policy.json `nemotron` block > built-in default. Retries cover
    transient failures (HTTP 429/5xx and connection errors) with exponential
    backoff and default to 0 (off).
    """
    policy = nemotron_defaults()
    env_config = resolve_environment()
    key = api_key if api_key is not None else env_config["api_key"]
    if not key:
        raise ValueError("NVIDIA_API_KEY is not configured. Set environment variable or define in .env.")

    if temperature is None:
        temperature = policy["temperature"]
    if top_p is None:
        top_p = policy["top_p"]
    if max_tokens is None:
        max_tokens = policy["max_tokens"]
    if timeout_sec is None:
        timeout_ms = _int_from_env(env_config.get("timeout_ms", ""), policy["timeout_ms"], "NEMOTRON_TIMEOUT_MS")
        timeout_sec = max(1, timeout_ms // 1000)
    if max_retries is None:
        max_retries = _int_from_env(env_config.get("max_retries", ""), policy["max_retries"], "NEMOTRON_MAX_RETRIES")
    max_retries = max(0, max_retries)

    endpoint = base_url or env_config["base_url"] or DEFAULT_BASE_URL
    target_model = model or env_config["default_model"]
    if not target_model:
        raise ValueError(
            "Target model is not configured. Set NEMOTRON_DEFAULT_MODEL environment variable or pass explicitly."
        )

    url = f"{endpoint.rstrip('/')}/chat/completions"
    if not url.startswith(("https://", "http://")):
        raise ValueError(f"Invalid URL scheme in endpoint: {endpoint}")

    payload = {
        "model": target_model,
        "messages": messages,
        "temperature": max(0.0, min(2.0, temperature)),
        "top_p": max(0.0, min(1.0, top_p)),
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice

    req_data = json.dumps(payload).encode("utf-8")
    req_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {key}",
        "User-Agent": "Agentic-SSD-Nemotron-Bridge/2.0",
    }

    # Explicit/env-resolved max_retries wins over the mapping's value; the rest
    # of the backoff shape (base, cap, jitter) comes from the same mapping.
    # Named `retry` rather than `policy`: `policy` above is the governance
    # nemotron block, and shadowing it here would silently discard it.
    retry = replace(RetryPolicy.from_mapping(env_config), max_retries=max_retries)

    _assert_egress_permitted(url)

    for attempt in range(retry.max_retries + 1):
        # Built per attempt: a urllib Request accumulates per-opener state (and
        # is mutated by redirect handling), so reusing one instance across
        # retries replays a request that is no longer the one we composed.
        req = urllib.request.Request(url, data=req_data, headers=req_headers, method="POST")
        start_time = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # nosec B310
                body = resp.read().decode("utf-8")
            latency_ms = int((time.time() - start_time) * 1000)
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            sanitized = err_msg.replace(key, mask_secret(key)) if key else err_msg
            if e.code in RETRYABLE_HTTP_STATUSES and retry.should_retry(attempt):
                # A server-supplied Retry-After is an instruction, not a hint:
                # honor it (capped) instead of guessing with exponential backoff.
                header = e.headers.get("Retry-After") if e.headers is not None else None
                backoff = retry.backoff(attempt, retry_after=parse_retry_after(header))
                logger.warning(
                    "Nemotron API HTTP %d (attempt %d/%d); retrying in %.1fs",
                    e.code,
                    attempt + 1,
                    retry.max_retries + 1,
                    backoff,
                )
                time.sleep(backoff)
                continue
            raise RuntimeError(f"Nemotron API HTTP {e.code} Error: {sanitized}") from e
        except Exception as e:
            sanitized = str(e).replace(key, mask_secret(key)) if key else str(e)
            if is_retryable_connection_error(e) and retry.should_retry(attempt):
                backoff = retry.backoff(attempt)
                logger.warning(
                    "Nemotron connection error (attempt %d/%d): %s; retrying in %.1fs",
                    attempt + 1,
                    retry.max_retries + 1,
                    sanitized,
                    backoff,
                )
                time.sleep(backoff)
                continue
            raise RuntimeError(f"Nemotron Connection Error: {sanitized}") from e

        # Parsed outside the retry try/except on purpose: a malformed body on an
        # otherwise successful response is a protocol error, not a connection
        # error, and must not be reported as "Nemotron Connection Error".
        try:
            data = cast(dict[str, Any], json.loads(body))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Nemotron API returned a non-JSON body: {e}") from e
        if not isinstance(data, dict):
            raise RuntimeError(f"Nemotron API returned {type(data).__name__}, expected a JSON object")
        data["latency_ms"] = latency_ms
        return data

    # Unreachable: the loop either returns or raises on its final attempt.
    raise RuntimeError("Nemotron retry loop exited without a response")


def main() -> None:
    parser = argparse.ArgumentParser(description="NVIDIA Nemotron Ultra Python Bridge")
    parser.add_argument("--prompt", required=True, help="User prompt to send to Nemotron")
    parser.add_argument(
        "--system",
        default="You are an expert AI architect and reasoning assistant.",
        help="System instruction prompt",
    )
    parser.add_argument("--model", default=None, help="Target model ID")
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Sampling temperature (default: governance-policy.json nemotron.temperature)",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON response")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_json_logging(level=logging.DEBUG if args.debug else logging.INFO)

    messages = [
        {"role": "system", "content": args.system},
        {"role": "user", "content": args.prompt},
    ]

    try:
        res = complete_chat(messages, model=args.model, temperature=args.temperature)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            content = res.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = res.get("usage", {})
            print(f"\n--- Nemotron Response [{res.get('model')}] ({res.get('latency_ms')}ms) ---\n")
            print(content)
            print(
                f"\nTokens: {usage.get('prompt_tokens', 0)} prompt + "
                f"{usage.get('completion_tokens', 0)} completion = "
                f"{usage.get('total_tokens', 0)} total\n"
            )
    except Exception as e:  # noqa: BLE001 - top-level CLI boundary: every failure
        # becomes a clean one-line message and exit 1, never a traceback on stdout.
        logger.error("Nemotron Bridge Error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
