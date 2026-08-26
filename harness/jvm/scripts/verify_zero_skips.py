"""Backward-compatible shim for verify_zero_skips."""
from harness.shared.governance.verify_zero_skips import main as verify_zero_skips_main

if __name__ == "__main__":
    verify_zero_skips_main()
