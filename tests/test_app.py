import pytest
from fastapi.testclient import TestClient

from adrobot.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'test.db'}")) as client:
        yield client


def test_home_serves_frontend(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Adrobot</h1>" in response.text


def test_health_checks_database(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_reports_database_failure(tmp_path):
    database = tmp_path / "missing-directory" / "test.db"
    with TestClient(create_app(f"sqlite:///{database}")) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
