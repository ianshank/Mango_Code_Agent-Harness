from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.meta_tools import (
    format_gaps_for_planner,
    hypothesis_register,
    knowledge_gap_log,
    load_open_gaps,
    resolve_memory_dir,
)


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
    # And it really did poll: without this, a file_lock that raised
    # immediately would satisfy the bound above and look correct.
    assert sleeps, "the contended loop never polled"
    assert all(s == 0.01 for s in sleeps), f"unexpected poll intervals: {sorted(set(sleeps))}"


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
    entered = False
    with file_lock(tmp_path / "data.json"):
        entered = True

    # Without these the test passes even if file_lock became a no-op: assert
    # the body ran, and that the lockfile really did survive (i.e. the
    # swallowed-cleanup path was the one exercised, not an unlink that worked).
    assert entered, "the caller's block never ran"
    assert (tmp_path / "data.lock").exists(), "cleanup succeeded; the swallow path was not exercised"


def test_read_json_safe_malformed(tmp_path: Path) -> None:
    """Test reading corrupted JSON file triggers backup and reset."""
    from harness.shared.meta_tools import _read_json_safe

    target = tmp_path / "corrupted.json"
    target.write_text("{not valid json", encoding="utf-8")

    data = _read_json_safe(target)
    assert data == []
    assert target.read_text(encoding="utf-8") == "[]"
    backup_files = list(tmp_path.glob("corrupted.json.malformed.*"))
    assert len(backup_files) == 1


def test_read_json_safe_non_list(tmp_path: Path) -> None:
    """Test reading JSON that is a dict instead of list triggers reset."""
    from harness.shared.meta_tools import _read_json_safe

    target = tmp_path / "dict.json"
    target.write_text('{"key": "value"}', encoding="utf-8")

    data = _read_json_safe(target)
    assert data == []
    assert target.read_text(encoding="utf-8") == "[]"


def test_read_json_safe_rename_oserror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A backup failure on an already-malformed store must raise, not silently reset.

    Regression for a test/source drift, not an environment flake: this test
    was written against an earlier `_read_json_safe` that swallowed the
    backup ``OSError`` and reset the store to ``[]`` regardless. That was
    deliberately changed (commit 5d9554c) to raise ``RuntimeError`` and leave
    the file untouched instead -- "the only surviving copy cannot be backed
    up; preserve it rather than destroying the malformed store" -- but this
    test kept asserting the old, now-incorrect behavior, so it failed
    deterministically (reproducible on the very first local run, unrelated to
    which user pytest runs as).
    """
    from harness.shared.meta_tools import _read_json_safe

    target = tmp_path / "locked.json"
    target.write_text("invalid", encoding="utf-8")

    def mock_rename(self: Path, target: Path) -> None:
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "rename", mock_rename)
    with pytest.raises(RuntimeError, match=r"is malformed and the backup attempt failed"):
        _read_json_safe(target)

    # The unbacked-up, still-malformed original must survive untouched --
    # this is the data-loss-prevention behavior the RuntimeError exists for.
    assert target.read_text(encoding="utf-8") == "invalid"
    assert not list(tmp_path.glob("locked.json.malformed.*"))


# ---------------------------------------------------------------------------
# NS-17: retention, workspace scoping, planner surfacing
# ---------------------------------------------------------------------------


def test_knowledge_gap_retention_fifo_trim(tmp_path, monkeypatch):
    """Writing past max_gaps keeps only the newest entries (FIFO)."""
    from harness.shared import meta_tools, policy_loader

    mock_memory_dir = tmp_path / ".mango" / "memory"
    monkeypatch.setattr(meta_tools, "MEMORY_DIR", mock_memory_dir)
    monkeypatch.setattr(
        policy_loader,
        "agent_memory_defaults",
        lambda policy_path=None: {
            "max_gaps": 3,
            "max_hypotheses": 100,
            "planner_gap_limit": 10,
        },
    )

    for i in range(5):
        knowledge_gap_log(f"q{i}", f"need{i}", f"approach{i}")

    data = load_open_gaps()  # most recent first
    assert len(data) <= 3
    # FIFO: oldest q0,q1 dropped; retained q2,q3,q4 (most recent first → q4..q2)
    questions = [g["question"] for g in data]
    assert questions == ["q4", "q3", "q2"]


def test_hypothesis_retention_fifo_trim(tmp_path, monkeypatch):
    from harness.shared import meta_tools, policy_loader

    mock_memory_dir = tmp_path / ".mango" / "memory"
    monkeypatch.setattr(meta_tools, "MEMORY_DIR", mock_memory_dir)
    monkeypatch.setattr(
        policy_loader,
        "agent_memory_defaults",
        lambda policy_path=None: {
            "max_gaps": 100,
            "max_hypotheses": 3,
            "planner_gap_limit": 10,
        },
    )

    for i in range(5):
        hypothesis_register(f"claim{i}", f"reason{i}", 0.5)

    hyp_file = mock_memory_dir / "hypotheses.json"
    data = json.loads(hyp_file.read_text(encoding="utf-8"))
    assert len(data) <= 3
    assert [h["claim"] for h in data] == ["claim2", "claim3", "claim4"]


def test_memory_dir_workspace_isolation(tmp_path):
    """Two workspaces must not share stores; None keeps the legacy root."""
    ws_a = tmp_path / "a"
    ws_b = tmp_path / "b"
    ws_a.mkdir()
    ws_b.mkdir()

    knowledge_gap_log("only-a", "need-a", "approach-a", workspace_dir=ws_a)
    knowledge_gap_log("only-b", "need-b", "approach-b", workspace_dir=ws_b)

    gaps_a = load_open_gaps(ws_a)
    gaps_b = load_open_gaps(ws_b)
    assert [g["question"] for g in gaps_a] == ["only-a"]
    assert [g["question"] for g in gaps_b] == ["only-b"]

    assert resolve_memory_dir(ws_a) == ws_a / ".mango" / "memory"
    assert resolve_memory_dir(ws_b) == ws_b / ".mango" / "memory"

    # Legacy path (None) still resolves to the install-root MEMORY_DIR constant.
    from harness.shared import meta_tools

    assert resolve_memory_dir(None) == meta_tools.MEMORY_DIR


def test_format_gaps_for_planner_empty_store_ok(tmp_path):
    assert format_gaps_for_planner(workspace_dir=tmp_path / "empty-ws") == ""
    assert format_gaps_for_planner([]) == ""


def test_format_gaps_for_planner_surfaces_seeded_gap(tmp_path, monkeypatch):
    from harness.shared import policy_loader

    monkeypatch.setattr(
        policy_loader,
        "agent_memory_defaults",
        lambda policy_path=None: {
            "max_gaps": 100,
            "max_hypotheses": 100,
            "planner_gap_limit": 2,
        },
    )
    knowledge_gap_log("oldest", "n0", "a0", workspace_dir=tmp_path)
    knowledge_gap_log("middle", "n1", "a1", workspace_dir=tmp_path)
    knowledge_gap_log("newest", "n2", "a2", workspace_dir=tmp_path)

    rendered = format_gaps_for_planner(workspace_dir=tmp_path)
    assert "newest" in rendered
    assert "middle" in rendered
    assert "oldest" not in rendered  # truncated by planner_gap_limit=2
    assert rendered.index("newest") < rendered.index("middle")
