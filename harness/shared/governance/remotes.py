#!/usr/bin/env python3
"""Single remote destination normalizer/checker used by every stack and layer.

Canonical form: lowercased host, significant explicit port, case-preserved path.
Examples: github.com/Org/Repo, github.com:2222/Org/Repo.
The path is intentionally NOT lowercased because Git servers may be case-sensitive.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class RemoteParseError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedRemote:
    host: str
    port: int | None
    path: str
    canonical: str


_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
_SCP = re.compile(r"^(?:[^@/]+@)?([^:/@\[\]]+):(.+)$")
_DEFAULT_PORTS = {"ssh": 22, "git": 9418, "http": 80, "https": 443}


def normalize_remote_url(raw: str) -> NormalizedRemote:
    s = raw.strip().rstrip("\r")
    if not s:
        raise RemoteParseError("empty remote URL")
    if s.startswith(("/", "./", "../", "file:")):
        raise RemoteParseError("local/file remotes are not approved network destinations")
    scheme = "ssh"
    host = ""
    port = None
    path = ""
    m = _SCP.match(s) if not _SCHEME.match(s) else None
    if m:
        host = m.group(1)
        path = m.group(2)
    else:
        candidate = s if _SCHEME.match(s) else "ssh://" + s
        try:
            u = urlsplit(candidate)
        except ValueError as e:
            raise RemoteParseError(f"unparseable remote URL: {e}") from e
        scheme = (u.scheme or "ssh").lower()
        if u.password:
            raise RemoteParseError("embedded password/token in remote URL")
        host = u.hostname or ""
        try:
            port = u.port
        except ValueError as e:
            raise RemoteParseError(f"invalid remote port: {e}") from e
        path = u.path
        if port == _DEFAULT_PORTS.get(scheme):
            port = None
    host = host.lower().strip("[]")
    path = path.lstrip("/").rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not host:
        raise RemoteParseError("remote URL has no host")
    if not path:
        raise RemoteParseError("remote URL has no repository path")
    hostpart = f"[{host}]" if ":" in host else host
    if port is not None:
        hostpart = f"{hostpart}:{port}"
    return NormalizedRemote(host, port, path, f"{hostpart}/{path}")


def parse_allowlist(text: str) -> list[str]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.rstrip("\r").strip()
        if not line or line.startswith("#"):
            continue
        if "://" in line or "@" in line:
            raise RemoteParseError(f"allowlist line {n} must be canonical host/path, not a URL")
        wildcard = line.endswith("/*")
        base = line[:-2] if wildcard else line
        if "/" not in base:
            raise RemoteParseError(f"allowlist line {n} has no repository/owner path")
        hostpart, path = base.split("/", 1)
        if not hostpart or not path:
            raise RemoteParseError(f"allowlist line {n} is malformed")
        # Lowercase host only; preserve path case.
        if hostpart.startswith("["):
            close = hostpart.find("]")
            if close < 0:
                raise RemoteParseError(f"allowlist line {n} has malformed IPv6 host")
            normalized_host = hostpart[: close + 1].lower() + hostpart[close + 1 :]
        else:
            if ":" in hostpart:
                h, p = hostpart.rsplit(":", 1)
                if not p.isdigit():
                    raise RemoteParseError(f"allowlist line {n} has invalid port")
                normalized_host = h.lower() + ":" + p
            else:
                normalized_host = hostpart.lower()
        value = f"{normalized_host}/{path.rstrip('/')}" + ("/*" if wildcard else "")
        if value not in out:
            out.append(value)
    return out


def check_url(raw: str, allowlist: list[str]) -> tuple[bool, str]:
    if not allowlist:
        return False, "allowlist is empty"
    try:
        c = normalize_remote_url(raw).canonical
    except RemoteParseError as e:
        return False, f"cannot normalize remote URL: {e}"
    for entry in allowlist:
        if entry.endswith("/*"):
            prefix = entry[:-1]
            if c.startswith(prefix):
                return True, f"owner-scoped allowlist match: {entry}"
        elif c == entry:
            return True, f"exact allowlist match: {entry}"
    return False, f"destination {c} is not on the allowlist"


def load_allowlist(path: Path) -> list[str]:
    try:
        return parse_allowlist(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, RemoteParseError) as e:
        raise RemoteParseError(f"cannot read/parse allowlist {path}: {e}") from e


def current_push_urls(repo: Path) -> list[tuple[str, str]]:
    try:
        names = subprocess.run(
            ["git", "-C", str(repo), "remote"], check=True, encoding="utf-8", capture_output=True
        ).stdout.split()
    except Exception as e:
        raise RemoteParseError(f"cannot enumerate git remotes: {e}") from e
    if not names:
        raise RemoteParseError("repository has no configured remotes")
    result = []
    for name in names:
        cmd = ["git", "-C", str(repo), "remote", "get-url", "--push", "--all", name]
        p = subprocess.run(cmd, encoding="utf-8", capture_output=True)
        if p.returncode != 0:
            p = subprocess.run(
                ["git", "-C", str(repo), "remote", "get-url", "--all", name], encoding="utf-8", capture_output=True
            )
        if p.returncode != 0 or not p.stdout.strip():
            raise RemoteParseError(f"cannot resolve push URL for remote {name}")
        for url in p.stdout.splitlines():
            if url.strip():
                result.append((name, url.strip()))
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-url")
    mode.add_argument("--check-current-remotes", action="store_true")
    mode.add_argument("--json", action="store_true")
    ap.add_argument("--allowlist", default=".governance/allowed-remotes.txt")
    ap.add_argument("--repo", default=".")
    ns = ap.parse_args(argv)
    try:
        allow = load_allowlist(Path(ns.allowlist))
    except RemoteParseError as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        return 1
    if ns.json:
        print(json.dumps({"allowlist": allow, "allowlistPath": ns.allowlist}, indent=2))
        return 0
    pairs = [("explicit", ns.check_url)] if ns.check_url is not None else current_push_urls(Path(ns.repo))
    failures = []
    for name, url in pairs:
        ok, reason = check_url(url, allow)
        if not ok:
            failures.append(f"{name}: {reason}")
    if failures:
        for f in failures:
            print("BLOCKED: " + f, file=sys.stderr)
        print(
            "Remediation: use an allowlisted destination or record an independently approved policy change.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
