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


def test_same_mock_request_has_stable_canonical_result_but_new_request_id() -> None:
    client = TestClient(app)
    request = {
        "data": {"room_hint": "genkan", "mock": "true"},
        "files": {"image": ("genkan.png", _png_bytes(), "image/png")},
    }

    first = client.post("/analyze", **request)
    second = client.post("/analyze", **request)

    assert first.status_code == 200
    assert second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["analysis_id"] != second_payload["analysis_id"]
    for key in ("result_key", "semantic_hash", "findings", "action_plan"):
        assert first_payload[key] == second_payload[key]


def test_result_key_changes_when_room_or_execution_mode_changes() -> None:
    client = TestClient(app)
    common = {"files": {"image": ("genkan.png", _png_bytes(), "image/png")}}

    forced_mock = client.post("/analyze", data={"room_hint": "genkan", "mock": "true"}, **common)
    another_room = client.post("/analyze", data={"room_hint": "bathroom", "mock": "true"}, **common)
    configured_mock = client.post("/analyze", data={"room_hint": "genkan", "mock": "false"}, **common)

    assert forced_mock.status_code == another_room.status_code == configured_mock.status_code == 200
    assert forced_mock.json()["result_key"] != another_room.json()["result_key"]
    assert forced_mock.json()["result_key"] != configured_mock.json()["result_key"]
