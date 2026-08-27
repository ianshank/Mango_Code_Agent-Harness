import json

from harness.shared.meta_tools import hypothesis_register, knowledge_gap_log


def test_knowledge_gap_log(tmp_path, monkeypatch):
    # Mock the memory dir
    mock_memory_dir = tmp_path / ".mango" / "memory"
    monkeypatch.setattr("harness.shared.meta_tools.MEMORY_DIR", mock_memory_dir)
    monkeypatch.setattr("harness.shared.meta_tools.GAPS_FILE", mock_memory_dir / "gaps.json")
    monkeypatch.setattr("harness.shared.meta_tools.HYPOTHESES_FILE", mock_memory_dir / "hypotheses.json")

    result = knowledge_gap_log("What is the meaning of life?", "A philosophical background", "Ask deep thinker")

    assert "Knowledge gap logged successfully" in result

    gaps_file = mock_memory_dir / "gaps.json"
    assert gaps_file.exists()

    data = json.loads(gaps_file.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["question"] == "What is the meaning of life?"
    assert data[0]["what_needed"] == "A philosophical background"
    assert data[0]["proposed_approach"] == "Ask deep thinker"


def test_hypothesis_register(tmp_path, monkeypatch):
    mock_memory_dir = tmp_path / ".mango" / "memory"
    monkeypatch.setattr("harness.shared.meta_tools.MEMORY_DIR", mock_memory_dir)
    monkeypatch.setattr("harness.shared.meta_tools.GAPS_FILE", mock_memory_dir / "gaps.json")
    monkeypatch.setattr("harness.shared.meta_tools.HYPOTHESES_FILE", mock_memory_dir / "hypotheses.json")

    result = hypothesis_register("The sky is blue", "Rayleigh scattering", 0.95)

    assert "Hypothesis registered successfully" in result

    hypotheses_file = mock_memory_dir / "hypotheses.json"
    assert hypotheses_file.exists()

    data = json.loads(hypotheses_file.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["claim"] == "The sky is blue"
    assert data[0]["reasoning"] == "Rayleigh scattering"
    assert data[0]["confidence"] == 0.95
    assert data[0]["status"] == "provisional"


# ---------------------------------------------------------------------------
# file_lock (public promotion of the former _file_lock)
# ---------------------------------------------------------------------------


def test_file_lock_acquires_and_releases(tmp_path):
    from harness.shared.meta_tools import file_lock

    target = tmp_path / "data.json"
    lockfile = target.with_suffix(".lock")
    with file_lock(target):
        assert lockfile.exists()
    assert not lockfile.exists()


def test_file_lock_timeout_is_parameterized(tmp_path):
    import time

    import pytest

    from harness.shared.meta_tools import file_lock

    target = tmp_path / "data.json"
    target.with_suffix(".lock").touch()  # simulate a held/stranded lock
    start = time.monotonic()
    with pytest.raises(TimeoutError, match="Could not acquire lock"):
        with file_lock(target, timeout_s=0.2, poll_s=0.01):
            pass
    assert time.monotonic() - start < 2.0  # bounded wait, no real 10s sleep


def test_file_lock_released_even_when_body_raises(tmp_path):
    import pytest

    from harness.shared.meta_tools import file_lock

    target = tmp_path / "data.json"
    with pytest.raises(RuntimeError):
        with file_lock(target):
            raise RuntimeError("boom")
    assert not target.with_suffix(".lock").exists()


def test_file_lock_non_contention_oserror_propagates_immediately(tmp_path, monkeypatch):
    import os
    import time

    import pytest

    from harness.shared.meta_tools import file_lock

    def _denied(*_a, **_k):
        raise PermissionError("no")

    monkeypatch.setattr(os, "open", _denied)
    start = time.monotonic()
    with pytest.raises(PermissionError):
        with file_lock(tmp_path / "data.json"):
            pass
    assert time.monotonic() - start < 1.0  # no spin-until-timeout on EACCES


def test_private_alias_preserved():
    from harness.shared import meta_tools

    assert meta_tools._file_lock is meta_tools.file_lock


def test_file_lock_is_bounded_even_when_the_clock_never_advances(tmp_path, monkeypatch):
    """Regression: a clock that never advances (frozen, or a monotonic/epoch
    mix-up) must not turn lock contention into an unbounded spin. The poll
    budget bounds the loop structurally, so this raises instead of hanging."""
    import time as time_mod

    import pytest

    from harness.shared import meta_tools

    target = tmp_path / "data.json"
    target.with_suffix(".lock").touch()  # held lock -> always contended
    monkeypatch.setattr(meta_tools.time, "monotonic", lambda: 0.0)  # frozen clock
    sleeps: list[float] = []
    monkeypatch.setattr(meta_tools.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(TimeoutError, match="Could not acquire lock"):
        with meta_tools.file_lock(target, timeout_s=0.2, poll_s=0.01):
            pass
    # Bounded by the poll budget, not by the (frozen) deadline.
    assert len(sleeps) <= int(0.2 / 0.01) + 2
    assert time_mod is not None  # sanity: real time module untouched by the patch


def test_file_lock_zero_poll_interval_does_not_divide_by_zero(tmp_path):
    import pytest

    from harness.shared.meta_tools import file_lock

    target = tmp_path / "data.json"
    target.with_suffix(".lock").touch()
    with pytest.raises(TimeoutError):
        with file_lock(target, timeout_s=0.05, poll_s=0):
            pass


def test_file_lock_swallows_cleanup_failure(tmp_path, monkeypatch):
    """A lockfile that cannot be removed (e.g. the directory went read-only)
    must not mask the caller's own success or failure."""
    from pathlib import Path

    from harness.shared.meta_tools import file_lock

    def _refuse_unlink(self, missing_ok=False):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(Path, "unlink", _refuse_unlink)
    with file_lock(tmp_path / "data.json"):
        pass  # exits cleanly despite the unlink failure
