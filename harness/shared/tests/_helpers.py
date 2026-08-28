"""Shared building blocks for the harness test suites.

Three things were reimplemented across the suite and are centralised here:

* ``REPO`` -- ``Path(__file__).resolve().parents[3]`` appeared verbatim in ten
  modules. It encodes the test file's depth in the tree, so moving a test
  broke it silently: the wrong root still resolves to *a* directory, and the
  assertions that use it then check the wrong files.
* ``load_module_by_path`` -- ``harness/control-plane`` is not a legal package
  name, so its tools can only be loaded by path. Five modules had their own
  copy, three of which leaked an entry into ``sys.modules`` that outlived the
  test.
* OpenAI-shaped chat-completion builders -- the orchestrator suites each need
  to fabricate model responses and tool calls.

The name is underscore-prefixed so pytest does not collect it as a test
module while it still imports normally as ``harness.shared.tests._helpers``.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

# harness/shared/tests/_helpers.py -> harness/shared/tests -> harness/shared
# -> harness -> repo root.
REPO = Path(__file__).resolve().parents[3]
HARNESS = REPO / "harness"
SHARED = HARNESS / "shared"
CONTROL_PLANE = HARNESS / "control-plane"


def load_module_by_path(path: Path | str, name: str, register: bool = True) -> ModuleType:
    """Import a module from an explicit path.

    ``register`` puts the module in ``sys.modules`` (needed when the module
    pickles, uses ``dataclasses``, or imports itself). Prefer
    ``imported_module`` when the registration should not outlive the test.
    """
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def imported_module(path: Path | str, name: str) -> Iterator[ModuleType]:
    """Load a module by path and restore ``sys.modules`` afterwards.

    Collection-time registration of a bare name (``sys.modules["remotes"]``)
    is a live collision hazard: whichever suite pytest collects first wins,
    and the other silently tests the wrong object. This restores whatever was
    there before, including nothing.
    """
    sentinel = object()
    previous: Any = sys.modules.get(name, sentinel)
    try:
        yield load_module_by_path(path, name, register=True)
    finally:
        if previous is sentinel:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def chat_response(content: str | None = None, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """An OpenAI-style chat completion response for a mocked bridge."""
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def tool_call(
    name: str,
    arguments: dict[str, Any] | str | None = None,
    call_id: str = "call_1",
    omit_arguments: bool = False,
) -> dict[str, Any]:
    """A single ``tool_calls`` entry.

    ``arguments`` accepts a dict (JSON-encoded), a raw string (used verbatim,
    to exercise malformed payloads) or ``None`` (emitted as JSON ``null``,
    which is a shape real models produce for zero-argument tools).
    ``omit_arguments`` drops the key entirely.
    """
    function: dict[str, Any] = {"name": name}
    if not omit_arguments:
        if isinstance(arguments, str):
            function["arguments"] = arguments
        elif arguments is None:
            function["arguments"] = None
        else:
            function["arguments"] = json.dumps(arguments)
    return {"id": call_id, "function": function}
