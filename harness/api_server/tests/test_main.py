from unittest.mock import patch

from fastapi.testclient import TestClient

from harness.api_server.main import app

client = TestClient(app)


def test_static_files():
    """Test that static UI files are served successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Mango MAS Dashboard" in response.text


@patch("harness.api_server.main.orchestrator.execute_sequential_thinking_loop")
def test_api_orchestrate_success(mock_execute):
    """Test successful orchestration via the API."""
    # Mock the return value of the MAS orchestrator
    mock_execute.return_value = "PASS: Successfully verified the output."

    # We also need to mock the conversation history property being set during the call
    with patch("harness.api_server.main.orchestrator") as mock_orchestrator:
        mock_orchestrator.execute_sequential_thinking_loop.return_value = "PASS: Successfully verified the output."
        mock_orchestrator.conversation_history = [
            {"role": "user", "content": "Write a python function"},
            {"role": "assistant", "content": "Here is the code"},
        ]

        # Override the app dependency if needed, but since we patched the module-level instance,
        # we can just use the mock directly. Actually, the module level patch is better.
        pass

    # A simpler way is to just let the real orchestrator object be mutated,
    # but mock its execute_sequential_thinking_loop to prevent real API calls.
    mock_execute.return_value = "PASS: verified"

    response = client.post("/api/orchestrate", json={"task": "Create a dummy test"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["result"] == "PASS: verified"
    assert isinstance(data["history"], list)


@patch("harness.api_server.main.orchestrator.execute_sequential_thinking_loop")
def test_api_orchestrate_failure(mock_execute):
    """Test orchestration failure handling."""
    mock_execute.side_effect = RuntimeError("Nemotron API failed")

    response = client.post("/api/orchestrate", json={"task": "Fail me"})

    assert response.status_code == 500
    assert "Nemotron API failed" in response.json()["detail"]
