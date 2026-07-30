from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main
from app.models import AnalysisResponse
from app.services.gemini_vision import GEMINI_FACTS_JSON_SCHEMA, GeminiVisionService
from app.services.orchestrator import AnalysisOrchestrator


def _valid_facts_json() -> str:
    return json.dumps(
        {
            "environment": "home",
            "room_type": "hallway",
            "visible_regions": ["floor", "walking_path"],
            "entities": [
                {
                    "ref": "entity_1",
                    "ontology_key": "hallway_cord",
                    "bbox": {"x": 0.1, "y": 0.6, "w": 0.5, "h": 0.1},
                    "visibility": "clear",
                    "model_score": 0.9,
                }
            ],
            "feature_observations": [],
            "relationships": [
                {
                    "subject": "entity_1",
                    "predicate": "intersects",
                    "object": "walking_path",
                }
            ],
            "not_applicable_reason_code": None,
        }
    )


def _image_bytes() -> bytes:
    image = Image.new("RGB", (12, 12), color="white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _load_web_module() -> object:
    app_path = Path(__file__).resolve().parents[2] / "sumai_web" / "app.py"
    module_name = f"sumai_web_async_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, app_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_gemini_client_is_lazy_reused_and_awaits_async_provider() -> None:
    generate = AsyncMock(return_value=SimpleNamespace(text=_valid_facts_json()))
    fake_client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    factory = MagicMock(return_value=fake_client)
    service = GeminiVisionService(client_factory=factory)

    assert factory.call_count == 0

    async def scenario() -> None:
        await service._call_gemini(b"image", "auto")
        await service._call_gemini(b"image", "auto")

    asyncio.run(scenario())

    assert factory.call_count == 1
    assert service._client is fake_client
    assert generate.await_count == 2
    config = generate.await_args.kwargs["config"]
    assert config.response_json_schema is GEMINI_FACTS_JSON_SCHEMA


def test_web_proxy_awaits_reusable_client_and_forwards_multipart() -> None:
    web = _load_web_module()
    backend_response = SimpleNamespace(status_code=200, json=MagicMock(return_value={"mode": "gemini"}))
    fake_client = SimpleNamespace(post=AsyncMock(return_value=backend_response), aclose=AsyncMock())
    web._backend_client = fake_client

    with TestClient(web.app) as client:
        response = client.post(
            "/analyze",
            files={"image": ("hallway.png", _image_bytes(), "image/png")},
            data={"room_hint": "hallway"},
        )
        assert response.status_code == 200
        assert response.json() == {"mode": "gemini"}
        fake_client.post.assert_awaited_once()
        _, kwargs = fake_client.post.await_args
        assert kwargs["data"]["room_hint"] == "hallway"
        assert kwargs["files"]["image"][0] == "hallway.png"
        assert kwargs["files"]["image"][2] == "image/png"

    fake_client.aclose.assert_awaited_once()
    assert web._backend_client is None


def test_web_backend_client_is_recreated_after_shutdown(monkeypatch) -> None:
    web = _load_web_module()
    fake_client = SimpleNamespace(aclose=AsyncMock())
    replacement = SimpleNamespace()
    web._backend_client = fake_client

    asyncio.run(web.close_backend_client())
    monkeypatch.setattr(web.httpx, "AsyncClient", MagicMock(return_value=replacement))

    assert web._backend_client is None
    assert web.backend_client() is replacement
    fake_client.aclose.assert_awaited_once()


@pytest.mark.parametrize("status_code", [400, 422])
def test_web_proxy_preserves_invalid_upload_status_without_upstream_detail(
    status_code: int,
) -> None:
    web = _load_web_module()
    upstream_response = SimpleNamespace(
        status_code=status_code,
        json=MagicMock(
            return_value={
                "detail": "SECRET_UPSTREAM_VALIDATION_DETAIL",
                "mode": "local_mock",
            }
        ),
    )
    web._backend_client = SimpleNamespace(
        post=AsyncMock(return_value=upstream_response),
        aclose=AsyncMock(),
    )

    with TestClient(web.app) as client:
        response = client.post(
            "/analyze",
            files={"image": ("room.png", _image_bytes(), "image/png")},
        )

    assert response.status_code == status_code
    assert response.json() == {
        "error": "invalid_upload",
        "message": "画像または入力内容が無効です。内容を確認して、もう一度お試しください。",
    }
    assert "local_mock" not in response.text
    assert "SECRET_UPSTREAM_VALIDATION_DETAIL" not in response.text
    upstream_response.json.assert_not_called()


def test_web_proxy_preserves_other_4xx_with_safe_message() -> None:
    web = _load_web_module()
    upstream_response = SimpleNamespace(
        status_code=409,
        json=MagicMock(return_value={"detail": "SECRET_UPSTREAM_CONFLICT"}),
    )
    web._backend_client = SimpleNamespace(
        post=AsyncMock(return_value=upstream_response),
        aclose=AsyncMock(),
    )

    with TestClient(web.app) as client:
        response = client.post(
            "/analyze",
            files={"image": ("room.png", _image_bytes(), "image/png")},
        )

    assert response.status_code == 409
    assert response.json() == {
        "error": "backend_request_rejected",
        "message": "分析リクエストを処理できませんでした。入力内容を確認してください。",
    }
    assert "local_mock" not in response.text
    assert "SECRET_UPSTREAM_CONFLICT" not in response.text
    upstream_response.json.assert_not_called()


def test_web_proxy_non_strict_500_uses_neutral_local_fallback() -> None:
    web = _load_web_module()
    upstream_response = SimpleNamespace(
        status_code=500,
        json=MagicMock(return_value={"detail": "SECRET_UPSTREAM_FAILURE"}),
    )
    web._backend_client = SimpleNamespace(
        post=AsyncMock(return_value=upstream_response),
        aclose=AsyncMock(),
    )

    with TestClient(web.app) as client:
        response = client.post(
            "/analyze",
            files={"image": ("room.png", _image_bytes(), "image/png")},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "local_mock"
    assert response.json()["is_not_applicable"] is True
    assert "backend_http_error" in response.text
    assert "SECRET_UPSTREAM_FAILURE" not in response.text
    upstream_response.json.assert_not_called()


def test_web_proxy_timeout_default_exceeds_backend_budget_and_configures_read_timeout(monkeypatch) -> None:
    web = _load_web_module()
    client_factory = MagicMock(return_value=SimpleNamespace())
    monkeypatch.setattr(web.httpx, "AsyncClient", client_factory)

    client = web.backend_client()

    assert web.SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS == 120.0
    assert web.SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS == 30.0
    assert web.SUMAI_AGENT_TIMEOUT_SECONDS == 150.0
    assert web.SUMAI_AGENT_TIMEOUT_SECONDS > web.SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS
    assert client is client_factory.return_value
    timeout = client_factory.call_args.kwargs["timeout"]
    assert timeout.read == 150.0
    assert timeout.connect < timeout.read


def test_web_proxy_timeout_uses_valid_explicit_override(monkeypatch) -> None:
    monkeypatch.setenv("SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS", "15")
    monkeypatch.setenv("SUMAI_AGENT_TIMEOUT_SECONDS", "75")

    web = _load_web_module()

    assert web.SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS == 45.0
    assert web.SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS == 15.0
    assert web.SUMAI_AGENT_TIMEOUT_SECONDS == 75.0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS", "0"),
        ("SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS", "nan"),
        ("SUMAI_AGENT_TIMEOUT_SECONDS", "-1"),
    ],
)
def test_web_proxy_timeout_rejects_non_finite_or_non_positive_values(monkeypatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        _load_web_module()


def test_web_proxy_timeout_rejects_override_below_required_margin(monkeypatch) -> None:
    monkeypatch.setenv("SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS", "30")
    monkeypatch.setenv("SUMAI_AGENT_TIMEOUT_SECONDS", "149.999")

    with pytest.raises(ValueError, match="SUMAI_AGENT_TIMEOUT_SECONDS"):
        _load_web_module()


def test_web_proxy_timeout_accepts_override_at_required_margin(monkeypatch) -> None:
    monkeypatch.setenv("SUMAI_AGENT_ANALYSIS_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("SUMAI_AGENT_TIMEOUT_MARGIN_SECONDS", "30")
    monkeypatch.setenv("SUMAI_AGENT_TIMEOUT_SECONDS", "150")

    web = _load_web_module()

    assert web.SUMAI_AGENT_TIMEOUT_SECONDS == 150.0


def test_gemini_client_close_is_idempotent_and_allows_recreation() -> None:
    first_generate = AsyncMock(return_value=SimpleNamespace(text=_valid_facts_json()))
    first_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=first_generate),
            aclose=AsyncMock(),
        )
    )
    second_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(
                generate_content=AsyncMock(return_value=SimpleNamespace(text=_valid_facts_json()))
            ),
            aclose=AsyncMock(),
        )
    )
    factory = MagicMock(side_effect=[first_client, second_client])
    service = GeminiVisionService(client_factory=factory)

    async def scenario() -> None:
        await service._call_gemini(b"image", "auto")
        await service.aclose()
        await service.aclose()
        await service._call_gemini(b"image", "auto")

    asyncio.run(scenario())

    first_client.aio.aclose.assert_awaited_once()
    assert factory.call_count == 2
    assert service._client is second_client


def test_orchestrator_and_app_shutdown_close_vision_client(monkeypatch) -> None:
    vision = SimpleNamespace(aclose=AsyncMock())
    orchestrator = AnalysisOrchestrator(vision=vision)

    asyncio.run(orchestrator.aclose())
    vision.aclose.assert_awaited_once()

    app_orchestrator = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(main, "orchestrator", app_orchestrator)
    with TestClient(main.app):
        pass
    app_orchestrator.aclose.assert_awaited_once()


def test_web_backend_503_is_safe_and_non_strict_unreachable_falls_back() -> None:
    web = _load_web_module()
    strict_response = SimpleNamespace(
        status_code=503,
        json=MagicMock(return_value={"error": "provider", "message": "SECRET_PROVIDER_DETAIL"}),
    )
    fake_client = SimpleNamespace(post=AsyncMock(return_value=strict_response), aclose=AsyncMock())
    web._backend_client = fake_client

    with TestClient(web.app) as client:
        response = client.post(
            "/analyze",
            files={"image": ("room.png", _image_bytes(), "image/png")},
        )
        assert response.status_code == 503
        assert "SECRET_PROVIDER_DETAIL" not in response.text
        assert response.json() == {
            "error": "gemini_unavailable",
            "message": "Real Gemini analysis is required but unavailable.",
        }

    web._backend_client = SimpleNamespace(
        post=AsyncMock(side_effect=httpx.ConnectError("SECRET_INTERNAL_URL")),
        aclose=AsyncMock(),
    )
    with TestClient(web.app) as client:
        fallback = client.post(
            "/analyze",
            files={"image": ("room.png", _image_bytes(), "image/png")},
        )
        fallback_again = client.post(
            "/analyze",
            files={"image": ("room.png", _image_bytes(), "image/png")},
        )
    assert fallback.status_code == 200
    payload = fallback.json()
    assert payload["mode"] == "local_mock"
    assert payload["is_not_applicable"] is True
    assert payload["room_type"] == "auto"
    assert payload["overall_risk_level"] == "low"
    assert payload["findings"] == []
    assert payload["action_plan"] == {
        "family_no_cost": [],
        "care_manager_purchase": [],
        "contractor_construction": [],
    }
    assert payload["not_applicable_reason_ja"].strip()
    assert payload["annotated_image_base64"] == payload["improvement_image_base64"]
    assert len(payload["result_key"]) == 64
    assert len(payload["semantic_hash"]) == 64
    assert set(payload["stage_timings_ms"]) == {
        "intake", "memo_lookup", "vision", "ontology",
        "render", "report", "serialize", "total",
    }
    misleading = " ".join(
        payload[field]
        for field in (
            "risk_summary_markdown",
            "family_actions_markdown",
            "care_manager_actions_markdown",
            "contractor_actions_markdown",
        )
    )
    assert "総合リスク" not in misleading
    assert "未検出" not in misleading
    assert "###" not in misleading
    assert "SECRET_INTERNAL_URL" not in fallback.text
    assert "backend_unreachable" in fallback.text
    AnalysisResponse.model_validate(payload)
    repeated_payload = fallback_again.json()
    assert repeated_payload["analysis_id"] != payload["analysis_id"]
    assert repeated_payload["result_key"] == payload["result_key"]
    assert repeated_payload["semantic_hash"] == payload["semantic_hash"]
