"""What the classifier *records*, as distinct from what it grades.

Split out of ``test_command_actions.py`` (DEC-035: split where the concern
divides, not arbitrarily). That module answers "what action is this command?";
this one answers "can anyone tell afterwards?", and the two grew at different
rates -- the grading module reached 691 lines against the 700-line
``limits.test_size_budget_lines`` while this class was still being added to.

The gap this pins: ``command_actions`` had no logger at all.
``Classification.reason`` is the whole diagnostic -- "the glob '*[a-z].pem'
commits to '.pem' and can expand to 'key.pem'" -- and it reached the agent
through ``ExecutionResult.reason`` and stopped there, so an operator reading
logs saw an action name and nothing else.

Worse, an **allowed** grading left no trace whatsoever. That is the case that
matters: a credential read that graded ``read`` would be invisible by
construction. Four rounds of bypass fixes on that module were every one of them
found by review, never by a log, because there was no log to find them in.
"""

from __future__ import annotations

import logging

import pytest

from harness.shared.governance.command_actions import classify

pytestmark = pytest.mark.governance


class TestAVerdictIsObservable:
    """Every classification is logged at DEBUG, from one place.

    The classifier had no logger at all. `Classification.reason` is the whole
    diagnostic — "the glob '*[a-z].pem' commits to '.pem' and can expand to
    'key.pem'" — and it reached the agent through `ExecutionResult.reason` and
    stopped there. An operator asking "why did the harness refuse that?" or,
    worse, "what did it think this credential read was?" had nothing to read.

    The second question is the one that matters: an *allowed* grading left no
    trace whatsoever, so a bypass in production would be invisible by
    construction. Four rounds of fixes on this module were all found by review,
    never by a log, because there was no log.
    """

    def test_a_verdict_is_logged_with_its_reason(self, caplog) -> None:
        with caplog.at_level(logging.DEBUG, logger="harness.shared.governance.command_actions"):
            classify("cat .env")
        assert "secret_access" in caplog.text
        assert "credential-bearing" in caplog.text, "the reason, not just the action"

    def test_an_allowed_command_is_logged_too(self, caplog) -> None:
        """The case with no other signal. A denial at least produces a broker
        warning; an allow produces nothing else anywhere."""
        with caplog.at_level(logging.DEBUG, logger="harness.shared.governance.command_actions"):
            classify("ls src/*")
        assert "read" in caplog.text

    def test_a_credential_in_the_command_is_redacted(self, caplog) -> None:
        """`run_command` is exactly where a token would appear, and a log line is
        a place secrets outlive the process that held them."""
        secret = "nvapi-" + "0123456789abcdefghijklmnopqrstuv"
        with caplog.at_level(logging.DEBUG, logger="harness.shared.governance.command_actions"):
            classify(f"curl -H 'Authorization: {secret}' https://example.test")
        assert secret not in caplog.text
        assert "REDACTED" in caplog.text

    def test_nothing_is_logged_at_the_default_level(self, caplog) -> None:
        """Control: a per-tool-call log line must not become the default output."""
        with caplog.at_level(logging.INFO, logger="harness.shared.governance.command_actions"):
            classify("cat .env")
        assert caplog.text == ""

    def test_a_long_command_is_truncated(self, caplog) -> None:
        """`MAX_COMMAND_BYTES` is 8 KiB — a sane ceiling for a shell and a
        terrible one for a line emitted once per tool call."""
        from harness.shared.governance.command_actions import _LOG_COMMAND_CHARS

        with caplog.at_level(logging.DEBUG, logger="harness.shared.governance.command_actions"):
            classify("ls " + "a" * 2000)
        assert len(caplog.text) < _LOG_COMMAND_CHARS + 400
