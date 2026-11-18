import io
import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_session
from app.main import app


@pytest.fixture
def image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (400, 500), "#467f72").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def no_outbox_relay(monkeypatch):
    """The outbox relay thread only runs in tests that start it explicitly, and every test starts with
    the fast path's broker pause cleared (it is process state)."""
    monkeypatch.setattr(get_settings(), "outbox_relay_enabled", False)
    monkeypatch.setattr("app.services.outbox._broker_down_until", 0.0)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.outbox.send", lambda task, job_id: None)  # no broker in tests
    settings = get_settings()
    monkeypatch.setattr(settings, "requests_per_minute", 10000)
    # The app's limiter outlives a test; a daily quota would accumulate across the whole suite.
    monkeypatch.setattr(settings, "daily_generation_quota", 0)
    monkeypatch.setattr(settings, "rate_limit_backend", "memory")
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path / "media"))
    monkeypatch.setattr(settings, "generation_mode", "demo")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)  # Test-only schema; production uses Alembic.
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    def session_override():
        with factory() as session:
            yield session
    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as test_client:
        test_client.session_factory = factory
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()
