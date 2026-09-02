"""Deprecated names still resolve, and say so (tech-debt-hardening-plan R-TDH-17, C-TDH-2).

Three compatibility exports had no first-party caller left. Deleting them would
break an adopter silently; keeping them silent would keep them forever. Each is
served for one minor release with a `DeprecationWarning`, and this module is
the only place in the suite allowed to touch them: `make ci`'s
`pytest -W error::DeprecationWarning ... -k "not deprecation_shims"` proves
nothing else does (AC-28).

Imports happen inside the tests on purpose: a module-level import would emit
the warning at collection time, where the `-W error` run would count it against
this file rather than against the shim it exercises.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.governance


class TestWritePolicy:
    def test_always_denied_prefixes_warns_and_still_matches_segments(self) -> None:
        from harness.shared import write_policy

        with pytest.warns(DeprecationWarning, match="ALWAYS_DENIED_SEGMENTS"):
            prefixes = write_policy.ALWAYS_DENIED_PREFIXES
        assert isinstance(prefixes, tuple)
        assert prefixes == tuple(f"{s}/" for s in write_policy.ALWAYS_DENIED_SEGMENTS)
        assert ".git/" in prefixes

    def test_an_unknown_name_is_still_an_attribute_error(self) -> None:
        from harness.shared import write_policy

        with pytest.raises(AttributeError):
            write_policy.NO_SUCH_NAME  # noqa: B018 - the access is the assertion


class TestNemotronBridge:
    def test_retry_backoff_base_sec_warns_and_equals_the_retry_policy_default(self) -> None:
        from harness.shared import nemotron_bridge, retry_policy

        with pytest.warns(DeprecationWarning, match="retry_policy.DEFAULT_BASE_SEC"):
            value = nemotron_bridge.RETRY_BACKOFF_BASE_SEC
        assert value == retry_policy.DEFAULT_BASE_SEC

    def test_an_unknown_name_is_still_an_attribute_error(self) -> None:
        from harness.shared import nemotron_bridge

        with pytest.raises(AttributeError):
            nemotron_bridge.NO_SUCH_NAME  # noqa: B018 - the access is the assertion


class TestToolBudget:
    def test_remaining_warns_and_is_never_negative(self) -> None:
        from harness.shared.tool_budget import ToolBudget

        budget = ToolBudget(limit=5)
        budget.consume(1)
        with pytest.warns(DeprecationWarning, match="consume"):
            assert budget.remaining == 4
        budget.consume(10)
        with pytest.warns(DeprecationWarning):
            assert budget.remaining == 0


class TestExperimentalMoves:
    """DEC-027: the old module paths warn on use and hand back the moved classes."""

    def test_autonomous_healing_old_path_warns_and_resolves(self) -> None:
        from harness.shared import autonomous_healing as old
        from harness.shared.experimental import autonomous_healing as new

        with pytest.warns(DeprecationWarning, match="experimental.autonomous_healing"):
            healer = old.TestHealer
        assert healer is new.TestHealer
        # Every access warns, not just the first: an adopter grepping their
        # own warnings sees each call site, not one.
        with pytest.warns(DeprecationWarning):
            assert old.TestHealer is new.TestHealer

    def test_lats_optimizer_old_path_warns_and_resolves(self) -> None:
        from harness.shared import lats_optimizer as old
        from harness.shared.experimental import lats_optimizer as new

        with pytest.warns(DeprecationWarning, match="experimental.lats_optimizer"):
            assert old.LATSOptimizer is new.LATSOptimizer

    def test_old_paths_import_silently(self, recwarn: pytest.WarningsRecorder) -> None:
        """Importing the shim must not warn; only using a name does (import purity)."""
        import importlib

        importlib.import_module("harness.shared.autonomous_healing")
        importlib.import_module("harness.shared.lats_optimizer")
        assert not [w for w in recwarn if issubclass(w.category, DeprecationWarning)]

    def test_unknown_names_are_attribute_errors(self) -> None:
        from harness.shared import autonomous_healing as old

        with pytest.raises(AttributeError):
            old.NO_SUCH_NAME  # noqa: B018 - the access is the assertion
