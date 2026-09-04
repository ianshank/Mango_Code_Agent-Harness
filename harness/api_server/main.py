import logging
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from harness.api_server.messages import HistoryMessage, parse_history
from harness.shared.debug_dump import redact_history
from harness.shared.json_logging import setup_json_logging
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator
from harness.shared.policy_loader import PolicyError, orchestrator_defaults

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

# The credential `/api/orchestrate` is gated on. Named once so the auth
# dependency and the readiness probe cannot drift apart on which variable
# "configured" means.
API_KEY_ENV_VAR = "API_SERVER_KEY"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Process-wide setup runs when the app starts, not when it imports.

    Importing this module used to create ``static/`` as a side effect, so every
    pytest collection and every ``python -c "import ..."`` mutated the working
    tree -- including in environments that only wanted to read the app object.
    Root-logger reconfiguration moved here for the same reason: importing the
    app object (to read its routes, to build an OpenAPI document, to run a
    test) must not replace the importing process's log handlers. The uvicorn
    entry point runs lifespan on startup, so a served process is configured
    exactly as before.
    """
    setup_json_logging(level=logging.INFO)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Mango MAS E2E API", lifespan=lifespan)


class TaskRequest(BaseModel):
    # Deliberately unbounded. The audit asked for a `max_length`, but no key
    # in governance-policy.json describes a task brief: `orchestrator.
    # max_command_bytes` bounds a sandbox command line and `max_output_bytes`
    # a captured tool output, and this string becomes neither -- it is the
    # user turn of the planner's conversation. Reusing either would enforce a
    # limit the policy does not state, and the policy file is a protected path,
    # so a purpose-made key is a separate, reviewed change.
    task: str


class TaskResponse(BaseModel):
    status: str
    result: str
    # Typed per role (audit B3): a tool-using run's history carries an
    # assistant turn with `content: None` + `tool_calls` and a `tool` turn with
    # `tool_call_id`, none of which `dict[str, str]` admits -- so every real run
    # returned 500. See `harness/api_server/messages.py`.
    history: list[HistoryMessage]
    # Additive. `status` keeps its existing meaning -- "the orchestration did not
    # raise" -- so a client reading only that field learns nothing about the
    # outcome; these carry the verdict the harness earned for the same run.
    # `verdict_detail` names the command and its exit code because the verdict
    # word alone overstates what was checked: the configured target is one gate,
    # not the repository's full matrix.
    # Optional[...] rather than `str | None`: FastAPI resolves these at runtime
    # and this module has no `from __future__ import annotations`.
    verdict: Optional[str] = None
    termination_reason: Optional[str] = None
    verdict_detail: Optional[str] = None


# NOTE: FastAPI resolves this annotation at runtime via typing.get_type_hints, so PEP 604
# unions (`str | None`) would fail on Python 3.9/3.10 even with `from __future__ import
# annotations`. Keep Optional[...] while 3.9 is in the CI matrix.
async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    expected_key = os.environ.get(API_KEY_ENV_VAR)
    if not expected_key:
        raise HTTPException(status_code=500, detail="Server misconfiguration: API_SERVER_KEY is not set.")
    # compare_digest, not ==: a short-circuiting comparison leaks the length of
    # the matching prefix through timing, which is enough to recover a key one
    # byte at a time against a remote endpoint.
    #
    # Compared as bytes, not str: compare_digest raises TypeError on a str
    # containing non-ASCII code points, so passing the header through directly
    # would turn any request carrying a non-ASCII X-API-Key into a 500 -- a
    # denial of service reachable by anyone, introduced by the hardening.
    #
    # surrogateescape rather than strict: header bytes are decoded as latin-1
    # by the server stack and environment values by the filesystem codec, so
    # either side can hold code points that plain UTF-8 encoding rejects. This
    # round-trips them to the original bytes and keeps the function total --
    # every input produces 401 or 200, never a 500.
    if not x_api_key or not secrets.compare_digest(
        x_api_key.encode("utf-8", "surrogateescape"),
        expected_key.encode("utf-8", "surrogateescape"),
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


@app.post("/api/orchestrate", response_model=TaskResponse, dependencies=[Depends(verify_api_key)])
async def orchestrate_task(request: TaskRequest) -> TaskResponse:
    """
    Executes the sequential thinking MAS loop for the given task.
    """
    try:
        from fastapi.concurrency import run_in_threadpool
        api_key = os.environ.get("NVIDIA_API_KEY")
        orchestrator = MangoMASOrchestrator(workspace_dir=PROJECT_ROOT, api_key=api_key)

        # Run the full sequence: Planner -> Reasoner -> Verifier (offloaded to thread)
        outcome = await run_in_threadpool(orchestrator.execute_loop, request.task)

        # The history carries prompts and tool output and is returned verbatim
        # to the client; run it through the same redactor the debug dumps use
        # so a credential resolved inside the bridge cannot leave over HTTP.
        verdict = outcome.verdict
        return TaskResponse(
            status="success",
            result=outcome.verifier_message,
            history=parse_history(redact_history(orchestrator.conversation_history, api_key=api_key)),
            verdict=verdict.status,
            termination_reason=verdict.termination_reason or None,
            verdict_detail=f"{verdict.command} exited {verdict.exit_code}: {verdict.reason}",
        )
    except HTTPException:
        # Re-raise explicit HTTP errors (e.g. auth) unchanged.
        raise
    except Exception:
        # Avoid leaking internals to clients; log the real cause server-side.
        logger.exception("Orchestration failed")
        raise HTTPException(status_code=500, detail="Internal orchestration error") from None


# Liveness and readiness (audit M14, additive). Both are unauthenticated: a
# probe that needs the API key cannot tell "the process is down" from "the
# key is missing", which is the second thing readiness exists to report.
# Declared before the static mount at "/" because Starlette matches routes in
# order and a mount at the root shadows everything registered after it.
@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process can answer HTTP. Always 200."""
    return {"status": "ok"}


def readiness_checks() -> dict[str, bool]:
    """What `/api/orchestrate` needs before it can serve a request.

    Each check is a boolean, never a message: a `PolicyError` names the file
    that failed, and a probe endpoint must not disclose paths. The cause is
    logged server-side, where it belongs.
    """
    checks = {"api_key": bool(os.environ.get(API_KEY_ENV_VAR))}
    try:
        # The accessor the orchestrator itself resolves through, so "the policy
        # loads" means the block a run depends on, not merely that a file parses.
        orchestrator_defaults()
        checks["policy"] = True
    except PolicyError:
        logger.exception("Readiness check failed: governance policy did not load")
        checks["policy"] = False
    return checks


# Plain `def`: FastAPI runs it in the threadpool, so the policy read does not
# block the event loop.
@app.get("/readyz")
def readyz() -> JSONResponse:
    """Readiness: 200 only when every dependency of `/api/orchestrate` is in place, else 503."""
    checks = readiness_checks()
    ready = all(checks.values())
    return JSONResponse(
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"status": "ready" if ready else "unavailable", "checks": checks},
    )


# Mount the static files for the frontend UI
# check_dir=False so mounting does not require the directory to exist at import
# time; lifespan creates it before the app serves a request.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True, check_dir=False), name="static")

if __name__ == "__main__":
    import uvicorn

    # Port matches the container's EXPOSE (see Dockerfile); auto-reload is a
    # dev-only behavior and must be opted into, never the default. Host
    # defaults to loopback-only (the secure default for a dev runner) but,
    # like port and reload, is env-overridable rather than a bare literal
    # with no escape hatch.
    uvicorn.run(
        "harness.api_server.main:app",
        host=os.environ.get("API_SERVER_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_SERVER_PORT", "8080")),
        reload=os.environ.get("API_SERVER_RELOAD") == "1",
    )
