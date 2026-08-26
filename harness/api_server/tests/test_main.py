import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness.api_server.main import app

client = TestClient(app)
os.environ["API_SERVER_KEY"] = "default-dev-key"


def test_static_files():
    """Test that static UI files are served successfully."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Mango MAS Dashboard" in response.text


def test_api_orchestrate_success():
    """Test successful orchestration via the API."""

    # We also need to mock the conversation history property being set during the call
    with patch("harness.api_server.main.MangoMASOrchestrator") as mock_orchestrator_class:
        mock_instance = mock_orchestrator_class.return_value
        mock_instance.execute_sequential_thinking_loop.return_value = "PASS: verified"
        mock_instance.conversation_history = [
            {"role": "user", "content": "Write a python function"},
            {"role": "assistant", "content": "Here is the code"},
        ]

        response = client.post(
            "/api/orchestrate",
            json={"task": "Create a dummy test"},
            headers={"X-API-Key": "default-dev-key"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["result"] == "PASS: verified"
        assert isinstance(data["history"], list)


@patch("harness.api_server.main.MangoMASOrchestrator")
def test_api_orchestrate_failure(mock_orchestrator_class):
    """Test orchestration failure handling."""
    mock_instance = mock_orchestrator_class.return_value
    mock_instance.execute_sequential_thinking_loop.side_effect = RuntimeError("Nemotron API failed")

    response = client.post(
        "/api/orchestrate",
        json={"task": "Fail me"},
        headers={"X-API-Key": "default-dev-key"}
    )

    assert response.status_code == 500
    assert "Nemotron API failed" in response.json()["detail"]

def test_api_orchestrate_unauthorized():
    """Test unauthorized access."""
    response = client.post(
        "/api/orchestrate",
        json={"task": "Create a dummy test"},
        headers={"X-API-Key": "wrong-key"}
    )
    assert response.status_code == 401
