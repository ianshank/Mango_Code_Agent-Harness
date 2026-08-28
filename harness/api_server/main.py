import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from harness.shared.json_logging import setup_json_logging
from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator

setup_json_logging(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Mango MAS E2E API")


class TaskRequest(BaseModel):
    task: str


class TaskResponse(BaseModel):
    status: str
    result: str
    history: list[dict[str, str]]


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Ensure static directory exists
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# NOTE: FastAPI resolves this annotation at runtime via typing.get_type_hints, so PEP 604
# unions (`str | None`) would fail on Python 3.9/3.10 even with `from __future__ import
# annotations`. Keep Optional[...] while 3.9 is in the CI matrix.
async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    expected_key = os.environ.get("API_SERVER_KEY")
    if not expected_key:
        raise HTTPException(status_code=500, detail="Server misconfiguration: API_SERVER_KEY is not set.")
    if not x_api_key or x_api_key != expected_key:
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

        return TaskResponse(status="success", result=final_result, history=orchestrator.conversation_history)
    except HTTPException:
        # Re-raise explicit HTTP errors (e.g. auth) unchanged.
        raise
    except Exception:
        # Avoid leaking internals to clients; log the real cause server-side.
        logger.exception("Orchestration failed")
        raise HTTPException(status_code=500, detail="Internal orchestration error")


# Mount the static files for the frontend UI
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

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
