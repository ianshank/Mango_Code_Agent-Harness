"""Hypothesis revision: the append-only supersession path (DEC-057).

Split from ``test_meta_tools.py`` when the revision suite pushed that module
past ``limits.test_size_budget_lines``. The division matches the source split:
``test_meta_tools.py`` covers the gap store, the memory-directory layout and
retention; this module covers the hypothesis lifecycle -- statuses, the
supersession graph, the confidence bound, and the observability of each.

Contract: ``docs/specs/hypothesis-revision.md`` (R-HR-1…5, C-HR-1…2).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.shared.meta_tools import hypothesis_register
from harness.shared.tests._helpers import REPO, agent_memory_policy
from harness.shared.tests._helpers import hypothesis_id_from_result as _entry_id

_agent_memory_policy = agent_memory_policy


def _hypotheses(ws: Path) -> list:
    entries: list = json.loads((ws / ".mango" / "memory" / "hypotheses.json").read_text(encoding="utf-8"))
    return entries


def test_hypothesis_revision_supersedes_prior_entry(tmp_path):
    """R-HR-1 / R-HR-2: a revision is a new entry; the prior one is kept and marked."""
    ws = tmp_path / "ws"
    ws.mkdir()
    first = hypothesis_register("cache is stale", "timestamps differ", 0.6, workspace_dir=ws)
    first_id = _entry_id(first)

    second = hypothesis_register(
        "cache is fine; the clock was wrong",
        "ntp drift confirmed",
        0.9,
        workspace_dir=ws,
        revises=first_id,
        status="retracted",
    )
    assert "registered successfully" in second
    assert f"Supersedes {first_id}" in second
    second_id = _entry_id(second)

    prior, latest = _hypotheses(ws)
    assert prior["id"] == first_id
    assert prior["claim"] == "cache is stale", "the prior text must never be edited"
    assert prior["reasoning"] == "timestamps differ"
    assert prior["confidence"] == 0.6
    # Supersession is structural: the key's presence records it, and the prior
    # entry's own status is left exactly as the model asserted it.
    assert prior["status"] == "provisional", "the prior entry's verdict must survive its revision"
    assert prior["superseded_by"] == [second_id]
    assert latest["id"] == second_id
    assert latest["revises"] == first_id
    assert latest["status"] == "retracted"
    assert "superseded_by" not in latest


def test_hypothesis_revision_with_unknown_prior_is_recorded_and_reported(tmp_path):
    """R-HR-3: a dangling pointer (trimmed or mistyped) is not an error, but the model is told."""
    ws = tmp_path / "ws"
    ws.mkdir()
    result = hypothesis_register("x", "y", 0.5, workspace_dir=ws, revises="no-such-id", status="confirmed")
    assert "registered successfully" in result
    assert "no-such-id not found" in result
    (only,) = _hypotheses(ws)
    assert only["revises"] == "no-such-id"
    assert only["status"] == "confirmed"


def test_hypothesis_register_refuses_unknown_status_and_writes_nothing(tmp_path):
    """R-HR-4: the validator does not model `enum`, so the function fails closed on status."""
    from harness.shared.tool_result_format import FAILED, tool_outcome

    ws = tmp_path / "ws"
    ws.mkdir()
    result = hypothesis_register("x", "y", 0.5, workspace_dir=ws, status="maybe")
    assert tool_outcome(result) == FAILED
    assert "not one of provisional, confirmed, retracted" in result
    # Refused before the store is touched: not even the empty file is created.
    assert not (ws / ".mango" / "memory" / "hypotheses.json").exists()


def test_hypothesis_status_defaults_to_provisional_and_accepts_settled_states(tmp_path):
    """R-HR-4 / C-HR-1: no status means what every pre-revision entry carried."""
    ws = tmp_path / "ws"
    ws.mkdir()
    hypothesis_register("a", "r", 0.5, workspace_dir=ws)
    hypothesis_register("b", "r", 0.5, workspace_dir=ws, status="confirmed")
    hypothesis_register("c", "r", 0.5, workspace_dir=ws, status="retracted")
    assert [h["status"] for h in _hypotheses(ws)] == ["provisional", "confirmed", "retracted"]
    assert all("revises" not in h for h in _hypotheses(ws)), "an unrevised entry carries no pointer"


def test_hypothesis_revision_survives_fifo_trim(tmp_path):
    """R-HR-3: the retention bound may drop the prior entry; the pointer on the revision stays."""
    policy = _agent_memory_policy(tmp_path, max_gaps=100, max_hypotheses=2, planner_gap_limit=10)
    ws = tmp_path / "ws"
    ws.mkdir()
    first_id = _entry_id(hypothesis_register("first", "r", 0.5, workspace_dir=ws, policy_path=policy))
    hypothesis_register("second", "r", 0.5, workspace_dir=ws, policy_path=policy)
    result = hypothesis_register(
        "third", "r", 0.5, workspace_dir=ws, policy_path=policy, revises=first_id, status="confirmed"
    )
    # `first` was still present when the revision was applied, so the result says so ...
    assert f"Supersedes {first_id}" in result
    # ... and then the trim dropped it; the revision keeps its pointer regardless.
    kept = _hypotheses(ws)
    assert [h["claim"] for h in kept] == ["second", "third"]
    assert kept[1]["revises"] == first_id


def test_superseded_is_not_a_model_settable_status(tmp_path, caplog):
    """R-HR-2: `superseded` records a transition the store made. A caller that
    could assert it directly could mark a live belief as revised by nothing, or
    forge a supersede without the entry that justifies it -- so it is absent
    from the settable set and refused like any other unknown status."""
    import logging

    from harness.shared import meta_tools
    from harness.shared.tool_result_format import FAILED, tool_outcome

    assert "superseded" not in meta_tools.HYPOTHESIS_STATUSES, (
        "supersession is structural (the `superseded_by` key), never a status a caller may assert"
    )
    ws = tmp_path / "ws"
    ws.mkdir()
    with caplog.at_level(logging.WARNING, logger="harness.shared.meta_tools"):
        result = hypothesis_register("c", "r", 0.5, workspace_dir=ws, status="superseded")
    assert tool_outcome(result) == FAILED
    assert "superseded" in result and "not one of" in result
    assert not (ws / ".mango" / "memory" / "hypotheses.json").exists()
    assert any("nothing written" in r.getMessage() for r in caplog.records), "a refused status must leave an audit line"


def test_revision_chain_keeps_every_link(tmp_path):
    """R-HR-1 / R-HR-2: A <- B <- C. The middle entry carries *both* pointers --
    `revises` to its ancestor and `superseded_by` to its successor -- so the
    chain can be walked in either direction and no link is overwritten."""
    ws = tmp_path / "ws"
    ws.mkdir()
    a_id = _entry_id(hypothesis_register("A", "r", 0.5, workspace_dir=ws))
    b_id = _entry_id(hypothesis_register("B", "r", 0.5, workspace_dir=ws, revises=a_id, status="retracted"))
    c_id = _entry_id(hypothesis_register("C", "r", 0.9, workspace_dir=ws, revises=b_id, status="confirmed"))

    by_claim = {h["claim"]: h for h in _hypotheses(ws)}
    assert by_claim["A"]["superseded_by"] == [b_id]
    assert "revises" not in by_claim["A"]
    # The middle link is where an in-place edit would have destroyed one of the
    # two pointers; assert both survive on the same record.
    assert by_claim["B"]["revises"] == a_id
    assert by_claim["B"]["superseded_by"] == [c_id]
    assert by_claim["C"]["revises"] == b_id
    assert "superseded_by" not in by_claim["C"], "the head of the chain supersedes nothing"


def test_a_revised_entry_keeps_the_status_its_own_evidence_produced(tmp_path):
    """Regression, R-HR-2. Supersession used to be written as
    ``prior["status"] = "superseded"``. That destroyed the one fact the store
    exists to keep: a belief registered ``confirmed`` on evidence, then later
    revised, read back as ``superseded`` and the verdict was gone -- an in-place
    lossy edit on a store the spec and DEC-057 both describe as append-only.
    Status is the model's verdict and is never overwritten; the presence of
    ``superseded_by`` is what records the revision."""
    ws = tmp_path / "ws"
    ws.mkdir()
    settled = _entry_id(hypothesis_register("B", "evidence", 0.9, workspace_dir=ws, status="confirmed"))
    hypothesis_register("C", "newer evidence", 0.8, workspace_dir=ws, revises=settled, status="retracted")

    prior = next(h for h in _hypotheses(ws) if h["id"] == settled)
    assert prior["status"] == "confirmed", "the verdict the evidence produced was overwritten"
    assert prior["superseded_by"], "the revision must still be recorded on the prior entry"


def test_two_revisions_of_one_entry_both_stay_linked(tmp_path):
    """Regression, R-HR-2. ``superseded_by`` was a scalar, so a second revision
    of the same entry overwrote the first: both revisions carried ``revises: A``
    while A pointed only at the later one, leaving the store holding two
    contradictory views of the same graph. Revision fans out -- a belief revised
    one way, then revised differently on further evidence -- and both are real,
    so the successors are a list appended in order."""
    ws = tmp_path / "ws"
    ws.mkdir()
    a_id = _entry_id(hypothesis_register("A", "r", 0.5, workspace_dir=ws))
    b_id = _entry_id(hypothesis_register("B", "r", 0.7, workspace_dir=ws, revises=a_id, status="confirmed"))
    c_id = _entry_id(hypothesis_register("C", "r", 0.2, workspace_dir=ws, revises=a_id, status="retracted"))

    a_entry = next(h for h in _hypotheses(ws) if h["id"] == a_id)
    assert a_entry["superseded_by"] == [b_id, c_id], "the first revision's link was dropped"
    # The forward and backward views must agree: everything naming A as its
    # ancestor appears in A's successor list, and nothing else does.
    backward = {h["id"] for h in _hypotheses(ws) if h.get("revises") == a_id}
    assert backward == set(a_entry["superseded_by"])


def test_revising_the_same_entry_twice_from_one_successor_does_not_duplicate(tmp_path):
    """Idempotence of the successor list under a replayed id."""
    from harness.shared import meta_tools

    ws = tmp_path / "ws"
    ws.mkdir()
    a_id = _entry_id(hypothesis_register("A", "r", 0.5, workspace_dir=ws))
    hypothesis_register("B", "r", 0.5, workspace_dir=ws, revises=a_id)
    store = ws / ".mango" / "memory" / "hypotheses.json"
    data = json.loads(store.read_text(encoding="utf-8"))
    successors = next(h for h in data if h["id"] == a_id)[meta_tools.HYPOTHESIS_SUPERSEDED_BY]
    assert len(successors) == 1
    assert len(set(successors)) == len(successors)


def test_a_scalar_superseded_by_written_by_an_older_build_is_migrated_not_lost(tmp_path):
    """The store outlives the code. An entry carrying the pre-fix scalar is
    upgraded to a list that keeps the original successor rather than dropping it."""
    from harness.shared import meta_tools

    ws = tmp_path / "ws"
    ws.mkdir()
    a_id = _entry_id(hypothesis_register("A", "r", 0.5, workspace_dir=ws))
    store = ws / ".mango" / "memory" / "hypotheses.json"
    data = json.loads(store.read_text(encoding="utf-8"))
    data[0][meta_tools.HYPOTHESIS_SUPERSEDED_BY] = "legacy-scalar-id"
    store.write_text(json.dumps(data), encoding="utf-8")

    new_id = _entry_id(hypothesis_register("B", "r", 0.5, workspace_dir=ws, revises=a_id))
    migrated = next(h for h in _hypotheses(ws) if h["id"] == a_id)[meta_tools.HYPOTHESIS_SUPERSEDED_BY]
    assert migrated == ["legacy-scalar-id", new_id]


def test_a_non_dict_entry_in_the_store_does_not_break_a_revision(tmp_path):
    """The `isinstance(prior, dict)` guard runs inside the lock; without it a
    hand-edited or partially-corrupt store raises mid-write."""
    ws = tmp_path / "ws"
    ws.mkdir()
    a_id = _entry_id(hypothesis_register("A", "r", 0.5, workspace_dir=ws))
    store = ws / ".mango" / "memory" / "hypotheses.json"
    data = json.loads(store.read_text(encoding="utf-8"))
    store.write_text(json.dumps(["junk", 42, None, *data]), encoding="utf-8")

    result = hypothesis_register("B", "r", 0.5, workspace_dir=ws, revises=a_id)
    assert "registered successfully" in result
    assert f"Supersedes {a_id}" in result


@pytest.mark.parametrize("bad", [-0.1, 1.1, 42.0])
def test_confidence_outside_the_advertised_range_is_refused(tmp_path, bad):
    """The schema advertises 0.0-1.0 and `tool_arg_validation` models neither
    `minimum` nor `maximum` -- the same gap that makes `status` hand-checked --
    so an out-of-range confidence was written verbatim and the advertised range
    was kept nowhere."""
    from harness.shared.tool_result_format import FAILED, tool_outcome

    ws = tmp_path / "ws"
    ws.mkdir()
    result = hypothesis_register("c", "r", bad, workspace_dir=ws)
    assert tool_outcome(result) == FAILED
    assert "confidence" in result
    assert not (ws / ".mango" / "memory" / "hypotheses.json").exists()


@pytest.mark.parametrize("edge", [0.0, 1.0])
def test_confidence_at_the_range_boundaries_is_accepted(tmp_path, edge):
    """The bound is inclusive: certainty and its absence are both expressible."""
    ws = tmp_path / "ws"
    ws.mkdir()
    assert "registered successfully" in hypothesis_register("c", "r", edge, workspace_dir=ws)
    assert _hypotheses(ws)[0]["confidence"] == edge


def test_whitespace_revises_is_normalised_rather_than_recorded(tmp_path):
    """`" "` is truthy, so an unnormalised pointer reached the store and rendered
    `Prior entry   not found`. Normalising in the store rather than at the door
    keeps the contract true for every caller, not just the dispatcher's."""
    ws = tmp_path / "ws"
    ws.mkdir()
    result = hypothesis_register("c", "r", 0.5, workspace_dir=ws, revises="   ")
    assert "not found" not in result
    assert "revises" not in _hypotheses(ws)[0]


def test_revision_logs_the_supersede_without_leaking_claim_text(tmp_path, caplog):
    """Observability with the same no-content rule the dispatcher's tool events
    follow (2026 standards audit H6): ids and statuses are logged, the
    model-authored claim and reasoning are not."""
    import logging

    ws = tmp_path / "ws"
    ws.mkdir()
    first = _entry_id(hypothesis_register("a secret-shaped claim", "reasoning body", 0.5, workspace_dir=ws))
    with caplog.at_level(logging.INFO, logger="harness.shared.meta_tools"):
        hypothesis_register("revised", "why", 0.8, workspace_dir=ws, revises=first, status="confirmed")
    emitted = " ".join(r.getMessage() for r in caplog.records)
    assert first in emitted and "supersedes" in emitted
    assert "a secret-shaped claim" not in emitted
    assert "reasoning body" not in emitted


def test_dangling_pointer_is_logged_as_retention_not_as_a_fault(tmp_path, caplog):
    """A trimmed ancestor is the retention bound working; it is recorded at INFO
    so a broken chain is explainable, and never at WARNING."""
    import logging

    ws = tmp_path / "ws"
    ws.mkdir()
    with caplog.at_level(logging.INFO, logger="harness.shared.meta_tools"):
        hypothesis_register("c", "r", 0.5, workspace_dir=ws, revises="gone-id")
    records = [r for r in caplog.records if "gone-id" in r.getMessage()]
    assert records, "a dangling pointer must be visible in the log"
    assert all(r.levelno == logging.INFO for r in records), "retention is not a fault"


def test_schema_rejects_a_non_string_revises_at_the_tool_boundary():
    """The store itself does not re-type-check `revises` -- the tool boundary
    does, from the same schema the model was shown, which is the repository's
    one-declaration rule (H7). Pin that the declared type is what closes this."""
    from typing import Any, cast

    from harness.shared.meta_tools import META_TOOLS_SCHEMA
    from harness.shared.tool_arg_validation import invalid_arguments_reason

    # `cast` because the schema literal is typed as a collection of str-keyed
    # values; indexing into the nested function block is what the production
    # readers (`parameter_schemas`, `_schema_argument_keys`) do too.
    functions = [cast(dict[str, Any], tool["function"]) for tool in META_TOOLS_SCHEMA]
    schema = next(f["parameters"] for f in functions if f["name"] == "hypothesis_register")
    good = {"claim": "c", "reasoning": "r", "confidence": 0.5, "revises": "abc", "status": "confirmed"}
    assert invalid_arguments_reason(schema, good) is None

    reason = invalid_arguments_reason(schema, {**good, "revises": 123})
    assert reason == "argument 'revises' must be string, got integer"
    reason = invalid_arguments_reason(schema, {**good, "status": ["confirmed"]})
    assert reason == "argument 'status' must be string, got array"
    # The closure still holds with the two new properties declared.
    assert invalid_arguments_reason(schema, {**good, "branchId": "x"}) == "unexpected argument 'branchId'"


def test_prompt_builders_read_hypotheses_only_through_the_bounded_formatter():
    """C-HS-1 (`docs/specs/hypothesis-surfacing.md`), which supersedes C-HR-2.

    Phase 1 pinned that no prompt builder read the store at all. Phase 2
    (DEC-058) surfaces open hypotheses to the reasoner, so the invariant
    narrows: a prompt builder may reach the store through
    `format_hypotheses_for_reasoner` -- bounded by policy in count and in
    estimated tokens -- and through nothing else. The unbounded readers stay
    out because an unbounded read is exactly the prompt cost DEC-057 deferred.

    A call-graph check rather than a substring scan, for the reasons the
    phase-1 version gave: a comment mentioning a reader must pass, and a third
    prompt builder must be graded without being named here. The check itself is
    `hypothesis_reader_violations`, shared with the negative test below so the
    fixture that proves it non-vacuous trips the *same* function.
    """
    from harness.shared.tests._helpers import (
        BOUNDED_HYPOTHESIS_FORMATTER,
        hypothesis_reader_violations,
        prompt_building_modules,
    )

    builders = prompt_building_modules()
    assert {path.name for path in builders} >= {"agent_prompts.py", "loop.py", "nodes.py"}, (
        f"discovery must find every known prompt builder, found {sorted(p.name for p in builders)}"
    )
    violations = [violation for path in builders for violation in hypothesis_reader_violations(path)]
    assert not violations, f"unbounded hypothesis readers in prompt builders: {violations}"
    # Control: the one permitted path is actually taken, so the pin is not
    # passing on a loop that reads nothing.
    loop_source = (REPO / "harness" / "shared" / "orchestrator" / "loop.py").read_text(encoding="utf-8")
    assert BOUNDED_HYPOTHESIS_FORMATTER in loop_source


def test_the_bounded_formatter_pin_rejects_a_violating_module(tmp_path):
    """AC-HS-12's non-vacuity proof: the same function, over a module that violates it."""
    from harness.shared.tests._helpers import UNBOUNDED_HYPOTHESIS_READERS, hypothesis_reader_violations

    importer = tmp_path / "importing_prompt.py"
    importer.write_text(
        "from harness.shared.memory_view import format_hypotheses_for_review\n"
        "def build(): return format_hypotheses_for_review()\n",
        encoding="utf-8",
    )
    aliased_caller = tmp_path / "aliased_prompt.py"
    aliased_caller.write_text(
        "from harness.shared import memory_view\ndef build(): return memory_view.load_hypotheses()\n",
        encoding="utf-8",
    )
    compliant = tmp_path / "compliant_prompt.py"
    compliant.write_text(
        "from harness.shared.memory_view import format_hypotheses_for_reasoner\n"
        "# a comment naming load_hypotheses must not trip the pin\n"
        "def build(): return format_hypotheses_for_reasoner()\n",
        encoding="utf-8",
    )

    # The two bypasses the first version of the pin missed (review finding L3).
    getattr_caller = tmp_path / "getattr_prompt.py"
    getattr_caller.write_text(
        'from harness.shared import memory_view as mv\ndef build(): return getattr(mv, "load_hypotheses")()\n',
        encoding="utf-8",
    )
    reference_holder = tmp_path / "reference_prompt.py"
    reference_holder.write_text(
        "from harness.shared import memory_view\nreader = memory_view.successors_of\ndef build(): return reader({})\n",
        encoding="utf-8",
    )

    assert hypothesis_reader_violations(importer) == [
        "importing_prompt.py imports format_hypotheses_for_review",
        "importing_prompt.py calls format_hypotheses_for_review()",
    ]
    assert hypothesis_reader_violations(aliased_caller) == ["aliased_prompt.py calls load_hypotheses()"]
    assert hypothesis_reader_violations(getattr_caller) == ["getattr_prompt.py names load_hypotheses in a string"]
    assert hypothesis_reader_violations(reference_holder) == ["reference_prompt.py references successors_of"]
    assert hypothesis_reader_violations(compliant) == []
    assert "format_hypotheses_for_reasoner" not in UNBOUNDED_HYPOTHESIS_READERS


def test_no_field_of_a_prior_entry_changes_except_its_successor_list(tmp_path):
    """The invariant both shipped defects violated, stated once.

    An append-only store may add to a prior record and may never alter what it
    already said. The status overwrite and the scalar `superseded_by` were two
    symptoms of breaking that; enumerating symptoms catches the two we thought
    of, so this asserts the property instead and catches the next one too.

    Deliberately snapshots the *whole* record and compares byte-for-byte with a
    single key excused, rather than checking named fields -- a field added later
    is then covered without anyone remembering to extend this test.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    for claim, status in (("A", "confirmed"), ("B", "retracted"), ("C", "provisional")):
        hypothesis_register(claim, f"why {claim}", 0.75, workspace_dir=ws, status=status)
    before = {e["id"]: json.dumps(e, sort_keys=True) for e in _hypotheses(ws)}
    target = next(iter(before))

    hypothesis_register("D", "new evidence", 0.1, workspace_dir=ws, revises=target, status="retracted")

    for entry in _hypotheses(ws):
        if entry["id"] not in before:
            continue  # the revision itself
        without_successors = {k: v for k, v in entry.items() if k != "superseded_by"}
        assert json.dumps(without_successors, sort_keys=True) == before[entry["id"]], (
            f"revision altered prior entry {entry['id']} beyond its successor list"
        )
    revised = next(e for e in _hypotheses(ws) if e["id"] == target)
    assert revised["superseded_by"], "the one permitted change did not happen"


def test_the_cross_record_update_runs_while_the_store_lock_is_held(tmp_path):
    """The deterministic guard for concurrent revision.

    A threading test cannot pin this: `threading.Barrier` only synchronises
    entry into the writer, so after release either thread may run to completion
    before the other is scheduled and the assertions pass on a serial execution.
    Measured, that shape caught a deliberately lock-less implementation in
    roughly two runs out of three -- a coin flip, not a guard.

    What actually makes concurrent revision safe is that the read of the prior
    record and the write of its pointer happen inside the same lock. That is
    checkable directly and without a race: the callback asserts the lockfile
    exists while it runs, so an implementation that moved the mutation outside
    the lock fails this every time.
    """
    from harness.shared.memory_store import append_locked

    store = tmp_path / "store.json"
    store.write_text("[]", encoding="utf-8")
    observed: list[bool] = []

    def _before(entries: list) -> None:
        observed.append(store.with_suffix(".lock").exists())

    append_locked(store, {"id": "x"}, 10, label="probe", before_append=_before)

    assert observed == [True], "before_append ran outside the store lock"
    assert not store.with_suffix(".lock").exists(), "the lock outlived the write"


def test_the_cross_record_update_sees_writes_from_earlier_calls(tmp_path):
    """The other half of the same property: the callback is handed the store as
    it currently is, not a list read before the lock was taken. A revision that
    saw stale entries would fail to find a prior written moments earlier."""
    from harness.shared.memory_store import append_locked

    store = tmp_path / "store.json"
    store.write_text("[]", encoding="utf-8")
    append_locked(store, {"id": "first"}, 10, label="probe")

    seen: list[list] = []
    append_locked(store, {"id": "second"}, 10, label="probe", before_append=lambda e: seen.append([x["id"] for x in e]))
    assert seen == [["first"]]


def test_a_raising_before_append_writes_nothing_and_frees_the_lock(tmp_path):
    """A callback is caller code and may raise. The store must be unchanged and
    the lock released, or one bad revision would wedge every later writer."""
    from harness.shared.memory_store import append_locked

    store = tmp_path / "store.json"
    store.write_text('[{"id": "keep"}]', encoding="utf-8")

    def _boom(entries: list) -> None:
        entries.clear()  # prove even a mutation before the raise is not persisted
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        append_locked(store, {"id": "new"}, 10, label="probe", before_append=_boom)

    assert json.loads(store.read_text(encoding="utf-8")) == [{"id": "keep"}]
    assert not store.with_suffix(".lock").exists(), "a raising callback stranded the lock"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_confidence_is_refused(tmp_path, bad):
    """R-HR-6 for the values that reach the tool by an accident of JSON.

    ``NaN`` and ``Infinity`` are not valid JSON, but ``json.loads`` accepts the
    literals by default -- and ``_normalize_tool_arguments`` uses the default.
    They then pass ``tool_arg_validation`` (both are genuine ``float``s, and the
    validator models ``type`` only), so a model emitting
    ``{"confidence": NaN}`` reaches this function with a non-finite value.

    The guard refuses them because it is written as the chained comparison
    ``not _CONFIDENCE_MIN <= confidence <= _CONFIDENCE_MAX``: every comparison
    against NaN is False, so the chain is False and the negation refuses. The
    obvious-looking rewrite ``if confidence < MIN or confidence > MAX`` would
    **accept** NaN for exactly the same reason. That is why this is pinned
    rather than left to the range test above.
    """
    from harness.shared.tool_result_format import FAILED, tool_outcome

    ws = tmp_path / "ws"
    ws.mkdir()
    result = hypothesis_register("c", "r", bad, workspace_dir=ws)
    assert tool_outcome(result) == FAILED
    assert "confidence" in result
    assert not (ws / ".mango" / "memory" / "hypotheses.json").exists()


def test_a_revision_under_disabled_retention_still_reports_its_pointer(tmp_path):
    """R-HR-3 at the retention floor. The result is built before the
    retention-disabled early return, so a revision made when nothing can be
    kept still tells the model whether its pointer resolved -- previously that
    branch returned first and dropped the note entirely."""
    policy = _agent_memory_policy(tmp_path, max_gaps=100, max_hypotheses=0, planner_gap_limit=10)
    ws = tmp_path / "ws"
    ws.mkdir()
    result = hypothesis_register("c", "r", 0.5, workspace_dir=ws, policy_path=policy, revises="some-id")
    assert "not retained" in result.lower() or "retention disabled" in result.lower()
    assert "some-id" in result, "a revision must report its pointer even when nothing is kept"
    assert "nothing was kept" in result, "the result must not claim a pointer is kept when the bound is zero"
    assert "the pointer is kept" not in result
    assert json.loads((ws / ".mango" / "memory" / "hypotheses.json").read_text(encoding="utf-8")) == []


def test_a_boolean_confidence_is_refused_like_the_schema_door_refuses_it(tmp_path):
    """`True` equals 1 and so satisfies the range check, and would be stored as
    JSON `true`. `tool_arg_validation` already refuses a boolean for a `number`
    field, so accepting one here would leave the store's contract weaker than
    the door's for any direct caller."""
    from harness.shared.tool_result_format import FAILED, tool_outcome

    ws = tmp_path / "ws"
    ws.mkdir()
    result = hypothesis_register("c", "r", True, workspace_dir=ws)
    assert tool_outcome(result) == FAILED
    assert not (ws / ".mango" / "memory" / "hypotheses.json").exists()


def test_a_store_that_vanishes_before_the_lock_is_treated_as_empty(tmp_path):
    """`_ensure_memory_files` creates the store, but a cleaned workspace or a
    concurrent removal can delete it before the lock is taken. An absent store
    is an empty one; raising would surface as a `RAISED` outcome on one door and
    an exception to library callers, where every other failure is a readable
    string."""
    from harness.shared.memory_store import _read_json_safe

    assert _read_json_safe(tmp_path / "never-existed.json") == []


def test_a_store_whose_directory_vanishes_is_recreated_not_raised(tmp_path):
    """Regression for a review-bot finding: the "vanishes before the lock"
    recovery covered the store *file* but not its *directory*.

    `_read_json_safe` treats an absent file as an empty store, but that never
    ran when the directory had gone -- `file_lock` opens `<store>.lock` beside
    the store and raised `FileNotFoundError` first. Confirmed against the
    pre-fix code, which raised here.
    """
    import shutil

    from harness.shared.memory_store import append_locked

    memory = tmp_path / "memory"
    memory.mkdir()
    store = memory / "hypotheses.json"
    store.write_text("[]", encoding="utf-8")
    shutil.rmtree(memory)

    kept = append_locked(store, {"id": "x"}, 10, label="probe")
    assert kept == [{"id": "x"}]
    assert json.loads(store.read_text(encoding="utf-8")) == [{"id": "x"}]


def test_a_whole_workspace_removed_mid_run_does_not_break_the_tool(tmp_path):
    """The same fault through the public door rather than the primitive."""
    import shutil

    ws = tmp_path / "ws"
    ws.mkdir()
    hypothesis_register("first", "r", 0.5, workspace_dir=ws)
    shutil.rmtree(ws / ".mango")

    assert "registered successfully" in hypothesis_register("after", "r", 0.5, workspace_dir=ws)
    assert [h["claim"] for h in _hypotheses(ws)] == ["after"]
