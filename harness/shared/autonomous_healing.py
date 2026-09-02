"""Deprecated import path; the module lives in ``harness.shared.experimental`` (DEC-027).

Served for one minor release (tech-debt-hardening-plan R-TDH-18, C-TDH-2). The
warning fires on first *use* of a name, not on import, so importing this module
stays side-effect free (``test_import_purity.py``); ``from ... import TestHealer``
resolves through ``__getattr__`` (PEP 562) and warns once per access.
Import ``harness.shared.experimental.autonomous_healing`` instead.
"""

from __future__ import annotations

import warnings

#: Names the moved module still serves from here. Kept out of ``__all__`` on
#: purpose: they are resolved lazily, so a static ``__all__`` would name
#: attributes this module never binds.
_MOVED_NAMES = ("TestHealer",)

_MESSAGE = "harness.shared.autonomous_healing moved to harness.shared.experimental.autonomous_healing (DEC-027)"


def __getattr__(name: str) -> object:
    if name in _MOVED_NAMES:
        from harness.shared.experimental import autonomous_healing as _target

        warnings.warn(_MESSAGE, DeprecationWarning, stacklevel=2)
        return getattr(_target, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
