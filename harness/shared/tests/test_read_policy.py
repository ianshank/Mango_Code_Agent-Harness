"""Tests for harness/shared/read_policy.py -- the runtime read gate.

Spec: ``docs/specs/agent-read-patch-tools.md`` (R-RPT-2, R-RPT-3).
"""

from __future__ import annotations

import pytest

from harness.shared.read_policy import (
    CREDENTIAL_FILENAME_ALTERNATION,
    CREDENTIAL_FILENAME_PATTERN,
    read_denial_reason,
)

pytestmark = pytest.mark.governance

#: One representative per credential family the classifier already refuses
#: through `run_command`. If any stops being denied here, `read_file` becomes a
#: second door onto the credential the first door refuses.
CREDENTIAL_PATHS = [
    ".env",
    ".env.local",
    ".env.production",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "id_rsa",
    "id_dsa",
    "server.pem",
    "keys/id_rsa",
    "config/secrets.pem",
]

#: Files that share a prefix with something denied but are ordinary content.
#: `.gitignore` and `.gitleaks.toml` are the exact trap segment-matching exists
#: for; a prefix check would deny both.
LOOKS_DENIED_BUT_IS_NOT = [
    ".gitignore",
    ".gitleaks.toml",
    ".gitattributes",
    "notenv",
    "environment.py",
    "prod.pem.txt",
    "harness/shared/tool_schemas.py",
    "docs/specs/agent-containment.md",
]


class TestCredentialsAreDenied:
    @pytest.mark.parametrize("path", CREDENTIAL_PATHS)
    def test_credential_path_is_denied(self, path: str) -> None:
        reason = read_denial_reason(path)
        assert reason is not None, f"{path} was readable"
        assert "credential-bearing" in reason

    def test_a_credential_directory_segment_is_denied(self) -> None:
        """Every segment is matched, not only the filename: a `.env` directory
        holds the same secret one level up."""
        assert read_denial_reason("secrets/.env/note.txt") is not None


class TestOrdinaryFilesStayReadable:
    @pytest.mark.parametrize("path", LOOKS_DENIED_BUT_IS_NOT)
    def test_ordinary_path_is_permitted(self, path: str) -> None:
        assert read_denial_reason(path) is None, f"{path} was denied"

    def test_a_protected_path_is_still_readable(self) -> None:
        """The read policy deliberately does not mirror `protected_paths`. The
        agent has to read the Makefile and the policies to do its work."""
        assert read_denial_reason("Makefile") is None
        assert read_denial_reason("harness/shared/governance-policy.json") is None


class TestGitDirectoryIsDenied:
    @pytest.mark.parametrize("path", [".git/config", ".git/HEAD", "sub/.git/config"])
    def test_git_internals_are_denied(self, path: str) -> None:
        reason = read_denial_reason(path)
        assert reason is not None, f"{path} was readable"
        assert ".git directory" in reason


class TestPathShape:
    def test_absolute_path_is_denied(self) -> None:
        assert "absolute path" in (read_denial_reason("/etc/passwd") or "")

    def test_traversal_is_denied(self) -> None:
        assert "climbs out" in (read_denial_reason("../../etc/passwd") or "")

    def test_dot_prefixed_paths_are_not_mangled(self) -> None:
        """`lstrip("./")` would turn `./.env` into `env` and read as permitted."""
        assert read_denial_reason("./.env") is not None

    def test_a_plain_relative_path_is_permitted(self) -> None:
        assert read_denial_reason("./harness/shared/read_policy.py") is None


class TestThePatternIsOneDefinition:
    def test_the_alternation_composes_into_the_anchored_pattern(self) -> None:
        """`command_actions` builds its command-scanning form from the same
        alternation. If these drift, the two doors disagree."""
        assert CREDENTIAL_FILENAME_ALTERNATION in CREDENTIAL_FILENAME_PATTERN.pattern

    def test_the_anchored_pattern_matches_whole_segments_only(self) -> None:
        assert CREDENTIAL_FILENAME_PATTERN.match(".env")
        assert not CREDENTIAL_FILENAME_PATTERN.match("dotenv")
        assert not CREDENTIAL_FILENAME_PATTERN.match(".env.local.bak.txt")
