from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.main import app


def test_health() -> None:
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider"] in {"gemini", "sap_ai_core"}
    assert "x-request-id" in response.headers
    assert "x-correlation-id" in response.headers
