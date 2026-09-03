"""The INV-2 zero-skip gate: evidence handling and waiver semantics.

The `unique_id_glob` cases moved to `test_verify_zero_skips_glob_waivers.py`
when this module reached 684 lines against a 700-line budget — sixteen from a
red gate on the next test added, in the suite for the invariant most likely to
gain one. The runner and fixture both halves share live in `_zero_skip_harness`.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.shared.tests._zero_skip_harness import run_script, test_files

# `test_files` is imported for pytest to resolve as a fixture in this module, not
# called directly; ruff cannot see that use, hence the explicit re-export.
__all__ = ["run_script", "test_files"]


def test_all_passed_returns_zero(tmp_path, test_files):
    test_files["v_json"] = str(tmp_path / "vitest_pass.json")
    Path(test_files["v_json"]).write_text(
        json.dumps(
            {
                "testResults": [
                    {
                        "name": "some.test.ts",
                        "assertionResults": [{"title": "My test", "status": "passed"}],
                    }
                ]
            }
        )
    )

    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode == 0


def test_skipped_test_fails(tmp_path, test_files):
    test_files["v_json"] = str(tmp_path / "vitest_skip.json")
    Path(test_files["v_json"]).write_text(
        json.dumps(
            {
                "testResults": [
                    {
                        "name": "other.test.ts",
                        "assertionResults": [{"title": "Other test", "status": "skipped"}],
                    }
                ]
            }
        )
    )

    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "unapproved Vitest skip" in res.stderr


def test_waivered_skip_allowed(tmp_path, test_files):
    test_files["v_json"] = str(tmp_path / "vitest_waiver.json")
    Path(test_files["v_json"]).write_text(
        json.dumps(
            {
                "testResults": [
                    {
                        "name": "some.test.ts",
                        "assertionResults": [{"title": "My test", "status": "skipped"}],
                    }
                ]
            }
        )
    )

    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode == 0


def test_invalid_waiver_rejected(tmp_path, test_files):
    Path(test_files["waivers"]).write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "vitest",
                        "file": "some.test.ts",
                        "test": "My test",
                        "decision_id": "UNKNOWN-999",
                        "reason": "Wait for API",
                        "owner": "test",
                        "expires": "2099-12-31",
                    }
                ]
            }
        )
    )

    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "unknown decision UNKNOWN-999" in res.stderr


def test_missing_json_fails_closed(tmp_path, test_files):
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            str(tmp_path / "does-not-exist.json"),
        ],
    )
    assert res.returncode != 0


def test_malformed_json_fails_closed(tmp_path, test_files):
    test_files["v_json"] = str(tmp_path / "vitest_bad.json")
    Path(test_files["v_json"]).write_text("not json")

    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0


def test_empty_results_passes(tmp_path, test_files):
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode == 0


def test_multiple_skips_all_reported(tmp_path, test_files):
    test_files["v_json"] = str(tmp_path / "vitest_skip.json")
    Path(test_files["v_json"]).write_text(
        json.dumps(
            {
                "testResults": [
                    {
                        "name": "other.test.ts",
                        "assertionResults": [
                            {"title": "Other test 1", "status": "skipped"},
                            {"title": "Other test 2", "status": "todo"},
                        ],
                    }
                ]
            }
        )
    )

    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "Other test 1" in res.stderr
    assert "Other test 2" in res.stderr


# --- Coverage gap tests ---
def test_decision_log_missing(tmp_path, test_files):
    res = run_script(
        Path("."),
        [
            "--decision-log",
            str(tmp_path / "missing.md"),
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "decision log missing/unreadable or contains no IDs" in res.stderr


def test_waiver_cannot_read(test_files, tmp_path):
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            str(tmp_path / "missing.json"),
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "cannot read waiver registry" in res.stderr


def test_malformed_waiver_entry(test_files):
    Path(test_files["waivers"]).write_text(json.dumps({"waivers": [{}]}))
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "malformed waiver entry" in res.stderr


def test_unsupported_framework(test_files):
    Path(test_files["waivers"]).write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "mocha",
                        "decision_id": "DEC-123",
                        "reason": "a",
                        "owner": "a",
                        "expires": "2099-12-31",
                    }
                ],
            }
        )
    )
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "unsupported waiver framework" in res.stderr


def test_vitest_missing_file_test(test_files):
    Path(test_files["waivers"]).write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "vitest",
                        "decision_id": "DEC-123",
                        "reason": "a",
                        "owner": "a",
                        "expires": "2099-12-31",
                    }
                ],
            }
        )
    )
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "Vitest waiver requires exact file and test" in res.stderr


def test_a_junit_waiver_missing_its_address_is_rejected_before_any_evidence_is_read(test_files):
    """The registry is validated on load, so a malformed waiver fails whatever evidence runs.

    Named for what it asserts. It was `test_junit_missing_fields`, which read as a test about
    JUnit evidence — and it passes `--vitest-json`, with no JUnit events involved at all. The
    subject is a *waiver* declaring `framework: junit` without the fields that say which node
    id it addresses; rejecting that at load time is why the evidence format is irrelevant.
    """
    Path(test_files["waivers"]).write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "junit",
                        "decision_id": "DEC-123",
                        "reason": "a",
                        "owner": "a",
                        "expires": "2099-12-31",
                    }
                ],
            }
        )
    )
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "JUnit waiver requires test and exactly one of unique_id / unique_id_glob" in res.stderr


def test_invalid_expiry(test_files):
    Path(test_files["waivers"]).write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "vitest",
                        "file": "f",
                        "test": "t",
                        "decision_id": "DEC-123",
                        "reason": "a",
                        "owner": "a",
                        "expires": "invalid",
                    }
                ],
            }
        )
    )
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "invalid expiry 'invalid'" in res.stderr


def test_expired_waiver(test_files):
    Path(test_files["waivers"]).write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "vitest",
                        "file": "f",
                        "test": "t",
                        "decision_id": "DEC-123",
                        "reason": "a",
                        "owner": "a",
                        "expires": "2000-01-01",
                    }
                ],
            }
        )
    )
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--vitest-json",
            test_files["v_json"],
        ],
    )
    assert res.returncode != 0
    assert "expired waiver for f::t" in res.stderr


def test_no_test_evidence(test_files):
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
        ],
    )
    assert res.returncode != 0
    assert "no test evidence supplied; refusing a vacuous pass" in res.stderr


# --- JUnit tests ---
def test_junit_evidence_missing(test_files, tmp_path):
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--junit-events",
            str(tmp_path / "missing.events"),
        ],
    )
    assert res.returncode != 0
    assert "JUnit skip evidence missing" in res.stderr


def test_junit_waivered_allowed(test_files):
    Path(test_files["waivers"]).write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "junit",
                        "unique_id": "id1",
                        "test": "t",
                        "decision_id": "DEC-123",
                        "reason": "a",
                        "owner": "a",
                        "expires": "2099-12-31",
                    }
                ],
            }
        )
    )
    Path(test_files["j_events"]).write_text("id1\tt\tskip DEC-123")
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--junit-events",
            test_files["j_events"],
        ],
    )
    assert res.returncode == 0


def test_junit_unapproved_skip(test_files):
    Path(test_files["waivers"]).write_text(
        json.dumps(
            {
                "waivers": [
                    {
                        "framework": "junit",
                        "unique_id": "id1",
                        "test": "t",
                        "decision_id": "DEC-123",
                        "reason": "a",
                        "owner": "a",
                        "expires": "2099-12-31",
                    }
                ],
            }
        )
    )
    Path(test_files["j_events"]).write_text("id2\tt2\tno reason\nshortline")
    res = run_script(
        Path("."),
        [
            "--decision-log",
            test_files["log"],
            "--waivers",
            test_files["waivers"],
            "--junit-events",
            test_files["j_events"],
        ],
    )
    assert res.returncode != 0
    assert "unapproved JUnit skip" in res.stderr


