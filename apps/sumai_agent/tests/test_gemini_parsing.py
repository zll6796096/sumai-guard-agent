from __future__ import annotations

import asyncio
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.gemini_vision import (
    GEMINI_RESPONSE_JSON_SCHEMA,
    GeminiVisionService,
    VISION_PROMPT,
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


def test_parse_mixed_findings_and_canonical_markers_requires_canonical_shape() -> None:
    raw_json = json.dumps(
        {
            "is_home_environment": True,
            "room_type": "hallway",
            "observations": {"clear_path": True},
            "findings": [],
        }
    )

    with pytest.raises(ValueError, match="visible_hazards"):
        parse_vision_json(raw_json, fallback_room="auto")


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


@pytest.mark.parametrize("invalid_value", ["false", 0, 1, []])
def test_parse_canonical_observations_require_boolean_or_null_values(
    invalid_value: object,
) -> None:
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {"clear_path": invalid_value},
        "visible_hazards": [],
        "missing_safety_features": [],
    }

    with pytest.raises(ValueError, match="observations.clear_path"):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


@pytest.mark.parametrize("invalid_severity", [0, 6, 1.5])
def test_parse_canonical_hazard_rejects_severity_outside_integer_domain(
    invalid_severity: object,
) -> None:
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {},
        "visible_hazards": [
            {
                "risk_type": "floor_clutter",
                "label_ja": "床の物",
                "description_ja": "通路に物があります。",
                "severity": invalid_severity,
                "confidence": 0.8,
                "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
                "evidence_ja": "床に物が見えます。",
            }
        ],
        "missing_safety_features": [],
    }

    with pytest.raises(ValueError, match="severity"):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


@pytest.mark.parametrize(
    ("collection", "invalid_confidence"),
    [
        ("visible_hazards", -0.1),
        ("visible_hazards", 1.1),
        ("visible_hazards", float("nan")),
        ("visible_hazards", float("inf")),
        ("missing_safety_features", float("-inf")),
        ("missing_safety_features", 1.1),
    ],
)
def test_parse_canonical_items_reject_confidence_outside_finite_unit_interval(
    collection: str,
    invalid_confidence: float,
) -> None:
    hazard = {
        "risk_type": "floor_clutter",
        "label_ja": "床の物",
        "description_ja": "通路に物があります。",
        "severity": 3,
        "confidence": invalid_confidence,
        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        "evidence_ja": "床に物が見えます。",
    }
    feature = {
        "feature_key": "has_handrail",
        "confidence": invalid_confidence,
        "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4},
        "evidence_ja": "手すりが確認できません。",
    }
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {},
        "visible_hazards": [hazard] if collection == "visible_hazards" else [],
        "missing_safety_features": (
            [feature] if collection == "missing_safety_features" else []
        ),
    }

    with pytest.raises(ValueError, match="confidence"):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


@pytest.mark.parametrize(
    ("coordinate", "invalid_value"),
    [
        ("x", -0.1),
        ("y", 1.1),
        ("w", 0.0),
        ("h", 0.0),
        ("x", float("nan")),
        ("y", float("inf")),
        ("w", float("-inf")),
    ],
)
def test_parse_canonical_bbox_rejects_non_finite_or_invalid_domain(
    coordinate: str,
    invalid_value: float,
) -> None:
    bbox = {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    bbox[coordinate] = invalid_value
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

    with pytest.raises(ValueError, match=f"bbox.{coordinate}"):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


def test_parse_canonical_domain_boundaries_and_observation_null_remain_valid() -> None:
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {"clear_path": True, "lighting_poor": None},
        "visible_hazards": [
            {
                "risk_type": "floor_clutter",
                "label_ja": "床の物",
                "description_ja": "通路に物があります。",
                "severity": 1,
                "confidence": 0.0,
                "bbox": {"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1},
                "evidence_ja": "床に物が見えます。",
            }
        ],
        "missing_safety_features": [
            {
                "feature_key": "has_handrail",
                "confidence": 1.0,
                "bbox": {"x": 0.9, "y": 0.9, "w": 0.1, "h": 0.1},
                "evidence_ja": "手すりが確認できません。",
            }
        ],
    }

    result = parse_vision_json(json.dumps(payload), fallback_room="auto")

    assert result.visible_hazards[0].severity == 1
    assert result.visible_hazards[0].confidence == 0.0
    assert result.missing_safety_features[0].confidence == 1.0
    assert result.observations == {"clear_path": True, "lighting_poor": None}


@pytest.mark.parametrize("invalid_room", ["garage", "HALLWAY", " hallway "])
def test_parse_canonical_room_type_requires_exact_supported_member(
    invalid_room: str,
) -> None:
    payload = {
        "is_home_environment": True,
        "room_type": invalid_room,
        "observations": {},
        "visible_hazards": [],
        "missing_safety_features": [],
    }

    with pytest.raises(ValueError, match="room_type"):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


@pytest.mark.parametrize("invalid_reason", [{"secret": "value"}, 1, True, []])
def test_parse_canonical_not_applicable_reason_requires_string_or_null(
    invalid_reason: object,
) -> None:
    payload = {
        "is_home_environment": False,
        "room_type": "auto",
        "observations": {},
        "visible_hazards": [],
        "missing_safety_features": [],
        "not_applicable_reason_ja": invalid_reason,
    }

    with pytest.raises(ValueError, match="not_applicable_reason_ja"):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


@pytest.mark.parametrize(
    "bbox",
    [
        {"x": 0.8, "y": 0.2, "w": 0.3, "h": 0.4},
        {"x": 0.1, "y": 0.7, "w": 0.3, "h": 0.4},
    ],
)
def test_parse_canonical_bbox_must_fit_entirely_inside_image(
    bbox: dict[str, float],
) -> None:
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

    with pytest.raises(ValueError, match="bbox"):
        parse_vision_json(json.dumps(payload), fallback_room="auto")


def test_parse_pure_legacy_room_type_remains_normalized() -> None:
    payload = {"room_type": " HALLWAY ", "findings": []}

    result = parse_vision_json(json.dumps(payload), fallback_room="auto")

    assert result.room_type == "hallway"


@pytest.mark.parametrize("numeric_field", ["confidence", "bbox.x"])
def test_parse_canonical_huge_integer_is_schema_error_without_value_leakage(
    numeric_field: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    huge_integer = 10**400
    hazard = {
        "risk_type": "floor_clutter",
        "label_ja": "床の物",
        "description_ja": "通路に物があります。",
        "severity": 3,
        "confidence": huge_integer if numeric_field == "confidence" else 0.8,
        "bbox": {
            "x": huge_integer if numeric_field == "bbox.x" else 0.1,
            "y": 0.2,
            "w": 0.3,
            "h": 0.4,
        },
        "evidence_ja": "床に物が見えます。",
    }
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {},
        "visible_hazards": [hazard],
        "missing_safety_features": [],
    }

    with pytest.raises(ValueError, match="Gemini response") as exc_info:
        parse_vision_json(json.dumps(payload), fallback_room="auto")

    sensitive_value = str(huge_integer)
    assert sensitive_value not in str(exc_info.value)
    log_details = "\n".join(repr(record.__dict__) for record in caplog.records)
    assert sensitive_value not in log_details
    expected_field = (
        "visible_hazards[0].confidence"
        if numeric_field == "confidence"
        else "visible_hazards[0].bbox.x"
    )
    assert f"schema_field={expected_field}" in "\n".join(
        record.getMessage() for record in caplog.records
    )


def test_parse_canonical_rejects_unknown_observation_key_without_key_leakage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_key = "SECRET_PROVIDER_OBSERVATION_KEY"
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": {secret_key: True},
        "visible_hazards": [],
        "missing_safety_features": [],
    }

    with pytest.raises(ValueError, match=r"observations\.<invalid_key>") as exc_info:
        parse_vision_json(json.dumps(payload), fallback_room="auto")

    assert secret_key not in str(exc_info.value)
    log_details = "\n".join(repr(record.__dict__) for record in caplog.records)
    assert secret_key not in log_details
    log_messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "schema_field=observations.<invalid_key>" in log_messages
    assert (
        "schema_expected=a supported prompt observation" in log_messages
    )


def test_parse_canonical_accepts_exact_prompt_observation_allowlist() -> None:
    observations = {
        "has_handrail": True,
        "has_emergency_call_button": False,
        "has_non_slip_floor_or_mat": None,
        "has_bath_transfer_support": True,
        "has_floor_clutter": False,
        "has_loose_mat": None,
        "has_visible_threshold": True,
        "looks_slippery_floor": False,
        "lighting_poor": None,
        "space_looks_narrow": True,
        "clear_path": False,
    }
    payload = {
        "is_home_environment": True,
        "room_type": "hallway",
        "observations": observations,
        "visible_hazards": [],
        "missing_safety_features": [],
    }

    result = parse_vision_json(json.dumps(payload), fallback_room="auto")

    assert result.observations == observations


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


def test_call_gemini_passes_canonical_response_json_schema() -> None:
    captured: dict[str, object] = {}

    def generate_content(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            text=json.dumps(
                {
                    "is_home_environment": True,
                    "room_type": "hallway",
                    "observations": {},
                    "visible_hazards": [],
                    "missing_safety_features": [],
                }
            )
        )

    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    )
    google_module = ModuleType("google")
    genai_module = ModuleType("google.genai")
    types_module = ModuleType("google.genai.types")
    genai_module.Client = lambda **_kwargs: client  # type: ignore[attr-defined]
    types_module.Part = SimpleNamespace(  # type: ignore[attr-defined]
        from_bytes=lambda **_kwargs: object()
    )
    types_module.GenerateContentConfig = (  # type: ignore[attr-defined]
        lambda **kwargs: SimpleNamespace(**kwargs)
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
        asyncio.run(GeminiVisionService()._call_gemini(b"image", "auto"))

    config = captured["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema is GEMINI_RESPONSE_JSON_SCHEMA

    schema = config.response_json_schema
    assert schema["required"] == [
        "is_home_environment",
        "room_type",
        "observations",
        "visible_hazards",
        "missing_safety_features",
    ]
    assert schema["properties"]["room_type"]["enum"] == sorted(
        {
            "genkan",
            "hallway",
            "bathroom",
            "toilet",
            "bedroom",
            "kitchen",
            "auto",
        }
    )
    assert schema["properties"]["observations"]["additionalProperties"] is False
    hazard_schema = schema["properties"]["visible_hazards"]["items"]
    assert hazard_schema["required"] == [
        "risk_type",
        "label_ja",
        "description_ja",
        "severity",
        "confidence",
        "bbox",
        "evidence_ja",
    ]
    missing_schema = schema["properties"]["missing_safety_features"]["items"]
    assert missing_schema["required"] == [
        "feature_key",
        "confidence",
        "bbox",
        "evidence_ja",
    ]
    for item_schema in (hazard_schema, missing_schema):
        bbox_schema = item_schema["properties"]["bbox"]
        assert bbox_schema["required"] == ["x", "y", "w", "h"]
        assert bbox_schema["properties"]["w"]["minimum"] > 0
        assert bbox_schema["properties"]["h"]["minimum"] > 0
        assert bbox_schema["properties"]["x"]["minimum"] == 0
        assert bbox_schema["properties"]["x"]["maximum"] == 1


def test_vision_prompt_keeps_semantics_without_duplicating_json_schema() -> None:
    assert "If the photo is NOT a home/residential interior" in VISION_PROMPT
    assert "Do not invent objects" in VISION_PROMPT
    assert '"visible_hazards"' not in VISION_PROMPT
    assert '"missing_safety_features"' not in VISION_PROMPT
    assert "Output strict JSON only using this shape" not in VISION_PROMPT


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
