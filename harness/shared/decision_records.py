"""Decision-record schema helpers (stdlib-only).

Records live under ``docs/decisions/DEC-*.md`` with YAML frontmatter. The
committed ``index.md`` / ``index.json`` are derived; validators fail on drift.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_FM_KEYS = ("id", "status", "date", "supersedes", "owners")
REQUIRED_SECTIONS = ("Context", "Decision", "Consequences")
ALLOWED_STATUSES = frozenset({"accepted", "superseded", "deprecated", "proposed"})
DEC_FILE_RE = re.compile(r"^DEC-\d+\.md$")
FM_BOUNDARY = re.compile(r"^---\s*$", re.M)


@dataclass(frozen=True)
class DecisionRecord:
    path: Path
    meta: dict[str, Any]
    body: str

    @property
    def id(self) -> str:
        return str(self.meta["id"])

    @property
    def status(self) -> str:
        return str(self.meta["status"])


def find_decisions_dir(workspace: Path) -> Path | None:
    """Locate ``docs/decisions`` from a stack workspace or any parent."""
    start = workspace.resolve()
    for base in (start, *start.parents):
        candidate = base / "docs" / "decisions"
        if candidate.is_dir():
            return candidate
        if base.parent == base:
            break
    return None


def _parse_scalar(raw: str) -> Any:
    text = raw.strip()
    if text in ("null", "~", ""):
        return None
    if text in ("true", "false"):
        return text == "true"
    if text.startswith("[") and text.endswith("]"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            inner = text[1:-1].strip()
            if not inner:
                return []
            return [p.strip().strip("'\"") for p in inner.split(",")]
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        try:
            return json.loads(text) if text.startswith('"') else text[1:-1]
        except json.JSONDecodeError:
            return text[1:-1]
    return text


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse a minimal YAML frontmatter block; body is the remainder."""
    if not text.startswith("---"):
        raise ValueError("missing YAML frontmatter opening ---")
    match = FM_BOUNDARY.search(text, 3)
    if not match:
        raise ValueError("missing YAML frontmatter closing ---")
    fm_text = text[3 : match.start()]
    body = text[match.end() :].lstrip("\n")
    meta: dict[str, Any] = {}
    for line in fm_text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"frontmatter line missing ':': {line!r}")
        key, raw = line.split(":", 1)
        meta[key.strip()] = _parse_scalar(raw)
    return meta, body


def load_record(path: Path) -> DecisionRecord:
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    return DecisionRecord(path=path, meta=meta, body=body)


def iter_decision_files(decisions_dir: Path) -> list[Path]:
    return sorted(p for p in decisions_dir.iterdir() if p.is_file() and DEC_FILE_RE.match(p.name))


def load_all(decisions_dir: Path) -> list[DecisionRecord]:
    return [load_record(p) for p in iter_decision_files(decisions_dir)]


def validate_record(record: DecisionRecord) -> list[str]:
    """Return human-readable problems for one record (empty = ok)."""
    fail: list[str] = []
    meta = record.meta
    for key in REQUIRED_FM_KEYS:
        if key not in meta or meta[key] in (None, ""):
            fail.append(f"{record.path.name}: missing frontmatter field '{key}'")
    status = meta.get("status")
    if status is not None and status not in ALLOWED_STATUSES:
        fail.append(f"{record.path.name}: invalid status {status!r}")
    expected_name = f"{meta.get('id', '')}.md"
    if meta.get("id") and record.path.name != expected_name:
        fail.append(f"{record.path.name}: filename does not match id {meta.get('id')}")
    supersedes = meta.get("supersedes", [])
    if supersedes is None:
        fail.append(f"{record.path.name}: supersedes must be a list (use [])")
    elif not isinstance(supersedes, list):
        fail.append(f"{record.path.name}: supersedes must be a list")
    else:
        for item in supersedes:
            if not isinstance(item, str) or not re.fullmatch(r"DEC-\d+", item):
                fail.append(f"{record.path.name}: supersedes entry not a DEC id: {item!r}")
    owners = meta.get("owners")
    if owners is not None and (not isinstance(owners, list) or not owners):
        fail.append(f"{record.path.name}: owners must be a non-empty list")
    for section in REQUIRED_SECTIONS:
        if not re.search(rf"^## {re.escape(section)}\s*$", record.body, re.M):
            fail.append(f"{record.path.name}: missing '## {section}' section")
    return fail


def index_payload(records: list[DecisionRecord]) -> dict[str, Any]:
    rows = []
    for record in sorted(records, key=lambda r: r.id):
        meta = record.meta
        rows.append(
            {
                "id": record.id,
                "status": record.status,
                "date": meta.get("date"),
                "title": meta.get("title") or record.id,
                "path": f"docs/decisions/{record.path.name}",
                "supersedes": meta.get("supersedes") or [],
                "superseded_by": meta.get("superseded_by"),
                "owners": meta.get("owners") or [],
            }
        )
    return {"decisions": rows}


def render_index_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def render_index_md(payload: dict[str, Any]) -> str:
    lines = [
        "# Decision records",
        "",
        "Generated from `docs/decisions/DEC-*.md`. Do not edit by hand;",
        "regenerate via `python harness/shared/generate_decision_index.py`.",
        "",
        "| ID | Date | Status | Title |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["decisions"]:
        title = str(row["title"]).replace("|", "\\|")
        lines.append(f"| [{row['id']}]({row['id']}.md) | {row['date']} | {row['status']} | {title} |")
    lines.append("")
    return "\n".join(lines)


def render_thin_decision_log(payload: dict[str, Any]) -> str:
    lines = [
        "# Governance Decision Log",
        "",
        "> **Moved.** Source of truth is [`docs/decisions/`](../../../docs/decisions/).",
        "> This file is a thin ID index for `--decision-log` consumers",
        "> (`verify_zero_skips`, `check_projections`). Do not add pipe-delimited entries.",
        "",
        "Known decision IDs:",
        "",
    ]
    for row in payload["decisions"]:
        lines.append(f"- {row['id']}")
    lines.append("")
    return "\n".join(lines)


def skill_duplicates_decision_text(skill_text: str) -> list[str]:
    """Detect lockstep restatements of decision bodies inside the skill."""
    # Local bound (not an operational policy limit): skill pointers stay short.
    max_skill_dec_line_chars = 100
    fail: list[str] = []
    section = re.search(
        r"^## Decisions since \d{4}-\d{2}-\d{2}\s*$(.*?)(?=^## |\Z)",
        skill_text,
        re.M | re.S,
    )
    if not section:
        return fail
    body = section.group(1)
    for line in body.splitlines():
        m = re.match(r"^- (DEC-\d+)\s*[—\-:]?\s*(.*)$", line.strip())
        if not m:
            continue
        rest = m.group(2).strip()
        if len(rest) > max_skill_dec_line_chars:
            fail.append(
                f"governance skill restates {m.group(1)} in {len(rest)} chars "
                f"(max {max_skill_dec_line_chars}); point at docs/decisions instead"
            )
    return fail
