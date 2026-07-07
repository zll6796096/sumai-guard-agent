from __future__ import annotations

import io

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def _png_bytes() -> bytes:
    image = Image.new("RGB", (800, 600), (236, 232, 224))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_mock_analyze_returns_valid_schema_and_japanese_reports() -> None:
    client = TestClient(app)

    response = client.post(
        "/analyze",
        data={"room_hint": "genkan", "mock": "true"},
        files={"image": ("genkan.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis_id"]
    assert payload["room_type"] in {"genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "auto"}
    assert payload["overall_risk_level"] in {"low", "medium", "high"}
    assert payload["findings"]
    assert payload["action_plan"]["family_no_cost"]
    assert payload["annotated_image_base64"]
    assert payload["improvement_image_base64"]
    assert "家族で今日できること" in payload["family_actions_markdown"]
    assert "ケアマネ・福祉用具に相談" in payload["care_manager_actions_markdown"]
    assert "専門施工・現地確認" in payload["contractor_actions_markdown"]
    assert "医療・介護・施工判断を代替しません" in payload["disclaimer_ja"]
