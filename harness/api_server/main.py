import logging
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from harness.shared.debug_dump import redact_history
from harness.shared.json_logging import setup_json_logging
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator

setup_json_logging(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create the static directory when the app starts, not when it imports.

    Importing this module used to create ``static/`` as a side effect, so every
    pytest collection and every ``python -c "import ..."`` mutated the working
    tree -- including in environments that only wanted to read the app object.
    """
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Mango MAS E2E API", lifespan=lifespan)


class TaskRequest(BaseModel):
    task: str


class TaskResponse(BaseModel):
    status: str
    result: str
    history: list[dict[str, str]]


# NOTE: FastAPI resolves this annotation at runtime via typing.get_type_hints, so PEP 604
# unions (`str | None`) would fail on Python 3.9/3.10 even with `from __future__ import
# annotations`. Keep Optional[...] while 3.9 is in the CI matrix.
async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    expected_key = os.environ.get("API_SERVER_KEY")
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
        final_result = await run_in_threadpool(orchestrator.execute_sequential_thinking_loop, request.task)

        # The history carries prompts and tool output and is returned verbatim
        # to the client; run it through the same redactor the debug dumps use
        # so a credential resolved inside the bridge cannot leave over HTTP.
        return TaskResponse(
            status="success",
            result=final_result,
            history=redact_history(orchestrator.conversation_history, api_key=api_key),
        )
    except HTTPException:
        # Re-raise explicit HTTP errors (e.g. auth) unchanged.
        raise
    except Exception:
        # Avoid leaking internals to clients; log the real cause server-side.
        logger.exception("Orchestration failed")
        raise HTTPException(status_code=500, detail="Internal orchestration error")


# Mount the static files for the frontend UI
# check_dir=False so mounting does not require the directory to exist at import
# time; lifespan creates it before the app serves a request.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True, check_dir=False), name="static")

if __name__ == "__main__":
    import uvicorn

    # Port matches the container's EXPOSE (see Dockerfile); auto-reload is a
    # dev-only behavior and must be opted into, never the default.
    uvicorn.run(
        "harness.api_server.main:app",
        host="127.0.0.1",
        port=int(os.environ.get("API_SERVER_PORT", "8080")),
        reload=os.environ.get("API_SERVER_RELOAD") == "1",
    )
