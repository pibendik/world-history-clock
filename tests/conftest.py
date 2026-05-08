# clockapp/tests/conftest.py
import pytest


SAMPLE_ERAS = [
    {"name": "Viking Age", "start": 793, "end": 1100, "weight": 7, "category": "regional"},
    {"name": "High Middle Ages", "start": 1000, "end": 1300, "weight": 8, "category": "general"},
    {"name": "Early Middle Ages", "start": 500, "end": 1000, "weight": 5, "category": "general"},
    {"name": "Classical Antiquity", "start": -800, "end": 600, "weight": 9, "category": "general"},
    {"name": "Space Age", "start": 1957, "end": 9999, "weight": 6, "category": "science"},
    {"name": "Digital Age", "start": 1970, "end": 9999, "weight": 7, "category": "science"},
]


@pytest.fixture
def mock_eras(monkeypatch):
    """Patch _load_eras() to return a controlled era list without touching the filesystem."""
    import clockapp.data.epochs as epochs_module
    monkeypatch.setattr(epochs_module, "_load_eras", lambda: SAMPLE_ERAS)
