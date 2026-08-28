"""Unit tests for conversation-history redaction and debug dumping.

The behaviour under test is a safety property, so these lean on the awkward
cases: no key anywhere, a key only in the environment, a key that reached the
history from a source nobody tracked, and non-string payloads.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from harness.shared.debug_dump import (
    CREDENTIAL_PATTERN,
    DUMP_DIR_MODE,
    REDACTED,
    dump_enabled,
    redact_history,
    redact_text,
    resolve_credentials,
    write_dump,
)


class TestResolveCredentials:
    def test_explicit_key_comes_first(self) -> None:
        assert resolve_credentials("explicit", {"NVIDIA_API_KEY": "from-env"}) == ["explicit", "from-env"]

    def test_environment_is_read_even_without_an_explicit_key(self) -> None:
        """The defect this module exists for: the orchestrator normally passes
        None, and the old code then redacted nothing at all."""
        assert resolve_credentials(None, {"NVIDIA_API_KEY": "from-env"}) == ["from-env"]

    def test_no_credentials_anywhere(self) -> None:
        assert resolve_credentials(None, {}) == []

    def test_duplicates_are_collapsed(self) -> None:
        assert resolve_credentials("same", {"NVIDIA_API_KEY": "same"}) == ["same"]

    def test_empty_values_are_ignored(self) -> None:
        assert resolve_credentials("", {"NVIDIA_API_KEY": ""}) == []

    def test_falls_back_to_the_process_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NVIDIA_API_KEY", "ambient")
        assert "ambient" in resolve_credentials()


class TestRedactText:
    def test_known_literal_is_replaced(self) -> None:
        assert redact_text("before secret after", ["secret"]) == f"before {REDACTED} after"

    def test_provider_shaped_token_is_replaced_without_being_known(self) -> None:
        assert redact_text("used nvapi-abcdefgh12345678 here") == f"used {REDACTED} here"

    def test_every_occurrence_is_replaced(self) -> None:
        assert redact_text("k k k", ["k"]).count(REDACTED) == 3

    def test_ordinary_text_is_untouched(self) -> None:
        assert redact_text("nothing sensitive here", ["absent"]) == "nothing sensitive here"

    def test_empty_secret_does_not_shred_the_string(self) -> None:
        """``"".join`` semantics would otherwise insert the marker between
        every character."""
        assert redact_text("hello", [""]) == "hello"

    @pytest.mark.parametrize("token", ["nvapi-12345678", "nvapi-" + "z" * 60])
    def test_pattern_matches_realistic_tokens(self, token: str) -> None:
        assert CREDENTIAL_PATTERN.fullmatch(token)

    @pytest.mark.parametrize("text", ["nvapi-short", "napi-abcdefgh12345", "nvapi"])
    def test_pattern_does_not_match_near_misses(self, text: str) -> None:
        assert not CREDENTIAL_PATTERN.fullmatch(text)


class TestRedactHistory:
    def test_all_string_fields_are_covered_not_just_content(self) -> None:
        """A redactor that covers one field is a redactor that can be routed
        around: tool names and ids are model-influenced too."""
        secret = "sk-live-credential"
        history = [{"role": "assistant", "name": secret, "content": secret, "tool_call_id": secret}]
        assert redact_history(history, secret, env={}) == [
            {"role": "assistant", "name": REDACTED, "content": REDACTED, "tool_call_id": REDACTED}
        ]

    def test_a_short_credential_redacts_aggressively_by_design(self) -> None:
        """A one-character key shreds ordinary prose. That is the safe
        direction -- over-redacting a debug dump costs legibility, while
        under-redacting it leaks a credential -- and real keys are long.
        Pinned so the behaviour is a decision rather than a surprise.
        """
        assert redact_history([{"content": "assistant"}], "s", env={})[0]["content"].count(REDACTED) == 3

    def test_nested_lists_and_dicts_are_walked(self) -> None:
        secret = "sk-nested-credential"
        history = [{"content": {"outer": [secret, {"inner": secret}]}}]
        assert redact_history(history, secret, env={})[0]["content"] == {
            "outer": [REDACTED, {"inner": REDACTED}]
        }

    def test_non_string_values_survive_unchanged(self) -> None:
        history = [{"content": None, "count": 3, "ok": True, "score": 1.5}]
        assert redact_history(history, "sk-x", env={})[0] == {
            "content": None, "count": 3, "ok": True, "score": 1.5
        }

    def test_the_input_is_not_mutated(self) -> None:
        history = [{"content": "sk-original"}]
        redact_history(history, "sk-original", env={})
        assert history[0]["content"] == "sk-original"

    def test_empty_history(self) -> None:
        assert redact_history([], "sk-x", env={}) == []


class TestDumpEnabled:
    @pytest.mark.parametrize(("value", "expected"), [("1", True), ("0", False), ("true", False), ("", False)])
    def test_only_the_exact_opt_in_counts(self, value: str, expected: bool) -> None:
        assert dump_enabled({"MANGO_DEBUG_DUMP": value}) is expected

    def test_absent_flag_is_off(self) -> None:
        assert dump_enabled({}) is False


class TestWriteDump:
    def test_returns_none_when_disabled(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MANGO_DEBUG_DUMP", raising=False)
        assert write_dump([{"content": "x"}], "agent", dump_root=tmp_path / "d") is None

    def test_writes_redacted_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MANGO_DEBUG_DUMP", "1")
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        target = write_dump([{"content": "hold my secret"}], "planner", "secret", dump_root=tmp_path / "d")
        assert target is not None
        assert json.loads(target.read_text(encoding="utf-8"))[0]["content"] == f"hold my {REDACTED}"

    def test_directory_is_owner_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MANGO_DEBUG_DUMP", "1")
        root = tmp_path / "d"
        write_dump([], "planner", dump_root=root)
        assert stat.S_IMODE(root.stat().st_mode) == DUMP_DIR_MODE

    def test_a_pre_existing_lax_directory_is_tightened(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``mkdir``'s mode argument is ignored when the directory exists, so a
        leftover from an earlier, laxer run would keep its permissions."""
        monkeypatch.setenv("MANGO_DEBUG_DUMP", "1")
        root = tmp_path / "d"
        root.mkdir(mode=0o777)
        write_dump([], "planner", dump_root=root)
        assert stat.S_IMODE(root.stat().st_mode) == DUMP_DIR_MODE

    def test_filename_identifies_the_agent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MANGO_DEBUG_DUMP", "1")
        target = write_dump([], "verifier", dump_root=tmp_path / "d")
        assert target is not None and target.name.startswith("debug_verifier_")

    def test_an_unwritable_destination_is_logged_not_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A debugging aid must never be the reason an agent run dies."""
        monkeypatch.setenv("MANGO_DEBUG_DUMP", "1")
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("i am a file", encoding="utf-8")
        with caplog.at_level("WARNING"):
            assert write_dump([], "planner", dump_root=blocker / "sub") is None
        assert "Could not write debug dump" in caplog.text


class TestEveryCredentialEnvVarIsCovered:
    """`main.py` returns the conversation history over HTTP through
    `redact_history`, and the reviewed list covered only NVIDIA_API_KEY. Anything
    a tool echoed from the other two left the process in clear text."""

    def test_api_server_key_is_scrubbed(self):
        secrets = resolve_credentials(None, {"API_SERVER_KEY": "server-key-value"})
        assert redact_text("header X-API-Key: server-key-value", secrets) == f"header X-API-Key: {REDACTED}"

    def test_evidence_signing_key_is_scrubbed(self):
        """Leaking this one is an escalation, not a disclosure: it is the HMAC key
        EvidenceBuilder signs with, so holding it lets an attacker forge the
        manifests INV-7 and INV-13 rest on."""
        secrets = resolve_credentials(None, {"AGENT_EVIDENCE_KEY": "evidence-hmac-key"})
        assert REDACTED in redact_text("AGENT_EVIDENCE_KEY=evidence-hmac-key", secrets)

    def test_a_credential_named_variable_is_swept_without_editing_this_module(self):
        secrets = resolve_credentials(None, {"SOME_NEW_PROVIDER_TOKEN": "swept-token-value"})
        assert "swept-token-value" in secrets

    def test_a_non_credential_variable_is_not_swept(self):
        assert resolve_credentials(None, {"NEMOTRON_DEFAULT_MODEL": "some-model-name"}) == []

    def test_a_short_swept_value_is_ignored(self):
        """`redact_text` replaces by substring, so a swept variable set to "1"
        would rewrite every "1" in the history."""
        assert resolve_credentials(None, {"DEBUG_TOKEN": "1"}) == []


class TestProviderShapes:
    """Shapes catch a credential that arrived by a route we do not control -- a
    tool echoing it, a model pasting it back -- where value-equality cannot."""

    def test_shapes_are_redacted(self):
        for token in (
            "ctx7sk-abcdefgh12345678",
            "ghp_abcdefghijklmnopqrstuvwxyz012345",
            "github_pat_abcdefghijklmnopqrstuv1234",
            "AKIAIOSFODNN7EXAMPLE",
            "-----BEGIN RSA PRIVATE KEY-----",
        ):
            assert REDACTED in redact_text(f"leaked {token} here"), f"{token!r} survived redaction"

    def test_bearer_header_is_redacted(self):
        assert REDACTED in redact_text("Authorization: Bearer abcdef.ghijkl.mnopqr")

    def test_ordinary_text_is_untouched(self):
        text = "the model wrote a function called make_key and a token parser"
        assert redact_text(text) == text


class TestRedactionOrderingIsLoadBearing:
    """Regression for a defect found by probing rather than reading.

    `redact_text` replaces by substring in list order. When one credential is a
    prefix of another -- two keys sharing an issuer prefix, or a truncated copy of
    the same key -- replacing the shorter first consumed its head and left the
    remainder of the longer one in clear text: `<REDACTED_API_KEY>efgh5678`.
    """

    COLLIDING = {"API_SERVER_KEY": "abcd1234", "AGENT_EVIDENCE_KEY": "abcd1234efgh5678"}

    def test_the_longer_credential_is_redacted_first(self):
        assert resolve_credentials(None, self.COLLIDING) == ["abcd1234efgh5678", "abcd1234"]

    def test_no_tail_of_a_longer_credential_survives(self):
        secrets = resolve_credentials(None, self.COLLIDING)
        out = redact_text("token abcd1234efgh5678 here", secrets)
        assert "efgh5678" not in out, "the tail of the longer credential leaked"
        assert out == f"token {REDACTED} here"

    def test_both_credentials_are_still_redacted_independently(self):
        secrets = resolve_credentials(None, self.COLLIDING)
        assert redact_text("short abcd1234 only", secrets) == f"short {REDACTED} only"

    def test_equal_length_values_keep_their_declared_order(self):
        """`sorted` is stable, so the reviewed list still leads."""
        got = resolve_credentials("explicit", {"NVIDIA_API_KEY": "from-env"})
        assert got == ["explicit", "from-env"]
