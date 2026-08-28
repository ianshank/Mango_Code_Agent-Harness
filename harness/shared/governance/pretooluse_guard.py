#!/usr/bin/env python3
"""Fail-closed first-pass shell guard for Git push/public-repo actions.
The authoritative agent control is an external tool broker/PDP. This guard is
fast local enforcement and delegates destination decisions to remotes.py.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

DANGER = re.compile(r"\bgit\b[^\n]*\bpush\b|\bgh\b[^\n]*\brepo\b[^\n]*\bcreate\b[^\n]*--public\b", re.I)
UNMODELED = re.compile(r"`|\$\(|\bGIT_CONFIG_(?:COUNT|KEY_[0-9]+|VALUE_[0-9]+)\b")


def block(msg: str) -> int:
    print("BLOCKED: " + msg, file=sys.stderr)
    return 2


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
    root = Path(
        os.environ.get("CLAUDE_PROJECT_DIR") or git_output(Path.cwd(), ["rev-parse", "--show-toplevel"]) or Path.cwd()
    ).resolve()
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
                    ]
                )
                if p.returncode != 0:
                    return 2
    return 0 if saw else block("dangerous-shaped command was not attributable to a supported segment")

def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception:  # noqa: BLE001 - fail closed on an unparseable payload: if it
        # still looks dangerous textually, block it. An allow-by-exception here
        # would be a guard bypass.
        return block("unanalyzable payload contains a dangerous-shaped command") if DANGER.search(raw) else 0
    cmd = str(payload.get("tool_input", {}).get("command", ""))
    return check_command(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
