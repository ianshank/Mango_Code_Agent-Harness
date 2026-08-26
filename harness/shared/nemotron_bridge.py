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
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


def mask_secret(secret: str) -> str:
    """Mask sensitive tokens showing prefix and suffix."""
    if not secret:
        return "<UNSET>"
    s = secret.strip()
    if len(s) <= 10:
        return "****"
    return f"{s[:10]}...{s[-4:]}"


def resolve_environment() -> dict[str, str]:
    """Resolve API key, base URL, and default model from environment or local .env file."""
    env_vars = {
        "api_key": os.environ.get("NVIDIA_API_KEY", ""),
        "base_url": os.environ.get("NVIDIA_BASE_URL", ""),
        "default_model": os.environ.get("NEMOTRON_DEFAULT_MODEL", ""),
    }
    if env_vars["api_key"] and env_vars["default_model"]:
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
                        key_name = k.strip()
                        val = v.strip()
                        if key_name == "NVIDIA_API_KEY" and not env_vars["api_key"]:
                            env_vars["api_key"] = val
                        elif key_name == "NVIDIA_BASE_URL" and not env_vars["base_url"]:
                            env_vars["base_url"] = val
                        elif key_name == "NEMOTRON_DEFAULT_MODEL" and not env_vars["default_model"]:
                            env_vars["default_model"] = val
            except Exception:
                pass
    return env_vars


def resolve_api_key() -> str:
    """Resolve API key from environment variable or local .env file."""
    return resolve_environment()["api_key"]


def complete_chat(
    messages: list[dict[str, Any]],
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    timeout_sec: int = 30,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any | None = None,
) -> dict[str, Any]:
    """Execute a chat completion request against NVIDIA Nemotron API."""
    env_config = resolve_environment()
    key = api_key if api_key is not None else env_config["api_key"]
    if not key:
        raise ValueError("NVIDIA_API_KEY is not configured. Set environment variable or define in .env.")

    endpoint = base_url or env_config["base_url"] or DEFAULT_BASE_URL
    target_model = model or env_config["default_model"]
    if not target_model:
        raise ValueError(
            "Target model is not configured. Set NEMOTRON_DEFAULT_MODEL "
            "environment variable or pass explicitly."
        )

    url = f"{endpoint.rstrip('/')}/chat/completions"
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError(f"Invalid URL scheme in endpoint: {endpoint}")

    payload = {
        "model": target_model,
        "messages": messages,
        "temperature": max(0.0, min(2.0, temperature)),
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "Agentic-SSD-Nemotron-Bridge/2.0",
        },
        method="POST",
    )

    start_time = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:  # nosec B310
            body = resp.read().decode("utf-8")
            data = cast(dict[str, Any], json.loads(body))
            latency_ms = int((time.time() - start_time) * 1000)
            data["latency_ms"] = latency_ms
            return data
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        sanitized = err_msg.replace(key, mask_secret(key))
        raise RuntimeError(f"Nemotron API HTTP {e.code} Error: {sanitized}") from e
    except Exception as e:
        sanitized = str(e).replace(key, mask_secret(key))
        raise RuntimeError(f"Nemotron Connection Error: {sanitized}") from e


def main() -> None:
    parser = argparse.ArgumentParser(description="NVIDIA Nemotron Ultra Python Bridge")
    parser.add_argument("--prompt", required=True, help="User prompt to send to Nemotron")
    parser.add_argument(
        "--system",
        default="You are an expert AI architect and reasoning assistant.",
        help="System instruction prompt",
    )
    parser.add_argument("--model", default=None, help="Target model ID")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    parser.add_argument("--json", action="store_true", help="Output raw JSON response")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

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
    except Exception as e:
        logger.error(f"Nemotron Bridge Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
