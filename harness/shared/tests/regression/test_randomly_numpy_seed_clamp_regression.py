"""Regression: pytest-randomly + thinc must not crash on hashed seeds >= 2**32.

``thinc.util.fix_random_seed`` registers as a ``pytest_randomly.random_seeder``
and calls ``numpy.random.seed(seed)`` without clamping. With
``--randomly-seed=2192051406`` the derived per-test seed ``5917428844`` raised
``ValueError: Seed must be between 0 and 2**32 - 1`` at setup for hundreds of
tests. Root ``conftest.pytest_configure`` clamps ``numpy.random.seed``; this
pin proves the clamp holds.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.governance


def test_numpy_random_seed_accepts_hashed_randomly_seeds() -> None:
    # Hard import (not importorskip): numpy is pinned in requirements-dev.txt so
    # CI installs it; a soft-skip here would fail INV-2 without a DEC waiver.
    import numpy as np

    # The exact overflow observed under --randomly-seed=2192051406.
    overflow = 5917428844
    assert overflow >= 2**32
    np.random.seed(overflow)  # must not raise after conftest clamp
    np.random.seed(overflow % (2**32))  # in-range still works
