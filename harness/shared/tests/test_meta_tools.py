import json

from harness.shared.meta_tools import hypothesis_register, knowledge_gap_log


def test_knowledge_gap_log(tmp_path, monkeypatch):
    # Mock the memory dir
    mock_memory_dir = tmp_path / ".mango" / "memory"
    monkeypatch.setattr("harness.shared.meta_tools.MEMORY_DIR", mock_memory_dir)
    monkeypatch.setattr("harness.shared.meta_tools.GAPS_FILE", mock_memory_dir / "gaps.json")
    monkeypatch.setattr("harness.shared.meta_tools.HYPOTHESES_FILE", mock_memory_dir / "hypotheses.json")

    result = knowledge_gap_log("What is the meaning of life?", "A philosophical background", "Ask deep thinker")

    assert "Knowledge gap logged successfully" in result

    gaps_file = mock_memory_dir / "gaps.json"
    assert gaps_file.exists()

    data = json.loads(gaps_file.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["question"] == "What is the meaning of life?"
    assert data[0]["what_needed"] == "A philosophical background"
    assert data[0]["proposed_approach"] == "Ask deep thinker"


def test_hypothesis_register(tmp_path, monkeypatch):
    mock_memory_dir = tmp_path / ".mango" / "memory"
    monkeypatch.setattr("harness.shared.meta_tools.MEMORY_DIR", mock_memory_dir)
    monkeypatch.setattr("harness.shared.meta_tools.GAPS_FILE", mock_memory_dir / "gaps.json")
    monkeypatch.setattr("harness.shared.meta_tools.HYPOTHESES_FILE", mock_memory_dir / "hypotheses.json")

    result = hypothesis_register("The sky is blue", "Rayleigh scattering", 0.95)

    assert "Hypothesis registered successfully" in result

    hypotheses_file = mock_memory_dir / "hypotheses.json"
    assert hypotheses_file.exists()

    data = json.loads(hypotheses_file.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["claim"] == "The sky is blue"
    assert data[0]["reasoning"] == "Rayleigh scattering"
    assert data[0]["confidence"] == 0.95
    assert data[0]["status"] == "provisional"
