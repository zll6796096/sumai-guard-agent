from __future__ import annotations

import io
import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.config import Settings
from app.models import AnalysisResponse, BoundingBox, RiskFinding, RoomType, VisionFacts, VisionResult
from app.services.gemini_vision import parse_vision_json
from app.services.rule_engine import RuleEngine


SENTINEL = "SECRET_PROVIDER_DETAIL_12345"
HUGE_INTEGER = 10**400

MALFORMED_GEMINI_RESPONSES = [
    pytest.param(json.dumps({"provider_detail": SENTINEL}), id="empty-response-shape"),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "visible_hazards": [{"provider_detail": SENTINEL}],
                "missing_safety_features": [],
            }
        ),
        id="empty-visible-hazard",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "findings": [],
                "missing_safety_features": [{"provider_detail": SENTINEL}],
            }
        ),
        id="mixed-malformed-missing-feature",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "visible_hazards": [
                    {
                        "risk_type": "cluttered_path",
                        "label_ja": "床の物",
                        "description_ja": "通路に物があります。",
                        "severity": 99,
                        "confidence": 0.8,
                        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                        "evidence_ja": "床に物が見えます。",
                        "provider_detail": SENTINEL,
                    }
                ],
                "missing_safety_features": [],
            }
        ),
        id="canonical-severity-out-of-domain",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": SENTINEL,
                "observations": {},
                "visible_hazards": [],
                "missing_safety_features": [],
            }
        ),
        id="canonical-room-out-of-domain",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": False,
                "room_type": "auto",
                "observations": {},
                "visible_hazards": [],
                "missing_safety_features": [],
                "not_applicable_reason_ja": {"provider_detail": SENTINEL},
            }
        ),
        id="canonical-reason-wrong-type",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "visible_hazards": [
                    {
                        "risk_type": "cluttered_path",
                        "label_ja": "床の物",
                        "description_ja": "通路に物があります。",
                        "severity": 3,
                        "confidence": 0.8,
                        "bbox": {"x": 0.9, "y": 0.2, "w": 0.2, "h": 0.4},
                        "evidence_ja": "床に物が見えます。",
                        "provider_detail": SENTINEL,
                    }
                ],
                "missing_safety_features": [],
            }
        ),
        id="canonical-bbox-exceeds-image",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "visible_hazards": [
                    {
                        "risk_type": "cluttered_path",
                        "label_ja": "床の物",
                        "description_ja": "通路に物があります。",
                        "severity": 3,
                        "confidence": HUGE_INTEGER,
                        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                        "evidence_ja": "床に物が見えます。",
                        "provider_detail": SENTINEL,
                    }
                ],
                "missing_safety_features": [],
            }
        ),
        id="canonical-huge-confidence",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {},
                "visible_hazards": [
                    {
                        "risk_type": "cluttered_path",
                        "label_ja": "床の物",
                        "description_ja": "通路に物があります。",
                        "severity": 3,
                        "confidence": 0.8,
                        "bbox": {"x": HUGE_INTEGER, "y": 0.2, "w": 0.3, "h": 0.4},
                        "evidence_ja": "床に物が見えます。",
                        "provider_detail": SENTINEL,
                    }
                ],
                "missing_safety_features": [],
            }
        ),
        id="canonical-huge-bbox",
    ),
    pytest.param(
        json.dumps(
            {
                "is_home_environment": True,
                "room_type": "hallway",
                "observations": {SENTINEL: True},
                "visible_hazards": [],
                "missing_safety_features": [],
            }
        ),
        id="canonical-provider-observation-key",
    ),
]


def _captured_log_details(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(repr(record.__dict__) for record in caplog.records)


def _create_mock_image() -> bytes:
    img = Image.new("RGB", (100, 100), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_status_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "mock_mode" in data
    assert "require_real_gemini" in data
    assert "has_gemini_api_key" in data
    assert "gemini_model" in data
    assert "mock_allowed" in data


def test_strict_mode_without_api_key() -> None:
    new_settings = Settings(require_real_gemini=True, gemini_api_key="")
    
    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        
        client = TestClient(app)
        img_bytes = _create_mock_image()
        
        response = client.post(
            "/analyze",
            files={"image": ("test.png", img_bytes, "image/png")},
            data={"room_hint": "auto"}
        )
        assert response.status_code == 503
        data = response.json()
        assert data["error"] == "gemini_unavailable"
        assert "unavailable" in data["message"]


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
@pytest.mark.parametrize("raw_json", MALFORMED_GEMINI_RESPONSES)
def test_strict_mode_parse_failure_returns_503_without_detail_leakage(
    mock_call_gemini: AsyncMock,
    raw_json: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sumai.gemini_vision")

    async def parse_provider_response(*_args: object, **_kwargs: object) -> VisionResult:
        return parse_vision_json(raw_json, fallback_room="auto")

    mock_call_gemini.side_effect = parse_provider_response
    new_settings = Settings(
        require_real_gemini=True,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={"image": ("test.png", _create_mock_image(), "image/png")},
            data={"room_hint": "auto", "mock": "false"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "error": "gemini_unavailable",
        "message": "Real Gemini analysis is required but unavailable.",
    }
    assert SENTINEL not in response.text
    assert str(HUGE_INTEGER) not in response.text
    log_details = _captured_log_details(caplog)
    assert SENTINEL not in log_details
    assert str(HUGE_INTEGER) not in log_details
    assert "invalid_response" in log_details


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
@pytest.mark.parametrize("raw_json", MALFORMED_GEMINI_RESPONSES)
def test_non_strict_parse_failure_returns_labeled_deterministic_fallback(
    mock_call_gemini: AsyncMock,
    raw_json: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sumai.gemini_vision")

    async def parse_provider_response(*_args: object, **_kwargs: object) -> VisionResult:
        return parse_vision_json(raw_json, fallback_room="auto")

    mock_call_gemini.side_effect = parse_provider_response
    new_settings = Settings(
        require_real_gemini=False,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={"image": ("test.png", _create_mock_image(), "image/png")},
            data={"room_hint": "bathroom", "mock": "false"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "gemini_fallback(invalid_response)"
    assert SENTINEL not in response.text
    assert str(HUGE_INTEGER) not in response.text
    log_details = _captured_log_details(caplog)
    assert SENTINEL not in log_details
    assert str(HUGE_INTEGER) not in log_details
    assert data["room_type"] == "bathroom"
    assert [finding["risk_type"] for finding in data["findings"]] == ["bathroom_slip"]


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
def test_non_strict_provider_error_uses_stable_code_without_detail_leakage(
    mock_call_gemini: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sumai.gemini_vision")
    mock_call_gemini.side_effect = RuntimeError(f"Provider failed: {SENTINEL}")
    new_settings = Settings(
        require_real_gemini=False,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={"image": ("test.png", _create_mock_image(), "image/png")},
            data={"room_hint": "hallway", "mock": "false"},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "gemini_fallback(provider_error)"
    assert SENTINEL not in response.text
    assert SENTINEL not in _captured_log_details(caplog)


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
def test_non_strict_timeout_uses_stable_code_without_detail_leakage(
    mock_call_gemini: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="sumai.gemini_vision")
    mock_call_gemini.side_effect = TimeoutError(f"Timed out: {SENTINEL}")
    new_settings = Settings(
        require_real_gemini=False,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={"image": ("test.png", _create_mock_image(), "image/png")},
            data={"room_hint": "hallway", "mock": "false"},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "gemini_fallback(gemini_timeout)"
    assert SENTINEL not in response.text
    assert SENTINEL not in _captured_log_details(caplog)


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
def test_non_home_environment_returns_neutral_not_applicable_response(mock_call_gemini: AsyncMock) -> None:
    mock_call_gemini.return_value = VisionFacts(
        environment="non_home",
        room_type="unknown",
        visible_regions=[],
        entities=[],
        feature_observations=[],
        relationships=[],
        not_applicable_reason_code="non_home",
    )

    new_settings = Settings(require_real_gemini=False, gemini_api_key="dummy_key", mock_mode=False)

    with patch("app.main.settings", new_settings), \
         patch("app.services.gemini_vision.settings", new_settings), \
         patch("app.config.settings", new_settings):
        
        client = TestClient(app)
        img_bytes = _create_mock_image()
        
        response = client.post(
            "/analyze",
            files={"image": ("test.png", img_bytes, "image/png")},
            data={"room_hint": "auto"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_home_environment"] is False
        assert data["is_not_applicable"] is True
        assert AnalysisResponse.model_validate(data).is_not_applicable is True
        assert data["not_applicable_reason_ja"] == "住宅内の安全確認対象ではない可能性があります。"
        assert len(data["findings"]) == 0
        assert data["action_plan"] == {
            "family_no_cost": [],
            "care_manager_purchase": [],
            "contractor_construction": [],
        }
        assert data["overall_risk_level"] == "low"
        assert data["annotated_image_base64"] == data["improvement_image_base64"]
        visible_output = "\n".join(
            [
                data["risk_summary_markdown"],
                data["family_actions_markdown"],
                data["care_manager_actions_markdown"],
                data["contractor_actions_markdown"],
            ]
        )
        assert "判定できません" in visible_output
        assert "安全または低リスクという意味ではない" in visible_output
        assert "リスクは検出されませんでした" not in visible_output
        assert "総合リスク: 低" not in visible_output


def test_unknown_room_returns_neutral_not_applicable_response() -> None:
    client = TestClient(app)
    img_bytes = _create_mock_image()
    
    with patch("app.services.gemini_vision.GeminiVisionService.analyze") as mock_analyze:
        mock_analyze.return_value = (
            VisionFacts(
                environment="home",
                room_type="unknown",
                visible_regions=[],
                entities=[],
                feature_observations=[],
                relationships=[],
                not_applicable_reason_code=None,
            ),
            "mock"
        )
        
        response = client.post(
            "/analyze",
            files={"image": ("test.png", img_bytes, "image/png")},
            data={"room_hint": "auto"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["overall_risk_level"] == "low"
        assert data["is_not_applicable"] is True
        assert AnalysisResponse.model_validate(data).is_not_applicable is True
        assert len(data["findings"]) == 0
        assert data["not_applicable_reason_ja"] == "写真から確認対象の部屋を特定できないため、結果を表示していません。"
        assert data["action_plan"] == {
            "family_no_cost": [],
            "care_manager_purchase": [],
            "contractor_construction": [],
        }
        assert data["annotated_image_base64"] == data["improvement_image_base64"]
        visible_output = "\n".join(
            [
                data["risk_summary_markdown"],
                data["family_actions_markdown"],
                data["care_manager_actions_markdown"],
                data["contractor_actions_markdown"],
            ]
        )
        assert "対象外または判定不能" in visible_output
        assert "リスクは検出されませんでした" not in visible_output
        assert "総合リスク: 低" not in visible_output


def test_not_applicable_reason_code_returns_neutral_response() -> None:
    client = TestClient(app)
    img_bytes = _create_mock_image()

    with patch("app.services.gemini_vision.GeminiVisionService.analyze") as mock_analyze:
        mock_analyze.return_value = (
            VisionFacts(
                environment="home",
                room_type="bathroom",
                visible_regions=[],
                entities=[],
                feature_observations=[],
                relationships=[],
                not_applicable_reason_code="insufficient_visibility",
            ),
            "mock",
        )

        response = client.post(
            "/analyze",
            files={"image": ("test.png", img_bytes, "image/png")},
            data={"room_hint": "bathroom", "mock": "true"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["is_not_applicable"] is True
    assert AnalysisResponse.model_validate(data).is_not_applicable is True
    assert data["not_applicable_reason_ja"]
    assert data["findings"] == []
    assert data["action_plan"] == {
        "family_no_cost": [],
        "care_manager_purchase": [],
        "contractor_construction": [],
    }
    assert data["annotated_image_base64"] == data["improvement_image_base64"]
    visible_output = "\n".join(
        [
            data["risk_summary_markdown"],
            data["family_actions_markdown"],
            data["care_manager_actions_markdown"],
            data["contractor_actions_markdown"],
        ]
    )
    assert "対象外または判定不能" in visible_output
    assert "リスクは検出されませんでした" not in visible_output
    assert "総合リスク: 低" not in visible_output


def test_rule_engine_confidence_filtering() -> None:
    engine = RuleEngine()
    
    # Define a helper finding creator
    def _make_finding(risk_type: str, confidence: float) -> RiskFinding:
        return RiskFinding(
            id="test",
            risk_type=risk_type,
            label_ja="Test Risk",
            description_ja="Test Description",
            severity=1,
            confidence=confidence,
            bbox=BoundingBox(x=0.0, y=0.0, w=0.1, h=0.1),
            evidence_ja="evidence",
            basis_label_ja="",
            basis_summary_ja="",
            needs_human_confirmation=False
        )

    # 1. confidence < 0.45: dropped
    findings, _ = engine.apply([
        _make_finding("hallway_cord", 0.44),  # Known but too low confidence
        _make_finding("unknown_risk", 0.44)   # Unknown and too low confidence
    ], "hallway")
    assert len(findings) == 0

    # 2. 0.45 <= confidence < 0.60 with known risk: kept, needs_human_confirmation=True
    findings, _ = engine.apply([
        _make_finding("hallway_cord", 0.50)
    ], "hallway")
    assert len(findings) == 1
    assert findings[0].needs_human_confirmation is True

    # 3. 0.45 <= confidence < 0.60 with unknown risk: dropped
    findings, _ = engine.apply([
        _make_finding("unknown_risk", 0.50)
    ], "hallway")
    assert len(findings) == 0

    # 4. Unknown risk type: kept only if confidence >= 0.75
    findings, _ = engine.apply([
        _make_finding("unknown_risk", 0.74),  # Too low for unknown
        _make_finding("unknown_risk", 0.76)   # High enough
    ], "hallway")
    assert len(findings) == 1
    assert findings[0].risk_type == "unknown_risk"
    assert findings[0].confidence == 0.76
