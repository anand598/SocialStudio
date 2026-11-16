from fastapi.testclient import TestClient
from app.main import app
import app.main as main


def test_health():
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json() == {"status": "ok"}


def test_readiness_success(monkeypatch):
    async def healthy():
        return "ok"
    monkeypatch.setattr(main, "check_database", lambda: "ok")
    monkeypatch.setattr(main, "check_redis", healthy)
    monkeypatch.setattr(main, "check_ollama", healthy)
    with TestClient(app) as client:
        assert client.get("/api/v1/ready").status_code == 200


def test_readiness_failure_is_safe(monkeypatch):
    async def unavailable():
        return "unavailable"
    monkeypatch.setattr(main, "check_database", lambda: "unavailable")
    monkeypatch.setattr(main, "check_redis", unavailable)
    monkeypatch.setattr(main, "check_ollama", unavailable)
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"
        assert response.json()["dependencies"]["database"] == "unavailable"
