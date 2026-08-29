"""Decidable defect rules for a plan document, as pure functions.

Spec: ``docs/specs/plan-review-framework.md`` (R-PLR-1..R-PLR-7, C-PLR-2).

A plan has no oracle at review time -- no compiler, no suite, nothing to falsify
against. So every rule here is a *proxy* for falsifiability that a machine can
decide from the document alone, and each was calibrated against the fifteen plans
in this repository before it shipped. Three rules were wrong on first contact with
that corpus (a grammar that missed bare shell commands, a non-success vocabulary
missing bare ``fails``, and an orphan rule enforcing a convention the template
never asked for); the calibration is why they are not wrong here.

Stdlib only, no I/O: the caller reads files and decides exit codes. That keeps the
rules testable against strings and reusable by ``validate_specs`` and
``validate_plan`` alike, which is what C-PLR-2 asks for.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

#: Requirement/constraint IDs. Identical to the pattern in ``validate_specs`` and
#: ``governance.check_traceability`` -- C-PLR-2 forbids a second definition.
REQ_PATTERN = re.compile(r"\b([CR]-[A-Za-z0-9_-]+)\b")

#: Any traceable ID, acceptance criteria included. The normative-MUST rule uses
#: this rather than ``REQ_PATTERN``: an ``AC-*`` bullet containing MUST could
#: never satisfy a ``[CR]-`` pattern, so the rule was unsatisfiable for exactly
#: the bullets the template tells authors to write (NEXT_STEPS.md, R-PLR-7).
ANY_ID_PATTERN = re.compile(r"\b(?:AC|INV|DEC|[CR])-[A-Za-z0-9_-]+\b")

#: A backticked span is this corpus's own marker for "something a machine can run
#: or read" -- specs backtick commands, paths, symbols and policy keys alike. A
#: curated executable allowlist was tried first and missed ``ruff check .``,
#: ``git grep``, ``actionlint`` and ``python -m pytest``: 13 of its 20 findings
#: were that gap rather than a defect. It would also have been a hard-coded value.
CODE_SPAN = re.compile(r"`[^`]+`")

#: A named stage or test selector, which counts as an observable on its own so a
#: criterion written without backticks is not punished for formatting.
SELECTOR = re.compile(
    r"\bmake\s+[a-z][a-z0-9_-]*|\bpytest\b|\b[\w/]+\.py::\w+"
    r"|\b(?:Test[A-Z]\w+|test_\w+)\b|\bexit(?:s|ed)?\s+(?:code\s+)?-?\d+\b"
)

#: A criterion whose stated verification is a human reading it is not falsifiable,
#: however many code spans it carries. This is the template's own rule -- "No
#: criterion may be 'looks right' or 'reads well'" -- made decidable.
HUMAN_DEFERRAL = re.compile(
    r"verified by (?:review|inspection)|by inspection|\bmanually\b"
    r"|reviewer judge?ment|\bwe believe\b|\bshould (?:look|read)\b",
    re.IGNORECASE,
)

#: Non-success vocabulary. ``fail`` is matched with its inflections because the
#: first version had ``failure`` but not ``fails``, and read
#: "``test_lint_config_liveness.py`` fails when a dead pattern is present" as
#: having no failure path -- 4 of its 7 findings were that omission.
NON_SUCCESS = re.compile(
    r"\bMUST NOT\b|\braises?\b|\bdenie[sd]\b|\bdeny\b|\brejects?\b"
    r"|\bfail(?:s|ed|ing|ure)?\b|\bDENY\b|\bBLOCKED\b|\bexit 1\b|\bgoes red\b"
    r"|\bnon-zero\b|\brefuses?\b|\berrors?\b",
    re.IGNORECASE,
)

#: Phrases that assert nothing. Retained from the gate this module replaces.
BANNED_PHRASES = ("works correctly", "as expected", "appropriately")

#: Placeholder markers left by ``make spec``. Their presence means the scaffold
#: was never filled in -- previously every rule passed on an untouched copy.
TEMPLATE_MARKERS = ("R-EXAMPLE-", "C-EXAMPLE-", "<feature name>")

REQUIRED_SECTIONS = ("## Requirements", "## Acceptance criteria")

#: Sections this framework adds. Their presence is what makes a plan subject to
#: the orphan rule: requiring an ID citation from plans written against the older
#: template scored nine of eleven specs at 100% orphaned, because the template
#: never asked for the citation (R-PLR-4).
NEW_SECTION_KEYS = ("steps", "files touched")


@dataclass(frozen=True)
class Finding:
    """One defect, addressed to the thing that has to change."""

    defect_class: str
    spec: str
    ref: str
    detail: str
    remedy: str

    def render(self) -> str:
        return f"{self.spec}: [{self.defect_class}] {self.ref}: {self.detail}\n    remedy: {self.remedy}"


@dataclass(frozen=True)
class Plan:
    """A parsed plan document."""

    name: str
    text: str
    sections: Mapping[str, str]
    acceptance: tuple[str, ...]
    declared: frozenset[str]
    cited: frozenset[str]
    carries_new_sections: bool


def strip_code_spans(text: str) -> str:
    """Remove backticked spans so a phrase being *named* is not read as *used*.

    Without this the banned-phrase scan fails any document that documents the
    phrases it bans -- including this framework's own spec, which is how the
    defect was found (R-PLR-7).
    """
    return CODE_SPAN.sub(" ", text)


def split_sections(text: str) -> dict[str, str]:
    """Map lower-cased ``##`` heading -> body. Text before the first is ``_preamble``."""
    out: dict[str, str] = {}
    current = "_preamble"
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            out[current] = "\n".join(buf)
            current, buf = line[3:].strip().lower(), []
        else:
            buf.append(line)
    out[current] = "\n".join(buf)
    return out


def split_bullets(block: str) -> list[str]:
    """Bullets, each joined with its indented continuation lines.

    Criteria in this repository routinely wrap across three or four lines; reading
    them line-by-line would report a finding for every wrapped observable.
    """
    items: list[str] = []
    current: str | None = None
    for line in block.splitlines():
        if re.match(r"^\s*[-*]\s", line):
            if current is not None:
                items.append(current)
            current = line.strip()
        elif current is not None and line.strip() and line.startswith((" ", "\t")):
            current += " " + line.strip()
        elif current is not None:
            items.append(current)
            current = None
    if current is not None:
        items.append(current)
    return items


def _section(sections: Mapping[str, str], prefix: str) -> str:
    for key, body in sections.items():
        if key.startswith(prefix):
            return body
    return ""


def parse_plan(text: str, name: str) -> Plan:
    """Parse a plan document. Never raises: an unparseable plan is a *finding*."""
    sections = split_sections(text)
    acceptance_block = _section(sections, "acceptance")
    matrix = _section(sections, "validation matrix")

    declared: set[str] = set()
    for key, body in sections.items():
        if key.startswith(("requirement", "citation", "constraint")):
            for bullet in split_bullets(body):
                declared.update(REQ_PATTERN.findall(bullet))

    return Plan(
        name=name,
        text=text,
        sections=sections,
        acceptance=tuple(b for b in split_bullets(acceptance_block) if b.strip()),
        declared=frozenset(declared),
        cited=frozenset(REQ_PATTERN.findall(acceptance_block + "\n" + matrix)),
        carries_new_sections=any(
            any(key.startswith(marker) for marker in NEW_SECTION_KEYS) for key in sections
        ),
    )


def _criterion_ref(bullet: str) -> str:
    match = re.search(r"\bAC-[A-Za-z0-9_-]+", bullet)
    return match.group(0) if match else bullet.lstrip("-*[ ]x")[:40].strip()


def _has_observable(bullet: str) -> bool:
    return bool(CODE_SPAN.search(bullet) or SELECTOR.search(bullet))


def unfalsifiable_acceptance(plan: Plan) -> list[Finding]:
    """A criterion that names no observable at all (R-PLR-1)."""
    findings = []
    for bullet in plan.acceptance:
        if _has_observable(bullet):
            continue  # stage_reachability judges whether it is wired to a stage
        findings.append(
            Finding(
                defect_class="UNFALSIFIABLE_ACCEPTANCE",
                spec=plan.name,
                ref=_criterion_ref(bullet),
                detail="names no observable (no command, selector, path, exit code or policy key)",
                remedy="name the check that proves it, e.g. `pytest -k test_x` and `make <stage>`",
            )
        )
    return findings


def stage_reachability(plan: Plan) -> list[Finding]:
    """A criterion that names a check but hands it to a human (R-PLR-3).

    Distinct from ``UNFALSIFIABLE_ACCEPTANCE`` on purpose: the criterion already
    carries an observable, so telling its author to add one would be wrong. What
    is missing is the wiring -- nothing runs it.
    """
    findings = []
    for bullet in plan.acceptance:
        # The deferral is matched against prose only, for the same reason the
        # banned-phrase scan is: a criterion that *quotes* "verified by
        # inspection" as an example is naming the phrase, not deferring to a
        # human. This spec's own AC-2 does exactly that.
        if _has_observable(bullet) and HUMAN_DEFERRAL.search(strip_code_spans(bullet)):
            findings.append(
                Finding(
                    defect_class="STAGE_REACHABILITY",
                    spec=plan.name,
                    ref=_criterion_ref(bullet),
                    detail="names a check but assigns it to a human, so no stage runs it",
                    remedy="bind it to a stage (`· stage: `make <target>``) or drop the criterion",
                )
            )
    return findings


def missing_failure_path(plan: Plan) -> list[Finding]:
    """A plan whose criteria only describe success (R-PLR-2)."""
    if not plan.acceptance:
        return []
    if NON_SUCCESS.search("\n".join(plan.acceptance)):
        return []
    return [
        Finding(
            defect_class="MISSING_FAILURE_PATH",
            spec=plan.name,
            ref="## Acceptance criteria",
            detail="no criterion references a non-success outcome",
            remedy="add a criterion naming what the change rejects, denies, or fails closed on",
        )
    ]


def orphan_requirement(plan: Plan) -> list[Finding]:
    """A declared requirement no criterion cites (R-PLR-4).

    Scoped to plans carrying this framework's sections. Applied to the older
    template it scored nine of eleven specs at 100% orphaned -- measuring
    non-adoption of a convention the template never asked for, not defects.
    """
    if not plan.carries_new_sections:
        return []
    return [
        Finding(
            defect_class="ORPHAN_REQUIREMENT",
            spec=plan.name,
            ref=req,
            detail="declared but cited by no acceptance criterion or validation-matrix row",
            remedy=f"cite ({req}) from the criterion that proves it, or delete the requirement",
        )
        for req in sorted(plan.declared - plan.cited)
    ]


def required_sections(plan: Plan) -> list[Finding]:
    """The contract's mandatory headings."""
    return [
        Finding(
            defect_class="MISSING_SECTION",
            spec=plan.name,
            ref=section,
            detail="required section is absent",
            remedy=f"add a '{section}' section",
        )
        for section in REQUIRED_SECTIONS
        if section not in plan.text
    ]


def normative_must_has_id(plan: Plan) -> list[Finding]:
    """Every normative bullet carries a traceable ID."""
    findings = []
    for line in plan.text.splitlines():
        stripped = line.lstrip()
        if not stripped.startswith(("- ", "* ")) or "MUST" not in line:
            continue
        if ANY_ID_PATTERN.search(line):
            continue
        findings.append(
            Finding(
                defect_class="UNTRACEABLE_NORMATIVE",
                spec=plan.name,
                ref=stripped[:48].strip(),
                detail="normative MUST carries no requirement or criterion ID",
                remedy="give it an `R-<AREA>-<n>` / `C-<AREA>-<n>` ID, or cite the one it serves",
            )
        )
    return findings


def banned_phrases(plan: Plan) -> list[Finding]:
    """Phrases that assert nothing, ignoring any that are merely named."""
    prose = strip_code_spans(plan.text).lower()
    return [
        Finding(
            defect_class="UNFALSIFIABLE_ACCEPTANCE",
            spec=plan.name,
            ref=phrase,
            detail=f"unfalsifiable acceptance language {phrase!r}",
            remedy="replace it with the observable that would falsify the claim",
        )
        for phrase in BANNED_PHRASES
        if phrase in prose
    ]


def unfilled_template(plan: Plan) -> list[Finding]:
    """A scaffold nobody filled in.

    ``make spec`` copies the template verbatim, and every structural rule passed on
    an untouched copy: the placeholder IDs satisfy the ID patterns and the required
    headings are present (NEXT_STEPS.md, R-PLR-7).
    """
    return [
        Finding(
            defect_class="UNFILLED_TEMPLATE",
            spec=plan.name,
            ref=marker,
            detail=f"template placeholder {marker!r} was never replaced",
            remedy="fill in the scaffolded sections, or delete the spec",
        )
        for marker in TEMPLATE_MARKERS
        if marker in plan.text
    ]


def unparseable(plan: Plan) -> list[Finding]:
    """A plan the parser could not get criteria out of (R-PLR-6).

    Reported rather than skipped. A linter that silently passes what it cannot
    read is the protected-path pattern that matched zero files, in a new costume.
    """
    if "## Acceptance criteria" not in plan.text or plan.acceptance:
        return []
    return [
        Finding(
            defect_class="UNPARSEABLE_PLAN",
            spec=plan.name,
            ref="## Acceptance criteria",
            detail="section is present but no criteria could be parsed from it",
            remedy="write each criterion as a '- ' bullet under the heading",
        )
    ]


#: Every rule, in report order. A rule absent here is a rule nothing runs, so the
#: registry is asserted complete by ``test_plan_rules``.
RULES: tuple[Callable[[Plan], list[Finding]], ...] = (
    required_sections,
    unparseable,
    unfilled_template,
    unfalsifiable_acceptance,
    stage_reachability,
    missing_failure_path,
    orphan_requirement,
    normative_must_has_id,
    banned_phrases,
)


def check_plan(text: str, name: str) -> list[Finding]:
    """Run every rule against one plan document."""
    plan = parse_plan(text, name)
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(plan))
    return findings


#: The tier `make specs` has always run: shape rules that apply to every plan,
#: old template or new. Kept as its own tuple so the structural gate's contract is
#: unchanged by rules added to ``RULES`` later.
STRUCTURAL_RULES: tuple[Callable[[Plan], list[Finding]], ...] = (
    required_sections,
    unfilled_template,
    normative_must_has_id,
    banned_phrases,
)


def structural_findings(text: str, name: str) -> list[Finding]:
    """Run only the structural tier (R-PLR-7)."""
    plan = parse_plan(text, name)
    findings: list[Finding] = []
    for rule in STRUCTURAL_RULES:
        findings.extend(rule(plan))
    return findings


def structural_line(finding: Finding) -> str:
    """Render a finding in the structural tier's long-standing message shape.

    The gate's diagnostics are a contract: CI logs and ``test_validate_specs.py``
    match on these exact strings, so the wording lives here rather than being
    re-derived by each caller.
    """
    if finding.defect_class == "MISSING_SECTION":
        return f"{finding.spec}: missing {finding.ref}"
    if finding.defect_class == "UNTRACEABLE_NORMATIVE":
        return f"{finding.spec}: normative MUST has no requirement ID: {finding.ref}"
    return f"{finding.spec}: {finding.detail}"
