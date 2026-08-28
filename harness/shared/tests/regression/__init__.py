"""Regression / AQA tier.

Every module here reproduces a defect that reached ``main`` and is named for
the behavior that broke, not for the module it lives in. Each test in this
directory was confirmed **failing against the pre-fix commit** before its fix
landed; a test here that cannot fail is worse than no test, because it
converts an open question into a false assurance.

Tiering rationale: the tests under ``harness/shared/tests`` answer "does this
unit behave as specified"; the tests here answer "has this specific defect
come back". They are separated so the second question can be asked on its own
(``make test-regression``) and so a fix's proof is discoverable from the
defect rather than buried in a 700-test suite.
"""
