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
def reset_chaos(request):
    """Reset chaos state before/after every test that uses the Flask client."""
    if "app_client" not in request.fixturenames:
        yield
        return
    client = request.getfixturevalue("app_client")
    client.post("/chaos/reset", json={})
    yield
    client.post("/chaos/reset", json={})
