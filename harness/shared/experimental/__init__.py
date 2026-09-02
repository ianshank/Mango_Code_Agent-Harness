"""Shipped but unwired capabilities, parked behind an explicit boundary (DEC-027).

`autonomous_healing` and `lats_optimizer` arrived in v2.3.0 as headline features
and have never been reachable from a runtime path: no orchestrator, node or CLI
imports them, `synthesis.lats_enabled` is `false` with no reader, and INV-15
keeps LATS off until an ablation gate exists. Leaving them beside the live
modules made the public surface larger than the tested behaviour
(tech-debt-hardening-plan R-TDH-18).

Nothing here is deleted or weakened: the modules are unchanged, fully tested
(`test_autonomous_healing.py`, `test_lats_optimizer.py`, `make test-lats`), and
still policy-sourced (`orchestrator.max_healing_retries`, `lats.*`). What the
package boundary says is: importing from here is opting into an experiment.
The old import paths keep working for one minor release with a
`DeprecationWarning` (C-TDH-2). Wiring either capability into a runtime path is
its own spec, gated on `synthesis.lats_enabled` for LATS (INV-15).
"""
