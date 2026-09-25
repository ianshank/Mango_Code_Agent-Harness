"""Thresholds for the per-directory ``AGENTS.md`` gate; policy `agents_doc` block.

Split from :mod:`agents_doc` for the same reason :mod:`policy_defaults` was
split from :mod:`policy_loader`: the checks and the numbers they enforce grow
independently, and a module carrying both reaches
``limits.size_budget_lines`` while neither half is unreasonable on its own.
Callers keep importing whichever they need; nothing re-exports.

Every number here is a *default*, not the rule. The rule is
``governance-policy.json``. The defaults exist so a repository that has adopted
this gate without adopting the block still gets a working one -- and so a
policy that *declares* the block can be held to stating every numeric key it
owns, which is what makes a substituted threshold impossible.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

try:
    from harness.shared.policy_loader import PolicyError, _log_resolution, _Section, _section
except ImportError:  # sibling import when this dir is sys.path[0]
    from policy_loader import PolicyError, _log_resolution, _Section, _section  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

#: The policy block this module reads. Named once so an error can cite it.
POLICY_BLOCK = "agents_doc"

DEFAULT_FILENAME = "AGENTS.md"
DEFAULT_COMPANION_FILENAME = "CLAUDE.md"
DEFAULT_COMPANION_BODY = "@AGENTS.md"
#: Where Claude Code discovers project subagents. A file here whose frontmatter
#: is malformed is *silently* treated as documentation -- no error, no warning,
#: the agent simply never exists -- which is why the shape is gated at all.
DEFAULT_SUBAGENT_DIRECTORY = ".claude/agents"
DEFAULT_MAX_LINES = 150
DEFAULT_MIN_SCOPE_NAMES = 3
DEFAULT_MAX_KEY_FILES = 8
DEFAULT_MAX_DIAGRAMS = 2
DEFAULT_MAX_DIAGRAM_NODES = 40
DEFAULT_MIN_SOURCE_FILES = 3
DEFAULT_MIN_DOCUMENTED_DIRECTORIES = 20
DEFAULT_MIN_WAIVER_REASON_CHARS = 40
DEFAULT_SOURCE_EXTENSIONS = (".py", ".ts", ".kt", ".sh")
#: Build output, caches and vendored trees. Written as one string because the
#: list carries no per-entry rationale: it is the same prune set every walker
#: in this repository uses, and a column of quoted names costs ten lines of the
#: `limits.size_budget_lines` budget to say so.
DEFAULT_PRUNED_DIRECTORY_NAMES = tuple(
    ".git .venv venv node_modules __pycache__ .mypy_cache .pytest_cache .ruff_cache "
    ".gradle .artifacts htmlcov build dist".split()
)
#: Mermaid keywords accepted as a diagram's first line. A diagram that opens
#: with anything else never renders, and the failure is silent in review: the
#: block becomes an error box on GitHub, which is exactly the shape the audit
#: found in `c4_architecture.md`.
DEFAULT_DIAGRAM_TYPES = tuple(
    "flowchart graph sequenceDiagram classDiagram stateDiagram stateDiagram-v2 erDiagram "
    "journey gantt pie gitGraph mindmap timeline requirementDiagram quadrantChart "
    "C4Context C4Container C4Component C4Dynamic".split()
)

#: Environment overrides, applied above the policy and below an explicit
#: argument. Only the numeric keys are exposed: a run may need a tighter budget
#: without editing a protected policy, but no run should be able to rename the
#: file the gate looks for.
ENV_PREFIX = "AGENTS_DOC_"


@dataclass(frozen=True)
class AgentsDocConfig:
    """Resolved thresholds for one audit run.

    Frozen because an audit that could retune itself mid-run could not be
    reproduced from its own report.
    """

    filename: str = DEFAULT_FILENAME
    companion_filename: str = DEFAULT_COMPANION_FILENAME
    companion_body: str = DEFAULT_COMPANION_BODY
    subagent_directory: str = DEFAULT_SUBAGENT_DIRECTORY
    max_lines: int = DEFAULT_MAX_LINES
    min_scope_names: int = DEFAULT_MIN_SCOPE_NAMES
    max_key_files: int = DEFAULT_MAX_KEY_FILES
    max_diagrams: int = DEFAULT_MAX_DIAGRAMS
    max_diagram_nodes: int = DEFAULT_MAX_DIAGRAM_NODES
    min_source_files: int = DEFAULT_MIN_SOURCE_FILES
    min_documented_directories: int = DEFAULT_MIN_DOCUMENTED_DIRECTORIES
    min_waiver_reason_chars: int = DEFAULT_MIN_WAIVER_REASON_CHARS
    source_extensions: tuple[str, ...] = DEFAULT_SOURCE_EXTENSIONS
    pruned_directory_names: tuple[str, ...] = DEFAULT_PRUNED_DIRECTORY_NAMES
    diagram_types: tuple[str, ...] = DEFAULT_DIAGRAM_TYPES
    additional_directories: tuple[str, ...] = ()
    waived_directories: Mapping[str, str] = field(default_factory=dict)


def _escapes_checkout(value: str) -> bool:
    """True when `value` could resolve outside the directory it is joined to.

    Lexical rather than filesystem-resolved, because a configured location may
    legitimately not exist yet: `waiver_findings` reports a waiver naming a
    missing directory as a *finding*, which a load-time `resolve(strict=True)`
    would turn into a crash. Both flavours of `PurePath` are consulted because
    a policy is JSON and may be authored on either platform: `/etc` is absolute
    only to the posix parser, `C:/x` only to the Windows one, and `..\\x`
    splits into parts only for the latter.
    """
    if not value.strip():
        return True
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or value.startswith(("/", "\\")):
        return True
    # A drive without a root is *not* absolute to `PureWindowsPath`, so `C:foo`
    # passed every test above: joined to a checkout it resolves against drive
    # C's working directory, which is outside the repository by construction.
    # This also refuses a POSIX directory literally named `a:b`, which is a
    # portability hazard this repository already guards against elsewhere.
    if windows.drive:
        return True
    return ".." in posix.parts or ".." in windows.parts


def _checkout_path(key: str, value: str) -> str:
    """A configured directory, refused unless it stays inside the checkout (R-ADOC-6).

    `contains()` already refuses a path a *document* names outside its own
    directory. This is the same rule one level up, on the configuration, and it
    is the level that actually mattered: pointing `subagent_directory` at an
    empty directory elsewhere made `subagent_findings` return nothing at all,
    so the frontmatter gate reported success over a tree it had never read.
    A present policy fails closed; it does not silently audit somewhere else.
    """
    if _escapes_checkout(value):
        raise PolicyError(
            f"policy {POLICY_BLOCK}.{key} must be a path inside the checkout, got {value!r}; "
            "an absolute or escaping location points this gate at a tree it does not govern"
        )
    return value


def _bare_name(key: str, value: str) -> str:
    """A bare file name, so a lookup cannot leave its own directory (R-ADOC-6)."""
    if _escapes_checkout(value) or value in {".", ".."}:
        raise PolicyError(
            f"policy {POLICY_BLOCK}.{key} must be a bare file name, got {value!r}; "
            "a name that escapes redirects every document lookup off its own directory"
        )
    if PurePosixPath(value).parts != (value,) or PureWindowsPath(value).parts != (value,):
        raise PolicyError(
            f"policy {POLICY_BLOCK}.{key} must be a bare file name, got {value!r}; "
            "a separator makes the gate read a file the directory does not own"
        )
    return value


def _env_int(key: str) -> int | None:
    """An ``AGENTS_DOC_*`` override, or None. A non-numeric value is ignored.

    Ignored rather than raised: the environment is the least reviewed of the
    four precedence levels, and a typo there should not be able to take a whole
    CI leg down with it. The fallback is logged, so a run that quietly dropped
    to policy can still be explained afterwards.
    """
    raw = os.environ.get(f"{ENV_PREFIX}{key.upper()}")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("ignoring %s%s=%r: not an integer", ENV_PREFIX, key.upper(), raw)
        return None


def _as_str_map(value: object, key: str) -> Mapping[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(name, str) and isinstance(reason, str) for name, reason in value.items()
    ):
        raise PolicyError(f"policy {POLICY_BLOCK}.{key} must be an object of string reasons, got {value!r}")
    return dict(value)


def _resolve_number(key: str, default: int, section: _Section, declared: bool, overrides: Mapping[str, object]) -> int:
    """One threshold, under ``explicit argument > environment > policy > default``.

    Split out so the undeclared-block path runs the same three upper levels the
    declared path does. Only the bottom level differs: an undeclared block has
    no policy value to read, so it falls to the built-in default instead of
    ``_Section.int``, which would raise for a key a backed file never states.
    """
    explicit = overrides.get(key)
    if explicit is not None:
        if not isinstance(explicit, int) or isinstance(explicit, bool):
            raise PolicyError(f"{key} override must be an integer, got {explicit!r}")
        return explicit
    from_env = _env_int(key)
    if from_env is not None:
        return from_env
    return section.int(key, default) if declared else default


def load_config(policy_path: Path | None = None, **overrides: object) -> AgentsDocConfig:
    """Resolve thresholds: explicit argument > environment > policy > default.

    R-ADOC-4: every threshold is sourced from the policy rather than a
    literal. C-ADOC-1: a declared block missing a numeric key fails closed;
    an undeclared block takes the built-in defaults.

    The numeric keys go through ``_Section.int``, so a policy that declares the
    block and then drops one of them fails closed rather than substituting a
    plausible number. The string, list and map keys go through ``optional``:
    their absence is part of the schema -- an adopter with a different layout
    states its own ``additional_directories`` and waives nothing -- so "not
    declared" is a statement there, not a hole.

    A policy that predates the block entirely takes the built-in defaults for
    the *policy* level only. That branch is not a convenience: ``_section``
    marks any present *file* as backed, so without it every adopter policy
    written before this block would raise on its first numeric key -- the
    DEC-043 hazard, and the reason ``gate_floors`` carries the same guard. It
    returned early at first, which silently dropped the two levels *above* the
    policy: ``--max-lines 5`` against an adopter policy resolved to 150, so the
    documented precedence held only for deployments that had adopted the block.

    Every path-valued key is constrained to the checkout, and the two file
    names to a bare name. Unconstrained, they redirected the audit rather
    than failing it, which is the one outcome a gate must never have.

    Every threshold is also range-checked. A negative one is not a tighter
    gate, it is a disabled one: ``min_documented_directories: -1`` makes
    ``present < floor`` false for an empty tree, so the anti-vacuity check
    passes on a repository with no documents at all. A malformed number is
    refused rather than enforced.
    """
    section = _section(POLICY_BLOCK, policy_path)
    declared = section.declared()
    if not declared:
        _log_resolution(POLICY_BLOCK, {"declared": False}, policy_path)

    def number(key: str, default: int) -> int:
        resolved = _resolve_number(key, default, section, declared, overrides)
        if resolved < 0:
            raise PolicyError(
                f"policy {POLICY_BLOCK}.{key} must be zero or greater, got {resolved}; "
                "a negative threshold does not tighten this gate, it disables it"
            )
        return resolved

    def text(key: str, default: str) -> str:
        return str(section.optional(key, default))

    def names(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
        value = section.optional(key, default)
        if value is default:
            return default
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise PolicyError(f"policy {POLICY_BLOCK}.{key} must be a list of strings, got {value!r}")
        return tuple(value)

    def paths(key: str, default: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_checkout_path(key, value) for value in names(key, default))

    resolved = AgentsDocConfig(
        filename=_bare_name("filename", text("filename", DEFAULT_FILENAME)),
        companion_filename=_bare_name("companion_filename", text("companion_filename", DEFAULT_COMPANION_FILENAME)),
        companion_body=text("companion_body", DEFAULT_COMPANION_BODY),
        subagent_directory=_checkout_path("subagent_directory", text("subagent_directory", DEFAULT_SUBAGENT_DIRECTORY)),
        max_lines=number("max_lines", DEFAULT_MAX_LINES),
        min_scope_names=number("min_scope_names", DEFAULT_MIN_SCOPE_NAMES),
        max_key_files=number("max_key_files", DEFAULT_MAX_KEY_FILES),
        max_diagrams=number("max_diagrams", DEFAULT_MAX_DIAGRAMS),
        max_diagram_nodes=number("max_diagram_nodes", DEFAULT_MAX_DIAGRAM_NODES),
        min_source_files=number("min_source_files", DEFAULT_MIN_SOURCE_FILES),
        min_documented_directories=number("min_documented_directories", DEFAULT_MIN_DOCUMENTED_DIRECTORIES),
        min_waiver_reason_chars=number("min_waiver_reason_chars", DEFAULT_MIN_WAIVER_REASON_CHARS),
        source_extensions=names("source_extensions", DEFAULT_SOURCE_EXTENSIONS),
        pruned_directory_names=names("pruned_directory_names", DEFAULT_PRUNED_DIRECTORY_NAMES),
        diagram_types=names("diagram_types", DEFAULT_DIAGRAM_TYPES),
        additional_directories=paths("additional_directories", ()),
        waived_directories={
            _checkout_path("waived_directories", name): reason
            for name, reason in _as_str_map(section.optional("waived_directories", {}), "waived_directories").items()
        },
    )
    _log_resolution(POLICY_BLOCK, {"declared": declared, "max_lines": resolved.max_lines}, policy_path)
    logger.debug("%s config resolved: %s", POLICY_BLOCK, resolved)
    return resolved
