from __future__ import annotations

import asyncio
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.gemini_vision import (
    GeminiVisionService,
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


@pytest.mark.parametrize(
    "raw_json",
    [
        "",
        "not valid json {{{",
        "null",
        "[]",
        '"string"',
    ],
)
def test_parse_invalid_or_non_object_json_raises_value_error(raw_json: str) -> None:
    with pytest.raises(ValueError, match="Gemini response"):
        parse_vision_json(raw_json, fallback_room="bathroom")


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="empty-object"),
        pytest.param({"visible_hazards": [{}]}, id="empty-canonical-hazard"),
    ],
)
def test_parse_rejects_objects_without_a_complete_response_shape(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="Gemini response"):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


def test_parse_empty_findings_returns_empty() -> None:
    result = parse_vision_json('{"room_type": "hallway", "findings": []}', fallback_room="auto")

    assert result.room_type == "hallway"
    assert result.findings == []


def test_parse_legacy_findings_allows_supplemental_observations() -> None:
    raw_json = json.dumps(
        {
            "is_home_environment": True,
            "room_type": "hallway",
            "observations": {"clear_path": True},
            "findings": [],
        }
    )

    result = parse_vision_json(raw_json, fallback_room="auto")

    assert result.room_type == "hallway"
    assert result.observations == {"clear_path": True}
    assert result.visible_hazards == []


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        pytest.param("is_home_environment", "false", id="home-string"),
        pytest.param("is_home_environment", 0, id="home-number"),
        pytest.param("is_home_environment", None, id="home-null"),
        pytest.param("observations", [], id="observations-list"),
        pytest.param("observations", None, id="observations-null"),
        pytest.param("visible_hazards", {}, id="visible-hazards-object"),
        pytest.param("findings", "invalid", id="legacy-findings-string"),
        pytest.param("missing_safety_features", {}, id="missing-features-object"),
        pytest.param("room_type", 123, id="room-number"),
    ],
)
def test_parse_rejects_invalid_top_level_field_types(
    field: str,
    invalid_value: object,
) -> None:
    raw_json = json.dumps({field: invalid_value})

    with pytest.raises(ValueError, match=field):
        parse_vision_json(raw_json, fallback_room="auto")


@pytest.mark.parametrize(
    "field",
    ["visible_hazards", "findings", "missing_safety_features"],
)
def test_parse_rejects_non_object_list_elements(field: str) -> None:
    raw_json = json.dumps({field: ["SECRET_PROVIDER_ELEMENT"]})

    with pytest.raises(ValueError, match=field):
        parse_vision_json(raw_json, fallback_room="auto")


def test_explicit_empty_visible_hazards_overrides_legacy_findings() -> None:
    raw_json = json.dumps(
        {
            "is_home_environment": True,
            "room_type": "hallway",
            "observations": {},
            "visible_hazards": [],
            "missing_safety_features": [],
            "findings": [
                {
                    "risk_type": "legacy_risk",
                    "label_ja": "旧リスク",
                    "description_ja": "旧形式の所見です。",
                    "severity": 3,
                    "confidence": 0.8,
                    "bbox": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                    "evidence_ja": "旧形式の根拠です。",
                }
            ],
        }
    )

    result = parse_vision_json(raw_json, fallback_room="auto")

    assert result.visible_hazards == []


@pytest.mark.parametrize(
    "missing_field",
    [
        "is_home_environment",
        "room_type",
        "observations",
        "visible_hazards",
        "missing_safety_features",
    ],
)
def test_parse_canonical_response_requires_explicit_top_level_fields(
    missing_field: str,
) -> None:
    payload: dict[str, object] = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {},
        "visible_hazards": [],
        "missing_safety_features": [],
    }
    del payload[missing_field]

    with pytest.raises(ValueError, match=missing_field):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


@pytest.mark.parametrize(
    "missing_field",
    [
        "risk_type",
        "label_ja",
        "description_ja",
        "severity",
        "confidence",
        "bbox",
        "evidence_ja",
    ],
)
def test_parse_canonical_hazard_requires_explicit_item_fields(
    missing_field: str,
) -> None:
    hazard: dict[str, object] = {
        "risk_type": "floor_clutter",
        "label_ja": "床の物",
        "description_ja": "通路に物があります。",
        "severity": 3,
        "confidence": 0.8,
        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        "evidence_ja": "床に物が見えます。",
    }
    del hazard[missing_field]
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {},
        "visible_hazards": [hazard],
        "missing_safety_features": [],
    }

    with pytest.raises(ValueError, match=missing_field):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("risk_type", None),
        ("label_ja", 123),
        ("description_ja", None),
        ("severity", True),
        ("confidence", "0.8"),
        ("bbox", []),
        ("evidence_ja", None),
    ],
)
def test_parse_canonical_hazard_rejects_non_schema_values(
    field: str,
    invalid_value: object,
) -> None:
    hazard: dict[str, object] = {
        "risk_type": "floor_clutter",
        "label_ja": "床の物",
        "description_ja": "通路に物があります。",
        "severity": 3,
        "confidence": 0.8,
        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        "evidence_ja": "床に物が見えます。",
    }
    hazard[field] = invalid_value
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {},
        "visible_hazards": [hazard],
        "missing_safety_features": [],
    }

    with pytest.raises(ValueError, match=field):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


@pytest.mark.parametrize("missing_coordinate", ["x", "y", "w", "h"])
def test_parse_canonical_hazard_requires_complete_bbox(
    missing_coordinate: str,
) -> None:
    bbox = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    del bbox[missing_coordinate]
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {},
        "visible_hazards": [
            {
                "risk_type": "floor_clutter",
                "label_ja": "床の物",
                "description_ja": "通路に物があります。",
                "severity": 3,
                "confidence": 0.8,
                "bbox": bbox,
                "evidence_ja": "床に物が見えます。",
            }
        ],
        "missing_safety_features": [],
    }

    with pytest.raises(ValueError, match=f"bbox.{missing_coordinate}"):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


@pytest.mark.parametrize(
    "missing_field",
    ["feature_key", "confidence", "bbox", "evidence_ja"],
)
def test_parse_canonical_missing_feature_requires_explicit_item_fields(
    missing_field: str,
) -> None:
    feature: dict[str, object] = {
        "feature_key": "has_handrail",
        "confidence": 0.7,
        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        "evidence_ja": "手すりが確認できません。",
    }
    del feature[missing_field]
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {},
        "visible_hazards": [],
        "missing_safety_features": [feature],
    }

    with pytest.raises(ValueError, match=missing_field):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("feature_key", None),
        ("confidence", "0.7"),
        ("bbox", []),
        ("evidence_ja", None),
    ],
)
def test_parse_canonical_missing_feature_rejects_non_schema_values(
    field: str,
    invalid_value: object,
) -> None:
    feature: dict[str, object] = {
        "feature_key": "has_handrail",
        "confidence": 0.7,
        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        "evidence_ja": "手すりが確認できません。",
    }
    feature[field] = invalid_value
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {},
        "visible_hazards": [],
        "missing_safety_features": [feature],
    }

    with pytest.raises(ValueError, match=field):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


def test_parse_canonical_empty_lists_remain_valid() -> None:
    raw_json = json.dumps(
        {
            "is_home_environment": True,
            "room_type": "hallway",
            "observations": {},
            "visible_hazards": [],
            "missing_safety_features": [],
        }
    )

    result = parse_vision_json(raw_json, fallback_room="auto")

    assert result.is_home_environment is True
    assert result.room_type == "hallway"
    assert result.visible_hazards == []
    assert result.missing_safety_features == []


def test_parse_genuine_non_home_response_remains_valid() -> None:
    raw_json = json.dumps(
        {
            "is_home_environment": False,
            "room_type": "auto",
            "observations": {},
            "visible_hazards": [],
            "missing_safety_features": [],
            "not_applicable_reason_ja": "住宅内ではありません。",
        }
    )

    result = parse_vision_json(raw_json, fallback_room="hallway")

    assert result.is_home_environment is False
    assert result.room_type == "auto"
    assert result.visible_hazards == []
    assert result.not_applicable_reason_ja == "住宅内ではありません。"


def test_call_gemini_does_not_replace_empty_response_with_valid_object() -> None:
    client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **_kwargs: SimpleNamespace(text=""),
        )
    )
    google_module = ModuleType("google")
    genai_module = ModuleType("google.genai")
    types_module = ModuleType("google.genai.types")
    genai_module.Client = lambda **_kwargs: client  # type: ignore[attr-defined]
    types_module.Part = SimpleNamespace(  # type: ignore[attr-defined]
        from_bytes=lambda **_kwargs: object()
    )
    types_module.GenerateContentConfig = (  # type: ignore[attr-defined]
        lambda **_kwargs: object()
    )
    google_module.genai = genai_module  # type: ignore[attr-defined]
    genai_module.types = types_module  # type: ignore[attr-defined]

    with patch.dict(
        sys.modules,
        {
            "google": google_module,
            "google.genai": genai_module,
            "google.genai.types": types_module,
        },
    ):
        with pytest.raises(ValueError, match="Gemini response"):
            asyncio.run(GeminiVisionService()._call_gemini(b"image", "auto"))


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
