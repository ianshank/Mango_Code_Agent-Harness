import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from harness.shared.mango_mas_orchestrator import MangoMASOrchestrator

logging.basicConfig(level=logging.INFO)
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

# We will initialize the orchestrator locally
# For production, we'd use dependency injection, but this is a basic project test
api_key = os.environ.get("NVIDIA_API_KEY")
orchestrator = MangoMASOrchestrator(workspace_dir=PROJECT_ROOT, api_key=api_key)


@app.post("/api/orchestrate", response_model=TaskResponse)
async def orchestrate_task(request: TaskRequest):
    """
    Executes the sequential thinking MAS loop for the given task.
    """
    try:
        # Reset history for each request to keep this basic demo stateless
        orchestrator.conversation_history = []

        # Run the full sequence: Planner -> Reasoner -> Verifier
        final_result = orchestrator.execute_sequential_thinking_loop(request.task)

        return TaskResponse(status="success", result=final_result, history=orchestrator.conversation_history)
    except Exception as e:
        logger.error(f"Orchestration failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Mount the static files for the frontend UI
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("harness.api_server.main:app", host="127.0.0.1", port=8000, reload=True)
