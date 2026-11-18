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


def test_database_check_compares_with_the_latest_migration(tmp_path, monkeypatch):
    # The check used a hard-coded revision and reported every newer, fully migrated database as
    # "migration_required"; it must follow the migration scripts' head instead.
    from pathlib import Path
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path / 'ready.db'}"
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "database_url", url)
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    monkeypatch.setattr(main, "engine", create_engine(url))
    assert main.check_database() == "ok"
    command.downgrade(config, "-1")
    assert main.check_database() == "migration_required"
