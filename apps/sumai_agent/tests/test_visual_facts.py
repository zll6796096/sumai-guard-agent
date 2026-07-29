from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import app
from app.models import VisionFacts
from app.services.gemini_vision import (
    GEMINI_FACTS_JSON_SCHEMA,
    ONTOLOGY,
    parse_vision_facts_json,
)


def _valid_facts() -> dict[str, object]:
    return {
        "environment": "home",
        "room_type": "hallway",
        "visible_regions": ["floor", "walking_path"],
        "entities": [
            {
                "ref": "cord-1",
                "ontology_key": "hallway_cord",
                "bbox": {"x": 0.1, "y": 0.6, "w": 0.5, "h": 0.1},
                "visibility": "clear",
                "model_score": 0.92,
            }
        ],
        "feature_observations": [
            {
                "feature_key": "clear_path",
                "state": "cannot_determine",
                "evidence_bbox": None,
                "model_score": 0.55,
            }
        ],
        "relationships": [
            {"subject": "cord-1", "predicate": "intersects", "object": "walking_path"}
        ],
        "not_applicable_reason_code": None,
    }


def test_vision_facts_parses_typed_visual_evidence() -> None:
    facts = parse_vision_facts_json(json.dumps(_valid_facts()))

    assert isinstance(facts, VisionFacts)
    assert facts.entities[0].ontology_key == "hallway_cord"
    assert facts.relationships[0].predicate == "intersects"
    assert facts.feature_observations[0].state == "cannot_determine"


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
def test_strict_valid_facts_derive_relationship_backed_finding(
    mock_call_gemini: AsyncMock,
) -> None:
    mock_call_gemini.return_value = parse_vision_facts_json(json.dumps(_valid_facts()))
    strict_settings = Settings(
        require_real_gemini=True,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )

    with patch("app.main.settings", strict_settings), patch(
        "app.services.gemini_vision.settings", strict_settings
    ), patch("app.config.settings", strict_settings):
        response = TestClient(app).post(
            "/analyze",
            files={"image": ("room.png", _png_bytes(), "image/png")},
            data={"room_hint": "hallway", "mock": "false"},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "gemini"
    assert [finding["risk_type"] for finding in response.json()["findings"]] == [
        "hallway_cord"
    ]


def test_facts_schema_excludes_policy_and_report_fields() -> None:
    serialized = json.dumps(GEMINI_FACTS_JSON_SCHEMA, ensure_ascii=False)

    for forbidden_field in (
        "severity",
        "action_plan",
        "label_ja",
        "description_ja",
        "basis_label_ja",
        "basis_summary_ja",
    ):
        assert forbidden_field not in serialized


def _walk_objects(schema: object) -> list[dict[str, object]]:
    if isinstance(schema, dict):
        objects = [schema] if schema.get("type") == "object" else []
        for value in schema.values():
            objects.extend(_walk_objects(value))
        return objects
    if isinstance(schema, list):
        return [item for value in schema for item in _walk_objects(value)]
    return []


def test_facts_schema_requires_all_top_level_fields_and_forbids_extra_object_fields() -> None:
    assert set(GEMINI_FACTS_JSON_SCHEMA["required"]) == {
        "environment",
        "room_type",
        "visible_regions",
        "entities",
        "feature_observations",
        "relationships",
        "not_applicable_reason_code",
    }
    for schema in _walk_objects(GEMINI_FACTS_JSON_SCHEMA):
        assert schema["additionalProperties"] is False


def test_facts_schema_room_enum_matches_ontology_rooms() -> None:
    room_enum = GEMINI_FACTS_JSON_SCHEMA["properties"]["room_type"]["enum"]

    assert set(room_enum) == {*ONTOLOGY.room_names, "unknown"}
    assert room_enum == [*ONTOLOGY.room_names, "unknown"]


def test_facts_schema_visible_regions_enum_matches_ontology() -> None:
    region_enum = GEMINI_FACTS_JSON_SCHEMA["properties"]["visible_regions"]["items"]["enum"]

    assert region_enum == list(ONTOLOGY.visible_region_keys)


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    [
        (("entities", 0, "ontology_key"), "unknown_entity"),
        (("feature_observations", 0, "feature_key"), "unknown_feature"),
        (("relationships", 0, "predicate"), "unknown_predicate"),
    ],
)
def test_parse_rejects_unknown_ontology_vocabulary(
    path: tuple[str | int, ...], invalid_value: str
) -> None:
    payload = _valid_facts()
    target: object = payload
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = invalid_value  # type: ignore[index]

    with pytest.raises(ValueError, match="Gemini facts"):
        parse_vision_facts_json(json.dumps(payload))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["entities"][0].__setitem__("model_score", "0.92"),  # type: ignore[index]
        lambda payload: payload["entities"][0]["bbox"].__setitem__("x", "0.1"),  # type: ignore[index]
    ],
    ids=["string-model-score", "string-bbox-coordinate"],
)
def test_parse_rejects_schema_numeric_values_encoded_as_strings(
    mutate: object,
) -> None:
    payload = _valid_facts()
    mutate(payload)  # type: ignore[operator]

    with pytest.raises(ValueError, match="Gemini facts"):
        parse_vision_facts_json(json.dumps(payload))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["entities"].append(payload["entities"][0].copy()),  # type: ignore[index]
        lambda payload: payload["feature_observations"].append(payload["feature_observations"][0].copy()),  # type: ignore[index]
        lambda payload: payload["relationships"][0].update({"subject": "missing-ref"}),  # type: ignore[index]
        lambda payload: payload["relationships"][0].update({"object": "missing-region"}),  # type: ignore[index]
        lambda payload: payload.__setitem__("visible_regions", ["unknown-region"]),
    ],
    ids=[
        "duplicate-entity-ref",
        "duplicate-feature-observation",
        "dangling-relationship-subject",
        "dangling-relationship-object",
        "unknown-visible-region",
    ],
)
def test_parse_rejects_incomplete_or_ambiguous_evidence_references(mutate: object) -> None:
    payload = _valid_facts()
    mutate(payload)  # type: ignore[operator]

    with pytest.raises(ValueError, match="Gemini facts"):
        parse_vision_facts_json(json.dumps(payload))


def test_facts_parser_never_logs_raw_provider_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_payload = '{"provider_detail":"FACTS_PROVIDER_SECRET"}'
    caplog.set_level(logging.WARNING, logger="sumai.gemini_vision")

    with pytest.raises(ValueError, match="Gemini facts"):
        parse_vision_facts_json(secret_payload)

    assert "FACTS_PROVIDER_SECRET" not in "\n".join(
        repr(record.__dict__) for record in caplog.records
    )


def _png_bytes() -> bytes:
    image = Image.new("RGB", (20, 20), "white")
    from io import BytesIO

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
def test_invalid_facts_fail_closed_in_strict_mode(
    mock_call_gemini: AsyncMock,
) -> None:
    async def invalid_facts(*_args: object, **_kwargs: object) -> VisionFacts:
        payload = _valid_facts()
        payload["entities"][0]["model_score"] = "0.92"  # type: ignore[index]
        return parse_vision_facts_json(json.dumps(payload))

    mock_call_gemini.side_effect = invalid_facts
    strict_settings = Settings(
        require_real_gemini=True,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )
    with patch("app.main.settings", strict_settings), patch(
        "app.services.gemini_vision.settings", strict_settings
    ), patch("app.config.settings", strict_settings):
        response = TestClient(app).post(
            "/analyze",
            files={"image": ("room.png", _png_bytes(), "image/png")},
            data={"room_hint": "hallway", "mock": "false"},
        )

    assert response.status_code == 503
    assert "0.92" not in response.text


@patch("app.services.gemini_vision.GeminiVisionService._call_gemini")
def test_invalid_facts_use_labeled_fallback_outside_strict_mode(
    mock_call_gemini: AsyncMock,
) -> None:
    async def invalid_facts(*_args: object, **_kwargs: object) -> VisionFacts:
        payload = _valid_facts()
        payload["entities"][0]["bbox"]["x"] = "0.1"  # type: ignore[index]
        return parse_vision_facts_json(json.dumps(payload))

    mock_call_gemini.side_effect = invalid_facts
    fallback_settings = Settings(
        require_real_gemini=False,
        gemini_api_key="dummy_key",
        mock_mode=False,
    )
    with patch("app.main.settings", fallback_settings), patch(
        "app.services.gemini_vision.settings", fallback_settings
    ), patch("app.config.settings", fallback_settings):
        response = TestClient(app).post(
            "/analyze",
            files={"image": ("room.png", _png_bytes(), "image/png")},
            data={"room_hint": "hallway", "mock": "false"},
        )

    assert response.status_code == 200
    assert response.json()["mode"] == "gemini_fallback(invalid_response)"
    assert '"x":"0.1"' not in response.text
