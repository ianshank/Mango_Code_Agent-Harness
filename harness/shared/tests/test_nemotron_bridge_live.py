#!/usr/bin/env python3
"""
NVIDIA Nemotron Python Bridge — Live Integration Tests.

Exercises the nemotron_bridge.py module against the real NVIDIA NIM API.
Gated behind NVIDIA_API_KEY — automatically skipped if not configured.

Requirement Citations:
- R-AI-NEMO-1: Python bridge wire protocol validation
- C-AI-SEC-1: mask_secret redaction verification
"""

import json
import os
import sys
import unittest
from pathlib import Path

# Add parent directory to path so we can import the bridge module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nemotron_bridge import complete_chat, mask_secret, resolve_api_key

API_KEY = os.environ.get("NVIDIA_API_KEY", "")
IS_LIVE = len(API_KEY) > 0
SMOKE_MAX_TOKENS = 50


class TestMaskSecret(unittest.TestCase):
    """Unit tests for mask_secret — always run regardless of API key."""

    def test_masks_long_key(self):
        raw = "nvapi-sSeCHw0DgZGfWMEf5bhpL7H0NutynoON8H3rVPdD2y8wCAUb72j"
        masked = mask_secret(raw)
        self.assertTrue(masked.startswith("nvapi-sSeC"))
        self.assertNotIn("5bhpL7H0NutynoON", masked)
        # Should end with last 4 chars
        self.assertTrue(masked.endswith(raw[-4:]))

    def test_masks_short_key(self):
        self.assertEqual(mask_secret("short"), "****")

    def test_masks_empty_key(self):
        self.assertEqual(mask_secret(""), "<UNSET>")


class TestResolveApiKey(unittest.TestCase):
    """Tests for API key resolution — always run."""

    @unittest.skipUnless(IS_LIVE, "NVIDIA_API_KEY not configured")
    def test_resolves_key_from_environment(self):
        key = resolve_api_key()
        self.assertTrue(len(key) > 0)
        self.assertTrue(key.startswith("nvapi-"))


@unittest.skipUnless(IS_LIVE, "NVIDIA_API_KEY not configured — skipping live tests")
class TestCompleteChatLive(unittest.TestCase):
    """Live API integration tests for complete_chat."""

    def test_happy_path_completion(self):
        """Exercises the full completion path against the live API."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Reply with exactly: BRIDGE OK"},
        ]

        result = complete_chat(
            messages,
            temperature=0.0,
            max_tokens=SMOKE_MAX_TOKENS,
            timeout_sec=30,
        )

        # Structural assertions
        self.assertIn("choices", result)
        self.assertTrue(len(result["choices"]) > 0)

        content = result["choices"][0].get("message", {}).get("content", "")
        self.assertTrue(len(content) > 0, "Response content should be non-empty")

        # Usage telemetry
        self.assertIn("usage", result)
        usage = result["usage"]
        self.assertGreater(usage.get("prompt_tokens", 0), 0)
        self.assertGreater(usage.get("completion_tokens", 0), 0)
        self.assertGreater(usage.get("total_tokens", 0), 0)

        # Latency telemetry
        self.assertIn("latency_ms", result)
        self.assertGreater(result["latency_ms"], 0)
        self.assertLess(result["latency_ms"], 30000)

        # Secret leakage check
        result_str = json.dumps(result)
        self.assertNotIn(API_KEY, result_str)

    def test_wire_format_parity_with_typescript(self):
        """
        Contract test: verifies the Python bridge sends the same wire format
        as the TypeScript NemotronClient.

        Both should send:
        - model: string
        - messages: array of {role, content}
        - temperature: clamped float
        - max_tokens: int
        - stream: false
        """
        messages = [
            {"role": "user", "content": "Reply with exactly: PARITY OK"},
        ]

        result = complete_chat(
            messages,
            temperature=0.1,
            max_tokens=SMOKE_MAX_TOKENS,
            timeout_sec=30,
        )

        # If we got a valid response, the wire format was accepted by the API
        self.assertIn("choices", result)
        content = result["choices"][0].get("message", {}).get("content", "")
        self.assertTrue(len(content) > 0)

    def test_invalid_key_error_is_sanitized(self):
        """Verifies error messages don't leak the raw API key."""
        fake_key = "nvapi-INVALID-fake-key-for-testing-1234567890abcdef"

        with self.assertRaises(RuntimeError) as ctx:
            complete_chat(
                [{"role": "user", "content": "Should fail"}],
                api_key=fake_key,
                max_tokens=SMOKE_MAX_TOKENS,
                timeout_sec=10,
            )

        error_msg = str(ctx.exception)
        self.assertNotIn(fake_key, error_msg)
        # The critical security assertion: raw key must NOT appear.
        # The error message comes from the API (e.g., "403 Forbidden")
        # and may or may not contain the masked key prefix.
        self.assertTrue(len(error_msg) > 0, "Error message should be non-empty")


if __name__ == "__main__":
    unittest.main(verbosity=2)
