from __future__ import annotations

import contextlib
import json
import runpy
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest


def run_script(project_root: Path, args: list[str]) -> subprocess.CompletedProcess:
    """Execute verify_zero_skips.py in-process via runpy for coverage tracking."""
    old_argv = sys.argv
    try:
        sys.argv = ["verify_zero_skips.py"] + (args or [])
        script = project_root / "harness" / "shared" / "verify_zero_skips.py"

        stdout = StringIO()
        stderr = StringIO()
        returncode = 0

        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                runpy.run_path(str(script), run_name="__main__")
        except SystemExit as e:
            if isinstance(e.code, int):
                returncode = e.code
            elif e.code is None:
                returncode = 0
            else:
                returncode = 1
                stderr.write(str(e.code))
        except Exception as e:  # noqa: BLE001 — intentional catch-all for arbitrary script failures
            returncode = 1
            stderr.write(str(e))

        return subprocess.CompletedProcess(
            args=sys.argv,
            returncode=returncode,
            stdout=stdout.getvalue(),
            stderr=stderr.getvalue(),
        )
    finally:
        sys.argv = old_argv


@pytest.fixture
def test_files(tmp_path: Path):
    d_log = tmp_path / "decision-log.md"
    d_log.write_text("Decision DEC-123\n")

    waivers = tmp_path / "waivers.json"
    waivers.write_text(json.dumps({
        "waivers": [
            {
                "framework": "vitest",
                "file": "some.test.ts",
                "test": "My test",
                "decision_id": "DEC-123",
                "reason": "Wait for API",
                "owner": "test",
                "expires": "2099-12-31",
            }
        ]
    }))

    v_json = tmp_path / "vitest.json"
    v_json.write_text(json.dumps({"testResults": []}))

    j_events = tmp_path / "junit.events"
    j_events.write_text("")

    return {
        "log": str(d_log),
        "waivers": str(waivers),
        "v_json": str(v_json),
        "j_events": str(j_events),
    }


def test_all_passed_returns_zero(tmp_path, test_files):
    test_files["v_json"] = str(tmp_path / "vitest_pass.json")
    Path(test_files["v_json"]).write_text(json.dumps({
        "testResults": [{
            "name": "some.test.ts",
            "assertionResults": [{"title": "My test", "status": "passed"}],
        }]
    }))

    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode == 0

def test_skipped_test_fails(tmp_path, test_files):
    test_files["v_json"] = str(tmp_path / "vitest_skip.json")
    Path(test_files["v_json"]).write_text(json.dumps({
        "testResults": [{
            "name": "other.test.ts",
            "assertionResults": [{"title": "Other test", "status": "skipped"}],
        }]
    }))

    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "unapproved Vitest skip" in res.stderr

def test_waivered_skip_allowed(tmp_path, test_files):
    test_files["v_json"] = str(tmp_path / "vitest_waiver.json")
    Path(test_files["v_json"]).write_text(json.dumps({
        "testResults": [{
            "name": "some.test.ts",
            "assertionResults": [{"title": "My test", "status": "skipped"}],
        }]
    }))

    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode == 0

def test_invalid_waiver_rejected(tmp_path, test_files):
    Path(test_files["waivers"]).write_text(json.dumps({
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
    }))

    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "unknown decision UNKNOWN-999" in res.stderr

def test_missing_json_fails_closed(tmp_path, test_files):
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", str(tmp_path / "does-not-exist.json"),
    ])
    assert res.returncode != 0

def test_malformed_json_fails_closed(tmp_path, test_files):
    test_files["v_json"] = str(tmp_path / "vitest_bad.json")
    Path(test_files["v_json"]).write_text("not json")

    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0

def test_empty_results_passes(tmp_path, test_files):
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode == 0

def test_multiple_skips_all_reported(tmp_path, test_files):
    test_files["v_json"] = str(tmp_path / "vitest_skip.json")
    Path(test_files["v_json"]).write_text(json.dumps({
        "testResults": [{
            "name": "other.test.ts",
            "assertionResults": [
                {"title": "Other test 1", "status": "skipped"},
                {"title": "Other test 2", "status": "todo"},
            ],
        }]
    }))

    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "Other test 1" in res.stderr
    assert "Other test 2" in res.stderr


# --- Coverage gap tests ---
def test_decision_log_missing(tmp_path, test_files):
    res = run_script(Path("."), [
        "--decision-log", str(tmp_path / "missing.md"),
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "decision log missing/unreadable or contains no IDs" in res.stderr

def test_waiver_cannot_read(test_files, tmp_path):
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", str(tmp_path / "missing.json"),
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "cannot read waiver registry" in res.stderr

def test_malformed_waiver_entry(test_files):
    Path(test_files["waivers"]).write_text(json.dumps({"waivers": [{}]}))
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "malformed waiver entry" in res.stderr

def test_unsupported_framework(test_files):
    Path(test_files["waivers"]).write_text(json.dumps({
        "waivers": [{"framework": "mocha", "decision_id": "DEC-123", "reason": "a", "owner": "a", "expires": "2099-12-31"}],
    }))
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "unsupported waiver framework" in res.stderr

def test_vitest_missing_file_test(test_files):
    Path(test_files["waivers"]).write_text(json.dumps({
        "waivers": [{"framework": "vitest", "decision_id": "DEC-123", "reason": "a", "owner": "a", "expires": "2099-12-31"}],
    }))
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "Vitest waiver requires exact file and test" in res.stderr

def test_junit_missing_fields(test_files):
    Path(test_files["waivers"]).write_text(json.dumps({
        "waivers": [{"framework": "junit", "decision_id": "DEC-123", "reason": "a", "owner": "a", "expires": "2099-12-31"}],
    }))
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "JUnit waiver requires exact unique_id and test" in res.stderr

def test_invalid_expiry(test_files):
    Path(test_files["waivers"]).write_text(json.dumps({
        "waivers": [{"framework": "vitest", "file": "f", "test": "t", "decision_id": "DEC-123", "reason": "a", "owner": "a", "expires": "invalid"}],
    }))
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "invalid expiry 'invalid'" in res.stderr

def test_expired_waiver(test_files):
    Path(test_files["waivers"]).write_text(json.dumps({
        "waivers": [{"framework": "vitest", "file": "f", "test": "t", "decision_id": "DEC-123", "reason": "a", "owner": "a", "expires": "2000-01-01"}],
    }))
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--vitest-json", test_files["v_json"],
    ])
    assert res.returncode != 0
    assert "expired waiver for f::t" in res.stderr

def test_no_test_evidence(test_files):
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
    ])
    assert res.returncode != 0
    assert "no test evidence supplied; refusing a vacuous pass" in res.stderr


# --- JUnit tests ---
def test_junit_evidence_missing(test_files, tmp_path):
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--junit-events", str(tmp_path / "missing.events"),
    ])
    assert res.returncode != 0
    assert "JUnit skip evidence missing" in res.stderr

def test_junit_waivered_allowed(test_files):
    Path(test_files["waivers"]).write_text(json.dumps({
        "waivers": [{"framework": "junit", "unique_id": "id1", "test": "t", "decision_id": "DEC-123", "reason": "a", "owner": "a", "expires": "2099-12-31"}],
    }))
    Path(test_files["j_events"]).write_text("id1\tt\tskip DEC-123")
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--junit-events", test_files["j_events"],
    ])
    assert res.returncode == 0

def test_junit_unapproved_skip(test_files):
    Path(test_files["waivers"]).write_text(json.dumps({
        "waivers": [{"framework": "junit", "unique_id": "id1", "test": "t", "decision_id": "DEC-123", "reason": "a", "owner": "a", "expires": "2099-12-31"}],
    }))
    Path(test_files["j_events"]).write_text("id2\tt2\tno reason\nshortline")
    res = run_script(Path("."), [
        "--decision-log", test_files["log"],
        "--waivers", test_files["waivers"],
        "--junit-events", test_files["j_events"],
    ])
    assert res.returncode != 0
    assert "unapproved JUnit skip" in res.stderr
