from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_and_healthz_return_exact_safe_body() -> None:
    client = TestClient(app)

    for path in ("/health", "/healthz"):
        response = client.get(path)

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": "0.3.0"}


def test_ready_returns_exact_safe_body_without_configuration_terms() -> None:
    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "version": "0.3.0"}
    lowered = response.text.lower()
    for forbidden in ("key", "secret", "credential", "firebase", "model"):
        assert forbidden not in lowered
