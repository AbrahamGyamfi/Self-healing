import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "remediation"))


@pytest.fixture
def app_client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture(autouse=True)
def reset_chaos(app_client):
    """Ensure chaos is off before and after every test."""
    app_client.post("/chaos/reset", json={})
    yield
    app_client.post("/chaos/reset", json={})
