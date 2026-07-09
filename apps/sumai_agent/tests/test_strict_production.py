from __future__ import annotations

import io
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.config import Settings
from app.models import BoundingBox, RiskFinding, RoomType, VisionResult
from app.services.rule_engine import RuleEngine


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
def test_non_home_environment_returns_no_findings(mock_call_gemini: AsyncMock) -> None:
    # Setup mock call to return is_home_environment=False
    mock_call_gemini.return_value = VisionResult(
        room_type="auto",
        findings=[],
        is_home_environment=False,
        not_applicable_reason_ja="住宅内の安全確認対象ではない可能性があります。"
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
        assert data["not_applicable_reason_ja"] == "住宅内の安全確認対象ではない可能性があります。"
        assert len(data["findings"]) == 0
        assert data["overall_risk_level"] == "low"


def test_empty_findings_behavior() -> None:
    client = TestClient(app)
    img_bytes = _create_mock_image()
    
    with patch("app.services.gemini_vision.GeminiVisionService.analyze") as mock_analyze:
        mock_analyze.return_value = (
            VisionResult(room_type="auto", findings=[], is_home_environment=True),
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
        assert len(data["findings"]) == 0
        msg = "写真内に明確な転倒リスクは検出されませんでした。必要に応じて別角度で撮影してください。"
        assert data["family_actions_markdown"] == msg
        assert data["care_manager_actions_markdown"] == msg
        assert data["contractor_actions_markdown"] == msg


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
    ])
    assert len(findings) == 0

    # 2. 0.45 <= confidence < 0.60 with known risk: kept, needs_human_confirmation=True
    findings, _ = engine.apply([
        _make_finding("hallway_cord", 0.50)
    ])
    assert len(findings) == 1
    assert findings[0].needs_human_confirmation is True

    # 3. 0.45 <= confidence < 0.60 with unknown risk: dropped
    findings, _ = engine.apply([
        _make_finding("unknown_risk", 0.50)
    ])
    assert len(findings) == 0

    # 4. Unknown risk type: kept only if confidence >= 0.75
    findings, _ = engine.apply([
        _make_finding("unknown_risk", 0.74),  # Too low for unknown
        _make_finding("unknown_risk", 0.76)   # High enough
    ])
    assert len(findings) == 1
    assert findings[0].risk_type == "unknown_risk"
    assert findings[0].confidence == 0.76
