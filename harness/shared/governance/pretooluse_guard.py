#!/usr/bin/env python3
"""Fail-closed first-pass shell guard for Git push/public-repo actions.
The authoritative agent control is an external tool broker/PDP. This guard is
fast local enforcement and delegates destination decisions to remotes.py.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

DANGER = re.compile(r"\bgit\b[^\n]*\bpush\b|\bgh\b[^\n]*\brepo\b[^\n]*\bcreate\b[^\n]*--public\b", re.I)
UNMODELED = re.compile(r"`|\$\(|\bGIT_CONFIG_(?:COUNT|KEY_[0-9]+|VALUE_[0-9]+)\b")

#: PreToolUse block code. Claude Code treats 2 as "deny the tool call" and 1 as a
#: non-blocking error, so a denial that returns 1 is read as a broken hook rather
#: than a policy verdict. Named so no return site restates the number.
BLOCK_EXIT = 2
ALLOW_EXIT = 0

#: Envelope keys that may carry the tool payload. ``tool_input`` is the Claude Code
#: PreToolUse shape. ``args`` is the shape ``MangoMASOrchestrator`` sent, which this
#: guard read as an absent key and therefore evaluated as the empty string -- a
#: silent allow for every command (docs/specs/agent-containment.md, R-AC-1/R-AC-4).
COMMAND_ENVELOPE_KEYS = ("tool_input", "args")

#: Sentinel distinguishing "the envelope carried no command" from "the command was
#: the empty string". The former is a payload this guard does not model and must
#: deny; the latter is a real, harmless command.
UNRECOGNISED_ENVELOPE = object()


def _gate_logger() -> logging.Logger:
    """Return the shared gate logger, degrading to a bare one if unimportable.

    This module runs both as an imported function (the orchestrator calls
    ``check_command`` directly) and as ``python harness/shared/pretooluse_guard.py``,
    where the repo root may not be on ``sys.path``. Diagnostics must never be able
    to fail the gate, so an import problem degrades rather than raising.
    """
    try:
        from harness.shared.json_logging import configure_gate_logging

        return configure_gate_logging(__name__)
    except Exception:  # noqa: BLE001 - logging setup must never break a gate
        # Non-propagating: the root logger may be configured to write to stdout
        # (setup_json_logging does exactly that), and this gate's stdout is the
        # verdict channel its callers parse.
        fallback = logging.getLogger(__name__)
        fallback.propagate = False
        if not fallback.handlers:
            fallback.addHandler(logging.StreamHandler(sys.stderr))
        return fallback


logger = _gate_logger()


def block(msg: str, reason_code: str = "policy") -> int:
    """Deny the tool call, on stderr, with a stable reason code for log scraping."""
    logger.warning("guard blocked: reason=%s detail=%s", reason_code, msg)
    print("BLOCKED: " + msg, file=sys.stderr)
    return BLOCK_EXIT


def extract_command(payload: dict) -> object:
    """Return the command carried by a recognised envelope, else the sentinel.

    Accepting both envelope shapes is deliberate: it converts the historical
    ``args`` payload from a silent allow into an evaluated command, so an adopter
    still emitting it gets a verdict rather than a bypass.
    """
    for key in COMMAND_ENVELOPE_KEYS:
        section = payload.get(key)
        if isinstance(section, dict) and "command" in section:
            value = section["command"]
            logger.debug("guard envelope matched key=%s", key)
            return value if isinstance(value, str) else ""
    return UNRECOGNISED_ENVELOPE


def git_output(root: Path, args: list[str]) -> str:
    p = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def resolve_remote(root: Path, name: str) -> list[str]:
    urls = git_output(root, ["config", "--get-all", f"remote.{name}.pushurl"]).splitlines()
    if not urls:
        urls = git_output(root, ["config", "--get-all", f"remote.{name}.url"]).splitlines()
    return [u for u in urls if u]


def effective_remote(root: Path) -> str | None:
    branch = git_output(root, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    candidates = []
    if branch:
        candidates += [git_output(root, ["config", "--get", f"branch.{branch}.pushRemote"])]
    candidates += [git_output(root, ["config", "--get", "remote.pushDefault"])]
    if branch:
        candidates += [git_output(root, ["config", "--get", f"branch.{branch}.remote"])]
    candidates = [c for c in candidates if c and c != "."]
    if candidates:
        return candidates[0]
    remotes = git_output(root, ["remote"]).split()
    if "origin" in remotes:
        return "origin"
    if len(remotes) == 1:
        return remotes[0]
    return ""


def segments(command):
    lex = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lex.whitespace_split = True
    lex.commenters = ""
    toks = list(lex)
    out: list[list[str]] = []
    cur: list[str] = []
    for t in toks:
        if t and all(c in ";&|" for c in t):
            if cur:
                out.append(cur)
                cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def destinations(root: Path, seg: list[str]) -> list[str]:
    if "git" not in seg:
        return []
    gi = seg.index("git")
    toks = seg[gi + 1 :]
    i = 0
    # We refuse config/env mutation around a push rather than trying to emulate Git's entire config stack.
    if any(t == "--config-env" or t.startswith("GIT_CONFIG_") for t in seg):
        raise ValueError("environment/config injection around git push is outside the guard model")
    while i < len(toks) and toks[i] != "push":
        t = toks[i]
        if t in ("-C", "-c", "--git-dir", "--work-tree"):
            i += 2
            continue
        if t.startswith(("-C", "-c")) and len(t) > 2:
            i += 1
            continue
        if t.startswith("-"):
            i += 1
            continue
        return []
    if i >= len(toks):
        return []
    args = toks[i + 1 :]
    repo = None
    j = 0
    takes = {"-o", "--push-option", "--receive-pack", "--exec"}
    while j < len(args):
        t = args[j]
        if t == "--":
            j += 1
            break
        if t.startswith("--repo="):
            repo = t.split("=", 1)[1]
            j += 1
            break
        if t == "--repo":
            if j + 1 >= len(args):
                raise ValueError("--repo has no value")
            repo = args[j + 1]
            j += 2
            break
        if t in takes:
            if j + 1 >= len(args):
                raise ValueError(f"{t} has no value")
            j += 2
            continue
        if t.startswith("-"):
            j += 1
            continue
        repo = t
        break
    if repo is None:
        repo = effective_remote(root)
        if not repo:
            raise ValueError("cannot resolve effective remote for bare git push")
    # URL-ish destination or configured remote name.
    if "://" in repo or repo.startswith("git@") or re.match(r"^[^/]+:[^/].+", repo):
        return [repo]
    urls = resolve_remote(root, repo)
    if not urls:
        raise ValueError(f"cannot resolve URL for remote {repo}")
    return urls


def check_command(cmd: str) -> int:
    if not DANGER.search(cmd):
        return 0
    if re.search(r"\bgh\b[^\n]*\brepo\b[^\n]*\bcreate\b[^\n]*--public\b", cmd, re.I):
        return block("public repository creation requires explicit human approval through the external tool broker")
    if UNMODELED.search(cmd):
        return block("dangerous command uses an unmodeled shell/config form; spell it as a plain git push")
    try:
        segs = segments(cmd)
    except ValueError as e:
        return block(f"cannot tokenize dangerous command: {e}")
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    root = Path(env_root or git_output(Path.cwd(), ["rev-parse", "--show-toplevel"]) or Path.cwd()).resolve()
    logger.debug(
        "guard resolved root=%s source=%s allowlist=%s",
        root,
        "CLAUDE_PROJECT_DIR" if env_root else "git-toplevel-or-cwd",
        root / ".governance/allowed-remotes.txt",
    )
    saw = False
    for seg in segs:
        if "git" in seg and "push" in seg:
            saw = True
            try:
                urls = destinations(root, seg)
            except Exception as e:  # noqa: BLE001 - fail closed: any failure to
                # resolve push destinations must block the tool call, never allow
                # it. Narrowing the type here would let an unanticipated error
                # through as an implicit allow.
                return block(str(e))
            if not urls:
                return block("dangerous-shaped segment could not be attributed to a supported git push form")
            for url in urls:
                # We use the module directly if possible, else subprocess
                # For safety in the guard we stick to the subprocess or we can just import it
                remotes_path = Path(__file__).resolve().parent / "remotes.py"
                p = subprocess.run(
                    [
                        sys.executable,
                        str(remotes_path),
                        "--check-url",
                        url,
                        "--allowlist",
                        str(root / ".governance/allowed-remotes.txt"),
                    ],
                    capture_output=True,
                    text=True,
                )
                if p.returncode != 0:
                    # Captured rather than inherited: the destination check runs in a
                    # child process, so its stderr went to fd 2 and never reached the
                    # caller that has to explain the refusal (spec R-AC-5).
                    detail = (p.stderr or p.stdout or "").strip()
                    return block(detail or f"push destination {url} is not allowlisted", "remote-destination")
    return 0 if saw else block("dangerous-shaped command was not attributable to a supported segment")

def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001 - fail closed on an unparseable payload: if it
        # still looks dangerous textually, block it. An allow-by-exception here
        # would be a guard bypass. This leg is deliberately unchanged: it is the
        # path a non-JSON PreToolUse payload takes, and denying every one of those
        # would block tool calls this guard does not model (spec C-AC-1).
        if DANGER.search(raw):
            return block("unanalyzable payload contains a dangerous-shaped command", "unparseable")
        return ALLOW_EXIT
    if not isinstance(payload, dict):
        # Previously an AttributeError escaped here and exited 1, which reads as a
        # broken hook rather than a denial.
        return block(f"guard payload is a JSON {type(payload).__name__}, not an object", "not-an-object")
    cmd = extract_command(payload)
    if cmd is UNRECOGNISED_ENVELOPE:
        keys = ", ".join(COMMAND_ENVELOPE_KEYS)
        return block(
            f"guard payload carries no recognised command envelope (expected one of {keys} with a 'command' key)",
            "unrecognised-envelope",
        )
    return check_command(str(cmd))


if __name__ == "__main__":
    raise SystemExit(main())
