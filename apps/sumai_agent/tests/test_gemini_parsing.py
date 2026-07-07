from __future__ import annotations

from app.services.gemini_vision import (
    _normalize_bbox,
    mock_vision_result,
    parse_vision_json,
)


def test_parse_valid_json() -> None:
    raw = """{
        "room_type": "genkan",
        "findings": [
            {
                "risk_type": "genkan_step",
                "label_ja": "玄関段差",
                "description_ja": "段差があります。",
                "severity": 4,
                "confidence": 0.85,
                "bbox": {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.3},
                "evidence_ja": "段差が見えます。",
                "needs_human_confirmation": false
            }
        ]
    }"""
    result = parse_vision_json(raw, fallback_room="auto")

    assert result.room_type == "genkan"
    assert len(result.findings) == 1
    assert result.findings[0].risk_type == "genkan_step"
    assert result.findings[0].severity == 4
    assert result.findings[0].bbox.x == 0.1
    assert result.findings[0].bbox.w == 0.5


def test_parse_malformed_json_falls_back_to_mock() -> None:
    result = parse_vision_json("not valid json {{{", fallback_room="bathroom")

    assert result.room_type == "bathroom"
    assert len(result.findings) > 0  # mock findings for bathroom


def test_parse_empty_findings_returns_empty() -> None:
    result = parse_vision_json('{"room_type": "hallway", "findings": []}', fallback_room="auto")

    assert result.room_type == "hallway"
    assert result.findings == []


def test_bbox_1000_range_normalization() -> None:
    """Values in 0-1000 range should be divided by 1000."""
    normalized = _normalize_bbox({"x": 100, "y": 200, "w": 500, "h": 300})

    assert abs(normalized["x"] - 0.1) < 0.001
    assert abs(normalized["y"] - 0.2) < 0.001
    assert abs(normalized["w"] - 0.5) < 0.001
    assert abs(normalized["h"] - 0.3) < 0.001
    assert not normalized["_was_clamped"]


def test_bbox_normal_range_preserved() -> None:
    """Values already in 0-1 range should be unchanged."""
    normalized = _normalize_bbox({"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.3})

    assert abs(normalized["x"] - 0.1) < 0.001
    assert abs(normalized["y"] - 0.2) < 0.001
    assert not normalized["_was_clamped"]


def test_bbox_invalid_values_clamped() -> None:
    """Negative and out-of-range values should be clamped."""
    normalized = _normalize_bbox({"x": -0.5, "y": 1.5, "w": 0.3, "h": 0.2})

    assert normalized["x"] >= 0.0
    assert normalized["y"] <= 1.0
    assert normalized["_was_clamped"]


def test_bbox_empty_gets_defaults() -> None:
    """Empty bbox dict should produce safe defaults."""
    normalized = _normalize_bbox({})

    assert normalized["_was_clamped"]
    assert normalized["w"] > 0
    assert normalized["h"] > 0


def test_bbox_zero_size_gets_minimum() -> None:
    """Zero-size bbox should be replaced with minimum visible size."""
    normalized = _normalize_bbox({"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.0})

    assert normalized["w"] >= 0.01
    assert normalized["h"] >= 0.01
    assert normalized["_was_clamped"]


def test_parse_with_1000_range_bbox() -> None:
    """Full parse test with 0-1000 range bbox values from Gemini."""
    raw = """{
        "room_type": "bathroom",
        "findings": [
            {
                "risk_type": "bathroom_slip",
                "label_ja": "浴室床の滑り",
                "description_ja": "床が滑る。",
                "severity": 4,
                "confidence": 0.9,
                "bbox": {"x": 100, "y": 200, "w": 600, "h": 400},
                "evidence_ja": "床が見えます。"
            }
        ]
    }"""
    result = parse_vision_json(raw, fallback_room="auto")

    assert result.room_type == "bathroom"
    assert len(result.findings) == 1
    assert result.findings[0].bbox.x < 1.0
    assert result.findings[0].bbox.w < 1.0


def test_mock_vision_all_rooms() -> None:
    """Mock vision returns valid results for all room types."""
    for room in ["genkan", "hallway", "bathroom", "toilet", "bedroom", "kitchen", "auto"]:
        result = mock_vision_result(room)  # type: ignore[arg-type]
        assert result.room_type == room
        assert len(result.findings) >= 1
        for finding in result.findings:
            assert 0.0 <= finding.bbox.x <= 1.0
            assert 0.0 <= finding.bbox.y <= 1.0
            assert 0.0 <= finding.bbox.w <= 1.0
            assert 0.0 <= finding.bbox.h <= 1.0
