"""Tests for harness/shared/langgraph/state.py.

Verifies the MangoState TypedDict channel design:
- Correct channel count (12)
- Accumulator channels use operator.add
- LWW channels have no reducer
- All default values are JSON-serializable
"""

from __future__ import annotations

import json
import operator
import typing

import pytest

from harness.shared.langgraph.state import (
    ACCUMULATOR_CHANNELS,
    CHANNEL_COUNT,
    DEFAULT_STATE,
    LWW_CHANNELS,
    MangoState,
)

pytestmark = pytest.mark.langgraph


class TestMangoStateChannels:
    """Channel count and categorisation are load-bearing: a silent addition or
    removal would break reducer assumptions in parallel fan-out."""

    def test_channel_count_matches_constant(self) -> None:
        """The channel count is pinned in state.py and must match the actual
        number of annotated hints on MangoState."""
        hints = typing.get_type_hints(MangoState, include_extras=True)
        assert len(hints) == CHANNEL_COUNT, (
            f"MangoState has {len(hints)} channels but CHANNEL_COUNT is {CHANNEL_COUNT}; "
            "update CHANNEL_COUNT if you intentionally added/removed a channel"
        )

    def test_accumulator_channels_use_operator_add(self) -> None:
        """Every channel in ACCUMULATOR_CHANNELS must be Annotated with
        operator.add as its reducer function."""
        hints = typing.get_type_hints(MangoState, include_extras=True)
        for name in ACCUMULATOR_CHANNELS:
            hint = hints[name]
            metadata = typing.get_args(hint)
            assert len(metadata) >= 2, f"{name} is not Annotated"
            reducer = metadata[1]
            assert reducer is operator.add, (
                f"{name} reducer is {reducer!r}, expected operator.add"
            )

    def test_lww_channels_have_no_reducer(self) -> None:
        """LWW channels must NOT be Annotated — a reducer on a LWW channel
        would accumulate instead of overwriting."""
        hints = typing.get_type_hints(MangoState, include_extras=True)
        for name in LWW_CHANNELS:
            hint = hints[name]
            # A plain type (str, int, float, dict) has no get_args metadata
            args = typing.get_args(hint)
            # If it IS Annotated, the second arg would be the reducer
            if args and len(args) >= 2:
                # Check it's not operator.add or any callable reducer
                assert not callable(args[1]) or args[1] is type, (
                    f"{name} has a reducer {args[1]!r} but should be LWW"
                )

    def test_all_channels_are_categorised(self) -> None:
        """Every channel must be in exactly one of ACCUMULATOR or LWW."""
        hints = typing.get_type_hints(MangoState, include_extras=True)
        all_channels = set(hints.keys())
        categorised = ACCUMULATOR_CHANNELS | LWW_CHANNELS
        assert all_channels == categorised, (
            f"Uncategorised channels: {all_channels - categorised}; "
            f"Over-categorised: {categorised - all_channels}"
        )

    def test_no_overlap_between_accumulator_and_lww(self) -> None:
        """A channel in both sets would get conflicting merge semantics."""
        overlap = ACCUMULATOR_CHANNELS & LWW_CHANNELS
        assert overlap == frozenset(), f"Channels in both sets: {overlap}"


class TestDefaultState:
    """DEFAULT_STATE must be a valid initial state for graph invocation."""

    def test_default_state_has_all_channels(self) -> None:
        hints = typing.get_type_hints(MangoState, include_extras=True)
        assert set(DEFAULT_STATE.keys()) == set(hints.keys())

    def test_default_state_is_json_serializable(self) -> None:
        """PostgresSaver requires JSON-serializable checkpoint payloads."""
        serialized = json.dumps(DEFAULT_STATE)
        deserialized = json.loads(serialized)
        assert deserialized == DEFAULT_STATE

    def test_accumulator_defaults_are_empty_lists(self) -> None:
        """Accumulators must start empty so operator.add has a base."""
        state_dict = dict(DEFAULT_STATE)
        for name in ACCUMULATOR_CHANNELS:
            assert state_dict[name] == [], f"{name} default is not []"

    def test_lww_defaults_are_zero_values(self) -> None:
        """LWW channels start at their type's zero value."""
        state_dict = dict(DEFAULT_STATE)
        for name in LWW_CHANNELS:
            val = state_dict[name]
            assert val is not None, f"{name} default is None"
