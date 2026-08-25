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
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path


DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/llama-3.1-nemotron-70b-instruct"


def mask_secret(secret: str) -> str:
    """Mask sensitive tokens showing prefix and suffix."""
    if not secret:
        return "<UNSET>"
    s = secret.strip()
    if len(s) <= 10:
        return "****"
    return f"{s[:10]}...{s[-4:]}"


def resolve_api_key() -> str:
    """Resolve API key from environment variable or local .env file."""
    api_key = os.environ.get("NVIDIA_API_KEY")
    if api_key:
        return api_key

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
                        if k.strip() == "NVIDIA_API_KEY":
                            return v.strip()
            except Exception:
                pass
    return ""


def complete_chat(
    messages,
    model=None,
    api_key=None,
    base_url=None,
    temperature=0.2,
    max_tokens=4096,
    timeout_sec=30,
):
    """Execute a chat completion request against NVIDIA Nemotron API."""
    key = api_key or resolve_api_key()
    if not key:
        raise ValueError(
            "NVIDIA_API_KEY is not configured. Set environment variable or define in .env."
        )

    endpoint = base_url or os.environ.get("NVIDIA_BASE_URL") or DEFAULT_BASE_URL
    target_model = (
        model
        or os.environ.get("NEMOTRON_DEFAULT_MODEL")
        or DEFAULT_MODEL
    )

    url = f"{endpoint.rstrip('/')}/chat/completions"
    payload = {
        "model": target_model,
        "messages": messages,
        "temperature": max(0.0, min(2.0, temperature)),
        "max_tokens": max_tokens,
        "stream": False,
    }

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
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
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


def main():
    parser = argparse.ArgumentParser(description="NVIDIA Nemotron Ultra Python Bridge")
    parser.add_argument("--prompt", required=True, help="User prompt to send to Nemotron")
    parser.add_argument(
        "--system",
        default="You are an expert AI architect and reasoning assistant.",
        help="System instruction prompt",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Target model ID")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature")
    parser.add_argument("--json", action="store_true", help="Output raw JSON response")
    args = parser.parse_args()

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
                f"\nTokens: {usage.get('prompt_tokens', 0)} prompt + {usage.get('completion_tokens', 0)} completion = {usage.get('total_tokens', 0)} total\n"
            )
    except Exception as e:
        print(f"\n[Nemotron Bridge Error]: {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
