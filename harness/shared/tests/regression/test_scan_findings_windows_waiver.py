"""AQA-002: Regression pin for DEC-061 waiver covering TestScanFindings (RCA-2).

TestScanFindings uses #!/bin/sh stubs that cannot execute on Windows.
This regression test asserts the DEC-061 waiver entry covering that class
is present, schema-valid, and not expired.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]
WAIVERS_PATH = REPO / "harness" / "shared" / "tests" / "skip-waivers.json"
TARGET_GLOB = "harness/shared/tests/test_check_secret_allowlist.py::TestScanFindings::*"
TARGET_DEC = "DEC-061"


def _load_waivers() -> list[dict[str, Any]]:
    if not WAIVERS_PATH.exists():
        pytest.fail(f"skip-waivers.json not found at {WAIVERS_PATH}")
    raw = json.loads(WAIVERS_PATH.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    # Standard schema: {"schema_version": ..., "waivers": [...]}
    waivers = raw.get("waivers", [])
    if not isinstance(waivers, list):
        pytest.fail(f"skip-waivers.json 'waivers' key is not a list, got {type(waivers).__name__}")
    return waivers


def _find_scan_findings_waiver(waivers: list[dict[str, Any]]) -> dict[str, Any] | None:
    for entry in waivers:
        glob = entry.get("unique_id_glob", "")
        dec = entry.get("decision_id", "")
        if "TestScanFindings" in glob and dec == TARGET_DEC:
            return entry
    return None


def test_scan_findings_waiver_exists() -> None:
    """A DEC-061 waiver for TestScanFindings must exist in skip-waivers.json (RCA-2 fix)."""
    waivers = _load_waivers()
    waiver = _find_scan_findings_waiver(waivers)
    assert waiver is not None, (
        f"No DEC-061 waiver found for TestScanFindings in {WAIVERS_PATH}. "
        "TestScanFindings::* uses #!/bin/sh stubs that fail on Windows (RCA-2). "
        f"Expected a waiver with unique_id_glob matching {TARGET_GLOB!r} "
        f"and decision_id={TARGET_DEC!r}."
    )


def test_scan_findings_waiver_has_required_fields() -> None:
    """The DEC-061 waiver must contain all required schema fields."""
    waivers = _load_waivers()
    waiver = _find_scan_findings_waiver(waivers)
    if waiver is None:
        pytest.skip("No DEC-061 waiver found (test_scan_findings_waiver_exists will catch this)")

    required_fields = {"framework", "unique_id_glob", "decision_id", "reason", "owner", "expires"}
    missing = required_fields - set(waiver.keys())
    assert not missing, f"DEC-061 waiver for TestScanFindings is missing required fields: {sorted(missing)}"


def test_scan_findings_waiver_not_expired() -> None:
    """The DEC-061 waiver expiry must be in the future."""
    waivers = _load_waivers()
    waiver = _find_scan_findings_waiver(waivers)
    if waiver is None:
        pytest.skip("No DEC-061 waiver found (test_scan_findings_waiver_exists will catch this)")

    expires_str = waiver.get("expires", "")
    try:
        expires = date.fromisoformat(expires_str)
    except (ValueError, TypeError):
        pytest.fail(f"DEC-061 waiver 'expires' field {expires_str!r} is not a valid ISO date (YYYY-MM-DD)")

    today = datetime.now(timezone.utc).date()
    assert expires > today, (
        f"DEC-061 waiver for TestScanFindings expired on {expires}. "
        "Update the waiver expiry or remove the skip if the underlying issue is resolved."
    )


def test_scan_findings_waiver_glob_covers_class() -> None:
    """The waiver glob must cover all TestScanFindings test methods."""
    waivers = _load_waivers()
    waiver = _find_scan_findings_waiver(waivers)
    if waiver is None:
        pytest.skip("No DEC-061 waiver found (test_scan_findings_waiver_exists will catch this)")

    glob = waiver.get("unique_id_glob", "")
    assert "TestScanFindings" in glob, f"Waiver glob {glob!r} does not cover TestScanFindings class"
    assert glob.endswith(("::*", "*")), f"Waiver glob {glob!r} should use a wildcard suffix to cover all test methods"
