# Design: MG-E1 adapters

See `docs/architecture/mg-e1-swe-rex-opensandbox.md` (Critic DESIGN SHIP #142).

Bindings:
- Policy `execution_backend` top-level block (DEC-043) selects backend_id.
- Docker SWE-ReX never always-enforced; probe + deployment class required.
- SweRexBackend owns one asyncio.run bridge; no nested loops; close on all exits.
